"""Check and rebuild journal days against the session transcripts on disk.

`check` compares each day's entry with the sessions that have turns written
on that day: a session active that day but absent from the entry is missing;
a session in the entry with no turns that day is misfiled. A missing session
that is still running is listed as open instead: sessions are journaled when
they end, so it is not a fault. `rebuild`
regenerates a day's session blocks, auto notes and open threads from those
transcripts, keeping manual notes.

Old transcripts are deleted (cleanupPeriodDays, 30 by default), so
both only work for recent days. A day whose entry lists a session with no
transcript left is reported, and is not rebuilt, since that would drop it.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .generator import SessionSummary, Turn, load_turns, local_time, turn_day
from .git_sync import commit_and_push
from .lock import FileLock
from .merger import filed_session_ids, merge_session, reset_day
from .pipeline import summarize_day, turns_by_day
from .state import SessionCursor, State


@dataclass
class DaySession:
    session_id: str
    path: Path
    first_day: str      # first day the session has turns on
    turns: list[Turn]   # its turns written on the day in question

    def span(self, cfg: Config) -> str:
        start, end = (local_time(t.timestamp, cfg).strftime("%H:%M") for t in (self.turns[0], self.turns[-1]))
        return f"{start}–{end}"

    @property
    def project(self) -> str:
        cwd = next((t.cwd for t in self.turns if t.cwd), "")
        return cwd.rstrip("/").rsplit("/", 1)[-1] or "unknown"


@dataclass
class DayReport:
    day: str
    active: list[DaySession]
    missing: list[DaySession]   # active that day, absent from the entry, not running
    open: list[DaySession]      # active that day, absent from the entry, still running
    misfiled: list[str]         # in the entry, no turns that day
    unverifiable: list[str]     # in the entry, transcript no longer on disk

    @property
    def ok(self) -> bool:
        return not (self.missing or self.misfiled)


def _day_start_timestamp(day: str, cfg: Config) -> float:
    # tzinfo None gives a naive datetime, which .timestamp() reads as machine local
    start = _dt.datetime.combine(_dt.date.fromisoformat(day), _dt.time(), tzinfo=cfg.tzinfo)
    return start.timestamp()


def sessions_by_day(
    cfg: Config, days: list[str], root: Path | None = None,
) -> tuple[dict[str, list[DaySession]], set[str]]:
    """Map each day to the sessions with turns written on it, in order of
    their first turn that day; also return every session id on disk."""
    root = root or cfg.transcripts_dir
    earliest = _day_start_timestamp(min(days), cfg)
    out: dict[str, list[DaySession]] = {d: [] for d in days}
    on_disk: set[str] = set()
    for path in sorted(root.glob("*/*.jsonl")):
        on_disk.add(path.stem)
        if path.stat().st_mtime < earliest:
            continue  # last written before the first day asked about
        stamped = [t for t in load_turns(path) if t.timestamp is not None]
        if not stamped:
            continue
        by_day = turns_by_day(stamped, cfg, fallback="")
        first_day = min(by_day)
        for day in out.keys() & by_day.keys():
            out[day].append(DaySession(path.stem, path, first_day, by_day[day]))
    for sessions in out.values():
        sessions.sort(key=lambda s: s.turns[0].timestamp)
    return out, on_disk


def _proc_starttime(pid: str) -> str | None:
    """Field 22 of /proc/<pid>/stat; None if the process is gone."""
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # comm (field 2) may contain spaces and parens, so split after the last ")"
    fields = text.rsplit(")", 1)[-1].split()
    return fields[19] if len(fields) > 19 else None


def open_session_ids(cfg: Config) -> set[str]:
    """Ids of sessions whose process is alive: <claude dir>/sessions/<pid>.json
    names the pid (the file's "pid" field, else its stem) and the process start
    time, which guards against stale files and reused pids. Never raises."""
    out: set[str] = set()
    try:
        files = sorted(cfg.sessions_dir.glob("*.json"))
    except OSError:
        return out
    for path in files:
        try:
            data = json.loads(path.read_text())
            sid = str(data["sessionId"])
            pid = str(data.get("pid") or path.stem)
            if not pid.isdigit():
                continue
            start = _proc_starttime(pid)
            proc_start = data.get("procStart")
            if start is None or (proc_start is not None and str(proc_start) != start):
                continue
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
        out.add(sid)
    return out


def check_days(
    cfg: Config, days: list[str], root: Path | None = None, open_ids: set[str] | None = None,
) -> list[DayReport]:
    by_day, on_disk = sessions_by_day(cfg, days, root)
    if open_ids is None:
        open_ids = open_session_ids(cfg)
    reports = []
    for day in days:
        active = by_day[day]
        active_ids = {s.session_id for s in active}
        filed = filed_session_ids(cfg, day)
        unfiled = [s for s in active if s.session_id not in filed]
        reports.append(DayReport(
            day=day,
            active=active,
            missing=[s for s in unfiled if s.session_id not in open_ids],
            open=[s for s in unfiled if s.session_id in open_ids],
            misfiled=[sid for sid in filed if sid in on_disk and sid not in active_ids],
            unverifiable=[sid for sid in filed if sid not in on_disk],
        ))
    return reports


def _stranded(
    cfg: Config, reports: list[DayReport], days: list[str], root: Path | None, allow_drop: set[str],
) -> list[str]:
    """Misfiled sessions a rebuild would drop from the journal altogether:
    they have turns on days outside the rebuild whose entries don't list them."""
    root = root or cfg.transcripts_dir
    out = []
    for sid in dict.fromkeys(sid for r in reports for sid in r.misfiled):
        if sid in allow_drop:
            continue
        path = next(root.glob(f"*/{sid}.jsonl"))
        turn_days = {turn_day(t, cfg, "") for t in load_turns(path) if t.timestamp is not None}
        uncovered = sorted(d for d in turn_days if d not in days and sid not in filed_session_ids(cfg, d))
        if uncovered:
            out.append(f"{sid} ({', '.join(uncovered)})")
    return out


def _plan(
    cfg: Config, days: list[str], root: Path | None, allow_drop: set[str],
) -> list[DayReport]:
    reports = check_days(cfg, days, root)
    blocked = [r for r in reports if r.unverifiable]
    if blocked:
        detail = "; ".join(f"{r.day}: {', '.join(r.unverifiable)}" for r in blocked)
        raise RuntimeError(f"entries list sessions with no transcript left, not rebuilding: {detail}")
    stranded = _stranded(cfg, reports, days, root, allow_drop)
    if stranded:
        raise RuntimeError(
            "rebuilding would drop misfiled sessions whose days are not being rebuilt; "
            f"add those days, or --allow-drop a session whose work is already filed elsewhere: "
            f"{'; '.join(stranded)}"
        )
    return reports


def _cache_path(cfg: Config, day: str, s: DaySession) -> Path:
    # keyed on the day's last turn, so a session that grew since is summarized again
    key = hashlib.sha256(f"{s.turns[-1].uuid}|{len(s.turns)}".encode()).hexdigest()[:12]
    return cfg.state_dir / "rebuild_cache" / f"{day}_{s.session_id}_{key}.json"


def _summarize_cached(
    cfg: Config, client: Any, day: str, s: DaySession, attempts: int,
) -> tuple[SessionSummary, int]:
    path = _cache_path(cfg, day, s)
    if path.exists():
        cached = json.loads(path.read_text())
        return SessionSummary(**cached["summary"]), cached["redactions"]
    for attempt in range(1, attempts + 1):
        try:
            summary, redactions = summarize_day(cfg, client, s.turns, s.turns[0].cwd)
            break
        except Exception:
            if attempt == attempts:
                raise
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"summary": summary.model_dump(), "redactions": redactions}))
    return summary, redactions


def _summarize_all(
    cfg: Config, client: Any, reports: list[DayReport], jobs: int, attempts: int,
) -> list[tuple[str, DaySession, SessionSummary, int]]:
    work = [(r.day, s) for r in reports for s in r.active]
    results: list[Any] = [None] * len(work)
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        futures = {ex.submit(_summarize_cached, cfg, client, day, s, attempts): i
                   for i, (day, s) in enumerate(work)}
        for done, fut in enumerate(as_completed(futures), start=1):
            i = futures[fut]
            results[i] = (*work[i], *fut.result())
            print(f"[{done}/{len(work)}] {work[i][0]} {work[i][1].session_id}", file=sys.stderr, flush=True)
    return results


def _refuse_over_threshold(
    cfg: Config, results: list[tuple[str, DaySession, SessionSummary, int]], allow_drop: set[str],
) -> None:
    over = [f"{day} {s.session_id} ({redactions})" for day, s, _, redactions in results
            if redactions >= cfg.scrub_threshold and s.session_id not in allow_drop]
    if over:
        raise RuntimeError(
            f"summaries reach the scrub threshold ({cfg.scrub_threshold} redactions), not rebuilding; "
            f"review those sessions, or --allow-drop one to leave it out: {'; '.join(over)}"
        )


def _advance_cursor(
    cfg: Config, state: State, merged: list[tuple[str, DaySession, SessionSummary]],
) -> None:
    """Move a session's cursor over the turns this rebuild journaled: from the
    old cursor, through consecutive turns on the days it wrote. A day before
    them that is not journaled stops it, so the hook still picks that day up."""
    days = {day for day, _, _ in merged}
    upto = max(s.turns[-1].idx for _, s, _ in merged)  # turns written since were not summarized
    _, s, summary = merged[-1]
    cursor = state.get(s.session_id)
    last = None
    for t in load_turns(s.path)[cursor.last_processed_msg_idx + 1 if cursor else 0:]:
        if t.idx > upto or turn_day(t, cfg, "") not in days:
            break
        last = t
    if last is not None:
        state.set(s.session_id, SessionCursor(
            last_processed_msg_idx=last.idx,
            last_msg_uuid=last.uuid,
            last_update_date=turn_day(last, cfg, ""),
            first_seen_date=s.first_day,
            project=summary.project,
        ))


def rebuild_days(
    cfg: Config, client: Any, days: list[str], root: Path | None = None, *, jobs: int = 4,
    allow_drop: set[str] = frozenset(), attempts: int = 3,
) -> list[str]:
    """Regenerate each day from its transcripts. Every summary is made before
    any entry is touched, so a failed summary leaves the journal as it was;
    finished summaries are cached, so running the same rebuild again resumes.
    Summaries are made outside the journal lock (sessions ending meanwhile are
    journaled as usual), then the plan is re-checked under the lock.
    Returns one line per session, for the caller to print."""
    results = _summarize_all(cfg, client, _plan(cfg, days, root, allow_drop), jobs, attempts)
    _refuse_over_threshold(cfg, results, allow_drop)
    with FileLock(cfg.lock_path, wait_seconds=max(cfg.lock_wait_seconds, 600)):
        results = _summarize_all(cfg, client, _plan(cfg, days, root, allow_drop), jobs, attempts)
        _refuse_over_threshold(cfg, results, allow_drop)

        lines: list[str] = []
        state = State(cfg)
        for day in days:
            reset_day(cfg, day)
        merged: dict[str, list[tuple[str, DaySession, SessionSummary]]] = {}
        for day, s, summary, redactions in results:
            if redactions >= cfg.scrub_threshold:  # in allow_drop, or it would have been refused
                lines.append(f"{day}  {s.session_id}  SKIPPED: {redactions} redactions (threshold {cfg.scrub_threshold})")
                continue
            merge_session(cfg, day, s.session_id, summary,
                          continued_from=s.first_day if s.first_day != day else None)
            merged.setdefault(s.session_id, []).append((day, s, summary))
            lines.append(f"{day}  {s.session_id}  {s.span(cfg)}  {summary.project}")
        for session_days in merged.values():
            _advance_cursor(cfg, state, session_days)
        state.save()
        commit_and_push(cfg, f"journal: rebuild {', '.join(days)}")
        for day, s, _, _ in results:
            _cache_path(cfg, day, s).unlink(missing_ok=True)
        return lines

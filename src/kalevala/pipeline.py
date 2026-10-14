"""Orchestrate one session end-to-end.

Pipeline:
  1. Acquire lock (may queue and exit if starved)
  2. Drain pending.json (skip entries not yet due)
  3. Lookup session cursor
  4. If new turns since cursor — for each day those turns were written on,
     summarize all of the session's turns from that day
  5. Normalize paths → scrub secrets
  6. Check scrub threshold → merge into that day's file
  7. git commit + push
  8. Update state
  9. Release lock

A session is filed under the days its turns were written, not the day the
hook runs: a session closed the morning after is still yesterday's work.

Any step that raises is caught, logged to errors.log, and returns
processed=False. The hook itself never re-raises to the caller.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import random
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .generator import SessionSummary, Turn, load_turns, summarize_turns, turn_day
from .git_sync import commit_and_push
from .lock import FileLock, LockTimeout
from .merger import merge_session
from .path_normalizer import normalize_paths
from .scrubber import Scrubber
from .state import SessionCursor, State


@dataclass
class HookResult:
    processed: bool
    error: str | None = None


def next_retry_delay_seconds(attempt: int) -> float:
    base = min(60 * (2 ** attempt), 1800)
    jitter = random.uniform(0.75, 1.25)
    return base * jitter


def _log_error(cfg: Config, msg: str) -> None:
    try:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        with cfg.errors_log.open("a") as f:
            f.write(f"[{_dt.datetime.now().isoformat()}] {msg}\n")
    except Exception:
        # logging must never itself be a failure mode
        pass


def _write_status(cfg: Config, **kv) -> None:
    try:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        current: dict[str, Any] = {}
        if cfg.status_file.exists():
            try:
                current = json.loads(cfg.status_file.read_text())
            except json.JSONDecodeError:
                pass
        current.update(kv)
        current["updated_at"] = _dt.datetime.now().isoformat()
        cfg.status_file.write_text(json.dumps(current, indent=2))
    except Exception:
        pass


def _read_pending(cfg: Config) -> list:
    if not cfg.pending_file.exists():
        return []
    try:
        loaded = json.loads(cfg.pending_file.read_text())
        if isinstance(loaded, list):
            return loaded
    except json.JSONDecodeError:
        pass
    return []


def _write_pending(cfg: Config, items: list) -> None:
    try:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        cfg.pending_file.write_text(json.dumps(items, indent=2))
    except Exception:
        pass


def _queue_pending(cfg: Config, entry: dict, attempts: int = 0) -> None:
    try:
        import uuid as _uuid
        augmented = {
            "queue_id": entry.get("queue_id") or _uuid.uuid4().hex,
            **entry,
            "attempts": attempts,
            "next_retry_at": _dt.datetime.now().timestamp() + next_retry_delay_seconds(attempts),
        }
        existing = _read_pending(cfg)
        existing.append(augmented)
        _write_pending(cfg, existing)
    except Exception:
        # queueing must never be a failure mode that escapes
        pass


def _drain_pending(cfg: Config, client: Any, today: str) -> None:
    items = _read_pending(cfg)
    if not items:
        return
    original_qids = {it.get("queue_id") for it in items if it.get("queue_id")}
    now = _dt.datetime.now().timestamp()
    remaining = []
    for it in items:
        if it.get("next_retry_at", 0) > now:
            remaining.append(it)
            continue
        kind = it.get("kind")
        if kind == "session":
            if not Path(it["transcript_path"]).exists():
                # never written (a --no-session-persistence run) or already
                # cleaned up; retrying cannot bring it back
                _log_error(cfg, f"dropping queued session {it.get('session_id')}: transcript missing")
                continue
            try:
                _process_session(
                    cfg=cfg, client=client, today=today,
                    session_id=it["session_id"],
                    transcript_path=Path(it["transcript_path"]),
                )
            except Exception as e:
                _log_error(cfg, f"drain failure {it}: {e}")
                it["attempts"] = it.get("attempts", 0) + 1
                it["next_retry_at"] = now + next_retry_delay_seconds(it["attempts"])
                remaining.append(it)
        elif kind == "push":
            try:
                commit_and_push(cfg, it.get("message", "kalevala: drain"))
            except Exception as e:
                _log_error(cfg, f"drain push failure: {e}")
                it["attempts"] = it.get("attempts", 0) + 1
                it["next_retry_at"] = now + next_retry_delay_seconds(it["attempts"])
                remaining.append(it)

    # Re-read to pick up entries written concurrently (e.g. _queue_push from
    # inside commit_and_push during this drain). Skip any entry whose
    # queue_id matches an original — those were already handled (success =>
    # drop, failure => already in `remaining`).
    current = _read_pending(cfg)
    for it in current:
        qid = it.get("queue_id")
        if qid and qid in original_qids:
            continue
        remaining.append(it)
    _write_pending(cfg, remaining)


def _project_name(project_dir: str) -> str:
    return project_dir.rstrip("/").rsplit("/", 1)[-1] or "unknown"


def _scrub_summary_fields(summary_dict: dict) -> tuple[dict, int]:
    scrubber = Scrubber()
    total = 0
    out: dict[str, Any] = {}
    for k, v in summary_dict.items():
        if isinstance(v, str):
            cleaned, counts = scrubber.scrub(v)
            total += sum(counts.values())
            out[k] = cleaned
        elif isinstance(v, list):
            new_list = []
            for item in v:
                if isinstance(item, str):
                    cleaned, counts = scrubber.scrub(item)
                    total += sum(counts.values())
                    new_list.append(cleaned)
                else:
                    new_list.append(item)
            out[k] = new_list
        else:
            out[k] = v
    return out, total


def summarize_day(
    cfg: Config, client: Any, day_turns: list[Turn], project_dir: str,
) -> tuple[SessionSummary, int]:
    """Summarize one session's turns from one day; return the normalized,
    scrubbed summary and the number of redactions made."""
    summary = summarize_turns(day_turns, cfg, client)
    summary_dict = normalize_paths(
        summary.model_dump(),
        home=os.environ.get("HOME", str(Path.home())),
        project_dir=project_dir,
        project_name=summary.project or _project_name(project_dir),
    )
    summary_dict, total_redactions = _scrub_summary_fields(summary_dict)
    return SessionSummary(**summary_dict), total_redactions


def turns_by_day(turns: list[Turn], cfg: Config, fallback: str) -> dict[str, list[Turn]]:
    days: dict[str, list[Turn]] = {}
    for t in turns:
        days.setdefault(turn_day(t, cfg, fallback), []).append(t)
    return days


def _process_session(
    *,
    cfg: Config,
    client: Any,
    today: str,
    session_id: str,
    transcript_path: Path,
) -> bool:
    if not transcript_path.exists():
        _log_error(cfg, f"transcript missing: {transcript_path}")
        raise FileNotFoundError(f"transcript missing: {transcript_path}")

    state = State(cfg)
    cursor = state.get(session_id)
    start_idx = cursor.last_processed_msg_idx + 1 if cursor else 0

    turns = load_turns(transcript_path)
    new_turns = turns[start_idx:]
    # nothing new since the last run (a resume closed without a prompt) or an empty transcript
    if not new_turns:
        return False

    by_day = turns_by_day(turns, cfg, today)
    first_day = min(by_day)
    # each day with new turns is re-summarized whole, so the merge can replace
    # that day's block without losing what an earlier run of this session wrote
    days = sorted({turn_day(t, cfg, today) for t in new_turns})
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "") or turns[0].cwd

    summaries: list[tuple[str, SessionSummary]] = []
    for day in days:
        summary, total_redactions = summarize_day(cfg, client, by_day[day], project_dir)
        if total_redactions >= cfg.scrub_threshold:
            msg = f"[SCRUB_THRESHOLD_EXCEEDED] session={session_id} day={day} redactions={total_redactions}"
            print(msg, file=sys.stderr)
            _log_error(cfg, msg)
            _write_status(cfg, pending_manual_review=True)
            _queue_pending(cfg, {
                "kind": "session",
                "session_id": session_id,
                "transcript_path": str(transcript_path),
                "reason": "scrub_threshold_exceeded",
            })
            return False
        summaries.append((day, summary))

    for day, summary in summaries:
        merge_session(cfg, day, session_id, summary,
                      continued_from=first_day if day != first_day else None)

    project = summaries[-1][1].project
    result = commit_and_push(cfg, f"journal: session {session_id} ({project}) {', '.join(days)}")
    if not result.pushed and cfg.auto_push:
        print(f"[kalevala] commit not pushed: {result.message}", file=sys.stderr)

    new_cursor = SessionCursor(
        last_processed_msg_idx=turns[-1].idx,
        last_msg_uuid=turns[-1].uuid,
        last_update_date=days[-1],
        first_seen_date=first_day,
        project=project,
    )
    state.set(session_id, new_cursor)
    state.save()
    return True


def run_hook(
    session_id: str,
    transcript_path: Path,
    cfg: Config,
    client: Any,
    *,
    today: str | None = None,
) -> HookResult:
    today = today or cfg.today().isoformat()
    try:
        with FileLock(cfg.lock_path, wait_seconds=cfg.lock_wait_seconds):
            _drain_pending(cfg, client, today)
            processed = _process_session(
                cfg=cfg, client=client, today=today,
                session_id=session_id, transcript_path=transcript_path,
            )
            return HookResult(processed=processed)
    except LockTimeout:
        try:
            _queue_pending(cfg, {
                "kind": "session",
                "session_id": session_id,
                "transcript_path": str(transcript_path),
                "reason": "lock_timeout",
            })
        except Exception:
            pass
        return HookResult(processed=False, error="lock_timeout")
    except Exception as e:
        try:
            _log_error(cfg, f"hook failure {session_id}: {e}\n{traceback.format_exc()}")
        except Exception:
            pass
        return HookResult(processed=False, error=str(e))
    except BaseException as e:  # fatal fallback — KeyboardInterrupt, SystemExit, etc.
        return HookResult(processed=False, error=f"fatal: {type(e).__name__}")

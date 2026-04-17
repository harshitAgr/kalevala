"""Upsert session summaries into today's daily markdown file.

The daily file is the source of truth. Writes are atomic (tempfile +
os.replace). Summary concat is deterministic — no LLM call.
"""
from __future__ import annotations

import os
import re
from datetime import date as _date
from pathlib import Path

from .config import Config
from .generator import SessionSummary


_FRONTMATTER_RE = re.compile(r"^---\n(?P<body>.*?)\n---\n", re.DOTALL)
_SESSION_BLOCK_RE = re.compile(r"(### Session \d+ — .*?)(?=^### Session |^## |\Z)", re.MULTILINE | re.DOTALL)


def _daily_path(cfg: Config, date: str) -> Path:
    year, month, _ = date.split("-")
    return cfg.entries_dir / year / month / f"{date}.md"


def _cleanup_orphan_tempfiles(directory: Path) -> None:
    if not directory.exists():
        return
    for p in directory.glob("*.tmp*"):
        try:
            p.unlink()
        except OSError:
            pass


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _cleanup_orphan_tempfiles(path.parent)
    tmp = path.parent / f".{path.name}.tmp.{os.getpid()}"
    tmp.write_text(content)
    os.replace(tmp, path)


def _weekday(date_str: str) -> str:
    y, m, d = (int(x) for x in date_str.split("-"))
    return _date(y, m, d).strftime("%A")


def _parse_existing(path: Path) -> dict:
    """Return structured view of existing sessions + notes + open threads."""
    if not path.exists():
        return {"sessions": [], "notes": [], "open_threads": []}
    text = path.read_text()

    # sessions: each "### Session N — ..." block, keyed by id
    sessions_by_id: dict[str, str] = {}
    session_order: list[str] = []
    for m in _SESSION_BLOCK_RE.finditer(text):
        block = m.group(1).strip()
        id_match = re.search(r"id:\s*([A-Za-z0-9_\-]+)", block)
        if id_match:
            sid = id_match.group(1)
            sessions_by_id[sid] = block
            session_order.append(sid)

    def _section_items(header: str) -> list[str]:
        rx = re.compile(rf"## {re.escape(header)}\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
        m = rx.search(text)
        if not m:
            return []
        lines = [l.strip() for l in m.group(1).splitlines() if l.strip().startswith("- ")]
        return [l[2:] for l in lines]

    return {
        "sessions": [(sid, sessions_by_id[sid]) for sid in session_order],
        "notes": _section_items("Notes for Later"),
        "open_threads": _section_items("Open Threads"),
    }


def _render_session_block(
    *, index: int, session_id: str, summary: SessionSummary, continued_from: str | None,
) -> str:
    start, end = summary.time_range
    continued = f" · continued from {continued_from}" if continued_from else ""
    parts = [
        f"### Session {index} — {summary.project} ({start}–{end}) · id: {session_id}{continued}",
        "",
        f"**Summary:** {summary.summary}",
        "",
    ]
    if summary.files_touched:
        parts.append(f"**Files touched:** {', '.join(f'`{p}`' for p in summary.files_touched)}")
    if summary.commits:
        parts.append("**Commits:**")
        parts.extend(f"- `{c}`" for c in summary.commits)
    if summary.bugs_fixed:
        parts.append(f"**Bugs fixed:** {'; '.join(summary.bugs_fixed)}")
    if summary.decisions:
        parts.append(f"**Decisions:** {'; '.join(summary.decisions)}")
    if summary.learnings:
        parts.append(f"**Learnings:** {'; '.join(summary.learnings)}")
    return "\n".join(parts).rstrip() + "\n"


def _render_full(date: str, sessions: list[tuple[str, str]], notes: list[str], open_threads: list[str]) -> str:
    projects = []
    for _, block in sessions:
        m = re.search(r"### Session \d+ — (\S+)", block)
        if m and m.group(1) not in projects:
            projects.append(m.group(1))

    # frontmatter
    fm = [
        "---",
        f"date: {date}",
        f"sessions: {len(sessions)}",
        f"projects: [{', '.join(projects)}]",
        "---",
        "",
    ]

    # top summary: one line per session
    top_summary_lines = []
    for _, block in sessions:
        m = re.search(r"\*\*Summary:\*\*\s*(.+)", block)
        if m:
            top_summary_lines.append(f"- {m.group(1).strip()}")
    top_summary = "\n".join(top_summary_lines) if top_summary_lines else "_(no sessions yet)_"

    body_parts = [
        "\n".join(fm),
        f"# {date} — {_weekday(date)}",
        "",
        "## Summary",
        top_summary,
        "",
        "## Sessions",
        "",
        "\n\n".join(block.rstrip() for _, block in sessions),
        "",
    ]
    if notes:
        body_parts += ["## Notes for Later", "\n".join(f"- {n}" for n in notes), ""]
    if open_threads:
        body_parts += ["## Open Threads", "\n".join(f"- {t}" for t in open_threads), ""]
    return "\n".join(body_parts).rstrip() + "\n"


def merge_session(
    cfg: Config,
    date: str,
    session_id: str,
    summary: SessionSummary,
    *,
    continued_from: str | None = None,
) -> Path:
    path = _daily_path(cfg, date)
    existing = _parse_existing(path)

    # determine index and whether we're replacing in-place (same-day resume) or appending
    existing_ids = [sid for sid, _ in existing["sessions"]]
    if session_id in existing_ids:
        idx = existing_ids.index(session_id) + 1
    else:
        idx = len(existing_ids) + 1

    block = _render_session_block(
        index=idx, session_id=session_id, summary=summary, continued_from=continued_from,
    )

    if session_id in existing_ids:
        new_sessions = [(sid, block if sid == session_id else b) for sid, b in existing["sessions"]]
    else:
        new_sessions = list(existing["sessions"]) + [(session_id, block)]

    # merge notes (auto) / open threads without duplicates
    def _uniq_append(current: list[str], new_items: list[str], prefix: str) -> list[str]:
        existing_stripped = {x.removeprefix(prefix).strip() for x in current}
        out = list(current)
        for it in new_items:
            if it.strip() not in existing_stripped:
                out.append(f"{prefix}{it.strip()}")
                existing_stripped.add(it.strip())
        return out

    notes = _uniq_append(existing["notes"], summary.notes_for_later, "(auto) ")
    opens = _uniq_append(existing["open_threads"], summary.open_threads, "")

    rendered = _render_full(date, new_sessions, notes, opens)
    _atomic_write(path, rendered)
    return path

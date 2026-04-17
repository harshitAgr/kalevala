"""kalevala command-line interface."""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re as _re
import sys
from datetime import timedelta
from pathlib import Path

from .clients import build_client
from .config import Config, load_config
from .git_sync import commit_and_push
from .merger import add_manual_note, add_manual_todo
from .pipeline import run_hook


def _today() -> str:
    return _dt.date.today().isoformat()


def _client():
    return build_client()


def _resolve_hook_inputs(args: argparse.Namespace) -> tuple[str, str]:
    """Return (session_id, transcript_path).

    Claude Code's SessionEnd hook delivers its payload as JSON on stdin,
    not via environment variables. If CLI args are missing, parse stdin.
    """
    import json as _json
    sid = args.session_id
    tpath = args.transcript_path
    if (not sid or not tpath) and not sys.stdin.isatty():
        try:
            payload = _json.loads(sys.stdin.read() or "{}")
            sid = sid or payload.get("session_id", "")
            tpath = tpath or payload.get("transcript_path", "")
        except _json.JSONDecodeError:
            pass
    return sid or "", tpath or ""


def cmd_hook(args: argparse.Namespace, cfg: Config) -> int:
    session_id, transcript_path = _resolve_hook_inputs(args)
    if args.verify_scrub:
        from .scrubber import Scrubber
        scrubber = Scrubber()
        text = Path(transcript_path).read_text()
        _, counts = scrubber.scrub(text)
        print(f"scrub report: {counts}")
        return 0
    if not session_id or not transcript_path:
        print("[kalevala] missing session_id or transcript_path (pass via flags or stdin JSON)", file=sys.stderr)
        return 0  # still never nonzero
    client = _client()
    result = run_hook(
        session_id=session_id,
        transcript_path=Path(transcript_path),
        cfg=cfg,
        client=client,
    )
    if result.error:
        print(f"[kalevala] {result.error}", file=sys.stderr)
    return 0  # hook NEVER returns nonzero


def cmd_note(args: argparse.Namespace, cfg: Config) -> int:
    add_manual_note(cfg, _today(), args.text)
    commit_and_push(cfg, f"journal: manual note ({_today()})")
    return 0


def cmd_todo(args: argparse.Namespace, cfg: Config) -> int:
    add_manual_todo(cfg, _today(), args.text)
    commit_and_push(cfg, f"journal: manual TODO ({_today()})")
    return 0


def _date_file(cfg: Config, date_str: str) -> Path:
    y, m, _ = date_str.split("-")
    return cfg.entries_dir / y / m / f"{date_str}.md"


def cmd_show(args: argparse.Namespace, cfg: Config) -> int:
    target_date = args.date or _today()
    path = _date_file(cfg, target_date)
    if not path.exists():
        print(f"[kalevala] no entry for {target_date}")
        return 0
    sys.stdout.write(path.read_text())
    return 0


def cmd_last(args: argparse.Namespace, cfg: Config) -> int:
    yesterday = (_dt.date.today() - timedelta(days=1)).isoformat()
    path = _date_file(cfg, yesterday)
    if not path.exists():
        print(f"[kalevala] no entry for {yesterday}")
        return 0
    sys.stdout.write(path.read_text())
    return 0


def cmd_search(args: argparse.Namespace, cfg: Config) -> int:
    pattern = _re.compile(_re.escape(args.query), _re.IGNORECASE)
    any_match = False
    for entry in sorted(cfg.entries_dir.rglob("*.md")):
        text = entry.read_text()
        for i, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                any_match = True
                print(f"{entry.relative_to(cfg.entries_dir)}:{i}: {line.strip()}")
    if not any_match:
        print(f"[kalevala] no matches for {args.query!r}")
    return 0


def cmd_resume(args: argparse.Namespace, cfg: Config) -> int:
    pattern = _re.compile(_re.escape(args.query), _re.IGNORECASE)
    best: tuple[str, str] | None = None  # (date, session_id)
    for entry in sorted(cfg.entries_dir.rglob("*.md"), reverse=True):
        text = entry.read_text()
        if pattern.search(text):
            # find last session id in file
            ids = _re.findall(r"id:\s*([A-Za-z0-9_\-]+)", text)
            if ids:
                best = (entry.stem, ids[-1])
                break
    if best is None:
        print(f"[kalevala] no session matched {args.query!r}")
        return 0
    print(f"claude --resume {best[1]}  # from {best[0]}")
    return 0


def cmd_status(args: argparse.Namespace, cfg: Config) -> int:
    import json as _json
    pending_count = 0
    if cfg.pending_file.exists():
        try:
            pending_count = len(_json.loads(cfg.pending_file.read_text()))
        except Exception:
            pass
    state_file_exists = cfg.state_file.exists()
    errors_count = 0
    if cfg.errors_log.exists():
        errors_count = sum(1 for _ in cfg.errors_log.open())
    print(f"log_repo: {cfg.log_repo_path}")
    print(f"state_file: {'ok' if state_file_exists else 'missing'}")
    print(f"pending: {pending_count}")
    print(f"errors.log: {errors_count} lines")
    if cfg.status_file.exists():
        print("--- last status ---")
        print(cfg.status_file.read_text())
    return 0


def cmd_drain(args: argparse.Namespace, cfg: Config) -> int:
    from .pipeline import _drain_pending
    client = _client()
    _drain_pending(cfg, client, _today())
    print("drain complete")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="kalevala")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_hook = sub.add_parser("hook")
    p_hook.add_argument("--session-id", default=None)
    p_hook.add_argument("--transcript-path", default=None)
    p_hook.add_argument("--verify-scrub", action="store_true")
    p_hook.add_argument("--dry-run", action="store_true")

    p_note = sub.add_parser("note"); p_note.add_argument("text")
    p_todo = sub.add_parser("todo"); p_todo.add_argument("text")

    p_show = sub.add_parser("show")
    p_show.add_argument("date", nargs="?", default=None)

    sub.add_parser("last")

    p_search = sub.add_parser("search"); p_search.add_argument("query")
    p_resume = sub.add_parser("resume"); p_resume.add_argument("query")

    sub.add_parser("status")
    sub.add_parser("drain")

    args = parser.parse_args()
    cfg = load_config()
    handlers = {
        "hook": cmd_hook, "note": cmd_note, "todo": cmd_todo,
        "show": cmd_show, "last": cmd_last,
        "search": cmd_search, "resume": cmd_resume,
        "drain": cmd_drain, "status": cmd_status,
    }
    return handlers[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())

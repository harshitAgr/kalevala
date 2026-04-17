"""kalevala command-line interface."""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
from pathlib import Path

from anthropic import Anthropic

from .config import Config, load_config
from .git_sync import commit_and_push
from .merger import add_manual_note, add_manual_todo
from .pipeline import run_hook


def _today() -> str:
    return _dt.date.today().isoformat()


def _client() -> Anthropic:
    return Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))


def cmd_hook(args: argparse.Namespace, cfg: Config) -> int:
    if args.verify_scrub:
        from .scrubber import Scrubber
        scrubber = Scrubber()
        text = Path(args.transcript_path).read_text()
        _, counts = scrubber.scrub(text)
        print(f"scrub report: {counts}")
        return 0
    client = _client()
    result = run_hook(
        session_id=args.session_id,
        transcript_path=Path(args.transcript_path),
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


def main() -> int:
    parser = argparse.ArgumentParser(prog="kalevala")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_hook = sub.add_parser("hook")
    p_hook.add_argument("--session-id", required=True)
    p_hook.add_argument("--transcript-path", required=True)
    p_hook.add_argument("--verify-scrub", action="store_true")
    p_hook.add_argument("--dry-run", action="store_true")

    p_note = sub.add_parser("note")
    p_note.add_argument("text")

    p_todo = sub.add_parser("todo")
    p_todo.add_argument("text")

    args = parser.parse_args()
    cfg = load_config()
    handlers = {"hook": cmd_hook, "note": cmd_note, "todo": cmd_todo}
    return handlers[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())

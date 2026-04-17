"""CLI: note and todo subcommands write to today's entry."""
import os
import subprocess
import sys
from pathlib import Path

from kalevala.config import load_config


def test_note_subcommand_writes_manual_note(tmp_config: Path, tmp_log_repo: Path):
    cfg = load_config()
    proc = subprocess.run(
        [sys.executable, "-m", "kalevala", "note", "try new cache layout"],
        env={**os.environ, "KALEVALA_CONFIG": str(tmp_config)},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    # today's file should contain the note
    today_files = list(cfg.entries_dir.glob("**/*.md"))
    assert today_files, "no entry file created"
    content = today_files[0].read_text()
    assert "(manual) try new cache layout" in content


def test_todo_subcommand(tmp_config: Path):
    cfg = load_config()
    proc = subprocess.run(
        [sys.executable, "-m", "kalevala", "todo", "refactor the auth middleware"],
        env={**os.environ, "KALEVALA_CONFIG": str(tmp_config)},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    content = list(cfg.entries_dir.glob("**/*.md"))[0].read_text()
    assert "(manual) TODO: refactor the auth middleware" in content

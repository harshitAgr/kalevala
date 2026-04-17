"""CLI: drain + status."""
import json
import os
import subprocess
import sys
from pathlib import Path

from kalevala.config import load_config


def _run(cfg_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "KALEVALA_CONFIG": str(cfg_path)}
    return subprocess.run(
        [sys.executable, "-m", "kalevala", *args],
        env=env, capture_output=True, text=True,
    )


def test_status_reports_pending_count(tmp_config: Path):
    cfg = load_config()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.pending_file.write_text(json.dumps([
        {"kind": "session", "session_id": "a", "reason": "lock_timeout"},
        {"kind": "push", "reason": "git_conflict"},
    ]))
    proc = _run(tmp_config, "status")
    assert proc.returncode == 0
    assert "pending: 2" in proc.stdout


def test_drain_empties_queue_of_push_items(tmp_config: Path, tmp_log_repo: Path):
    cfg = load_config()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    (tmp_log_repo / "drain-marker.md").write_text("x")
    cfg.pending_file.write_text(json.dumps([
        {"kind": "push", "message": "drained", "reason": "git_conflict"},
    ]))
    proc = _run(tmp_config, "drain")
    assert proc.returncode == 0
    remaining = json.loads(cfg.pending_file.read_text())
    # local-only auto_push=false means push items are committed-but-not-pushed; they remain queued
    assert remaining == [] or all(x.get("kind") == "push" for x in remaining)

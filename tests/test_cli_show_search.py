"""CLI: show, last, search, resume."""
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path


def _run(cfg_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "KALEVALA_CONFIG": str(cfg_path)}
    return subprocess.run(
        [sys.executable, "-m", "kalevala", *args],
        env=env, capture_output=True, text=True,
    )


def _seed(tmp_log_repo: Path, date_str: str, sid: str, body_extra: str = "") -> None:
    from kalevala.config import load_config
    from kalevala.generator import SessionSummary
    from kalevala.merger import merge_session
    cfg = load_config()
    s = SessionSummary(
        summary=body_extra or "seed", files_touched=[], commits=[],
        bugs_fixed=[], decisions=[], learnings=[], notes_for_later=[],
        open_threads=[], time_range=["09:00", "09:30"], project="myapp",
        last_msg_uuid="u", last_msg_idx=0,
    )
    merge_session(cfg, date_str, sid, s)


def test_show_today(tmp_config: Path, tmp_log_repo: Path):
    today_str = date.today().isoformat()
    _seed(tmp_log_repo, today_str, "abc")
    proc = _run(tmp_config, "show")
    assert proc.returncode == 0
    assert "abc" in proc.stdout


def test_show_specific_date(tmp_config: Path, tmp_log_repo: Path):
    _seed(tmp_log_repo, "2026-04-17", "xyz")
    proc = _run(tmp_config, "show", "2026-04-17")
    assert proc.returncode == 0
    assert "xyz" in proc.stdout


def test_last_yesterday(tmp_config: Path, tmp_log_repo: Path):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    _seed(tmp_log_repo, yesterday, "yday")
    proc = _run(tmp_config, "last")
    assert proc.returncode == 0
    assert "yday" in proc.stdout


def test_search_finds_matches(tmp_config: Path, tmp_log_repo: Path):
    _seed(tmp_log_repo, "2026-04-17", "sid-1", body_extra="fixed request handler crash")
    _seed(tmp_log_repo, "2026-04-16", "sid-2", body_extra="totally unrelated")
    proc = _run(tmp_config, "search", "request handler")
    assert proc.returncode == 0
    assert "sid-1" in proc.stdout or "2026-04-17" in proc.stdout
    assert "sid-2" not in proc.stdout


def test_resume_prints_command(tmp_config: Path, tmp_log_repo: Path):
    _seed(tmp_log_repo, "2026-04-17", "target-id", body_extra="the request handler fix")
    proc = _run(tmp_config, "resume", "request handler fix")
    assert proc.returncode == 0
    assert "claude --resume target-id" in proc.stdout

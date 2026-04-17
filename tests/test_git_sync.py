"""git_sync: add / commit / push / conflict queueing."""
import subprocess
from pathlib import Path

from kalevala.config import load_config
from kalevala.git_sync import commit_and_push, CommitResult


def _run(args: list[str], cwd: Path) -> str:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout


def test_commit_without_push(tmp_config: Path, tmp_log_repo: Path):
    cfg = load_config()
    (tmp_log_repo / "entries").mkdir(exist_ok=True)
    entry = tmp_log_repo / "entries" / "demo.md"
    entry.write_text("hello\n")

    result = commit_and_push(cfg, message="test: demo")
    assert isinstance(result, CommitResult)
    assert result.committed is True
    assert result.pushed is False  # auto_push=False in the fixture
    log = _run(["git", "log", "--oneline"], cwd=tmp_log_repo)
    assert "test: demo" in log


def test_no_changes_no_commit(tmp_config: Path, tmp_log_repo: Path):
    cfg = load_config()
    result = commit_and_push(cfg, message="empty")
    assert result.committed is False

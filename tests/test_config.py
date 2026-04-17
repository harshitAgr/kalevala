"""Config loading and defaults."""
from pathlib import Path

import pytest

from kalevala.config import Config, load_config


def test_load_config_reads_toml(tmp_config: Path):
    cfg = load_config()
    assert isinstance(cfg, Config)
    assert cfg.model == "claude-sonnet-4-6"
    assert cfg.auto_push is False
    assert cfg.git_remote == "origin"
    assert cfg.git_branch == "main"


def test_log_repo_path_expanded(tmp_config: Path, tmp_log_repo: Path):
    cfg = load_config()
    assert cfg.log_repo_path == tmp_log_repo


def test_state_paths_under_log_repo(tmp_config: Path, tmp_log_repo: Path):
    cfg = load_config()
    assert cfg.state_dir == tmp_log_repo / ".kalevala"
    assert cfg.lock_path == tmp_log_repo / ".kalevala" / "lock"
    assert cfg.state_file == tmp_log_repo / ".kalevala" / "processed_sessions.json"
    assert cfg.pending_file == tmp_log_repo / ".kalevala" / "pending.json"
    assert cfg.status_file == tmp_log_repo / ".kalevala" / "status.json"
    assert cfg.errors_log == tmp_log_repo / ".kalevala" / "errors.log"


def test_missing_config_raises_clear_error(monkeypatch, tmp_path: Path):
    missing = tmp_path / "nope.toml"
    monkeypatch.setenv("KALEVALA_CONFIG", str(missing))
    with pytest.raises(FileNotFoundError, match="kalevala config not found"):
        load_config()

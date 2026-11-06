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


def test_secret_env_files_default_empty_and_expanded(tmp_config: Path, monkeypatch, tmp_path: Path):
    assert load_config().secret_env_files == ()
    monkeypatch.setenv("HOME", str(tmp_path))
    tmp_config.write_text(tmp_config.read_text() + 'secret_env_files = ["~/.config/tool/env"]\n')
    assert load_config().secret_env_files == (tmp_path / ".config" / "tool" / "env",)


def test_secret_env_files_must_be_a_list_of_paths(tmp_config: Path):
    tmp_config.write_text(tmp_config.read_text() + 'secret_env_files = "~/.config/tool/env"\n')
    with pytest.raises(ValueError, match="secret_env_files must be a list"):
        load_config()


def test_claude_json_path_follows_claude_config_dir(tmp_config: Path, tmp_path: Path):
    assert load_config().claude_json_path == tmp_path / "claude" / ".claude.json"


def test_claude_json_path_defaults_to_home(tmp_config: Path, monkeypatch, tmp_path: Path):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    assert load_config().claude_json_path == tmp_path / "home" / ".claude.json"

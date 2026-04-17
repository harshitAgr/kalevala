"""Shared pytest fixtures."""
import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tmp_log_repo(tmp_path: Path) -> Path:
    """A temp directory set up as a git repo, simulating kalevala-log."""
    repo = tmp_path / "kalevala-log"
    repo.mkdir()
    (repo / "entries").mkdir()
    (repo / ".kalevala").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)
    return repo


@pytest.fixture
def tmp_config(tmp_path: Path, tmp_log_repo: Path, monkeypatch) -> Path:
    """A temp config file pointing at tmp_log_repo."""
    config_dir = tmp_path / ".config" / "kalevala"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "config.toml"
    config_file.write_text(
        f'log_repo_path = "{tmp_log_repo}"\n'
        'model = "claude-sonnet-4-6"\n'
        'auto_push = false\n'
        'git_remote = "origin"\n'
        'git_branch = "main"\n'
    )
    monkeypatch.setenv("KALEVALA_CONFIG", str(config_file))
    return config_file


@pytest.fixture
def sample_transcript(tmp_path: Path) -> Path:
    """A minimal fixture transcript JSONL."""
    path = tmp_path / "transcript.jsonl"
    entries = [
        {"uuid": "msg_1", "role": "user", "content": "fix the request handler crash"},
        {"uuid": "msg_2", "role": "assistant", "content": "I'll investigate src/myapp/handlers.py"},
        {"uuid": "msg_3", "role": "assistant", "content": "Fixed: added empty-body guard"},
    ]
    with path.open("w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return path

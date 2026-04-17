"""Load ~/.config/kalevala/config.toml (or $KALEVALA_CONFIG override)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    log_repo_path: Path
    model: str
    auto_push: bool
    git_remote: str
    git_branch: str
    scrub_threshold: int = 20
    lock_wait_seconds: int = 30

    @property
    def state_dir(self) -> Path:
        return self.log_repo_path / ".kalevala"

    @property
    def lock_path(self) -> Path:
        return self.state_dir / "lock"

    @property
    def state_file(self) -> Path:
        return self.state_dir / "processed_sessions.json"

    @property
    def pending_file(self) -> Path:
        return self.state_dir / "pending.json"

    @property
    def status_file(self) -> Path:
        return self.state_dir / "status.json"

    @property
    def errors_log(self) -> Path:
        return self.state_dir / "errors.log"

    @property
    def entries_dir(self) -> Path:
        return self.log_repo_path / "entries"


def _config_path() -> Path:
    override = os.environ.get("KALEVALA_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".config" / "kalevala" / "config.toml"


def load_config() -> Config:
    path = _config_path()
    if not path.exists():
        raise FileNotFoundError(f"kalevala config not found at {path}")
    with path.open("rb") as f:
        data = tomllib.load(f)
    log_repo_path = Path(data["log_repo_path"]).expanduser().resolve()
    return Config(
        log_repo_path=log_repo_path,
        model=data.get("model", "claude-sonnet-4-6"),
        auto_push=bool(data.get("auto_push", True)),
        git_remote=data.get("git_remote", "origin"),
        git_branch=data.get("git_branch", "main"),
        scrub_threshold=int(data.get("scrub_threshold", 20)),
        lock_wait_seconds=int(data.get("lock_wait_seconds", 30)),
    )

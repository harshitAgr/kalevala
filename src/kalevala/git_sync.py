"""git operations via subprocess. No third-party git library.

Flow:
  add -A → commit (skip if nothing to commit) → push (if auto_push)
On push failure due to non-fast-forward:
  fetch → merge --no-rebase. If no conflict, push. Else queue the push
  in pending.json and surface via status.
"""
from __future__ import annotations

import datetime as _dt
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Config


class GitError(Exception):
    """Raised when a git command fails in a way the caller should know about."""


@dataclass
class CommitResult:
    committed: bool
    pushed: bool
    message: str


def _git(cfg: Config, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cfg.log_repo_path,
        capture_output=True,
        text=True,
        check=check,
    )


def _log_git_error(cfg: Config, operation: str, stderr: str) -> None:
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    with cfg.errors_log.open("a") as f:
        f.write(f"[{_dt.datetime.now().isoformat()}] git {operation} failed: {stderr.strip()}\n")


def _has_staged_or_unstaged_changes(cfg: Config) -> bool:
    out = _git(cfg, "status", "--porcelain")
    return bool(out.stdout.strip())


def _queue_push(cfg: Config, message: str, reason: str, stderr: str = "") -> None:
    import uuid as _uuid
    path = cfg.pending_file
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list = []
    if path.exists():
        try:
            loaded = json.loads(path.read_text())
            if isinstance(loaded, list):
                existing = loaded
        except json.JSONDecodeError:
            existing = []
    entry = {
        "queue_id": _uuid.uuid4().hex,
        "kind": "push",
        "message": message,
        "reason": reason,
    }
    if stderr:
        entry["stderr"] = stderr.strip()
    existing.append(entry)
    path.write_text(json.dumps(existing, indent=2))


def commit_and_push(cfg: Config, message: str) -> CommitResult:
    if not _has_staged_or_unstaged_changes(cfg):
        return CommitResult(False, False, "nothing to commit")
    _git(cfg, "add", "-A")
    try:
        _git(cfg, "commit", "-m", message)
    except subprocess.CalledProcessError as e:
        raise GitError(f"git commit failed: {e.stderr.strip()}") from e

    if not cfg.auto_push:
        return CommitResult(True, False, "auto_push disabled")

    push = _git(cfg, "push", cfg.git_remote, cfg.git_branch, check=False)
    if push.returncode == 0:
        return CommitResult(True, True, "pushed")

    _log_git_error(cfg, "push", push.stderr)

    fetch = _git(cfg, "fetch", cfg.git_remote, check=False)
    if fetch.returncode != 0:
        _log_git_error(cfg, "fetch", fetch.stderr)
        _queue_push(cfg, message, reason="fetch_failed", stderr=fetch.stderr)
        return CommitResult(True, False, "fetch failed — queued")

    merge = _git(cfg, "merge", "--no-rebase", "--no-edit",
                 f"{cfg.git_remote}/{cfg.git_branch}", check=False)
    if merge.returncode == 0:
        push2 = _git(cfg, "push", cfg.git_remote, cfg.git_branch, check=False)
        if push2.returncode == 0:
            return CommitResult(True, True, "merged + pushed")
        _log_git_error(cfg, "push_after_merge", push2.stderr)
        _queue_push(cfg, message, reason="push_failed_after_merge", stderr=push2.stderr)
        return CommitResult(True, False, "merged but push still failed — queued")

    # merge conflict
    _git(cfg, "merge", "--abort", check=False)
    _log_git_error(cfg, "merge", merge.stderr)
    _queue_push(cfg, message, reason="git_conflict", stderr=merge.stderr)
    return CommitResult(True, False, "git conflict — queued for manual resolution")

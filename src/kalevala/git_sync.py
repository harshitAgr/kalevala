"""git operations via subprocess. No third-party git library.

Flow:
  add -A → commit (skip if nothing to commit) → push (if auto_push)
On push failure due to non-fast-forward:
  fetch → merge --no-rebase. If no conflict, push. Else queue the push
  in pending.json and surface via status.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Config


class GitError(Exception):
    pass


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


def _has_staged_or_unstaged_changes(cfg: Config) -> bool:
    out = _git(cfg, "status", "--porcelain")
    return bool(out.stdout.strip())


def _queue_push(cfg: Config, message: str, reason: str) -> None:
    path = cfg.pending_file
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
        except json.JSONDecodeError:
            existing = []
    existing.append({"kind": "push", "message": message, "reason": reason})
    path.write_text(json.dumps(existing, indent=2))


def commit_and_push(cfg: Config, message: str) -> CommitResult:
    if not _has_staged_or_unstaged_changes(cfg):
        return CommitResult(False, False, "nothing to commit")
    _git(cfg, "add", "-A")
    _git(cfg, "commit", "-m", message)

    if not cfg.auto_push:
        return CommitResult(True, False, "auto_push disabled")

    push = _git(cfg, "push", cfg.git_remote, cfg.git_branch, check=False)
    if push.returncode == 0:
        return CommitResult(True, True, "pushed")

    # non-fast-forward: try merge
    _git(cfg, "fetch", cfg.git_remote, check=False)
    merge = _git(cfg, "merge", "--no-rebase", "--no-edit",
                 f"{cfg.git_remote}/{cfg.git_branch}", check=False)
    if merge.returncode == 0:
        push2 = _git(cfg, "push", cfg.git_remote, cfg.git_branch, check=False)
        if push2.returncode == 0:
            return CommitResult(True, True, "merged + pushed")
        _queue_push(cfg, message, reason="push_failed_after_merge")
        return CommitResult(True, False, "merged but push still failed — queued")

    # merge conflict
    _git(cfg, "merge", "--abort", check=False)
    _queue_push(cfg, message, reason="git_conflict")
    return CommitResult(True, False, "git conflict — queued for manual resolution")

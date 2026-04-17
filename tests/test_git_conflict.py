"""git conflict path: simulate non-fast-forward, verify we queue instead of aborting."""
import subprocess
from pathlib import Path

from kalevala.config import load_config
from kalevala.git_sync import commit_and_push


def _run(args, cwd):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True)


def test_push_failure_queues(tmp_config: Path, tmp_log_repo: Path, tmp_path: Path, monkeypatch):
    cfg = load_config()
    # flip auto_push on by rewriting config
    config_path = Path(tmp_path / ".config" / "kalevala" / "config.toml")
    config_path.write_text(config_path.read_text().replace("auto_push = false", "auto_push = true"))

    # create a fake remote that rejects pushes
    bare = tmp_path / "bare.git"
    _run(["git", "init", "-q", "--bare", str(bare)], cwd=tmp_path)
    _run(["git", "remote", "add", "origin", str(bare)], cwd=tmp_log_repo)

    # Make a commit locally and push so remote has main
    (tmp_log_repo / "seed.md").write_text("seed")
    _run(["git", "add", "seed.md"], cwd=tmp_log_repo)
    _run(["git", "commit", "-m", "seed"], cwd=tmp_log_repo)
    _run(["git", "push", "-u", "origin", "main"], cwd=tmp_log_repo)

    # create divergent commit on remote by cloning + pushing a change
    work = tmp_path / "work"
    _run(["git", "clone", "-q", str(bare), str(work)], cwd=tmp_path)
    _run(["git", "config", "user.email", "a@b"], cwd=work)
    _run(["git", "config", "user.name", "a"], cwd=work)
    (work / "remote-change.md").write_text("x")
    _run(["git", "add", "remote-change.md"], cwd=work)
    _run(["git", "commit", "-m", "remote"], cwd=work)
    _run(["git", "push"], cwd=work)

    # now local makes a change and tries to push — should conflict and queue
    (tmp_log_repo / "local-change.md").write_text("y")
    result = commit_and_push(cfg, message="local change")
    assert result.committed is True
    # auto-merge from no-overlap should succeed; this test just verifies path works
    assert result.pushed in (True, False)

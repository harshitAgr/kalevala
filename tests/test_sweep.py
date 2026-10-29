"""sweep: journal sessions that ended without running the hook."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

from kalevala.config import load_config
from kalevala.pipeline import SWEEP_DAYS, run_hook, sweep_unended
from kalevala.state import State

from test_activity_dates import day_file, prompts, recording_client, turn, write_transcript


@pytest.fixture
def setup(tmp_config: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    with tmp_config.open("a") as f:
        f.write('timezone = "UTC"\n')
    return load_config(), tmp_path / "claude" / "projects"


def _session(root: Path, sid: str, ts: str, project: str = "myapp", age_days: float = 0) -> Path:
    """A two-turn session whose transcript was last written `age_days` ago."""
    cwd = f"/home/u/projects/{project}"
    path = write_transcript(root / f"-home-u-projects-{project}" / f"{sid}.jsonl", [
        {**turn(0, ts, cwd=cwd), "message": {"role": "user", "content": f"work in {sid}"}},
        turn(1, ts, "assistant", cwd=cwd),
    ])
    mtime = time.time() - age_days * 86400
    os.utime(path, (mtime, mtime))
    return path


def test_sweep_journals_a_session_that_ended_without_its_hook(setup):
    cfg, root = setup
    _session(root, "retired", "2026-10-27T09:00:00Z")
    client = recording_client()

    assert sweep_unended(cfg, client, "2026-10-29", root=root, open_ids=set()) == ["retired"]
    assert "id: retired" in day_file(cfg, "2026-10-27").read_text()
    assert State(cfg).get("retired").last_processed_msg_idx == 1

    # journaled once: the cursor is at its last turn, so the next sweep leaves it
    assert sweep_unended(cfg, client, "2026-10-29", root=root, open_ids=set()) == []
    assert client.messages.create.call_count == 1


def test_sweep_leaves_running_queued_skipped_and_old_sessions(setup):
    cfg, root = setup
    for sid in ("running", "queued", "own"):
        _session(root, sid, "2026-10-27T09:00:00Z")
    _session(root, "old", "2026-10-10T09:00:00Z", age_days=SWEEP_DAYS + 1)
    cfg.pending_file.write_text(json.dumps([
        {"kind": "session", "session_id": "queued", "transcript_path": "x", "next_retry_at": 0},
    ]))
    client = recording_client()

    journaled = sweep_unended(cfg, client, "2026-10-29", skip={"own"}, root=root, open_ids={"running"})

    assert journaled == [] and client.messages.create.call_count == 0


def test_sweep_stops_at_the_limit_oldest_first(setup):
    cfg, root = setup
    _session(root, "newest", "2026-10-28T09:00:00Z", age_days=1)
    _session(root, "oldest", "2026-10-26T09:00:00Z", age_days=3)
    _session(root, "middle", "2026-10-27T09:00:00Z", age_days=2)
    client = recording_client()

    assert sweep_unended(cfg, client, "2026-10-29", limit=2, root=root, open_ids=set()) == ["oldest", "middle"]
    assert sweep_unended(cfg, client, "2026-10-29", limit=2, root=root, open_ids=set()) == ["newest"]


def test_sweep_logs_a_failure_and_carries_on(setup):
    cfg, root = setup
    _session(root, "flaky", "2026-10-27T09:00:00Z", age_days=2)
    _session(root, "fine", "2026-10-27T10:00:00Z", age_days=1)
    client = recording_client()
    ok = client.messages.create.return_value

    def create(**kwargs):
        if "work in flaky" in kwargs["messages"][0]["content"]:
            raise TimeoutError("simulated summary timeout")
        return ok
    client.messages.create.side_effect = create

    assert sweep_unended(cfg, client, "2026-10-29", root=root, open_ids=set()) == ["fine"]
    assert "sweep failure flaky: simulated summary timeout" in cfg.errors_log.read_text()
    assert State(cfg).get("flaky") is None  # so the next sweep tries it again


def test_hook_sweeps_after_its_own_session_with_each_sessions_own_project_dir(setup, tmp_path, monkeypatch):
    cfg, root = setup
    monkeypatch.setenv("HOME", "/home/u")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/home/u/projects/own")  # the hook's own session
    own = _session(root, "own", "2026-10-29T08:00:00Z", project="own")
    _session(root, "retired", "2026-10-28T09:00:00Z", project="other")
    client = recording_client()
    body = json.loads(client.messages.create.return_value.content[0].text)
    client.messages.create.return_value.content[0].text = json.dumps(
        {**body, "files_touched": ["/home/u/projects/other/x.py"]})

    result = run_hook("own", own, cfg, client, today="2026-10-29")

    assert result.processed is True and result.error is None
    assert len(prompts(client)) == 2
    # the swept session's paths are relative to its own project, not the hook's
    assert "`myapp/x.py`" in day_file(cfg, "2026-10-28").read_text()
    assert State(cfg).get("retired") is not None


def test_cli_sweep_prints_what_it_journaled(setup, monkeypatch, capsys):
    from kalevala import cli
    cfg, root = setup
    _session(root, "retired", "2026-10-27T09:00:00Z")
    monkeypatch.setattr(cli, "_client", recording_client)
    monkeypatch.setattr(sys, "argv", ["kalevala", "sweep"])

    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "journaled  retired" in out and "sweep complete: 1 journaled" in out

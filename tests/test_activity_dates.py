"""Sessions are filed under the days their turns were written, not the day the hook runs."""
import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kalevala.config import load_config
from kalevala.pipeline import _drain_pending, run_hook


def turn(i: int, ts: str, role: str = "user", cwd: str = "/home/u/projects/myapp") -> dict:
    return {"type": role, "uuid": f"u{i}", "timestamp": ts, "cwd": cwd,
            "message": {"role": role, "content": f"turn {i}"}}


def write_transcript(path: Path, lines: list[dict], mode: str = "w") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode) as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return path


def recording_client() -> MagicMock:
    """Returns the same summary every call; the model's time guess is deliberately wrong."""
    client = MagicMock()
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps({
        "summary": "did work", "files_touched": [], "commits": [], "bugs_fixed": [],
        "decisions": [], "learnings": [], "notes_for_later": [], "open_threads": [],
        "time_range": ["00:00", "00:00"], "project": "myapp",
    }))]
    client.messages.create.return_value = resp
    return client


def prompts(client: MagicMock) -> list[str]:
    return [c.kwargs["messages"][0]["content"] for c in client.messages.create.call_args_list]


def day_file(cfg, day: str) -> Path:
    y, m, _ = day.split("-")
    return cfg.entries_dir / y / m / f"{day}.md"


@pytest.fixture
def utc_config(tmp_config: Path) -> Path:
    with tmp_config.open("a") as f:
        f.write('timezone = "UTC"\n')
    return tmp_config


def test_session_closed_next_morning_is_filed_under_the_days_it_ran(utc_config, tmp_path):
    cfg = load_config()
    transcript = write_transcript(tmp_path / "s.jsonl", [
        turn(0, "2026-10-12T15:00:00Z"), turn(1, "2026-10-12T15:30:00Z", "assistant"),
        turn(2, "2026-10-13T08:00:00Z"), turn(3, "2026-10-13T09:00:00Z", "assistant"),
    ])
    client = recording_client()

    result = run_hook("s1", transcript, cfg, client, today="2026-10-14")

    assert result.processed is True
    assert not day_file(cfg, "2026-10-14").exists()
    day1 = day_file(cfg, "2026-10-12").read_text()
    day2 = day_file(cfg, "2026-10-13").read_text()
    assert "(15:00–15:30) · id: s1" in day1 and "continued from" not in day1
    assert "(08:00–09:00) · id: s1 · continued from 2026-10-12" in day2
    first, second = prompts(client)
    assert "turn 1" in first and "turn 2" not in first
    assert "turn 2" in second and "turn 1" not in second


def test_same_day_resume_resummarizes_the_whole_day(utc_config, tmp_path):
    cfg = load_config()
    transcript = write_transcript(tmp_path / "s.jsonl", [
        turn(0, "2026-10-13T08:00:00Z"), turn(1, "2026-10-13T08:10:00Z", "assistant"),
    ])
    client = recording_client()
    run_hook("s1", transcript, cfg, client, today="2026-10-13")
    write_transcript(transcript, [
        turn(2, "2026-10-13T14:00:00Z"), turn(3, "2026-10-13T14:20:00Z", "assistant"),
    ], mode="a")

    assert run_hook("s1", transcript, cfg, client, today="2026-10-13").processed is True

    # the replaced block must still cover the morning, not only the resumed part
    assert "turn 0" in prompts(client)[-1] and "turn 3" in prompts(client)[-1]
    text = day_file(cfg, "2026-10-13").read_text()
    assert text.count("id: s1") == 1
    assert "(08:00–14:20)" in text


def test_resume_closed_without_new_turns_writes_nothing(utc_config, tmp_path):
    cfg = load_config()
    transcript = write_transcript(tmp_path / "s.jsonl", [
        {"type": "summary", "summary": "x"},
        turn(0, "2026-10-13T08:00:00Z"), turn(1, "2026-10-13T08:10:00Z", "assistant"),
    ])
    client = recording_client()
    run_hook("s1", transcript, cfg, client, today="2026-10-13")
    # lines that are not turns (hooks, snapshots) must not count as new work
    write_transcript(transcript, [{"type": "system", "content": ""}, {"type": "file-history-snapshot"}], mode="a")

    result = run_hook("s1", transcript, cfg, client, today="2026-10-14")

    assert result.processed is False
    assert client.messages.create.call_count == 1
    assert not day_file(cfg, "2026-10-14").exists()


def test_timezone_setting_decides_the_day(tmp_config, tmp_path):
    with tmp_config.open("a") as f:
        f.write('timezone = "Europe/Helsinki"\n')
    cfg = load_config()
    transcript = write_transcript(tmp_path / "s.jsonl", [turn(0, "2026-10-12T22:30:00Z")])

    run_hook("s1", transcript, cfg, recording_client(), today="2026-10-14")

    assert "(01:30–01:30) · id: s1" in day_file(cfg, "2026-10-13").read_text()


def test_drain_drops_sessions_whose_transcript_is_gone(tmp_config, tmp_path):
    cfg = load_config()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    cfg.pending_file.write_text(json.dumps([
        {"queue_id": "q1", "kind": "session", "session_id": "ghost",
         "transcript_path": str(tmp_path / "never-written.jsonl"),
         "next_retry_at": _dt.datetime.now().timestamp() - 60, "attempts": 3, "reason": "lock_timeout"},
    ]))

    _drain_pending(cfg, recording_client(), today="2026-10-14")

    assert json.loads(cfg.pending_file.read_text()) == []
    assert "dropping queued session ghost" in cfg.errors_log.read_text()


def test_hook_is_a_noop_inside_our_own_summary_runs(tmp_config, tmp_path):
    cfg = load_config()
    payload = json.dumps({"session_id": "child", "transcript_path": str(tmp_path / "never-written.jsonl")})
    env = {**os.environ, "KALEVALA_CONFIG": str(tmp_config), "KALEVALA_INTERNAL": "1"}

    proc = subprocess.run([sys.executable, "-m", "kalevala", "hook"], input=payload,
                          env=env, capture_output=True, text=True)

    assert proc.returncode == 0
    assert not cfg.errors_log.exists()
    assert not cfg.pending_file.exists()


def test_cli_client_marks_its_children_internal(monkeypatch):
    from kalevala import clients
    seen = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs)
        return MagicMock(stdout="{}")
    monkeypatch.setattr(clients.subprocess, "run", fake_run)

    clients.ClaudeCliClient().messages.create(model="m", messages=[{"role": "user", "content": "hi"}])

    assert seen["env"]["KALEVALA_INTERNAL"] == "1"

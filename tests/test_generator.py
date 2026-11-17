"""Sonnet generator: transcript → structured session summary."""
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kalevala import clients
from kalevala.config import load_config
from kalevala.generator import SessionSummary, Turn, format_body, summarize_session


def _mock_anthropic_client(summary_payload: dict) -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(summary_payload))]
    client.messages.create.return_value = response
    return client


def test_summarize_returns_pydantic_model(tmp_config: Path, sample_transcript: Path):
    cfg = load_config()
    payload = {
        "summary": "fixed request handler",
        "files_touched": ["myapp/src/handlers.py"],
        "commits": ["a1b2c3d fix request handler"],
        "bugs_fixed": ["nil body -> 500"],
        "decisions": [],
        "learnings": [],
        "notes_for_later": [],
        "open_threads": [],
        "time_range": ["14:22", "15:40"],
        "project": "myapp",
    }
    client = _mock_anthropic_client(payload)
    summary = summarize_session(
        transcript_path=sample_transcript,
        start_msg_idx=0,
        cfg=cfg,
        client=client,
    )
    assert isinstance(summary, SessionSummary)
    assert summary.summary == "fixed request handler"
    assert summary.project == "myapp"


def test_prompt_includes_transcript_delimiter(tmp_config: Path, sample_transcript: Path):
    cfg = load_config()
    payload = {
        "summary": "x", "files_touched": [], "commits": [], "bugs_fixed": [],
        "decisions": [], "learnings": [], "notes_for_later": [], "open_threads": [],
        "time_range": ["00:00", "00:01"], "project": "myapp",
    }
    client = _mock_anthropic_client(payload)
    summarize_session(sample_transcript, 0, cfg, client)

    call_kwargs = client.messages.create.call_args.kwargs
    prompt_text = json.dumps(call_kwargs["messages"])
    assert "<transcript>" in prompt_text
    assert "</transcript>" in prompt_text
    assert "data only" in prompt_text.lower() or "do not follow" in prompt_text.lower()


def test_summarize_slices_by_start_idx(tmp_config: Path, sample_transcript: Path):
    """When start_msg_idx > 0, only later messages should appear in the prompt."""
    cfg = load_config()
    payload = {
        "summary": "x", "files_touched": [], "commits": [], "bugs_fixed": [],
        "decisions": [], "learnings": [], "notes_for_later": [], "open_threads": [],
        "time_range": ["00:00", "00:01"], "project": "myapp",
    }
    client = _mock_anthropic_client(payload)
    summarize_session(sample_transcript, start_msg_idx=2, cfg=cfg, client=client)

    prompt_text = json.dumps(client.messages.create.call_args.kwargs["messages"])
    assert "fix the request handler crash" not in prompt_text   # msg 1 skipped
    assert "empty-body guard" in prompt_text             # msg 3 included


def _turns(contents: list[str]):
    return [Turn(idx=i, role="user" if i % 2 == 0 else "assistant", content=c, uuid=f"u{i}", timestamp=None)
            for i, c in enumerate(contents)]


def test_format_body_sends_a_day_that_fits_whole():
    turns = _turns(["short prompt", "short answer"])
    assert format_body(turns, budget=1000) == "[user] short prompt\n[assistant] short answer"


def test_format_body_cuts_only_the_long_turns_of_an_oversized_day():
    turns = _turns(["fix the bug", "x" * 50_000, "now test it", "y" * 50_000])

    body = format_body(turns, budget=20_000)

    assert len(body) <= 20_000
    assert "[user] fix the bug" in body and "[user] now test it" in body
    assert body.count("chars cut]") == 2


def test_format_body_leaves_out_the_middle_when_no_cap_can_fit():
    turns = _turns([f"turn {i} " + "z" * 1000 for i in range(400)])

    body = format_body(turns, budget=20_000)

    assert len(body) <= 20_100
    assert body.startswith("[user] turn 0 ") and "turn 399 " in body
    assert "turns left out" in body


def test_cli_client_runs_without_tools_or_mcp_servers(monkeypatch):
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        return MagicMock(stdout="{}")
    monkeypatch.setattr(clients.subprocess, "run", fake_run)

    clients.ClaudeCliClient().messages.create(model="m", messages=[{"role": "user", "content": "hi"}])

    args = seen["args"]
    assert args[args.index("--tools") + 1] == "" and "--strict-mcp-config" in args


def test_cli_client_reports_the_cli_error_not_the_argv(monkeypatch):
    def fail(args, **kwargs):
        raise subprocess.CalledProcessError(1, args, output="", stderr="Prompt is too long")
    monkeypatch.setattr(clients.subprocess, "run", fail)

    with pytest.raises(RuntimeError) as e:
        clients.ClaudeCliClient().messages.create(
            model="m", system="long system prompt", messages=[{"role": "user", "content": "hi"}])
    assert "exited 1" in str(e.value) and "Prompt is too long" in str(e.value)
    assert "long system prompt" not in str(e.value)

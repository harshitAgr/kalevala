"""Sonnet generator: transcript → structured session summary."""
import json
from pathlib import Path
from unittest.mock import MagicMock

from kalevala.config import load_config
from kalevala.generator import SessionSummary, summarize_session


def _mock_anthropic_client(summary_payload: dict) -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(summary_payload))]
    client.messages.create.return_value = response
    return client


def test_summarize_returns_pydantic_model(tmp_config: Path, sample_transcript: Path):
    cfg = load_config()
    payload = {
        "summary": "fixed val loop",
        "files_touched": ["opet/src/val.py"],
        "commits": ["a1b2c3d fix val"],
        "bugs_fixed": ["empty batch → NaN"],
        "decisions": [],
        "learnings": [],
        "notes_for_later": [],
        "open_threads": [],
        "time_range": ["14:22", "15:40"],
        "project": "opet",
    }
    client = _mock_anthropic_client(payload)
    summary = summarize_session(
        transcript_path=sample_transcript,
        start_msg_idx=0,
        cfg=cfg,
        client=client,
    )
    assert isinstance(summary, SessionSummary)
    assert summary.summary == "fixed val loop"
    assert summary.project == "opet"


def test_prompt_includes_transcript_delimiter(tmp_config: Path, sample_transcript: Path):
    cfg = load_config()
    payload = {
        "summary": "x", "files_touched": [], "commits": [], "bugs_fixed": [],
        "decisions": [], "learnings": [], "notes_for_later": [], "open_threads": [],
        "time_range": ["00:00", "00:01"], "project": "opet",
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
        "time_range": ["00:00", "00:01"], "project": "opet",
    }
    client = _mock_anthropic_client(payload)
    summarize_session(sample_transcript, start_msg_idx=2, cfg=cfg, client=client)

    prompt_text = json.dumps(client.messages.create.call_args.kwargs["messages"])
    assert "fix the val loop crash" not in prompt_text   # msg 1 skipped
    assert "empty-batch guard" in prompt_text             # msg 3 included

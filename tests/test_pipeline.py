"""End-to-end pipeline for a single session, using mocked Sonnet."""
import datetime as _dt
import json
from pathlib import Path
from unittest.mock import MagicMock

from kalevala.config import load_config
from kalevala.pipeline import run_hook
from kalevala.state import State


def _mock_client(payload: dict) -> MagicMock:
    client = MagicMock()
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(payload))]
    client.messages.create.return_value = resp
    return client


def _transcript(path: Path, n: int = 3) -> Path:
    with path.open("w") as f:
        for i in range(n):
            f.write(json.dumps({"uuid": f"msg_{i}", "role": "assistant", "content": f"step {i}"}) + "\n")
    return path


def test_first_run_creates_daily_entry(tmp_config: Path, tmp_log_repo: Path, tmp_path: Path):
    cfg = load_config()
    transcript = _transcript(tmp_path / "t.jsonl")
    client = _mock_client({
        "summary": "did work", "files_touched": [], "commits": [], "bugs_fixed": [],
        "decisions": [], "learnings": [], "notes_for_later": [], "open_threads": [],
        "time_range": ["10:00", "10:30"], "project": "myapp",
    })

    result = run_hook(
        session_id="abc123",
        transcript_path=transcript,
        cfg=cfg,
        client=client,
        today="2026-04-17",
    )
    assert result.processed is True
    daily = cfg.entries_dir / "2026" / "04" / "2026-04-17.md"
    assert daily.exists()
    assert "abc123" in daily.read_text()


LEAKED = "fake0token0a1b2c3d4e5f6a7b8c9d0e1f2a3b4"  # shapeless 40-char token, not a real credential


def _quoting_client(secret: str) -> MagicMock:
    """A summariser that quotes the secret, as one did into a pushed journal entry."""
    return _mock_client({
        "summary": f"rotated the token {secret} for the codabench MCP",
        "files_touched": [], "commits": [], "bugs_fixed": [], "decisions": [],
        "learnings": [f"the old value was {secret}"], "notes_for_later": [], "open_threads": [],
        "time_range": ["10:00", "10:30"], "project": "myapp",
    })


def _entries_text(cfg) -> str:
    return "".join(p.read_text() for p in cfg.entries_dir.rglob("*.md"))


def test_secret_in_environment_is_redacted_from_the_journal(tmp_config: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KT_TEST_API_TOKEN", LEAKED)
    cfg = load_config()
    result = run_hook("abc", _transcript(tmp_path / "t.jsonl"), cfg, _quoting_client(LEAKED), today="2026-04-17")
    assert result.processed is True
    text = _entries_text(cfg)
    assert LEAKED not in text
    assert "[REDACTED:literal]" in text


def test_secret_in_claude_mcp_config_is_redacted_from_the_journal(tmp_config: Path, tmp_path: Path):
    cfg = load_config()
    cfg.claude_json_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.claude_json_path.write_text(json.dumps(
        {"mcpServers": {"codabench": {"env": {"CODABENCH_API_TOKEN": LEAKED}}}}))
    result = run_hook("abc", _transcript(tmp_path / "t.jsonl"), cfg, _quoting_client(LEAKED), today="2026-04-17")
    assert result.processed is True
    assert LEAKED not in _entries_text(cfg)


def test_secret_in_a_declared_env_file_is_redacted_from_the_journal(tmp_config: Path, tmp_path: Path):
    env_file = tmp_path / "tool.env"
    env_file.write_text(f"CODABENCH_API_TOKEN={LEAKED}\n")
    tmp_config.write_text(tmp_config.read_text() + f'secret_env_files = ["{env_file}"]\n')
    cfg = load_config()
    result = run_hook("abc", _transcript(tmp_path / "t.jsonl"), cfg, _quoting_client(LEAKED), today="2026-04-17")
    assert result.processed is True
    assert LEAKED not in _entries_text(cfg)


def test_unreadable_secret_source_fails_closed_without_calling_the_model(tmp_config: Path, tmp_path: Path):
    cfg = load_config()
    cfg.claude_json_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.claude_json_path.write_text('{"mcpServers": {')  # truncated, as when read mid-write
    client = _quoting_client(LEAKED)

    result = run_hook("abc", _transcript(tmp_path / "t.jsonl"), cfg, client, today="2026-04-17")

    assert result.processed is False
    assert "cannot read MCP secrets" in (result.error or "")
    client.messages.create.assert_not_called()
    assert not list(cfg.entries_dir.rglob("*.md"))      # nothing journaled
    assert State(cfg).get("abc") is None                # cursor not advanced: the sweep retries it


def test_second_run_same_session_is_idempotent(tmp_config: Path, tmp_path: Path):
    cfg = load_config()
    transcript = _transcript(tmp_path / "t.jsonl", n=3)
    client = _mock_client({
        "summary": "x", "files_touched": [], "commits": [], "bugs_fixed": [],
        "decisions": [], "learnings": [], "notes_for_later": [], "open_threads": [],
        "time_range": ["10:00", "10:30"], "project": "myapp",
    })
    r1 = run_hook("abc", transcript, cfg, client, today="2026-04-17")
    r2 = run_hook("abc", transcript, cfg, client, today="2026-04-17")
    assert r1.processed is True
    assert r2.processed is False  # no new messages since last run


def test_hook_never_raises(tmp_config: Path, tmp_path: Path):
    cfg = load_config()
    transcript = _transcript(tmp_path / "t.jsonl")
    client = MagicMock()
    client.messages.create.side_effect = TimeoutError("simulated summary timeout")
    result = run_hook("abc", transcript, cfg, client, today="2026-04-17")
    assert result.processed is False
    assert result.error is not None


def test_missing_transcript_is_a_quiet_no_op(tmp_config: Path, tmp_path: Path):
    """A session closed before its first prompt never writes a transcript; that is not a failure."""
    cfg = load_config()
    client = MagicMock()
    client.messages.create.side_effect = AssertionError("the model must not be called")

    result = run_hook("abc", tmp_path / "missing.jsonl", cfg, client, today="2026-04-17")

    assert result.processed is False and result.error is None
    assert not cfg.errors_log.exists() or "transcript missing" not in cfg.errors_log.read_text()


def test_empty_transcript_first_run_skips_llm(tmp_config: Path, tmp_path: Path):
    """Empty transcript on first run should not call Sonnet or write a daily file."""
    cfg = load_config()
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    client = MagicMock()
    client.messages.create.side_effect = AssertionError("Sonnet must not be called")

    result = run_hook("new", empty, cfg, client, today="2026-04-17")
    assert result.processed is False
    assert not (cfg.entries_dir / "2026" / "04" / "2026-04-17.md").exists()


def test_drain_preserves_items_added_during_drain(tmp_config: Path, tmp_path: Path, monkeypatch):
    """When a concurrent writer re-queues during drain, drain must preserve the new entry
    AND must not duplicate the original entry."""
    cfg = load_config()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)

    import uuid as _uuid
    due = _dt.datetime.now().timestamp() - 60
    seed_qid = _uuid.uuid4().hex
    cfg.pending_file.write_text(json.dumps([
        {"queue_id": seed_qid, "kind": "session", "session_id": "drainA",
         "transcript_path": str(_transcript(tmp_path / "drainA.jsonl")),
         "next_retry_at": due, "attempts": 0, "reason": "seed"}
    ]))

    from kalevala import pipeline as _pl
    def _injecting_process(*args, **kwargs):
        current = _pl._read_pending(cfg)
        current.append({"queue_id": _uuid.uuid4().hex, "kind": "push",
                        "message": "injected-during-drain",
                        "next_retry_at": 0, "attempts": 0})
        _pl._write_pending(cfg, current)
        raise RuntimeError("simulated summary failure")
    monkeypatch.setattr(_pl, "_process_session", _injecting_process)

    client = MagicMock()
    _pl._drain_pending(cfg, client, today="2026-04-17")

    pending = json.loads(cfg.pending_file.read_text())
    # injected entry is preserved
    assert any(e.get("message") == "injected-during-drain" for e in pending), pending
    # seed appears EXACTLY ONCE (failure path mutates it in-place, re-read must not duplicate)
    seed_entries = [e for e in pending if e.get("queue_id") == seed_qid]
    assert len(seed_entries) == 1, seed_entries

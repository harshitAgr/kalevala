"""End-to-end pipeline for a single session, using mocked Sonnet."""
import datetime as _dt
import json
from pathlib import Path
from unittest.mock import MagicMock

from kalevala.config import load_config
from kalevala.pipeline import run_hook


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
        "time_range": ["10:00", "10:30"], "project": "opet",
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


def test_second_run_same_session_is_idempotent(tmp_config: Path, tmp_path: Path):
    cfg = load_config()
    transcript = _transcript(tmp_path / "t.jsonl", n=3)
    client = _mock_client({
        "summary": "x", "files_touched": [], "commits": [], "bugs_fixed": [],
        "decisions": [], "learnings": [], "notes_for_later": [], "open_threads": [],
        "time_range": ["10:00", "10:30"], "project": "opet",
    })
    r1 = run_hook("abc", transcript, cfg, client, today="2026-04-17")
    r2 = run_hook("abc", transcript, cfg, client, today="2026-04-17")
    assert r1.processed is True
    assert r2.processed is False  # no new messages since last run


def test_hook_never_raises(tmp_config: Path, tmp_path: Path):
    cfg = load_config()
    transcript = tmp_path / "missing.jsonl"  # doesn't exist
    client = _mock_client({})
    result = run_hook("abc", transcript, cfg, client, today="2026-04-17")
    assert result.processed is False
    assert result.error is not None


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
    """When a pending-entry processor re-queues during drain, drain must not clobber it."""
    cfg = load_config()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)

    # seed a due session pending item whose transcript is missing (will fail -> requeue)
    due = _dt.datetime.now().timestamp() - 60
    cfg.pending_file.write_text(json.dumps([
        {"kind": "session", "session_id": "drainA", "transcript_path": str(tmp_path / "nope.jsonl"),
         "next_retry_at": due, "attempts": 0, "reason": "seed"}
    ]))

    # simulate: while draining, another writer appends a new entry
    from kalevala import pipeline as _pl
    original_process = _pl._process_session
    def _injecting_process(*args, **kwargs):
        # append a new pending entry as if another writer did so
        current = _pl._read_pending(cfg)
        current.append({"kind": "push", "message": "injected-during-drain",
                        "next_retry_at": 0, "attempts": 0})
        _pl._write_pending(cfg, current)
        return original_process(*args, **kwargs)
    monkeypatch.setattr(_pl, "_process_session", _injecting_process)

    client = MagicMock()
    _pl._drain_pending(cfg, client, today="2026-04-17")

    pending = json.loads(cfg.pending_file.read_text())
    # The injected entry must survive
    assert any(e.get("message") == "injected-during-drain" for e in pending), pending

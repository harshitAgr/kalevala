"""Full-pipeline integration test with mocked Sonnet."""
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock


def _transcript(path: Path, messages: list[str]) -> Path:
    with path.open("w") as f:
        for i, m in enumerate(messages):
            f.write(json.dumps({"uuid": f"u_{i}", "role": "assistant", "content": m}) + "\n")
    return path


def test_end_to_end_new_and_resume(tmp_config, tmp_log_repo, tmp_path):
    def _mk_payload(summary_text: str):
        return {
            "summary": summary_text, "files_touched": ["opet/src/a.py"],
            "commits": [], "bugs_fixed": [], "decisions": [],
            "learnings": [], "notes_for_later": [], "open_threads": [],
            "time_range": ["10:00", "10:30"], "project": "opet",
        }
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(_mk_payload("first run")))]
    client.messages.create.return_value = response

    transcript = _transcript(tmp_path / "t.jsonl", ["hello", "goodbye"])

    from kalevala.config import load_config
    from kalevala.pipeline import run_hook
    cfg = load_config()
    today = date.today().isoformat()

    # first run
    r1 = run_hook("sess-e2e", transcript, cfg, client, today=today)
    assert r1.processed is True

    daily_path = next(cfg.entries_dir.rglob("*.md"))
    assert "first run" in daily_path.read_text()
    assert "sess-e2e" in daily_path.read_text()

    # same session, new messages → resumed path
    _transcript(tmp_path / "t.jsonl", ["hello", "goodbye", "third message"])
    response2 = MagicMock()
    response2.content = [MagicMock(text=json.dumps(_mk_payload("second run")))]
    client.messages.create.return_value = response2

    r2 = run_hook("sess-e2e", tmp_path / "t.jsonl", cfg, client, today=today)
    assert r2.processed is True
    content = daily_path.read_text()
    assert "second run" in content
    # same-day: single session block
    assert content.count("### Session 1") == 1


def test_end_to_end_scrub_threshold_trips(tmp_config, tmp_log_repo, tmp_path, capsys):
    # forge a summary with many fake secrets to blow past threshold (20)
    fake_secrets = [f"AKIA{'X' * 16}" for _ in range(25)]
    payload = {
        "summary": " ".join(fake_secrets), "files_touched": [],
        "commits": [], "bugs_fixed": [], "decisions": [],
        "learnings": [], "notes_for_later": [], "open_threads": [],
        "time_range": ["10:00", "10:30"], "project": "opet",
    }
    client = MagicMock()
    response = MagicMock()
    response.content = [MagicMock(text=json.dumps(payload))]
    client.messages.create.return_value = response

    transcript = _transcript(tmp_path / "t.jsonl", ["garbage"])
    from kalevala.config import load_config
    from kalevala.pipeline import run_hook
    cfg = load_config()

    result = run_hook("overscrub", transcript, cfg, client, today=date.today().isoformat())
    assert result.processed is False
    # threshold warning should have gone to stderr
    err = capsys.readouterr().err
    assert "SCRUB_THRESHOLD_EXCEEDED" in err
    # pending.json should record it
    pending = json.loads(cfg.pending_file.read_text())
    assert any(x.get("reason") == "scrub_threshold_exceeded" for x in pending)

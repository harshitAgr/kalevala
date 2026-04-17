"""State file: processed_sessions.json read/modify/write."""
from pathlib import Path

from kalevala.config import load_config
from kalevala.state import SessionCursor, State


def test_empty_state_returns_none_for_unknown(tmp_config: Path):
    cfg = load_config()
    state = State(cfg)
    assert state.get("never-seen") is None


def test_set_and_get_cursor(tmp_config: Path):
    cfg = load_config()
    state = State(cfg)
    cursor = SessionCursor(
        last_processed_msg_idx=5,
        last_msg_uuid="msg_5",
        last_update_date="2026-04-17",
        first_seen_date="2026-04-17",
        project="opet",
    )
    state.set("abc123", cursor)
    state.save()

    # re-load
    fresh = State(cfg)
    got = fresh.get("abc123")
    assert got == cursor


def test_atomic_write_leaves_no_tempfile(tmp_config: Path):
    cfg = load_config()
    state = State(cfg)
    state.set("s1", SessionCursor(3, "u", "2026-04-17", "2026-04-17", "p"))
    state.save()
    # no .tmp files left behind
    tmps = list(cfg.state_dir.glob("*.tmp*"))
    assert tmps == []

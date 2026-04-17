"""Merger uses tempfile + os.replace — never leaves partial files."""
from pathlib import Path

from kalevala.config import load_config
from kalevala.generator import SessionSummary
from kalevala.merger import merge_session


def _min_summary() -> SessionSummary:
    return SessionSummary(
        summary="x", files_touched=[], commits=[], bugs_fixed=[],
        decisions=[], learnings=[], notes_for_later=[], open_threads=[],
        time_range=["00:00", "00:01"], project="opet",
        last_msg_uuid="u", last_msg_idx=0,
    )


def test_no_tempfiles_remain(tmp_config: Path):
    cfg = load_config()
    merge_session(cfg, "2026-04-17", "abc", _min_summary())
    target_dir = cfg.entries_dir / "2026" / "04"
    tmps = list(target_dir.glob("*.tmp*"))
    assert tmps == []


def test_orphan_tempfile_cleaned_on_write(tmp_config: Path):
    cfg = load_config()
    target_dir = cfg.entries_dir / "2026" / "04"
    target_dir.mkdir(parents=True, exist_ok=True)
    orphan = target_dir / ".2026-04-17.md.tmp.9999"
    orphan.write_text("stale")

    merge_session(cfg, "2026-04-17", "abc", _min_summary())
    assert not orphan.exists()

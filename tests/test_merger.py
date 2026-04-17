"""Merger: upsert a session summary into today's daily markdown file."""
from pathlib import Path

from kalevala.config import load_config
from kalevala.generator import SessionSummary
from kalevala.merger import merge_session


def _summary(**overrides) -> SessionSummary:
    base = dict(
        summary="fixed val loop",
        files_touched=["opet/src/val.py"],
        commits=["a1b2c3d fix: skip empty batches"],
        bugs_fixed=["empty batch -> NaN"],
        decisions=["deferred heatmap refactor"],
        learnings=["DiceMetric returns NaN on empty preds"],
        notes_for_later=["revisit val-heatmap"],
        open_threads=["fingerprint cache mismatch"],
        time_range=["14:22", "15:40"],
        project="opet",
        last_msg_uuid="msg_10",
        last_msg_idx=10,
    )
    base.update(overrides)
    return SessionSummary(**base)


def test_merge_creates_daily_file(tmp_config: Path):
    cfg = load_config()
    merge_session(cfg=cfg, date="2026-04-17", session_id="abc123", summary=_summary())
    target = cfg.entries_dir / "2026" / "04" / "2026-04-17.md"
    assert target.exists()
    body = target.read_text()
    assert "# 2026-04-17" in body
    assert "### Session 1 — opet" in body
    assert "id: abc123" in body
    assert "fixed val loop" in body
    assert "## Notes for Later" in body
    assert "- (auto) revisit val-heatmap" in body
    assert "## Open Threads" in body


def test_merge_appends_second_session(tmp_config: Path):
    cfg = load_config()
    merge_session(cfg, "2026-04-17", "abc123", _summary(project="opet", summary="first"))
    merge_session(cfg, "2026-04-17", "def456", _summary(project="AortaAIM", summary="second"))
    body = (cfg.entries_dir / "2026" / "04" / "2026-04-17.md").read_text()
    assert "### Session 1 — opet" in body
    assert "### Session 2 — AortaAIM" in body
    assert "first" in body
    assert "second" in body


def test_top_summary_is_deterministic_concat(tmp_config: Path):
    cfg = load_config()
    merge_session(cfg, "2026-04-17", "a", _summary(summary="alpha work"))
    merge_session(cfg, "2026-04-17", "b", _summary(summary="beta work", project="AortaAIM"))
    body = (cfg.entries_dir / "2026" / "04" / "2026-04-17.md").read_text()
    # "## Summary" section comes before sessions and lists both lines
    summary_section = body.split("## Sessions")[0]
    assert "alpha work" in summary_section
    assert "beta work" in summary_section


def test_notes_deduped_across_sessions(tmp_config: Path):
    cfg = load_config()
    merge_session(cfg, "2026-04-17", "a", _summary(notes_for_later=["dup note", "unique a"]))
    merge_session(cfg, "2026-04-17", "b", _summary(notes_for_later=["dup note", "unique b"]))
    body = (cfg.entries_dir / "2026" / "04" / "2026-04-17.md").read_text()
    assert body.count("- (auto) dup note") == 1
    assert "- (auto) unique a" in body
    assert "- (auto) unique b" in body


def test_frontmatter_populated(tmp_config: Path):
    cfg = load_config()
    merge_session(cfg, "2026-04-17", "a", _summary(project="opet"))
    merge_session(cfg, "2026-04-17", "b", _summary(project="AortaAIM"))
    body = (cfg.entries_dir / "2026" / "04" / "2026-04-17.md").read_text()
    head = body.split("---", 2)[1]
    assert "date: 2026-04-17" in head
    assert "sessions: 2" in head
    assert "opet" in head and "AortaAIM" in head

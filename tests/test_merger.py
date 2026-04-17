"""Merger: upsert a session summary into today's daily markdown file."""
from pathlib import Path

from kalevala.config import load_config
from kalevala.generator import SessionSummary
from kalevala.merger import merge_session


def _summary(**overrides) -> SessionSummary:
    base = dict(
        summary="fixed request handler",
        files_touched=["myapp/src/handlers.py"],
        commits=["a1b2c3d fix: handle nil request body"],
        bugs_fixed=["nil body -> 500"],
        decisions=["deferred auth cache refactor"],
        learnings=["JSON decoder returns None on empty body"],
        notes_for_later=["revisit auth-cache"],
        open_threads=["session token mismatch"],
        time_range=["14:22", "15:40"],
        project="myapp",
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
    assert "### Session 1 — myapp" in body
    assert "id: abc123" in body
    assert "fixed request handler" in body
    assert "## Notes for Later" in body
    assert "- (auto) revisit auth-cache" in body
    assert "## Open Threads" in body


def test_merge_appends_second_session(tmp_config: Path):
    cfg = load_config()
    merge_session(cfg, "2026-04-17", "abc123", _summary(project="myapp", summary="first"))
    merge_session(cfg, "2026-04-17", "def456", _summary(project="webapp", summary="second"))
    body = (cfg.entries_dir / "2026" / "04" / "2026-04-17.md").read_text()
    assert "### Session 1 — myapp" in body
    assert "### Session 2 — webapp" in body
    assert "first" in body
    assert "second" in body


def test_top_summary_is_deterministic_concat(tmp_config: Path):
    cfg = load_config()
    merge_session(cfg, "2026-04-17", "a", _summary(summary="alpha work"))
    merge_session(cfg, "2026-04-17", "b", _summary(summary="beta work", project="webapp"))
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
    merge_session(cfg, "2026-04-17", "a", _summary(project="myapp"))
    merge_session(cfg, "2026-04-17", "b", _summary(project="webapp"))
    body = (cfg.entries_dir / "2026" / "04" / "2026-04-17.md").read_text()
    head = body.split("---", 2)[1]
    assert "date: 2026-04-17" in head
    assert "sessions: 2" in head
    assert "myapp" in head and "webapp" in head


from kalevala.merger import add_manual_note, add_manual_todo  # noqa: E402


def test_same_day_resume_replaces_block(tmp_config: Path):
    cfg = load_config()
    first = _summary(summary="first pass", time_range=["09:00", "10:00"])
    merge_session(cfg, "2026-04-17", "same", first)
    second = _summary(summary="second pass with guards", time_range=["11:00", "12:00"])
    merge_session(cfg, "2026-04-17", "same", second)

    body = (cfg.entries_dir / "2026" / "04" / "2026-04-17.md").read_text()
    assert body.count("### Session 1 — myapp") == 1  # still one block
    assert "second pass with guards" in body
    assert "first pass" not in body  # replaced, not appended


def test_cross_day_resume_has_continued_from_tag(tmp_config: Path):
    cfg = load_config()
    # day 1
    merge_session(cfg, "2026-04-17", "xday", _summary(summary="day 1 work"))
    # day 2 — continued_from passed by caller
    merge_session(cfg, "2026-04-18", "xday", _summary(summary="day 2 work"),
                  continued_from="2026-04-17")
    day1 = (cfg.entries_dir / "2026" / "04" / "2026-04-17.md").read_text()
    day2 = (cfg.entries_dir / "2026" / "04" / "2026-04-18.md").read_text()
    assert "day 1 work" in day1
    assert "day 1 work" not in day2
    assert "continued from 2026-04-17" in day2


def test_manual_note_added(tmp_config: Path):
    cfg = load_config()
    add_manual_note(cfg, "2026-04-17", "try new cache layout")
    body = (cfg.entries_dir / "2026" / "04" / "2026-04-17.md").read_text()
    assert "## Notes for Later" in body
    assert "- (manual) try new cache layout" in body


def test_manual_todo_added(tmp_config: Path):
    add_manual_todo(load_config(), "2026-04-17", "refactor the auth middleware")
    body = (load_config().entries_dir / "2026" / "04" / "2026-04-17.md").read_text()
    assert "- (manual) TODO: refactor the auth middleware" in body

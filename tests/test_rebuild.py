"""check / rebuild: compare and regenerate days from the transcripts on disk."""
from pathlib import Path

import pytest

from kalevala.config import load_config
from kalevala.generator import SessionSummary
from kalevala.merger import add_manual_note, merge_session
from kalevala.rebuild import check_days, rebuild_days
from kalevala.state import State

from test_activity_dates import day_file, recording_client, turn, write_transcript


def _summary(text: str) -> SessionSummary:
    return SessionSummary(summary=text, time_range=["00:00", "00:00"], project="myapp")


@pytest.fixture
def setup(tmp_config: Path, tmp_path: Path):
    with tmp_config.open("a") as f:
        f.write('timezone = "UTC"\n')
    cfg = load_config()
    root = tmp_path / "projects"
    # s1 ran on the 13th but its hook fired on the 14th, so the old pipeline filed it there
    write_transcript(root / "-home-u-projects-myapp" / "s1.jsonl", [
        turn(0, "2026-10-13T08:00:00Z"), turn(1, "2026-10-13T09:00:00Z", "assistant"),
    ])
    merge_session(cfg, "2026-10-14", "s1", _summary("old misfiled text"))
    add_manual_note(cfg, "2026-10-14", "call the vendor")
    return cfg, root


def test_check_reports_missing_and_misfiled(setup):
    cfg, root = setup

    by_day = {r.day: r for r in check_days(cfg, ["2026-10-13", "2026-10-14"], root)}

    assert [s.session_id for s in by_day["2026-10-13"].missing] == ["s1"]
    assert by_day["2026-10-14"].misfiled == ["s1"]
    assert not by_day["2026-10-13"].ok and not by_day["2026-10-14"].ok


def test_rebuild_moves_the_session_and_keeps_manual_notes(setup):
    cfg, root = setup

    lines = rebuild_days(cfg, recording_client(), ["2026-10-13", "2026-10-14"], root, jobs=1)

    assert lines == ["2026-10-13  s1  08:00–09:00  myapp"]
    assert "(08:00–09:00) · id: s1" in day_file(cfg, "2026-10-13").read_text()
    day14 = day_file(cfg, "2026-10-14").read_text()
    assert "s1" not in day14 and "old misfiled text" not in day14
    assert "(manual) call the vendor" in day14
    assert all(r.ok for r in check_days(cfg, ["2026-10-13", "2026-10-14"], root))
    assert State(cfg).get("s1").last_processed_msg_idx == 1


def test_rebuild_refuses_to_strand_a_misfiled_session(setup):
    cfg, root = setup
    before = day_file(cfg, "2026-10-14").read_text()

    # s1 belongs on the 13th, which is not being rebuilt and does not list it
    with pytest.raises(RuntimeError, match=r"s1 \(2026-10-13\)"):
        rebuild_days(cfg, recording_client(), ["2026-10-14"], root, jobs=1)

    assert day_file(cfg, "2026-10-14").read_text() == before

    rebuild_days(cfg, recording_client(), ["2026-10-14"], root, jobs=1, allow_drop={"s1"})
    assert "s1" not in day_file(cfg, "2026-10-14").read_text()


def test_rebuild_refuses_to_drop_sessions_without_transcripts(setup):
    cfg, root = setup
    merge_session(cfg, "2026-10-13", "gone", _summary("only record left"))
    before = day_file(cfg, "2026-10-13").read_text()

    with pytest.raises(RuntimeError, match="gone"):
        rebuild_days(cfg, recording_client(), ["2026-10-13"], root, jobs=1)

    assert day_file(cfg, "2026-10-13").read_text() == before


def _client_failing_on(marker: str, times: int):
    """A recording client whose call raises the first `times` times its prompt contains `marker`."""
    client = recording_client()
    ok = client.messages.create.return_value
    left = {"n": times}

    def create(**kwargs):
        if marker in kwargs["messages"][0]["content"] and left["n"] > 0:
            left["n"] -= 1
            raise TimeoutError("simulated summary timeout")
        return ok
    client.messages.create.side_effect = create
    return client


def test_failed_rebuild_resumes_from_cached_summaries(setup):
    cfg, root = setup
    write_transcript(root / "-home-u-projects-other" / "s2.jsonl", [
        {**turn(0, "2026-10-13T10:00:00Z"), "message": {"role": "user", "content": "flaky s2"}},
    ])
    before = day_file(cfg, "2026-10-14").read_text()

    with pytest.raises(TimeoutError):
        rebuild_days(cfg, _client_failing_on("flaky s2", times=1), ["2026-10-13", "2026-10-14"],
                     root, jobs=1, attempts=1)
    assert day_file(cfg, "2026-10-14").read_text() == before

    client = recording_client()
    rebuild_days(cfg, client, ["2026-10-13", "2026-10-14"], root, jobs=1, attempts=1)

    # s1 came from the cache; only s2 needed the model
    assert client.messages.create.call_count == 1
    assert "flaky s2" in client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "id: s2" in day_file(cfg, "2026-10-13").read_text()
    assert not list((cfg.state_dir / "rebuild_cache").glob("*.json"))


def test_rebuild_retries_a_failed_summary(setup):
    cfg, root = setup

    rebuild_days(cfg, _client_failing_on("turn 1", times=1), ["2026-10-13", "2026-10-14"],
                 root, jobs=1, attempts=2)

    assert "id: s1" in day_file(cfg, "2026-10-13").read_text()

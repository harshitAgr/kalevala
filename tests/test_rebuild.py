"""check / rebuild: compare and regenerate days from the transcripts on disk."""
import dataclasses
import json
import os
import sys
from pathlib import Path

import pytest

from kalevala.config import load_config
from kalevala.generator import SessionSummary
from kalevala.merger import add_manual_note, merge_session
from kalevala.rebuild import check_days, open_session_ids, rebuild_days
from kalevala.state import State

from test_activity_dates import day_file, recording_client, turn, write_transcript


def _summary(text: str) -> SessionSummary:
    return SessionSummary(summary=text, time_range=["00:00", "00:00"], project="myapp")


@pytest.fixture
def setup(tmp_config: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
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


def test_rebuild_refuses_a_summary_over_the_scrub_threshold(setup):
    cfg, root = setup
    cfg = dataclasses.replace(cfg, scrub_threshold=0)  # every summary reaches it
    before = day_file(cfg, "2026-10-14").read_text()

    with pytest.raises(RuntimeError, match="scrub threshold"):
        rebuild_days(cfg, recording_client(), ["2026-10-13", "2026-10-14"], root, jobs=1)
    assert day_file(cfg, "2026-10-14").read_text() == before

    lines = rebuild_days(cfg, recording_client(), ["2026-10-13", "2026-10-14"], root, jobs=1,
                         allow_drop={"s1"})
    assert lines == ["2026-10-13  s1  SKIPPED: 0 redactions (threshold 0)"]
    assert State(cfg).get("s1") is None


def test_rebuild_leaves_the_cursor_before_a_day_it_did_not_journal(setup):
    cfg, root = setup
    # s3 is still open: it ran on the 12th and the 13th, and nothing of it is journaled yet
    write_transcript(root / "-home-u-projects-myapp" / "s3.jsonl", [
        turn(0, "2026-10-12T20:00:00Z"), turn(1, "2026-10-13T10:00:00Z", "assistant"),
    ])

    rebuild_days(cfg, recording_client(), ["2026-10-13", "2026-10-14"], root, jobs=1)
    assert State(cfg).get("s3") is None  # so the hook still files the 12th when s3 ends

    rebuild_days(cfg, recording_client(), ["2026-10-12", "2026-10-13"], root, jobs=1)
    assert State(cfg).get("s3").last_processed_msg_idx == 1


def test_cli_rejects_bad_arguments_and_prints_refusals(tmp_config, monkeypatch, capsys):
    from kalevala import cli, rebuild

    for argv in (["check", "--days", "0"], ["rebuild", "2026-13-01"]):
        monkeypatch.setattr(sys, "argv", ["kalevala", *argv])
        with pytest.raises(SystemExit):
            cli.main()

    def refuse(*args, **kwargs):
        raise RuntimeError("would drop s9")
    monkeypatch.setattr(rebuild, "rebuild_days", refuse)
    monkeypatch.setattr(cli, "_client", lambda: None)
    monkeypatch.setattr(sys, "argv", ["kalevala", "rebuild", "2026-10-13"])
    assert cli.main() == 1
    assert "would drop s9" in capsys.readouterr().err


def test_check_lists_running_session_as_open_not_missing(setup):
    cfg, root = setup

    (live,) = check_days(cfg, ["2026-10-13"], root, open_ids={"s1"})
    (dead,) = check_days(cfg, ["2026-10-13"], root, open_ids=set())

    assert [s.session_id for s in live.open] == ["s1"] and live.missing == [] and live.ok
    assert [s.session_id for s in dead.missing] == ["s1"] and dead.open == [] and not dead.ok


def _starttime(pid: str) -> str:
    return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[-1].split()[19]


def test_open_session_ids(setup, tmp_path):
    cfg, _ = setup
    assert open_session_ids(cfg) == set()  # no sessions dir
    sessions = tmp_path / "claude" / "sessions"
    sessions.mkdir(parents=True)
    me = str(os.getpid())

    def put(name: str, **data) -> None:
        (sessions / name).write_text(json.dumps(data))

    put(f"{me}.json", pid=me, sessionId="live", procStart=_starttime(me))
    put("1.json", pid=me, sessionId="reused", procStart="1")        # same pid, other process
    put("999999999.json", pid="999999999", sessionId="gone", procStart="5")
    put("stem.json", sessionId="nopid")                              # no pid, non-numeric stem
    put(f"{me}.abc.key", sessionId="key")
    (sessions / "bad.json").write_text("{not json")
    (sessions / "list.json").write_text("[]")

    assert open_session_ids(cfg) == {"live"}

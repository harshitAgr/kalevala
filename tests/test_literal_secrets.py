"""Exact-value secret sources: environment, Claude Code MCP config, declared dotenv files."""
import json
from pathlib import Path

import pytest

from kalevala.literal_secrets import (
    SecretSourceError, collect, from_claude_json, from_dotenv_files, from_environ,
)

TOK = "fake0token0a1b2c3d4e5f6a7b8c9d0e1f2a3b4"  # 40 chars, not a real credential
OTHER = "fake1other1a1b2c3d4e5f6a7b8c9d0e1f2a3b4"


def test_environ_only_secret_named_plausible_values(tmp_path: Path):
    keyfile = tmp_path / "id_ed25519_long_enough_name"
    keyfile.write_text("x")
    env = {
        "CODABENCH_API_TOKEN": TOK,
        "AWS_SECRET_ACCESS_KEY": OTHER,
        "DB_PASSWORD": "short",                       # too short to redact safely
        "SSH_KEY": str(keyfile),                      # a path to a key, not the key
        "GITHUB_TOKEN": "${SOME_OTHER_VAR_NAME_HERE}",  # a reference, not a value
        "TOKENIZERS_PARALLELISM": "false-but-long-enough-x",  # name does not end in a secret word
        "EDITOR": "vim",
        "PATH": "/usr/bin:/bin:/usr/local/bin:/home/someone/.local/bin",
        "BASE_URL_KEY": "https://example.org/some/long/plain/url",  # plain URL
    }
    assert sorted(from_environ(env)) == sorted([TOK, OTHER])


def test_claude_json_collects_env_and_headers_in_every_scope(tmp_path: Path):
    path = tmp_path / ".claude.json"
    path.write_text(json.dumps({
        "mcpServers": {"a": {"command": "x", "env": {"A_TOKEN": TOK, "MODE": "stdio"}}},
        "projects": {
            "/p/one": {"mcpServers": {"b": {"env": {"B": OTHER}}}},
            "/p/two": {"mcpServers": {"c": {"headers": {"Authorization": "Bearer " + TOK + "zz"}}}},
            "/p/three": {"allowedTools": []},
        },
    }))
    got = from_claude_json(path)
    assert TOK in got and OTHER in got
    assert TOK + "zz" in got                       # the bearer value without the scheme word
    assert "Bearer " + TOK + "zz" not in got       # whitespace: only the token itself is kept
    assert "stdio" not in got


def test_claude_json_variable_reference_is_not_a_secret(tmp_path: Path):
    path = tmp_path / ".claude.json"
    path.write_text(json.dumps({"mcpServers": {"a": {"env": {"CODABENCH_API_TOKEN": "${CODABENCH_API_TOKEN}"}}}}))
    assert from_claude_json(path) == []


def test_claude_json_missing_is_empty_but_corrupt_fails_closed(tmp_path: Path):
    assert from_claude_json(tmp_path / "absent.json") == []
    bad = tmp_path / ".claude.json"
    bad.write_text('{"mcpServers": {')           # e.g. read mid-write by another session
    with pytest.raises(SecretSourceError, match="cannot read MCP secrets"):
        from_claude_json(bad)
    bad.write_text("[1, 2]")
    with pytest.raises(SecretSourceError, match="not a JSON object"):
        from_claude_json(bad)


def test_dotenv_parses_export_quotes_and_inline_comments(tmp_path: Path):
    f = tmp_path / "env"
    f.write_text(
        "# a comment\n"
        "\n"
        f"CODABENCH_API_TOKEN={TOK}\n"
        f'export QUOTED="{OTHER}"\n'
        "SINGLE='single-quoted-secret-1'\n"
        "WITH_COMMENT=commented-secret-2 # trailing note\n"
        "SHORT=abc\n"
        "NOT_AN_ASSIGNMENT\n"
    )
    got = from_dotenv_files([f])
    assert set(got) == {TOK, OTHER, "single-quoted-secret-1", "commented-secret-2"}


def test_dotenv_declared_values_use_a_lower_length_floor(tmp_path: Path):
    f = tmp_path / "env"
    f.write_text("PGPASS=hunter2hunter\nSHORTER=1234567\n")  # 12 chars kept, 7 dropped
    assert from_dotenv_files([f]) == ["hunter2hunter"]


def test_declared_dotenv_file_missing_fails_closed(tmp_path: Path):
    with pytest.raises(SecretSourceError, match="secret_env_files: cannot read"):
        from_dotenv_files([tmp_path / "gone"])


def test_collect_dedups_and_orders_longest_first(tmp_path: Path):
    f = tmp_path / "env"
    f.write_text(f"A={TOK}\nB={TOK}extra\n")
    got = collect(env={"X_TOKEN": TOK}, claude_json=tmp_path / "absent.json", dotenv_files=[f])
    assert got == (TOK + "extra", TOK)

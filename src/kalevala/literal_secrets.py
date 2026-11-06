"""Exact-value secret sources for the scrubber.

The regex patterns only catch credentials that have a recognisable shape (an
`sk-ant-` prefix, a JWT, a PEM block). A token with no shape, such as a 40-hex
API token or a database password, passes straight through them, so the
summariser can quote it into a journal entry that is then pushed.

This module collects the *values* of secrets known to exist on this machine, so
the scrubber can redact them by exact match wherever the summary repeats them.

Sources:
  1. Environment variables whose name looks like a secret (`*_TOKEN`, `*_KEY`,
     `*SECRET`, `*PASSWORD`, ...).
  2. `env` and `headers` values of every MCP server in the Claude Code config
     (user scope and per-project scope).
  3. Every value in the dotenv-style files listed as `secret_env_files` in the
     kalevala config. Use this for secrets kept outside the two places above,
     e.g. a launcher script that sources `~/.config/<tool>/env`.

A source that is missing is skipped (a fresh machine has no Claude config yet).
A source that exists but cannot be read, or a declared file that is gone, raises
`SecretSourceError`: silently scrubbing with fewer secrets than expected is worse
than a journal gap. A failed run leaves the session's cursor where it was, so a
later hook run's sweep (or `kalevala sweep`) journals it once the source is fixed.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable, Iterator, Mapping


class SecretSourceError(RuntimeError):
    """A configured secret source is unreadable or missing."""


# Anchored at the end so TOKENIZERS_PARALLELISM or SECRET_FILE do not match.
_NAME_RE = re.compile(r"(?i)(?:token|secret|passw(?:or)?d|credentials?|api_?key|_key|^key)s?$")

# Inferred values must be long enough that redacting them cannot eat ordinary
# words; values from a file the user declared are secrets by definition.
_MIN_LEN_INFERRED = 16
_MIN_LEN_DECLARED = 8


def _plausible(value: object, *, declared: bool) -> bool:
    if not isinstance(value, str):
        return False
    if len(value) < (_MIN_LEN_DECLARED if declared else _MIN_LEN_INFERRED):
        return False
    if not declared and any(c.isspace() for c in value):
        return False
    if "${" in value or value.startswith("$"):
        return False  # a reference to a variable, not the secret itself
    if value.startswith(("http://", "https://")) and "@" not in value and "?" not in value:
        return False  # a plain URL; credentials in userinfo or a query string stay
    if value.startswith(("/", "~")) and os.path.exists(os.path.expanduser(value)):
        return False  # a path to a key file, not the key
    return True


def from_environ(env: Mapping[str, str]) -> list[str]:
    return [v for k, v in env.items() if _NAME_RE.search(k) and _plausible(v, declared=False)]


def _mcp_servers(data: dict) -> Iterator[dict]:
    scopes = [data.get("mcpServers")]
    projects = data.get("projects")
    if isinstance(projects, dict):
        scopes += [p.get("mcpServers") for p in projects.values() if isinstance(p, dict)]
    for servers in scopes:
        if isinstance(servers, dict):
            yield from (s for s in servers.values() if isinstance(s, dict))


def from_claude_json(path: Path) -> list[str]:
    """`env` and `headers` values of every MCP server in the Claude Code config."""
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        raise SecretSourceError(f"cannot read MCP secrets from {path}: {e}") from e
    if not isinstance(data, dict):
        raise SecretSourceError(f"{path} is not a JSON object")
    out: list[str] = []
    for server in _mcp_servers(data):
        env = server.get("env")
        if isinstance(env, dict):
            out += [v for v in env.values() if _plausible(v, declared=False)]
        headers = server.get("headers")
        if isinstance(headers, dict):
            for v in headers.values():
                if not isinstance(v, str):
                    continue
                out.append(v)
                if " " in v:  # "Bearer <token>": the token alone is what gets quoted
                    out.append(v.split(" ", 1)[1])
    return [v for v in out if _plausible(v, declared=False)]


def _parse_dotenv(text: str) -> Iterator[str]:
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        _, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()  # inline comment
        yield value


def from_dotenv_files(paths: Iterable[Path]) -> list[str]:
    out: list[str] = []
    for path in paths:
        try:
            text = path.read_text()
        except OSError as e:
            raise SecretSourceError(f"secret_env_files: cannot read {path}: {e}") from e
        out += [v for v in _parse_dotenv(text) if _plausible(v, declared=True)]
    return out


def collect(
    *, env: Mapping[str, str], claude_json: Path, dotenv_files: Iterable[Path],
) -> tuple[str, ...]:
    """All known secret values, deduplicated, longest first so that a value that
    contains another is redacted whole rather than leaving a tail."""
    values = set(from_environ(env)) | set(from_claude_json(claude_json)) | set(from_dotenv_files(dotenv_files))
    return tuple(sorted(values, key=lambda v: (-len(v), v)))

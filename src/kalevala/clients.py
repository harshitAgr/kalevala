"""Claude client: shells out to the `claude` CLI, using the user's existing auth.

Implements the same minimal `.messages.create(...)` surface the Anthropic SDK
exposes so tests mocking the client don't care which backend is in use.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

# set on our own `claude --print` children; their SessionEnd hook is a no-op
INTERNAL_ENV = "KALEVALA_INTERNAL"


@dataclass
class ClaudeCliClient:
    """Shell out to the `claude` CLI for one-shot prompt execution.

    Why: avoids requiring ANTHROPIC_API_KEY. The `claude` CLI uses whatever
    auth the user has configured (OAuth via Pro/Max login, or API key).

    --no-session-persistence keeps the summarization run from writing a
    transcript. It does not stop that run's SessionEnd hook from firing, so
    INTERNAL_ENV is set on the child and `kalevala hook` returns at once when
    it sees it; without that, every summary queued a dead pending entry
    after a lock wait.
    """

    binary: str = "claude"
    # a day of a long session runs to a few hundred kB of prompt; 120 s timed out on those
    timeout_seconds: int = 600

    @property
    def messages(self) -> "ClaudeCliClient":
        # lets callers write `client.messages.create(...)` like the Anthropic SDK
        return self

    def create(
        self,
        *,
        model: str,
        messages: list[dict],
        system: str = "",
        max_tokens: int = 2000,
        **_ignored,
    ) -> SimpleNamespace:
        if not messages:
            raise ValueError("messages must be non-empty")
        prompt = messages[0].get("content", "")

        args = [
            self.binary,
            "--print",
            "--model", model,
            "--no-session-persistence",
            "--output-format", "text",
            # a summary is one reply, no tool calls; the default tool and MCP
            # definitions added ~21k input tokens to every call
            "--tools", "",
            "--strict-mcp-config",
        ]
        if system:
            args.extend(["--append-system-prompt", system])

        # errors name the CLI's own message, not the argv: the argv carries the
        # whole system prompt and said nothing about why a call failed
        try:
            result = subprocess.run(
                args,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=True,
                cwd=os.environ.get("HOME", str(Path.home())),
                env={**os.environ, INTERNAL_ENV: "1"},
            )
        except subprocess.CalledProcessError as e:
            detail = " ".join(((e.stderr or "") + " " + (e.stdout or "")).split())[-500:]
            raise RuntimeError(
                f"claude --print exited {e.returncode} ({len(prompt)} chars in): {detail or 'no output'}"
            ) from None
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"claude --print timed out after {self.timeout_seconds}s ({len(prompt)} chars in)"
            ) from None
        if not result.stdout.strip():
            # seen now and then on the same prompt that succeeds on a retry
            detail = " ".join((result.stderr or "").split())[-500:]
            raise RuntimeError(f"claude --print exited 0 with no output ({len(prompt)} chars in): {detail}")
        return SimpleNamespace(content=[SimpleNamespace(text=result.stdout)])


def build_client() -> ClaudeCliClient:
    return ClaudeCliClient()

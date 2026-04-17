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


@dataclass
class ClaudeCliClient:
    """Shell out to the `claude` CLI for one-shot prompt execution.

    Why: avoids requiring ANTHROPIC_API_KEY. The `claude` CLI uses whatever
    auth the user has configured (OAuth via Pro/Max login, or API key).

    --no-session-persistence is load-bearing: it prevents the hook's own
    summarization from creating a new session transcript, which would
    re-trigger the SessionEnd hook on its own shutdown (infinite loop).
    """

    binary: str = "claude"
    timeout_seconds: int = 120

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
        ]
        if system:
            args.extend(["--append-system-prompt", system])

        result = subprocess.run(
            args,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=True,
            cwd=os.environ.get("HOME", str(Path.home())),
        )
        return SimpleNamespace(content=[SimpleNamespace(text=result.stdout)])


def build_client() -> ClaudeCliClient:
    return ClaudeCliClient()

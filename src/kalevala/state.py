"""Per-session cursor persistence.

processed_sessions.json is a performance cache; the markdown entries are
the source of truth. If this file is lost, cursors can be rebuilt by
grepping session IDs from entries/.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Config


@dataclass(frozen=True)
class SessionCursor:
    last_processed_msg_idx: int
    last_msg_uuid: str
    last_update_date: str   # YYYY-MM-DD
    first_seen_date: str    # YYYY-MM-DD, set once, never mutated
    project: str


class State:
    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._data: dict[str, SessionCursor] = {}
        self._load()

    def _load(self) -> None:
        path = self._cfg.state_file
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            # treat corrupt state as empty; markdown is source of truth
            self._data = {}
            return
        self._data = {
            sid: SessionCursor(**vals) for sid, vals in raw.items()
        }

    def get(self, session_id: str) -> SessionCursor | None:
        return self._data.get(session_id)

    def set(self, session_id: str, cursor: SessionCursor) -> None:
        self._data[session_id] = cursor

    def save(self) -> None:
        self._cfg.state_dir.mkdir(parents=True, exist_ok=True)
        final = self._cfg.state_file
        tmp = final.with_suffix(final.suffix + f".tmp.{os.getpid()}")
        payload = {sid: asdict(cur) for sid, cur in self._data.items()}
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.replace(tmp, final)

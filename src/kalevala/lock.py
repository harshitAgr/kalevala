"""Advisory file lock via fcntl. POSIX-only; unreliable on NFS."""
from __future__ import annotations

import fcntl
import time
from pathlib import Path


class LockTimeout(Exception):
    """Raised when the lock could not be acquired within wait_seconds."""


class FileLock:
    def __init__(self, path: Path, wait_seconds: int = 30, poll_interval: float = 0.1) -> None:
        self._path = path
        self._wait = wait_seconds
        self._poll = poll_interval
        self._fd: int | None = None

    def __enter__(self) -> "FileLock":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # keep the file object alive for the duration of the lock so the fd stays valid
        self._fh = open(self._path, "w")
        self._fd = self._fh.fileno()
        deadline = time.time() + self._wait
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except BlockingIOError:
                if time.time() >= deadline:
                    self._fh.close()
                    self._fd = None
                    raise LockTimeout(f"could not acquire {self._path} in {self._wait}s")
                time.sleep(self._poll)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fd = None

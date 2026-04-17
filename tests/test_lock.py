"""fcntl advisory lock for serializing concurrent kalevala runs."""
import multiprocessing
import time
from pathlib import Path

from kalevala.lock import FileLock, LockTimeout
from kalevala.config import load_config


def _hold_lock_for(lock_path_str: str, seconds: float, barrier_path: str) -> None:
    """Child process: acquire lock, write a marker, sleep."""
    lock = FileLock(Path(lock_path_str), wait_seconds=1)
    with lock:
        Path(barrier_path).write_text("held")
        time.sleep(seconds)


def test_lock_serializes_access(tmp_config: Path, tmp_path: Path):
    cfg = load_config()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    barrier = tmp_path / "barrier"

    proc = multiprocessing.Process(
        target=_hold_lock_for,
        args=(str(cfg.lock_path), 2.0, str(barrier)),
    )
    proc.start()
    # wait for child to grab the lock
    while not barrier.exists():
        time.sleep(0.05)

    lock = FileLock(cfg.lock_path, wait_seconds=1)
    start = time.time()
    raised = False
    try:
        with lock:
            pass
    except LockTimeout:
        raised = True
    elapsed = time.time() - start

    proc.join()
    assert raised, "expected LockTimeout"
    assert 0.9 <= elapsed <= 1.6, f"timeout took {elapsed:.2f}s"


def test_lock_released_on_exit(tmp_config: Path):
    cfg = load_config()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(cfg.lock_path, wait_seconds=1)
    with lock:
        pass
    # second acquisition should succeed immediately
    with FileLock(cfg.lock_path, wait_seconds=1):
        pass

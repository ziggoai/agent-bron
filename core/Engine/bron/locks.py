"""One lock per ticket while a run works it.

Every operation runs under a single exclusive guard (.bron/locks/.guard), and records are written
to a temp file and renamed into place, so two runs can never both hold a ticket and a lock is never
seen half-written. A crashed or expired run's lock is recovered by the next acquire.

A run queued behind full slots holds its ticket's lock marked `waiting`: the ticket is taken (and
`ticket wait` keeps waiting for it), but it doesn't count as one of the running slots.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .vault import Vault

_SAFE_ID = re.compile(r"^[A-Za-z0-9-]+$")


@dataclass
class Lock:
    ticket_id: str
    run_id: str
    pid: int
    started: float
    waiting: bool = False


def _dir(vault: Vault) -> Path:
    return vault.bron_dir / "locks"


def _path(vault: Vault, ticket_id: str) -> Path:
    if not _SAFE_ID.match(ticket_id):
        raise ValueError(f"'{ticket_id}' isn't a valid ticket id for a lock")
    return _dir(vault) / f"{ticket_id}.lock"


@contextlib.contextmanager
def _guard(vault: Vault) -> Iterator[None]:
    _dir(vault).mkdir(parents=True, exist_ok=True)
    guard_path = _dir(vault) / ".guard"
    fd = os.open(str(guard_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (OSError, OverflowError, ValueError):
        return False
    return True


def _read(path: Path, ticket_id: str) -> Lock | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return Lock(ticket_id, "", -1, 0.0)  # unreadable: stale
    try:
        pid, started = int(data["pid"]), float(data["started"])
        run_id = str(data["run_id"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return Lock(ticket_id, "", -1, 0.0)
    if not (0 < pid < 2**31) or not math.isfinite(started):
        return Lock(ticket_id, run_id, -1, 0.0)
    return Lock(ticket_id, run_id, pid, started, data.get("waiting") is True)


def _write(path: Path, run_id: str, pid: int, started: float, waiting: bool) -> None:
    record = {"run_id": run_id, "pid": pid, "started": started}
    if waiting:
        record["waiting"] = True
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    tmp.replace(path)


def read_lock(vault: Vault, ticket_id: str) -> Lock | None:
    with _guard(vault):
        return _read(_path(vault, ticket_id), ticket_id)


def is_stale(lock: Lock, max_minutes: int, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    if lock.pid <= 0 or not _alive(lock.pid):
        return True
    return now - lock.started > (max_minutes + 5) * 60


def acquire(
    vault: Vault, ticket_id: str, run_id: str, *, pid: int | None = None, max_minutes: int = 30, now: float | None = None, waiting: bool = False
) -> bool:
    """Take the ticket's lock. `waiting`: the run is queued for a free slot and doesn't count as running yet."""
    path = _path(vault, ticket_id)
    with _guard(vault):
        current = _read(path, ticket_id)
        if current is not None and not is_stale(current, max_minutes, now):
            return False
        _write(path, run_id, os.getpid() if pid is None else pid, time.time() if now is None else now, waiting)
        return True


def take_slot(vault: Vault, ticket_id: str, run_id: str, *, max_parallel: int, max_minutes: int, now: float | None = None) -> str:
    """Turn this run's waiting lock into a running one if a slot is free, in one step so two queued runs can't
    both take the last slot. Returns "running", "full", or "lost" (the lock isn't this run's any more)."""
    path = _path(vault, ticket_id)
    with _guard(vault):
        current = _read(path, ticket_id)
        if current is None or current.run_id != run_id:
            return "lost"
        if not current.waiting:
            return "running"
        others = [other for other in sorted(_dir(vault).glob("*.lock")) if other.stem != ticket_id]
        held = [_read(other, other.stem) for other in others]
        running = [lock for lock in held if lock is not None and not lock.waiting and not is_stale(lock, max_minutes, now)]
        if len(running) >= max_parallel:
            return "full"
        # The run's time limit starts now, not when it joined the queue.
        _write(path, run_id, current.pid, time.time() if now is None else now, False)
        return "running"


def release(vault: Vault, ticket_id: str, run_id: str | None = None) -> None:
    path = _path(vault, ticket_id)
    with _guard(vault):
        current = _read(path, ticket_id)
        if current is None or (run_id is not None and current.run_id != run_id):
            return
        path.unlink(missing_ok=True)


def _all(vault: Vault) -> list[Lock]:
    if not _dir(vault).is_dir():
        return []
    with _guard(vault):
        locks = [_read(path, path.stem) for path in sorted(_dir(vault).glob("*.lock"))]
    return [lock for lock in locks if lock is not None]


def active(vault: Vault, max_minutes: int, now: float | None = None) -> list[Lock]:
    """Runs holding a slot (a queued run's waiting lock doesn't)."""
    return [lock for lock in _all(vault) if not lock.waiting and not is_stale(lock, max_minutes, now)]


def stale(vault: Vault, max_minutes: int, now: float | None = None) -> list[Lock]:
    return [lock for lock in _all(vault) if is_stale(lock, max_minutes, now)]

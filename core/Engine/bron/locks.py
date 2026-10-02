"""One lock per ticket while a run works it. Created atomically; a crashed or expired run's lock is recovered."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .vault import Vault


@dataclass
class Lock:
    ticket_id: str
    run_id: str
    pid: int
    started: float


def _dir(vault: Vault) -> Path:
    return vault.bron_dir / "locks"


def _path(vault: Vault, ticket_id: str) -> Path:
    return _dir(vault) / f"{ticket_id}.lock"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock(vault: Vault, ticket_id: str) -> Lock | None:
    path = _path(vault, ticket_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Lock(ticket_id, str(data["run_id"]), int(data["pid"]), float(data["started"]))
    except (OSError, ValueError, KeyError, TypeError):
        return Lock(ticket_id, "", -1, 0.0)  # unreadable: treated as stale


def is_stale(lock: Lock, max_minutes: int, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    if lock.pid <= 0 or not _alive(lock.pid):
        return True
    return now - lock.started > (max_minutes + 5) * 60


def acquire(vault: Vault, ticket_id: str, run_id: str, *, pid: int | None = None, max_minutes: int = 30, now: float | None = None) -> bool:
    _dir(vault).mkdir(parents=True, exist_ok=True)
    record = json.dumps({"run_id": run_id, "pid": pid or os.getpid(), "started": time.time() if now is None else now})
    for _ in range(2):
        try:
            fd = os.open(_path(vault, ticket_id), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            current = read_lock(vault, ticket_id)
            if current is not None and is_stale(current, max_minutes, now):
                _path(vault, ticket_id).unlink(missing_ok=True)
                continue
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(record)
        return True
    return False


def release(vault: Vault, ticket_id: str, run_id: str | None = None) -> None:
    current = read_lock(vault, ticket_id)
    if current is None or (run_id is not None and current.run_id != run_id):
        return
    _path(vault, ticket_id).unlink(missing_ok=True)


def _all(vault: Vault) -> list[Lock]:
    if not _dir(vault).is_dir():
        return []
    locks = [read_lock(vault, path.stem) for path in sorted(_dir(vault).glob("*.lock"))]
    return [lock for lock in locks if lock is not None]


def active(vault: Vault, max_minutes: int, now: float | None = None) -> list[Lock]:
    return [lock for lock in _all(vault) if not is_stale(lock, max_minutes, now)]


def stale(vault: Vault, max_minutes: int, now: float | None = None) -> list[Lock]:
    return [lock for lock in _all(vault) if is_stale(lock, max_minutes, now)]

import json
import math
import multiprocessing
import os
import threading

from bron.check import run_checks
from bron.loader import load
from bron.locks import acquire, active, is_stale, read_lock, release, stale
from bron.vault import Vault

DEAD_PID = 999_999


def _worker_acquire(vault_root, ticket, i, q):
    """Worker function for multiprocessing test (must be at module level for pickling)."""
    v = Vault(vault_root)
    result = acquire(v, ticket, f"run-{i}")
    q.put((i, result))


def test_acquire_is_exclusive_and_release_frees_it(vault):
    assert acquire(vault, "T-0001", "run-a")
    assert not acquire(vault, "T-0001", "run-b")
    lock = read_lock(vault, "T-0001")
    assert lock.run_id == "run-a" and lock.pid == os.getpid()
    release(vault, "T-0001", "run-b")  # someone else's run can't release it
    assert read_lock(vault, "T-0001") is not None
    release(vault, "T-0001", "run-a")
    assert read_lock(vault, "T-0001") is None


def test_a_dead_process_or_old_lock_is_stale_and_recovered(vault):
    assert acquire(vault, "T-0002", "crashed", pid=DEAD_PID)
    assert is_stale(read_lock(vault, "T-0002"), 30)
    assert acquire(vault, "T-0002", "fresh")
    assert read_lock(vault, "T-0002").run_id == "fresh"
    assert acquire(vault, "T-0003", "slow", now=1000.0)
    assert is_stale(read_lock(vault, "T-0003"), 30, now=1000.0 + 36 * 60)
    assert not is_stale(read_lock(vault, "T-0003"), 30, now=1000.0 + 10 * 60)


def test_active_and_stale_lists(vault):
    acquire(vault, "T-0001", "a")
    acquire(vault, "T-0002", "b", pid=DEAD_PID)
    assert [lock.ticket_id for lock in active(vault, 30)] == ["T-0001"]
    assert [lock.ticket_id for lock in stale(vault, 30)] == ["T-0002"]


def test_unreadable_lock_counts_as_stale(vault):
    (vault.bron_dir / "locks").mkdir(parents=True)
    (vault.bron_dir / "locks" / "T-0004.lock").write_text("garbage")
    assert acquire(vault, "T-0004", "fresh")


def test_health_check_warns_about_leftover_locks(vault):
    acquire(vault, "T-0002", "b", pid=DEAD_PID)
    issues = run_checks(load(vault), include_environment=False)
    assert any(i.code == "locks.stale" and i.level == "warning" and "T-0002" in i.message for i in issues)


def test_many_racers_on_a_stale_lock_exactly_one_wins(vault):
    acquire(vault, "T-0005", "stale", pid=DEAD_PID)
    barrier = threading.Barrier(20)
    results = []

    def racer(i):
        barrier.wait()
        results.append((i, acquire(vault, "T-0005", f"run-{i}")))

    threads = [threading.Thread(target=racer, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [i for i, won in results if won]
    assert len(winners) == 1
    lock = read_lock(vault, "T-0005")
    assert lock.run_id == f"run-{winners[0]}"


def test_many_processes_never_both_hold(vault):
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    processes = []
    for i in range(8):
        p = ctx.Process(target=_worker_acquire, args=(vault.root, "T-0006", i, q))
        p.start()
        processes.append(p)
    for p in processes:
        p.join()

    results = []
    while not q.empty():
        results.append(q.get())

    winners = [i for i, won in results if won]
    assert len(winners) == 1
    lock = read_lock(vault, "T-0006")
    assert lock is not None
    assert lock.run_id == f"run-{winners[0]}"


def test_late_release_cannot_remove_a_newer_lock(vault):
    acquire(vault, "T-0007", "old", pid=DEAD_PID)
    lock = read_lock(vault, "T-0007")
    assert lock.run_id == "old"
    assert acquire(vault, "T-0007", "new")
    lock = read_lock(vault, "T-0007")
    assert lock.run_id == "new"
    release(vault, "T-0007", "old")
    lock = read_lock(vault, "T-0007")
    assert lock is not None and lock.run_id == "new"


def test_hand_edited_lock_values_never_crash(vault):
    (vault.bron_dir / "locks").mkdir(parents=True, exist_ok=True)

    # Invalid pid (too large)
    (vault.bron_dir / "locks" / "T-0008.lock").write_text('{"run_id":"x","pid":1e30,"started":1}')
    assert acquire(vault, "T-0008", "fresh")

    # NaN started time
    (vault.bron_dir / "locks" / "T-0009.lock").write_text('{"run_id":"x","pid":123,"started":NaN}')
    assert acquire(vault, "T-0009", "fresh")

    # Invalid JSON: array
    (vault.bron_dir / "locks" / "T-0010.lock").write_text("[]")
    assert acquire(vault, "T-0010", "fresh")

    # Invalid JSON: empty string
    (vault.bron_dir / "locks" / "T-0011.lock").write_text('""')
    assert acquire(vault, "T-0011", "fresh")

    # Ensure run_checks doesn't crash either
    issues = run_checks(load(vault), include_environment=False)
    assert isinstance(issues, list)


def test_bad_ticket_id_is_rejected(vault):
    import pytest

    with pytest.raises(ValueError, match="isn't a valid ticket id"):
        acquire(vault, "../x", "r")
    with pytest.raises(ValueError, match="isn't a valid ticket id"):
        read_lock(vault, "T@invalid")
    with pytest.raises(ValueError, match="isn't a valid ticket id"):
        release(vault, "T/0001")

import os

from bron.check import run_checks
from bron.loader import load
from bron.locks import acquire, active, is_stale, read_lock, release, stale

DEAD_PID = 999_999


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

"""Background reading jobs, kept in .bron/kb/jobs/<job-id>.json.

One job reads at a time; the others wait. Every document is written down as soon as it's done, so a job that was
interrupted (a crash, the laptop closed) picks up where it stopped and never reads a finished document again.
A file that stopped the reader twice is skipped, and `bron kb status --cancel` stops what's waiting.
"""
from __future__ import annotations

import contextlib
import dataclasses
import fcntl
import json
import os
import secrets
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .. import statefile
from ..vault import Vault
from . import notices, store
from .sources import Item

KEEP_FINISHED = 20
STALE_QUEUED_SECONDS = 60
MAX_ATTEMPTS = 2
TWICE = "Bron stopped while reading this file twice; skipped it."


@dataclass
class Job:
    job_id: str
    created: str
    items: list[dict]
    done: list[str]  # identities of the items read
    failed: list[dict]  # {"identity", "name", "error"}; a link that wasn't found has no identity or name
    status: str = "queued"  # queued | running | done | cancelled
    read: list[str] = field(default_factory=list)  # ids of the documents read, in order
    finished: str = ""
    attempts: dict = field(default_factory=dict)  # identity -> times a reader started on it
    cancelled: list[str] = field(default_factory=list)  # names of the items not read because of a cancel
    again: bool = False  # `bron kb add --again`: read documents again even when they haven't changed
    unchanged: list[str] = field(default_factory=list)  # ids of the documents skipped as already read, unchanged


def _dir(vault: Vault) -> Path:
    return store.kb_dir(vault) / "jobs"


def _path(vault: Vault, job_id: str) -> Path:
    return _dir(vault) / f"{job_id}.json"


def _lock_path(vault: Vault) -> Path:
    return _dir(vault) / "runner.lock"


def _runner_path(vault: Vault) -> Path:
    return _dir(vault) / "runner.status"


def _cancel_path(vault: Vault, job_id: str) -> Path:
    return _dir(vault) / f"{job_id}.cancel"


def save(vault: Vault, job: Job) -> None:
    statefile.write_json(_path(vault, job.job_id), asdict(job))


def load(vault: Vault, job_id: str) -> Job | None:
    data = statefile.read_json(_path(vault, job_id), {})
    try:
        return Job(**{k: v for k, v in data.items() if k in Job.__dataclass_fields__})
    except TypeError:
        return None


def all_jobs(vault: Vault) -> list[Job]:
    folder = _dir(vault)
    if not folder.is_dir():
        return []
    found = [load(vault, p.stem) for p in folder.glob("*.json")]
    return sorted((j for j in found if j is not None), key=lambda j: (j.created, j.job_id))


def pending(vault: Vault) -> list[Job]:
    return [j for j in all_jobs(vault) if j.status in ("queued", "running")]


def _prune(vault: Vault) -> None:
    finished = [j for j in all_jobs(vault) if j.status in ("done", "cancelled")]
    for job in finished[:-KEEP_FINISHED]:
        for path in (_path(vault, job.job_id), _cancel_path(vault, job.job_id)):
            try:
                path.unlink()
            except OSError:
                pass


def create(vault: Vault, items: list, *, failed: list[str] | tuple = (), again: bool = False) -> Job:
    """A queued job. `failed`: sentences about links that couldn't be found, reported with the job's result.
    `again`: read every item even if it was read before and hasn't changed."""
    _prune(vault)
    job = Job(
        job_id=time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2),
        created=datetime.now().isoformat(timespec="microseconds"),
        items=[asdict(i) if isinstance(i, Item) else dict(i) for i in items],
        done=[],
        failed=[{"identity": "", "name": "", "error": str(f)} for f in failed],
        again=again,
    )
    save(vault, job)
    return job


# ---- the one runner ----

@contextlib.contextmanager
def _hold_lock(vault: Vault):
    path = _lock_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            _beat(vault)
            yield True
        finally:
            try:
                _runner_path(vault).unlink()
            except OSError:
                pass
            fcntl.flock(handle, fcntl.LOCK_UN)


def _beat(vault: Vault) -> None:
    """Who is reading, for `runner_active` (which must never touch the runner's lock)."""
    statefile.write_json(_runner_path(vault), {"pid": os.getpid(), "beat": time.time()})


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


RUNNER_COMMAND = "kb run-job"


def _command_of(pid: int) -> str:
    """The command line of a running process ("" when there's none, or ps can't tell)."""
    try:
        done = subprocess.run(["ps", "-o", "command=", "-p", str(int(pid))], capture_output=True, text=True, timeout=5)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def runner_active(vault: Vault) -> bool:
    """A runner is at work: the process in runner.status is alive and really is `bron kb run-job`
    (after a crash and a restart, its old process number may belong to something else)."""
    try:
        data = json.loads(_runner_path(vault).read_text(encoding="utf-8"))
        pid = int(data.get("pid", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    if not _alive(pid):
        return False
    return pid == os.getpid() or RUNNER_COMMAND in _command_of(pid)


def stalled(vault: Vault) -> list[Job]:
    """Jobs nobody is working on: interrupted ones, and queued ones whose runner never started."""
    if runner_active(vault):
        return []
    now = datetime.now()
    out = []
    for job in pending(vault):
        try:
            age = (now - datetime.fromisoformat(job.created)).total_seconds()
        except ValueError:
            age = STALE_QUEUED_SECONDS
        if job.status == "running" or age >= STALE_QUEUED_SECONDS:
            out.append(job)
    return out


def resume(vault: Vault, *, popen=subprocess.Popen) -> bool:
    """Start a runner for jobs nobody is working on (a crash or restart stopped them)."""
    if not _dir(vault).is_dir():
        return False
    waiting = stalled(vault)
    return bool(waiting) and spawn(vault, waiting[0].job_id, popen=popen)


# ---- reports ----

def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def report(vault: Vault, job: Job) -> str:
    from . import ingest

    docs = [d for d in (store.load(vault, i) for i in job.read) if d is not None]
    skipped = (store.load(vault, i) for i in job.unchanged)
    docs += [dataclasses.replace(d, status="unchanged") for d in skipped if d is not None]
    docs += [store.Doc("", f.get("identity", ""), "", "", f.get("name", ""), "", status="failed", error=f.get("error", ""))
             for f in job.failed if f.get("name")]
    notes = [f.get("error", "") for f in job.failed if not f.get("name")]
    if job.cancelled:
        notes.append(f"Cancelled: {_plural(len(job.cancelled), 'document')} weren't read"
                     if len(job.cancelled) != 1 else "Cancelled: 1 document wasn't read")
        notes[-1] += " (" + ", ".join(job.cancelled[:5]) + (", …" if len(job.cancelled) > 5 else "") + ")."
    return ingest.summary(docs, notes)


def _remaining(job: Job) -> list[dict]:
    handled = set(job.done) | {f.get("identity") for f in job.failed if f.get("identity")}
    return [raw for raw in job.items if not (isinstance(raw, dict) and raw.get("identity") in handled)]


def _finish(vault: Vault, job: Job, status: str, *, shown: bool = False) -> str:
    """Report first, then mark the job finished: an interruption in between gives the report once, never zero times."""
    if status == "cancelled":
        job.cancelled = [str(raw.get("name", "")) if isinstance(raw, dict) else str(raw) for raw in _remaining(job)]
    text = report(vault, job)
    notices.add(vault, text, job_id=job.job_id, shown=shown)
    job.status = status
    job.finished = time.strftime("%Y-%m-%d %H:%M")
    save(vault, job)  # the cancel flag stays until the job is pruned: a runner that already picked it up stops too
    return text


def cancel(vault: Vault) -> list[str]:
    """Stop every waiting or running job. Jobs nobody is working on stop now (their reports are returned, for the
    caller to print); the one being read stops after its current document and reports as usual."""
    texts: list[str] = []
    active = runner_active(vault)
    for job in pending(vault):
        _cancel_path(vault, job.job_id).touch()
        if job.status == "queued" or not active:
            texts.append(_finish(vault, job, "cancelled", shown=True))
    return texts


# ---- working ----

def _default_embedder(vault: Vault):
    from . import embed

    return embed.get(vault)


def _work(vault: Vault, cfg, job: Job, *, embedder, readers_ocr, model_call, label_call) -> None:
    from . import ingest

    fresh = load(vault, job.job_id)
    if fresh is None or fresh.status not in ("queued", "running"):
        return  # finished or cancelled since it was picked
    job = fresh
    job.status = "running"
    save(vault, job)
    for raw in _remaining(job):
        if _cancel_path(vault, job.job_id).exists():
            _finish(vault, job, "cancelled")
            return
        identity = str(raw.get("identity", "")) if isinstance(raw, dict) else ""
        try:
            item = Item(**raw)
        except TypeError:
            job.failed.append({"identity": identity, "name": str(raw)[:80], "error": "This entry of the job is damaged."})
            save(vault, job)
            continue
        tries = int(job.attempts.get(identity, 0))
        if tries >= MAX_ATTEMPTS:  # it took the whole reader down twice: never a third time
            job.failed.append({"identity": identity, "name": item.name, "error": TWICE})
            save(vault, job)
            continue
        job.attempts[identity] = tries + 1
        save(vault, job)  # written down before reading, so a crash on this file counts
        doc = ingest.read_item(vault, cfg, item, readers_ocr=readers_ocr, model_call=model_call,
                               label_call=label_call, embedder=embedder, again=job.again)
        if doc.status == "read":
            job.done.append(identity)
            job.read.append(doc.doc_id)
        elif doc.status == "unchanged":
            job.done.append(identity)
            job.unchanged.append(doc.doc_id)
        else:
            job.failed.append({"identity": identity, "name": doc.name, "error": doc.error})
        save(vault, job)  # committed: an interrupted job never reads this item again
        _beat(vault)
    _finish(vault, job, "done")


def run(vault: Vault, job_id: str, *, embedder=None, readers_ocr=None, model_call=None, label_call=None, cfg=None) -> bool:
    """Run this job and any others waiting, oldest first. False when another runner is already at work
    (it picks up every waiting job, this one included)."""
    if cfg is None:
        from ..loader import load as load_cfg

        cfg = load_cfg(vault)
    embedder = embedder or _default_embedder(vault)
    deps = dict(embedder=embedder, readers_ocr=readers_ocr, model_call=model_call, label_call=label_call)
    while True:
        with _hold_lock(vault) as got:
            if not got:
                return False
            _finish_indexing(vault, embedder)
            while True:
                waiting = pending(vault)
                if not waiting:
                    break
                _work(vault, cfg, waiting[0], **deps)
        # A job queued while this runner was finishing found the lock taken: look once more after letting go.
        if not pending(vault):
            return True


def give_up(vault: Vault, reason: str) -> None:
    """The reading tools couldn't be set up: every waiting job ends now with a report that says why. A runner that
    holds the lock got its tools and is reading, so the jobs are left to it."""
    with _hold_lock(vault) as got:
        if not got:
            return
        for job in pending(vault):
            names = [str(raw.get("name", "")) if isinstance(raw, dict) else str(raw) for raw in _remaining(job)]
            if names:
                shown = ", ".join(names[:5]) + (", …" if len(names) > 5 else "")
                job.failed.append({"identity": "", "name": "", "error": (
                    f"{reason.rstrip()} Nothing was read ({shown}); run the same `bron kb add` again to try again.")})
            _finish(vault, job, "done")


def _finish_indexing(vault: Vault, embedder) -> None:
    """Documents an interruption left half-indexed are finished first."""
    from . import index

    try:
        index.finish_pending(vault, embedder)
    except Exception as exc:  # noqa: BLE001 - the next search tries again
        from .ingest import _log

        _log(vault, "finishing the index", exc)


def spawn(vault: Vault, job_id: str, *, popen=subprocess.Popen) -> bool:
    from ..background import spawn_detached

    return spawn_detached(vault, ["kb", "run-job", job_id], "kb.log", popen=popen)


def _when(stamp: str) -> str:
    return stamp[:16].replace("T", " ")


def status_lines(vault: Vault) -> list[str]:
    lines: list[str] = []
    active = runner_active(vault)
    for job in pending(vault):
        total = len(job.items)
        failed = sum(1 for f in job.failed if f.get("identity"))
        left = total - len(job.done) - failed
        if job.status == "running" and active:
            lines.append(f"Reading {_plural(total, 'document')}: {len(job.done)} read, {failed} couldn't be read, "
                         f"{left} to go (started {_when(job.created)}).")
        elif job.status == "running":
            lines.append(f"Reading {_plural(total, 'document')} stopped part-way: {len(job.done)} read, {left} to go.")
        else:
            lines.append(f"Waiting to read {_plural(total, 'document')} (since {_when(job.created)}).")
    if not lines:
        lines.append("No documents are being read right now.")
    finished = [j for j in all_jobs(vault) if j.status in ("done", "cancelled")]
    if finished:
        last = finished[-1]
        failed = sum(1 for f in last.failed if f.get("name"))
        how = "was cancelled" if last.status == "cancelled" else "finished"
        lines.append(f"Last reading {how} {last.finished}: read {_plural(len(last.read), 'document')}, "
                     f"{failed} couldn't be read.")
    return lines

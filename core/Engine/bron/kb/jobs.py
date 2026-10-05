"""Background reading jobs, kept in .bron/kb/jobs/<job-id>.json.

One job reads at a time; the others wait. Every document is written down as soon as it's done, so a job that was
interrupted (a crash, the laptop closed) picks up where it stopped and never reads a finished document again.
A file that stopped the reader twice is skipped, and `bron kb status --cancel` stops what's waiting.

Once a job is read, its documents' wiki pages are written by background agent runs (kb/wiki_run.py), one ticket per
batch of documents, one batch after another. A batch that was interrupted or whose run failed is tried once more; an
interrupted job picks up at its first unfinished batch. One wiki run at a time: others wait. The reader and the wiki
writer have their own locks, so documents can be read while a folder is being written.
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
IDLE = "Nothing is being read."
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
    wiki: bool = False  # write the wiki pages in the background once read
    wiki_status: str = ""  # "" (no wiki run) | waiting | writing | done | failed | cancelled
    wiki_docs: list[str] = field(default_factory=list)  # ids of the documents whose pages the run writes
    wiki_since: str = ""  # when it began waiting to be written
    wiki_attempts: int = 0  # runs started for the current batch (a third is never tried)
    ticket: str = ""  # the current batch's ticket ("" until it's made; the last batch's once done)
    wiki_batch: int = 0  # batches of wiki_docs written (wiki_run.BATCH documents each); the next one is this index
    wiki_tickets: list[str] = field(default_factory=list)  # every batch's ticket, in order
    label: str = ""  # "the Leases folder" (empty: "N documents"), for the ticket's title
    report: str = ""  # the reading report: handed to the wiki run, and told to the user if the run fails
    started: str = ""  # when reading began; with the three below, how long each part took
    read_done: str = ""
    wiki_started: str = ""
    wiki_done: str = ""


def _dir(vault: Vault) -> Path:
    return store.kb_dir(vault) / "jobs"


def _path(vault: Vault, job_id: str) -> Path:
    return _dir(vault) / f"{job_id}.json"


def _lock_path(vault: Vault) -> Path:
    return _dir(vault) / "runner.lock"


def _runner_path(vault: Vault) -> Path:
    return _dir(vault) / "runner.status"


def _wiki_lock_path(vault: Vault) -> Path:
    return _dir(vault) / "wiki.lock"


def _writer_path(vault: Vault) -> Path:
    return _dir(vault) / "wiki.status"


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


def wiki_pending(vault: Vault) -> list[Job]:
    """Jobs whose wiki pages are waiting to be written, or being written."""
    return [j for j in all_jobs(vault) if j.wiki_status in ("waiting", "writing")]


def wiki_left(job: Job) -> list[str]:
    """The documents whose batch isn't written yet."""
    from .wiki_run import BATCH

    return job.wiki_docs[job.wiki_batch * BATCH:]


def _prune(vault: Vault) -> None:
    finished = [j for j in all_jobs(vault) if j.status in ("done", "cancelled") and j.wiki_status not in ("waiting", "writing")]
    for job in finished[:-KEEP_FINISHED]:
        for path in (_path(vault, job.job_id), _cancel_path(vault, job.job_id)):
            try:
                path.unlink()
            except OSError:
                pass


def create(vault: Vault, items: list, *, failed: list[str] | tuple = (), again: bool = False, wiki: bool = False,
           label: str = "") -> Job:
    """A queued job. `failed`: sentences about links that couldn't be found, reported with the job's result.
    `again`: read every item even if it was read before and hasn't changed. `wiki`: write their wiki pages in the
    background once read; `label`: "the Leases folder", for the run's title."""
    _prune(vault)
    job = Job(
        job_id=time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2),
        created=datetime.now().isoformat(timespec="microseconds"),
        items=[asdict(i) if isinstance(i, Item) else dict(i) for i in items],
        done=[],
        failed=[{"identity": "", "name": "", "error": str(f)} for f in failed],
        again=again,
        wiki=wiki,
        label=label,
    )
    save(vault, job)
    return job


def create_wiki(vault: Vault, doc_ids: list[str], *, label: str = "") -> Job:
    """Documents read in a conversation while a background wiki run is writing: their pages are written after it."""
    _prune(vault)
    stamp = datetime.now().isoformat(timespec="microseconds")
    job = Job(job_id=time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2), created=stamp, items=[], done=[],
              failed=[], status="done", finished=time.strftime("%Y-%m-%d %H:%M"), wiki=True, wiki_status="waiting",
              wiki_docs=list(doc_ids), wiki_since=stamp, label=label)
    save(vault, job)
    return job


# ---- the one runner ----

@contextlib.contextmanager
def _hold_lock(vault: Vault, *, wiki: bool = False):
    path = _wiki_lock_path(vault) if wiki else _lock_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            _beat(vault, wiki=wiki)
            yield True
        finally:
            try:
                (_writer_path(vault) if wiki else _runner_path(vault)).unlink()
            except OSError:
                pass
            fcntl.flock(handle, fcntl.LOCK_UN)


def _beat(vault: Vault, *, wiki: bool = False) -> None:
    """Who is reading (or writing the wiki), for `runner_active` (which must never touch the locks)."""
    statefile.write_json(_writer_path(vault) if wiki else _runner_path(vault), {"pid": os.getpid(), "beat": time.time()})


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


def runner_active(vault: Vault, *, wiki: bool = False) -> bool:
    """A runner is at work: the process in runner.status is alive and really is `bron kb run-job`
    (after a crash and a restart, its old process number may belong to something else).
    `wiki`: the wiki writer instead of the reader."""
    try:
        data = json.loads((_writer_path(vault) if wiki else _runner_path(vault)).read_text(encoding="utf-8"))
        pid = int(data.get("pid", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    if not _alive(pid):
        return False
    return pid == os.getpid() or RUNNER_COMMAND in _command_of(pid)


def wiki_active(vault: Vault) -> bool:
    """A background wiki run is writing pages right now."""
    return runner_active(vault, wiki=True)


def _age(stamp: str, now: datetime) -> float:
    try:
        return (now - datetime.fromisoformat(stamp)).total_seconds()
    except ValueError:
        return STALE_QUEUED_SECONDS


def stalled(vault: Vault) -> list[Job]:
    """Jobs nobody is working on: interrupted ones, queued ones whose runner never started, and wiki runs nobody is
    writing (a reader at work writes them once it's done)."""
    reading = runner_active(vault)
    now = datetime.now()
    out: list[Job] = []
    if not reading:
        out += [j for j in pending(vault) if j.status == "running" or _age(j.created, now) >= STALE_QUEUED_SECONDS]
        if not runner_active(vault, wiki=True):
            out += [j for j in wiki_pending(vault)
                    if j.wiki_status == "writing" or _age(j.wiki_since, now) >= STALE_QUEUED_SECONDS]
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


def _now() -> str:
    return datetime.now().isoformat(timespec="microseconds")


def _span(start: str, end: str) -> float | None:
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except (TypeError, ValueError):
        return None


def took(seconds: float) -> str:
    """19 s, 2 min 42 s, 1 h 2 min."""
    s = max(1, round(seconds))
    if s < 60:
        return f"{s} s"
    if s < 3600:
        m, s = divmod(s, 60)
        return f"{m} min" + (f" {s} s" if s else "")
    h, m = s // 3600, s % 3600 // 60
    return f"{h} h" + (f" {m} min" if m else "")


def _banner(text: str) -> None:
    from .. import desktop

    desktop.notify(text)


def _read_banner(job: Job) -> None:
    failed = sum(1 for f in job.failed if f.get("name"))
    parts = [f"read {_plural(len(job.read), 'document')}"]
    if job.unchanged:
        parts.append(f"{len(job.unchanged)} unchanged")
    if failed:
        parts.append(f"{failed} couldn't be read")
    seconds = _span(job.started or job.created, job.read_done)
    _banner("Bron " + ", ".join(parts) + (f" ({took(seconds)})." if seconds is not None else "."))


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


def _needs_pages(vault: Vault, job: Job) -> list[str]:
    """The documents a wiki run writes pages for: those just read (a page is updated when its document is read again)
    and those skipped as unchanged that have no page yet."""
    out: list[str] = []
    for doc_id in [*job.read, *job.unchanged]:
        doc = store.load(vault, doc_id)
        if doc is not None and doc.status == "read" and (doc_id in job.read or not doc.page) and doc_id not in out:
            out.append(doc_id)
    return out


def _finish(vault: Vault, job: Job, status: str, *, shown: bool = False, banner: bool = False) -> str:
    """Report first, then mark the job finished: an interruption in between gives the report once, never zero times.
    A wiki job keeps its report for its wiki run, whose ticket update becomes what the user is told. A background read
    (banner) that ends here shows a Mac banner; one with a wiki run shows it when its pages are written."""
    if status == "cancelled":
        job.cancelled = [str(raw.get("name", "")) if isinstance(raw, dict) else str(raw) for raw in _remaining(job)]
    text = report(vault, job)
    pages = _needs_pages(vault, job) if job.wiki and status == "done" else []
    if pages:
        job.report, job.wiki_docs, job.wiki_status = text, pages, "waiting"
        job.wiki_since = _now()
    else:
        notices.add(vault, text, job_id=job.job_id, shown=shown)
    job.status, job.read_done = status, _now()
    job.finished = time.strftime("%Y-%m-%d %H:%M")
    save(vault, job)  # the cancel flag stays until the job is pruned: a runner that already picked it up stops too
    if banner and status == "done" and not pages:
        _read_banner(job)
    return text


def cancel(vault: Vault) -> list[str]:
    """Stop every waiting or running job, and every wiki run that is waiting. Jobs nobody is working on stop now (their
    reports are returned, for the caller to print); the one being read stops after its current document and reports as
    usual; a wiki run already writing finishes, unless its writer is gone (then it stops now, like a waiting one).
    Each job is read again just before it's changed, so one that finished meanwhile is left as it is."""
    texts: list[str] = []
    active = runner_active(vault)
    for listed in pending(vault):
        _cancel_path(vault, listed.job_id).touch()
        job = load(vault, listed.job_id)
        if job is None or job.status not in ("queued", "running"):
            continue
        if job.status == "queued" or not active:
            texts.append(_finish(vault, job, "cancelled", shown=True))
    writer = wiki_active(vault)
    for listed in wiki_pending(vault):
        job = load(vault, listed.job_id)
        if job is None or not (job.wiki_status == "waiting" or (job.wiki_status == "writing" and not writer)):
            continue
        left = wiki_left(job)
        job.wiki_status, job.finished = "cancelled", time.strftime("%Y-%m-%d %H:%M")
        save(vault, job)
        note = (f"Cancelled: the wiki pages for {_plural(len(left), 'document')} weren't written; "
                "say \"finish the wiki pages\" when you want them.")
        texts.append(f"{job.report}\n{note}" if job.report else note)
    return texts


# ---- working ----

def _default_embedder(vault: Vault):
    from . import embed

    return embed.get(vault)


def _work(vault: Vault, cfg, job: Job, *, embedder, readers_ocr, model_call) -> None:
    from . import ingest

    fresh = load(vault, job.job_id)
    if fresh is None or fresh.status not in ("queued", "running"):
        return  # finished or cancelled since it was picked
    job = fresh
    job.status, job.started = "running", job.started or _now()
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
                               embedder=embedder, again=job.again)
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
    _finish(vault, job, "done", banner=True)


def run(vault: Vault, job_id: str, *, embedder=None, readers_ocr=None, model_call=None, cfg=None, run_ticket=None) -> bool:
    """Run this job and any others waiting, oldest first; then let go of the reader and write the wiki pages of what was
    read. False when another runner is already reading (it picks up every waiting job, this one included)."""
    if cfg is None:
        from ..loader import load as load_cfg

        cfg = load_cfg(vault)
    embedder = embedder or _default_embedder(vault)
    deps = dict(embedder=embedder, readers_ocr=readers_ocr, model_call=model_call)
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
            break
    _write_wiki(vault, cfg, run_ticket=run_ticket)
    return True


def _write_wiki(vault: Vault, cfg, *, run_ticket=None) -> None:
    """Write every waiting wiki run, oldest first: one writer at a time (another one already at work writes them)."""
    while True:
        with _hold_lock(vault, wiki=True) as got:
            if not got:
                return
            while True:
                waiting = wiki_pending(vault)
                if not waiting:
                    break
                _write_one(vault, cfg, waiting[0], run_ticket=run_ticket)
        # One queued while this writer was finishing found the lock taken: look once more after letting go.
        if not wiki_pending(vault):
            return


def _wiki_failed(vault: Vault, job: Job, why: str) -> None:
    note = f"Bron read the documents but couldn't write all their wiki pages ({why.rstrip('.')})."
    names = {d: (doc.name if (doc := store.load(vault, d)) is not None else d) for d in job.wiki_docs}
    missing = _needs_pages(vault, dataclasses.replace(job, read=[], unchanged=job.wiki_docs))
    written = [n for d, n in names.items() if d not in missing]
    unwritten = [n for d, n in names.items() if d in missing]
    if written:
        note += f"\nPages written for: {', '.join(written)}."
    if unwritten:
        note += f"\nNo page yet: {', '.join(unwritten)}."
    note += "\nSay \"finish the wiki pages\" to write the rest."
    notices.add(vault, f"{job.report}\n{note}" if job.report else note, job_id=f"{job.job_id}-wiki")
    job.wiki_status, job.finished, job.wiki_done = "failed", time.strftime("%Y-%m-%d %H:%M"), _now()
    save(vault, job)
    what = job.label or _plural(len(job.wiki_docs), "document")
    _banner(f"Bron couldn't write all the wiki pages for {what}. Say \"finish the wiki pages\" to write the rest.")


def _wiki_written(vault: Vault, job: Job) -> None:
    """How long it took: a line in the last ticket's thread and the Mac banner."""
    from .. import tickets

    n = len(job.wiki_docs)
    total, writing = _span(job.started or job.created, job.wiki_done), _span(job.wiki_started, job.wiki_done)
    reading = _span(job.started, job.read_done) if job.started else None
    parts = [f"{_plural(len(job.read), 'document')} read in {took(reading)}"] if reading is not None else []
    if writing is not None:
        parts.append(f"wiki pages written in {took(writing)}")
    if total is not None:
        parts.append(f"{took(total)} in all")
    if parts and job.ticket:
        try:
            with tickets.editing(vault, job.ticket) as ticket:
                tickets.add_message(ticket, "runner", "Timing: " + "; ".join(parts) + ".")
        except Exception as exc:  # noqa: BLE001 - the pages are written; a timing line never undoes that
            from .ingest import _log

            _log(vault, f"the timing line of job {job.job_id}", exc)
    head = (job.label[:1].upper() + job.label[1:] + " is") if job.label else \
        (_plural(n, "document") + (" is" if n == 1 else " are"))
    detail = ", ".join(([_plural(n, "document")] if job.label else []) + ([took(total)] if total is not None else []))
    _banner(f"{head} in the wiki" + (f" ({detail})." if detail else "."))


WENT_WRONG = "something went wrong; the details are in .bron/logs/kb-errors.log"


def _write_batch(vault: Vault, cfg, job: Job, run_ticket) -> tuple[bool, str, bool]:
    """One run of the job's current batch: (written, why not, worth trying again)."""
    from . import wiki_run

    job.wiki_status, job.wiki_attempts = "writing", job.wiki_attempts + 1
    save(vault, job)  # written down first, so an interruption counts
    _beat(vault, wiki=True)
    try:
        if not job.ticket:
            job.ticket = wiki_run.start_ticket(vault, cfg, job)
            job.wiki_tickets.append(job.ticket)
            save(vault, job)
        outcome = run_ticket(vault, job.ticket)
    except store.KbError as exc:  # already a plain sentence (no default agent, say): another run wouldn't help
        return False, str(exc), False
    except Exception as exc:  # noqa: BLE001 - one failed run never stops the queue (Ctrl-C still stops it)
        from .ingest import _log

        _log(vault, f"the wiki run of job {job.job_id}", exc)
        return False, WENT_WRONG, True
    if outcome.status == "in-review":  # a ticket already in review (finished before a crash) counts as written
        return True, "", False
    return False, outcome.message or f"its ticket is {outcome.status or 'not finished'}", True


def _write_one(vault: Vault, cfg, job: Job, *, run_ticket=None) -> None:
    """Write the job's batches one after another, from the first unfinished one. A batch whose run failed or was
    interrupted is tried once more; after that the user is told which documents got pages."""
    from . import wiki_run

    fresh = load(vault, job.job_id)
    if fresh is None or fresh.wiki_status not in ("waiting", "writing"):
        return  # cancelled or written since it was picked
    job = fresh
    if run_ticket is None:
        from ..runner import run_ticket
    parts = wiki_run.batches(job.wiki_docs)
    if not job.wiki_started:
        job.wiki_started = _now()
        save(vault, job)
    while job.wiki_batch < len(parts):
        if job.wiki_attempts >= MAX_ATTEMPTS:  # it stopped the writer twice: never a third time
            _wiki_failed(vault, job, "it stopped twice before finishing")
            return
        ok, why, again = _write_batch(vault, cfg, job, run_ticket)
        if ok:
            job.wiki_batch += 1
            if job.wiki_batch < len(parts):
                job.ticket, job.wiki_attempts = "", 0
            save(vault, job)
        elif not again or job.wiki_attempts >= MAX_ATTEMPTS:
            _wiki_failed(vault, job, why)
            return
    job.wiki_status, job.finished, job.wiki_done = "done", time.strftime("%Y-%m-%d %H:%M"), _now()
    save(vault, job)
    _wiki_written(vault, job)


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
            _finish(vault, job, "done", banner=True)


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
    """What `bron kb status` says. Idle, nothing in it contains "reading" (an agent once waited for that word)."""
    from . import wiki_run

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
    writer = runner_active(vault, wiki=True)
    for job in wiki_pending(vault):
        what = job.label or _plural(len(job.wiki_docs), "document")
        parts = len(wiki_run.batches(job.wiki_docs))
        if job.wiki_status == "writing" and parts > 1:
            what += f", part {min(job.wiki_batch + 1, parts)} of {parts},"
        if job.wiki_status == "writing" and writer:
            lines.append(f"Writing {what} into the wiki ({job.ticket or 'starting'}, since {_when(job.wiki_since)}).")
        elif job.wiki_status == "writing":
            lines.append(f"Writing {what} into the wiki stopped part-way; Bron picks it up again.")
        else:
            lines.append(f"Waiting to write {what} into the wiki (since {_when(job.wiki_since)}).")
    if not lines:
        lines.append(IDLE)
    finished = [j for j in all_jobs(vault) if j.status in ("done", "cancelled") and j.items]
    if finished:
        last = finished[-1]
        failed = sum(1 for f in last.failed if f.get("name"))
        how = "was cancelled" if last.status == "cancelled" else "finished"
        reading = _span(last.started or last.created, last.read_done) if last.read_done else None
        writing = _span(last.wiki_started, last.wiki_done) if last.wiki_status == "done" else None
        lines.append(f"Last batch {how} {last.finished}: {_plural(len(last.read), 'document')} read"
                     + (f" in {took(reading)}" if reading is not None else "") + f", {failed} couldn't be read"
                     + (f"; wiki pages written in {took(writing)}" if writing is not None else "") + ".")
    return lines

"""`bron kb …`: read what the user points to, search it, and look after what was read."""
from __future__ import annotations

import os
import re
from pathlib import Path

NOTHING = "Nothing in the knowledge base matches that. Try other words, or check `bron kb list`."
HIDDEN = {"serve", "run-job"}
KEYWORD_NOTE = "Meaning search isn't available right now; these are keyword matches."
MAX_DOCS = 300
MAX_PAGES = 3000
FOREGROUND = 3  # up to 3 documents are read in the conversation; a folder, or more, in the background
FOREGROUND_SECONDS = 300  # …and only while they read in about 5 minutes, so a command never outlasts its 10-minute limit
TEXT_SECONDS_PER_PAGE = 0.05
SCAN_SECONDS_PER_PAGE = 1.0  # Mac text recognition
SECONDS_PER_PAGE = 0.2  # a mix of text and scanned pages, for estimates of what isn't opened
BACKGROUND = "Reading {count} into the wiki in the background ({duration}); I'll report when it's done."
BACKGROUND_CODEX = ("Reading {count} into the wiki in the background ({duration}); a Mac notification will say when "
                    "it's done, and I'll tell you in your next message.")
BACKGROUND_TICKET = ("Reading {count} into the wiki in the background ({duration}); it starts after this run, and its "
                     "own ticket reports when it's done.")
BEHIND = "A folder is already being written into the wiki; these start right after it and should be done in {duration}."
NEXT = "Next: load the read-documents skill, write their wiki pages, then run `.bron/bin/bron wiki done`."
SHOW_PAGES = 20
SHOW_CHARS = 20_000  # one `show` stays well under what Claude Code and Codex print of a command in full (about 30,000)
WAIT_HINT = ("To tell the user as soon as it's done, run `.bron/bin/bron kb wait --job {job}` now as a background "
             "command (run_in_background); when it finishes, tell them what it printed.")
WAIT_HOURS = 8
NEEDS_TOOLS = {"search", "serve", "run-job"}  # `add` sets the tools up itself, in the conversation
CRASHED = "Something went wrong in the knowledge base ({}). Details are in .bron/logs/kb-errors.log."


def add_parser(sub) -> None:
    parser = sub.add_parser("kb", help="read the documents you point Bron to, and search them")
    commands = parser.add_subparsers(dest="kb_command", required=True)

    add = commands.add_parser("add", help="read Drive links, files, folders, web links or the inbox")
    add.add_argument("targets", nargs="*", help="Drive links, file or folder paths, web links")
    add.add_argument("--inbox", action="store_true", help="read what's in Knowledge/Inbox")
    add.add_argument("--yes", action="store_true", help="go ahead with a big folder without asking")
    add.add_argument("--again", action="store_true", help="read documents again even if they haven't changed")
    add.add_argument("--file", default="", help="a Google Doc, Sheet or Slides file exported to text")
    add.add_argument("--source", default="", help="with --file: the Google Drive link of the exported document")
    add.add_argument("--name", default="", help="with --file: the document's title")

    search = commands.add_parser("search", help="search the knowledge base")
    search.add_argument("query")
    search.add_argument("--organisation", "--company", dest="company", default="",
                        help="the organisation a document is mainly about (--company works too)")
    search.add_argument("--type", dest="doc_type", default="")
    search.add_argument("--after", default="", help="only documents dated on or after YYYY-MM-DD")
    search.add_argument("--before", default="", help="only documents dated on or before YYYY-MM-DD")
    search.add_argument("--limit", type=int, default=8)
    search.add_argument("--pages-only", action="store_true", help="only wiki pages, no document passages")

    show = commands.add_parser("show", help="the text Bron read from one document")
    show.add_argument("doc", help="the document's id, name or part of its name")
    show.add_argument("--pages", default="", help="a page or a range, like 14 or 14-16")
    show.add_argument("--part", type=int, default=1, help="with one long page: which part of it")

    listing = commands.add_parser("list", help="the documents Bron has read")
    listing.add_argument("--organisation", "--company", dest="company", default="")
    listing.add_argument("--type", dest="doc_type", default="")
    listing.add_argument("--failed", action="store_true", help="only the documents that couldn't be read")

    forget = commands.add_parser("forget", help="remove a document from the knowledge base")
    forget.add_argument("doc", help="the document's id, name or part of its name")

    wait = commands.add_parser("wait", help="wait until background reading and wiki writing are done, then report")
    wait.add_argument("--job", default="", help="wait for this reading only, and report only it (the id `add` printed)")

    status = commands.add_parser("status", help="reading in progress, and how many documents Bron has")
    status.add_argument("--cancel", action="store_true", help="stop the reading that's waiting or under way")
    commands.add_parser("serve")  # the warm search helper; started automatically, so it has no help line
    run_job = commands.add_parser("run-job")  # a background reading job; started by `add`
    run_job.add_argument("job_id")
    # The usage line lists the real subcommands; internal ones stay out.
    commands.metavar = "{" + ",".join(name for name in commands.choices if name not in HIDDEN) + "}"


def handle(args, vault) -> int:
    from .store import KbError

    try:
        if args.kb_command in NEEDS_TOOLS:
            from . import tools

            try:
                tools.ensure(vault)  # first: the code behind these commands needs the tools to import
            except KbError as exc:
                if args.kb_command == "run-job":
                    from . import jobs

                    jobs.give_up(vault, str(exc))  # the user hears why nothing was read
                raise
        if args.kb_command == "search":
            return _search(args, vault)
        if args.kb_command == "serve":
            from . import service

            service.serve(vault)
            return 0
        command = {"add": _add, "show": _show, "list": _list, "forget": _forget, "status": _status,
                   "wait": _wait, "run-job": _run_job}.get(args.kb_command)
        if command is not None:
            return command(args, vault)
    except BrokenPipeError:  # the output was cut short on purpose (`| head`): not an error
        _quiet_stdout()
        return 0
    except KbError as exc:
        print(exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - never a traceback for the user (Ctrl-C still stops it)
        _log_crash(vault, args, exc)
        print(CRASHED.format(exc.__class__.__name__))
        return 1
    print("Not available yet.")
    return 1


def _quiet_stdout() -> None:
    """After a closed pipe, Python's last flush of stdout would fail again: point it at nothing."""
    import sys

    try:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    except (OSError, ValueError):
        pass


def _log_crash(vault, args, exc: BaseException) -> None:
    import time
    import traceback

    try:
        path = vault.bron_dir / "logs" / "kb-errors.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} bron kb {args.kb_command}: "
                     f"{''.join(traceback.format_exception(exc))}\n")
    except OSError:
        pass


def _embedder(vault):
    from . import embed

    return embed.get(vault)


def _search(args, vault) -> int:
    from . import embed, search, service, wiki_index

    request = {"query": args.query, "company": args.company, "doc_type": args.doc_type, "after": args.after,
               "before": args.before, "limit": args.limit, "pages_only": args.pages_only}
    reply = service.query(vault, request)
    if reply is not None and "error" in reply:
        print(reply["error"])
        return 1
    if reply is not None:
        found = search.Results([wiki_index.PageHit(**p) for p in reply.get("pages", [])],
                               [search.Hit(**h) for h in reply.get("hits", [])])
        note = bool(reply.get("keyword_only"))
    else:
        probe = service.Probe(embed.get(vault))
        found = search.find(vault, args.query, embedder=probe, company=args.company, doc_type=args.doc_type,
                            after=args.after, before=args.before, limit=args.limit, pages_only=args.pages_only)
        note = probe.failed
    if note:
        print(KEYWORD_NOTE)
    print(search.render_all(found) if (found.pages or found.hits) else NOTHING)
    return 0


# ---- add ----

def _duration(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes < 120:
        return f"about {minutes} minute" + ("" if minutes == 1 else "s")
    return f"about {round(minutes / 60)} hours"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _ask_first(vault, documents: int, pages: int) -> str:
    from ..loader import load

    text = (f"This is {_plural(documents, 'document')} (about {pages:,} pages). The first reading takes "
            f"{_duration(pages * SECONDS_PER_PAGE)} in the background")
    settings = load(vault).settings
    if settings.kb_model_pages:
        text += (f"; up to {settings.kb_max_model_pages} pages per document may be read by your Claude or Codex "
                 "model")
    return text + ". Run the same command with --yes to go ahead."


def _ahead(vault) -> tuple[int, bool]:
    """Documents whose wiki pages are due before new ones (jobs still reading count: they write the wiki after), and
    whether a wiki writer is, or will be, at work (one at a time)."""
    from . import jobs

    waiting = sum(len(jobs.wiki_left(j)) for j in jobs.wiki_pending(vault))  # batches already written don't count
    reading = [j for j in jobs.pending(vault) if j.wiki]
    count = waiting + sum(len(j.items) for j in reading)
    return count, bool(count) or bool(reading) or jobs.wiki_active(vault)


def _who_hears() -> str:
    """Who the background job's end reaches: "claude" (a Claude Code conversation: the agent is woken), "other" (a Codex
    conversation: a Mac notification and the next message), or "ticket" (a background run: nobody is woken and there
    is no next message; the run's own ticket reports)."""
    if os.environ.get("BRON_TICKET"):
        return "ticket"
    return "claude" if os.environ.get("CLAUDECODE") else "other"


def _background_line(count: str, duration: str) -> str:
    text = {"claude": BACKGROUND, "other": BACKGROUND_CODEX, "ticket": BACKGROUND_TICKET}[_who_hears()]
    return text.format(count=count, duration=duration)


def _behind_line(duration: str) -> str:
    return BEHIND.format(duration=duration)


def _queue(vault, items, failed, *, again: bool, label: str, pages: int) -> int:
    """Read in the background, then write the wiki pages in the same background job."""
    from . import jobs, wiki_run

    ahead, behind = _ahead(vault)
    job = jobs.create(vault, items, failed=failed, again=again, wiki=True, label=label)
    if not jobs.spawn(vault, job.job_id):
        print("Bron couldn't start reading in the background (.bron/bin/bron is missing). Run `.bron/bin/bron check`.")
        return 1
    duration = _duration(pages * SECONDS_PER_PAGE + (ahead + len(items)) * wiki_run.SECONDS_PER_DOC)
    print(_behind_line(duration) if behind else _background_line(_plural(len(items), "document"), duration))
    _wait_hint(job.job_id)
    return 0


def _wait_hint(job_id: str) -> None:
    """In a Claude Code conversation a background command wakes the agent when it ends, so `kb wait` lets it tell the
    user unasked. Codex has no such command: the Mac notification and the next message's notice tell them. The wait is
    for this conversation's job only: with two conversations reading, each reports its own."""
    if os.environ.get("CLAUDECODE") and not os.environ.get("BRON_TICKET"):
        print(WAIT_HINT.format(job=job_id))


def _report(vault, docs, notes) -> int:
    """What was read in the conversation; then either "write their pages now" or, while a background wiki run is
    writing, queue them behind it (one wiki writer at a time)."""
    from . import ingest, jobs, wiki_run

    print(ingest.lines(docs, notes))
    todo = [d.doc_id for d in docs if d.status == "read" or (d.status == "unchanged" and not d.page)]
    if todo:
        ahead, behind = _ahead(vault)
        if behind:
            job = jobs.create_wiki(vault, todo)
            jobs.spawn(vault, job.job_id)  # if it can't start now, the next session or `bron kb status` starts it
            print(_behind_line(_duration((ahead + len(todo)) * wiki_run.SECONDS_PER_DOC)))
            _wait_hint(job.job_id)
        else:
            print(NEXT)
    return 0 if any(d.status in ("read", "unchanged", "duplicate") for d in docs) else 1


def _add_export(args, vault) -> int:
    from ..loader import load
    from . import ingest, tools

    if args.targets or args.inbox:
        print("--file reads one exported Google file on its own. Run it separately from other links, paths or --inbox.")
        return 1
    if not (args.file and args.source and args.name):
        print("To add an exported Google Doc, give all three: --file <text file> --source <Drive link> --name '<title>'.")
        return 1
    ingest.export_item(args.file, args.source, args.name)  # a plain error now: the link, the file, or not text
    tools.ensure(vault)  # the first time, the tools are set up right here
    doc = ingest.add_export(vault, load(vault), args.file, args.source, args.name, embedder=_embedder(vault))
    return _report(vault, [doc], [])


def _sizes(items) -> tuple[int, float]:
    """Pages and estimated reading seconds of a few documents (PDFs on this Mac are opened to count them). An online-only
    PDF isn't downloaded to look inside, so it's timed as a scan: a big one goes to the background rather than outlast
    the command."""
    from . import ingest

    pages, seconds = 0, 0.0
    for item in items:
        n = ingest.page_count(item)
        pages += n
        unseen = (item.kind in ("file", "drive") and Path(item.path).suffix.lower() == ".pdf"
                  and ingest.online_only(item.path))
        seconds += n * (SCAN_SECONDS_PER_PAGE if unseen or ingest.looks_scanned(item) else TEXT_SECONDS_PER_PAGE)
    return pages, seconds


def _add(args, vault) -> int:
    from ..loader import load
    from . import ingest, jobs, sources, tools

    if args.file or args.source or args.name:
        return _add_export(args, vault)
    if not args.targets and not args.inbox:
        print("Tell me what to read: a Google Drive link, a file or folder path, a web link, or --inbox.")
        return 1
    found = sources.resolve_targets(vault, args.targets, inbox=args.inbox)
    items, seen = [], set()
    for item in found.items:  # the same file named twice is read once
        if item.identity not in seen:
            seen.add(item.identity)
            items.append(item)
    if not items:
        if found.failed:
            print("\n".join(found.failed))
            return 1
        print("The inbox (Knowledge/Inbox) is empty." if args.inbox and not args.targets else "There's nothing to read there.")
        return 0
    few = len(items) <= FOREGROUND and not found.folders
    if few:
        tools.ensure(vault)  # the first time, the tools are set up right here (a few minutes; one line says so)
        pages, seconds = _sizes(items)
    else:
        # Many files are estimated from their size, so nothing is downloaded from Drive before the user says yes.
        pages, seconds = (0 if args.yes else sum(ingest.guess_pages(item) for item in items)), 0.0
    if not args.yes and (len(items) > MAX_DOCS or pages > MAX_PAGES):
        print(_ask_first(vault, len(items), pages))
        return 0
    if not few or seconds > FOREGROUND_SECONDS or jobs.runner_active(vault):  # never two readers at once
        label = sources.folder_label(found, items)
        return _queue(vault, items, found.failed, again=args.again, label=label, pages=pages)
    cfg, embedder = load(vault), _embedder(vault)
    docs = [ingest.read_item(vault, cfg, item, embedder=embedder, again=args.again) for item in items]
    return _report(vault, docs, found.failed)


def _run_job(args, vault) -> int:
    from . import jobs

    jobs.run(vault, args.job_id, embedder=_embedder(vault))
    return 0


# ---- finding one document ----

def _find(vault, text: str):
    """The one document `text` names (id, exact name or title, or a unique part of either), or None after saying why."""
    from ..memory.facts import fold
    from . import ingest, store

    wanted = text.strip()
    if not wanted:
        print("Name a document: its id, its name or part of it (see `bron kb list`).")
        return None
    docs = store.all_docs(vault)
    folded = fold(wanted)

    def names(d):
        return [d.name, str(store.effective_labels(d).get("title") or "")]

    for test in (lambda d: d.doc_id == wanted,
                 lambda d: wanted in names(d),
                 lambda d: folded in [fold(n) for n in names(d)],
                 lambda d: bool(folded) and any(folded in fold(n) for n in names(d))):
        matches = [d for d in docs if test(d)]
        if len(matches) == 1:
            return matches[0]
        if matches:
            print(f"Several documents match '{wanted}':")
            for d in sorted(matches, key=lambda d: d.name.casefold()):
                labels = ingest.label_line(d)
                print(f"- {d.name}" + (f" — {labels}" if labels else "") + f" (id {d.doc_id})")
            print("Nothing was changed. Use more of the name, or the id.")
            return None
    print(f"No document matches '{wanted}'. See `bron kb list`.")
    return None


# ---- show, list ----

def _page_range(text: str, total: int):
    if not text.strip():
        return 1, min(total, SHOW_PAGES)
    m = re.fullmatch(r"\s*(\d+)\s*(?:-\s*(\d+))?\s*", text)
    if not m:
        return None
    first = int(m.group(1))
    last = int(m.group(2) or first)
    return (first, min(last, total)) if first <= last else (last, min(first, total))


def _clean(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _show(args, vault) -> int:
    from . import ingest, store

    doc = _find(vault, args.doc)
    if doc is None:
        return 1
    labels = ingest.label_line(doc)
    print(f"{doc.name}" + (f" — {labels}" if labels else ""))
    title = store.effective_labels(doc).get("title")
    if title:
        print(f"Title: {title}")
    if doc.page:
        print(f"Page: [[{Path(doc.page).stem}]]")
    print(doc.source)
    if doc.status == "failed":
        print(f"It couldn't be read: {doc.error}")
        return 0
    pages = [_clean(p) for p in store.pages(vault, doc.doc_id)]
    print(f"{_plural(len(pages), 'page')}, read {doc.read_at}.")
    span = _page_range(args.pages, len(pages))
    if span is None:
        print("Pages should look like 14 or 14-16.")
        return 1
    first, last = span
    if first < 1 or first > len(pages):
        print(f"{doc.name} has {_plural(len(pages), 'page')}.")
        return 1
    if len(pages[first - 1]) > SHOW_CHARS:  # one page longer than a whole `show` (a big sheet): in parts
        return _show_part(doc, pages, first, args.part)
    used, n = 0, first
    while n <= last and (n == first or used + len(pages[n - 1]) <= SHOW_CHARS):
        print(f"\n--- p. {n} ---\n{pages[n - 1]}")
        used += len(pages[n - 1])
        n += 1
    if args.pages:  # the range asked for: what's left of it
        left, end = last - n + 1, last
    else:
        left, end = len(pages) - n + 1, min(len(pages), n - 1 + SHOW_PAGES)
    if left > 0:
        print(f"\n…{_plural(left, 'more page')}; continue with --pages {n}" + (f"-{end}" if end > n else "") + ".")
    return 0


def _show_part(doc, pages: list[str], n: int, part: int) -> int:
    text = pages[n - 1]
    parts = -(-len(text) // SHOW_CHARS)
    if not 1 <= part <= parts:
        print(f"p. {n} of {doc.name} has {_plural(parts, 'part')}.")
        return 1
    print(f"\n--- p. {n} (part {part} of {parts}) ---\n{text[(part - 1) * SHOW_CHARS:part * SHOW_CHARS]}")
    if part < parts:
        print(f"\n…p. {n} goes on; continue with --pages {n} --part {part + 1}.")
    elif n < len(pages):
        print(f"\n…{_plural(len(pages) - n, 'more page')}; continue with --pages {n + 1}.")
    return 0


def _list(args, vault) -> int:
    from ..memory.facts import fold
    from . import ingest, store

    docs = store.all_docs(vault)
    if args.failed:
        docs = [d for d in docs if d.status == "failed"]
        if not docs:
            print("No documents failed to read.")
            return 0
    if not docs:
        print("The knowledge base is empty. Point Bron to documents with `bron kb add <link or path>`.")
        return 0
    want_company, want_type = fold(args.company).strip(), fold(args.doc_type).strip()
    shown = 0
    for d in sorted(docs, key=lambda d: (d.name.casefold(), d.doc_id)):
        labels = store.effective_labels(d)
        if want_company and want_company not in fold(str(labels.get("company") or "")):
            continue
        if want_type and want_type != fold(str(labels.get("doc_type") or "")):
            continue
        if d.status == "failed":
            print(f"{d.doc_id}  {d.name} — couldn't be read: {d.error}")
        else:
            line = ingest.label_line(d)
            print(f"{d.doc_id}  {d.name}" + (f" — {line}" if line else ""))
        shown += 1
    if not shown:
        print("No documents match.")
    return 0


# ---- forget ----

def _tools_ready() -> bool:
    from . import tools

    return not tools.missing()


def _drop_index_files(vault) -> None:
    """Without the tools the index can't be edited; removing it makes the next search rebuild it from the store."""
    from .store import kb_dir

    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            (kb_dir(vault) / f"index.db{suffix}").unlink()
        except OSError:
            pass


def _forget(args, vault) -> int:
    from . import store, wiki

    doc = _find(vault, args.doc)
    if doc is None:
        return 1
    if _tools_ready():
        from . import index

        index.drop(vault, doc.doc_id)
    else:
        _drop_index_files(vault)
    store.forget(vault, doc.doc_id)
    kept = " Its copy in Knowledge/Files is still there." if doc.kind == "file" else ""
    text = f"Forgot {doc.name}; searches won't find it any more. The original wasn't touched.{kept}"
    note = f"{doc.name} (doc {doc.doc_id})"
    if doc.page:  # the page isn't deleted: the check flags it until the user decides
        title = Path(doc.page).stem
        text += f" Its page [[{title}]] is still there; delete it or keep it."
        note += f"; its page [[{title}]] was kept"
    print(text)
    try:
        wiki.append_log(vault, [("forget", note)])
    except store.KbError as exc:  # log.md can't be read: the document is forgotten all the same
        print(exc)
    return 0


# ---- status ----

def _wait(args, vault, *, sleep=None, clock=None) -> int:
    """Wait until nothing is being read or written into the wiki, then print what the user is to be told (the same
    reports and ticket updates their next message would bring, which are then not told again)."""
    import time

    from .. import hooks
    from . import jobs

    sleep, clock = sleep or time.sleep, clock or time.monotonic
    start, idle = clock(), 0
    job_id = getattr(args, "job", "") or ""
    if job_id and jobs.load(vault, job_id) is None:
        print(f"There's no reading {job_id}; `.bron/bin/bron kb status` shows what's being read.")
        return 1

    def busy() -> bool:
        if job_id:
            return any(j.job_id == job_id for j in jobs.pending(vault) + jobs.wiki_pending(vault))
        return bool(jobs.pending(vault) or jobs.wiki_pending(vault))

    while busy():
        if jobs.stalled(vault):
            idle += 1
            if idle >= 3:  # nobody has been at work for three checks in a row
                print("Reading stopped before it finished. Run `.bron/bin/bron kb status` to start it again.")
                return 1
        else:
            idle = 0
        if clock() - start > WAIT_HOURS * 3600:
            print(f"Still reading after {WAIT_HOURS} hours; `.bron/bin/bron kb status` shows where it is.")
            return 1
        sleep(10)
    if job_id:
        print(_job_report(vault, jobs.load(vault, job_id)))
        return 0
    text = hooks.updates_text("kb-wait")
    print(text.rstrip() if text.strip() else "Everything is read and written; it was already reported.")
    return 0


def _job_report(vault, job) -> str:
    """What one reading came to: its reports and its wiki tickets, even when another conversation told them first (this
    one asked for it). They aren't told again at the next message."""
    from .. import notifications, tickets
    from . import notices

    lines = notices.take_jobs(vault, [job.job_id, f"{job.job_id}-wiki"])
    done = []
    for ticket_id in job.wiki_tickets:
        try:
            ticket = tickets.load_ticket(tickets.find_ticket(vault, ticket_id))
        except Exception:  # noqa: BLE001 - a ticket deleted by hand: the rest are still told
            continue
        notifications.acknowledge(vault, ticket.id)
        done.append(f"- {ticket.id} \"{ticket.title}\" is {ticket.status}")
    if done:
        lines += ["Wiki pages written in:", *done,
                  "Read each ticket's result (.bron/bin/bron ticket show <id>) and tell the user what was learned."]
    return "\n".join(lines) if lines else "That reading is finished; nothing more to report."


def _status(args, vault) -> int:
    from . import jobs, store, tools

    if args.cancel:
        if not jobs.pending(vault) and not jobs.wiki_pending(vault):
            print("Nothing is being read, so there's nothing to cancel.")
            return 0
        reports = jobs.cancel(vault)
        for text in reports:
            print(text)
        if jobs.runner_active(vault):
            print("Bron stops after the document it's reading now and reports what it read.")
        if jobs.wiki_active(vault):
            print("Bron finishes the wiki pages it's writing now.")
        return 0
    missing = tools.missing()
    if not missing and store.indexing_ids(vault):
        from . import index

        try:
            index.finish_pending(vault, _embedder(vault))  # an interruption left documents half-indexed
        except Exception:  # noqa: BLE001 - the next search tries again
            pass
    docs = store.all_docs(vault)
    failed = sum(1 for d in docs if d.status == "failed")
    line = f"The knowledge base has {_plural(len(docs) - failed, 'document')}."
    if failed:
        line += f" {_plural(failed, 'document')} couldn't be read; see `bron kb list --failed`."
    print(line)
    if missing:
        print("The knowledge base tools aren't installed yet; Bron sets them up the first time you add or search.")
    for text in jobs.status_lines(vault):
        print(text)
    stalled = jobs.stalled(vault)
    if stalled and jobs.spawn(vault, stalled[0].job_id):
        print("Bron stopped before it finished; it's picking it up again in the background.")
    return 0

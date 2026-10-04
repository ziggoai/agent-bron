"""`bron kb …`: read what the user points to, search it, and look after what was read."""
from __future__ import annotations

import re

NOTHING = "Nothing in the knowledge base matches that. Try other words, or check `bron kb list`."
HIDDEN = {"serve", "run-job"}
KEYWORD_NOTE = "Meaning search isn't available right now; these are keyword matches."
MAX_DOCS = 300
MAX_PAGES = 3000
FOREGROUND = 5
FOREGROUND_PAGES = 50  # more pages than this, or any scan or photo, is read in the background
SECONDS_PER_PAGE = 0.2  # 0.05 s per text page, about 1 s per scanned page: 0.2 s on average
SHOW_PAGES = 20
NEEDS_TOOLS = {"search", "serve", "run-job"}  # `add` never installs in the foreground: its background job does
SETTING_UP = "Setting up the knowledge base tools and reading in the background; I'll report when it's done."
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
    search.add_argument("--company", default="", help="the company or organisation a document is about")
    search.add_argument("--type", dest="doc_type", default="")
    search.add_argument("--after", default="", help="only documents dated on or after YYYY-MM-DD")
    search.add_argument("--before", default="", help="only documents dated on or before YYYY-MM-DD")
    search.add_argument("--limit", type=int, default=8)

    show = commands.add_parser("show", help="the text Bron read from one document")
    show.add_argument("doc", help="the document's id, name or part of its name")
    show.add_argument("--pages", default="", help="a page or a range, like 14 or 14-16")

    listing = commands.add_parser("list", help="the documents Bron has read")
    listing.add_argument("--company", default="")
    listing.add_argument("--type", dest="doc_type", default="")
    listing.add_argument("--failed", action="store_true", help="only the documents that couldn't be read")

    forget = commands.add_parser("forget", help="remove a document from the knowledge base")
    forget.add_argument("doc", help="the document's id, name or part of its name")

    label = commands.add_parser("label", help="correct a document's company, type, date or title")
    label.add_argument("doc", help="the document's id, name or part of its name")
    for flag, dest in (("--company", "company"), ("--type", "doc_type"), ("--date", "date"), ("--title", "title")):
        label.add_argument(flag, dest=dest, default=None, help="empty ('') undoes your correction")

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
        command = {"add": _add, "show": _show, "list": _list, "forget": _forget, "label": _label,
                   "status": _status, "run-job": _run_job}.get(args.kb_command)
        if command is not None:
            return command(args, vault)
    except KbError as exc:
        print(exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - never a traceback for the user (Ctrl-C still stops it)
        _log_crash(vault, args, exc)
        print(CRASHED.format(exc.__class__.__name__))
        return 1
    print("Not available yet.")
    return 1


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
    from . import embed, search, service

    request = {"query": args.query, "company": args.company, "doc_type": args.doc_type,
               "after": args.after, "before": args.before, "limit": args.limit}
    reply = service.query(vault, request)
    if reply is not None and "error" in reply:
        print(reply["error"])
        return 1
    if reply is not None:
        hits = [search.Hit(**h) for h in reply.get("hits", [])]
        note = bool(reply.get("keyword_only"))
    else:
        probe = service.Probe(embed.get(vault))
        hits = search.search(vault, args.query, embedder=probe, company=args.company,
                             doc_type=args.doc_type, after=args.after, before=args.before, limit=args.limit)
        note = probe.failed
    if note:
        print(KEYWORD_NOTE)
    print(search.render(hits) if hits else NOTHING)
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


def _queue(vault, items, failed, *, again: bool, setting_up: bool) -> int:
    from . import jobs

    job = jobs.create(vault, items, failed=failed, again=again)
    if not jobs.spawn(vault, job.job_id):
        print("Bron couldn't start reading in the background (.bron/bin/bron is missing). Run `.bron/bin/bron check`.")
        return 1
    print(SETTING_UP if setting_up else f"Reading {_plural(len(items), 'document')} in the background; I'll report when it's done.")
    return 0


def _add_export(args, vault, setting_up: bool) -> int:
    from ..loader import load
    from . import ingest

    if args.targets or args.inbox:
        print("--file reads one exported Google file on its own. Run it separately from other links, paths or --inbox.")
        return 1
    if not (args.file and args.source and args.name):
        print("To add an exported Google Doc, give all three: --file <text file> --source <Drive link> --name '<title>'.")
        return 1
    item = ingest.export_item(args.file, args.source, args.name)  # a plain error now if the link or file is wrong
    if setting_up:
        return _queue(vault, [item], [], again=False, setting_up=True)
    doc = ingest.add_export(vault, load(vault), args.file, args.source, args.name, embedder=_embedder(vault))
    print(ingest.summary([doc]))
    return 0 if doc.status == "read" else 1


def _add(args, vault) -> int:
    from ..loader import load
    from . import ingest, jobs, sources, tools

    setting_up = bool(tools.missing())  # the first time: the background job installs the tools, then reads
    if args.file or args.source or args.name:
        return _add_export(args, vault, setting_up)
    if not args.targets and not args.inbox:
        print("Tell me what to read: a Google Drive link, a file or folder path, a web link, or --inbox.")
        return 1
    found, failed = sources.resolve(vault, args.targets, inbox=args.inbox)
    items, seen = [], set()
    for item in found:  # the same file named twice is read once
        if item.identity not in seen:
            seen.add(item.identity)
            items.append(item)
    if not items:
        if failed:
            print("\n".join(failed))
            return 1
        print("The inbox (Knowledge/Inbox) is empty." if args.inbox and not args.targets else "There's nothing to read there.")
        return 0
    # A few files are opened to count their pages; more are estimated from their size, so nothing is downloaded
    # from Drive before the user says yes. Online-only files are never opened to count.
    few = len(items) <= FOREGROUND and not setting_up
    pages = sum((ingest.page_count if few else ingest.guess_pages)(item) for item in items) if few or not args.yes else 0
    if not args.yes and (len(items) > MAX_DOCS or pages > MAX_PAGES):
        print(_ask_first(vault, len(items), pages))
        return 0
    # Only a quick read stays in the foreground, so an agent's command never outlasts its time limit.
    quick = (few and pages <= FOREGROUND_PAGES and not any(ingest.looks_scanned(item) for item in items)
             and not jobs.runner_active(vault))  # never two readers at once
    if not quick:
        return _queue(vault, items, failed, again=args.again, setting_up=setting_up)
    cfg, embedder = load(vault), _embedder(vault)
    docs = [ingest.read_item(vault, cfg, item, embedder=embedder, again=args.again) for item in items]
    print(ingest.summary(docs, failed))
    return 0 if any(d.status in ("read", "unchanged") for d in docs) else 1


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
    print(doc.source)
    if doc.status == "failed":
        print(f"It couldn't be read: {doc.error}")
        return 0
    pages = store.pages(vault, doc.doc_id)
    print(f"{_plural(len(pages), 'page')}, read {doc.read_at}.")
    span = _page_range(args.pages, len(pages))
    if span is None:
        print("Pages should look like 14 or 14-16.")
        return 1
    first, last = span
    if first < 1 or first > len(pages):
        print(f"{doc.name} has {_plural(len(pages), 'page')}.")
        return 1
    for n in range(first, last + 1):
        print(f"\n--- p. {n} ---\n{pages[n - 1]}")
    if not args.pages and len(pages) > last:
        print(f"\n…{_plural(len(pages) - last, 'more page')}; use --pages, like --pages {last + 1}-{min(len(pages), last + SHOW_PAGES)}.")
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


# ---- forget, label ----

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
    from . import store

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
    print(f"Forgot {doc.name}; searches won't find it any more. The original wasn't touched.{kept}")
    return 0


def _label(args, vault) -> int:
    from datetime import datetime

    from . import ingest, models, store
    from .passages import split

    doc = _find(vault, args.doc)
    if doc is None:
        return 1
    given = {k: v for k, v in (("company", args.company), ("doc_type", args.doc_type), ("date", args.date),
                               ("title", args.title)) if v is not None}
    if not given:
        print(f"Labels for {doc.name}: {ingest.label_line(doc) or 'none'}")
        return 0
    if doc.status == "failed":
        print(f"{doc.name} couldn't be read, so there's nothing to label. Read it again first.")
        return 1
    if given.get("date"):
        try:
            given["date"] = datetime.strptime(given["date"].strip(), "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            print("Dates should look like YYYY-MM-DD (for example 2025-01-21).")
            return 1
    if given.get("doc_type"):
        from ..loader import load

        types = models.doc_types(load(vault))
        kind = models.match_type(given["doc_type"], types)
        if kind is None:
            print("The type should be one of: " + ", ".join(types) + ". You can set your own list with "
                  "`knowledge: doc_types:` in System/Settings.md.")
            return 1
        given["doc_type"] = kind
    for key in ("company", "title"):
        if key in given:
            given[key] = models.clean(given[key], None, 120)
    user = dict(doc.user_labels)
    fund = user.pop("fund", "")  # Bron 0.7.0 had a fund label: it becomes the company when there is none
    if fund and not user.get("company") and not (isinstance(doc.labels, dict) and doc.labels.get("company")):
        user["company"] = fund
    user.update(given)
    doc.user_labels = {k: v for k, v in user.items() if v}  # an empty value undoes a correction
    pages = store.pages(vault, doc.doc_id)
    passages = split([(i + 1, t) for i, t in enumerate(pages)], store.effective_labels(doc))  # headers carry the labels
    store.save(vault, doc, pages, passages)
    if _tools_ready():
        from . import index

        index.put(vault, doc, passages, _embedder(vault))
        if doc.status == "indexing":  # an interrupted reading: now it's indexed
            doc.status = "read"
            store.save_meta(vault, doc)
            store.clear_indexing(vault, doc.doc_id)
    else:
        _drop_index_files(vault)
    print(f"Labels for {doc.name}: {ingest.label_line(doc) or 'none'}")
    return 0


# ---- status ----

def _status(args, vault) -> int:
    from . import jobs, store, tools

    if args.cancel:
        if not jobs.pending(vault):
            print("Nothing is being read, so there's nothing to cancel.")
            return 0
        reports = jobs.cancel(vault)
        for text in reports:
            print(text)
        if jobs.runner_active(vault):
            print("Bron stops after the document it's reading now and reports what it read.")
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
        print("The reading and search tools aren't installed yet; Bron sets them up the first time you add or search.")
    for text in jobs.status_lines(vault):
        print(text)
    stalled = jobs.stalled(vault)
    if stalled and jobs.spawn(vault, stalled[0].job_id):
        print("Reading stopped before it finished; Bron is picking it up again in the background.")
    return 0

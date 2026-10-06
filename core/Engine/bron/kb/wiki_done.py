"""`bron wiki done`: run by an agent after writing pages. It records document pages, indexes the changed pages, rewrites
index.md, logs what happened and checks what changed. One bad page never stops the rest."""
from __future__ import annotations

from pathlib import Path

from .. import statefile
from ..vault import Vault
from . import store, wiki, wiki_check

STATE = "wiki-state.json"  # what `wiki done` saw last time (searches keep their own record in index.db)


def _state_path(vault: Vault) -> Path:
    return store.kb_dir(vault) / STATE


def _read_stamp(vault: Vault, doc_id: str) -> float:
    """When the document's text was last saved (it changes only when it is read)."""
    try:
        return (store.kb_dir(vault) / "docs" / doc_id / "pages.jsonl").stat().st_mtime
    except OSError:
        return 0.0


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _index(vault: Vault) -> None:
    """The changed pages' words go into the search database now; the next search adds their meaning."""
    from . import tools

    if tools.missing():
        return  # the first search after setup indexes them
    from . import index, wiki_index
    from .store import KbError

    if not index.db_path(vault).is_file():
        return  # no search database yet: the next search builds it from the stored documents

    def run():
        con = index.open(vault)
        try:
            wiki_index.refresh(vault, con, None)
        finally:
            con.close()

    try:
        index.with_recovery(vault, index._Lazy(vault), run)
    except KbError:
        pass  # busy: the next search catches up


def done(vault: Vault, *, log_text: str = "") -> str:
    """One `wiki done` at a time: two at once would both see the same changed pages and log them twice."""
    with statefile.locked(store.kb_dir(vault) / "wiki-done"):  # not "wiki-log": append_log takes that one inside
        return _done(vault, log_text)


def _done(vault: Vault, log_text: str) -> str:
    state = statefile.read_json(_state_path(vault), {})
    before = state.get("pages") if isinstance(state.get("pages"), dict) else {}
    reads = state.get("docs") if isinstance(state.get("docs"), dict) else {}
    pages = wiki.all_pages(vault)
    now = {p.rel: [p.mtime, p.size] for p in pages}
    changed = [p for p in pages if before.get(p.rel) != now[p.rel]]
    removed = sorted(set(before) - set(now))
    new = [p for p in changed if p.rel not in before]
    wiki.link_documents(vault, changed, removed)
    _index(vault)
    wiki.write_index(vault, pages)
    entries: list[tuple[str, str]] = []
    others: list[wiki.Page] = []
    for page in sorted(changed, key=lambda p: p.title.casefold()):
        if page.error:
            continue
        if page.is_document and page.rel not in before:
            entries.append(("ingest", f"[[{page.title}]]"))
        elif page.is_document and page.doc_id in reads and reads[page.doc_id] != _read_stamp(vault, page.doc_id):
            entries.append(("ingest", f"[[{page.title}]] (read again)"))
        else:
            others.append(page)
    if others or removed:
        text = ", ".join(f"[[{p.title}]]" for p in others)
        if removed:
            text += ("; " if text else "") + "removed: " + ", ".join(Path(rel).stem for rel in removed)
        entries.append(("update", text))
    if log_text.strip():
        entries.append(wiki.parse_log_text(log_text))
    notes: list[str] = []
    try:
        wiki.append_log(vault, entries)
    except store.KbError as exc:
        notes.append(str(exc))  # log.md can't be read: say so, carry on with everything else
    scope = {p.rel for p in changed}
    names = {wiki.name_of(p.title) for p in changed} | {wiki.name_of(Path(rel).stem) for rel in removed}
    scope |= {p.rel for p in pages if not p.error and any(wiki.name_of(t) in names for t in p.links())}
    problems = wiki_check.run(vault, only=scope, pages=pages) if scope else []
    docs = {p.doc_id: _read_stamp(vault, p.doc_id) for p in pages
            if not p.error and p.doc_id and store.exists(vault, p.doc_id)}
    statefile.write_json(_state_path(vault), {"pages": now, "docs": docs})
    if not changed and not removed:
        head = "Nothing changed in the wiki" + ("; the log line is recorded." if log_text.strip() and not notes else ".")
    else:
        head = f"Wiki updated: {_plural(len(changed), 'page')} ({len(new)} new)."
    if not problems:
        return "\n".join([head, *notes])
    return "\n".join([head, *notes, *[f"- {p.text}" for p in problems],
                      "Fix these, then run `.bron/bin/bron wiki done` again."])

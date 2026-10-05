"""Wiki pages in the search database: their words and meaning, refreshed from the files' modification times on every
search (a quick look at Knowledge/**/*.md) and by `bron wiki done`."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..vault import Vault
from . import index, store, wiki
from .embed import DIM
from .passages import normal_tokens, windows
from .store import KbError

PAGES = 3  # wiki pages a search shows
TOP = 50
EXCERPT = 400


@dataclass
class PageHit:
    path: str  # vault-relative
    title: str
    kind: str
    summary: str
    excerpt: str  # the best-matching part of the page
    score: float


def _stats(vault: Vault) -> dict[str, tuple[float, int, Path]]:
    out: dict[str, tuple[float, int, Path]] = {}
    for path in wiki.page_paths(vault):
        try:
            st = path.stat()
        except OSError:
            continue
        out[path.relative_to(vault.root).as_posix()] = (st.st_mtime, st.st_size, path)
    return out


def _pieces(page: wiki.Page) -> list[tuple[str, str]]:
    """(excerpt, searchable text) per ~100-word window; the title, other names and summary go with every window."""
    head = " ".join([page.title, *page.aliases, page.summary]).strip()
    body = wiki.LINK.sub(lambda m: m.group(1), page.body)  # [[Acme Ltda|Acme]] reads as Acme Ltda
    return [(w, f"{head} {w}".strip()) for w in (windows(body) or [""])]


def _delete(con: sqlite3.Connection, rel: str) -> None:
    for table in ("pages", "page_fts", "page_vectors"):
        con.execute(f"DELETE FROM {table} WHERE path = ?", (rel,))


def _put(con: sqlite3.Connection, page: wiki.Page, embedder, *, only_with_vectors: bool = False) -> None:
    """Index one page. Without the meaning model (or embedder None) its words go in now and its vectors later."""
    pieces = _pieces(page)
    matrix = None
    if embedder is not None:
        try:
            matrix = np.asarray(embedder.embed([t for _, t in pieces]), dtype=np.float32)
        except KbError:
            matrix = None
    if only_with_vectors and matrix is None:
        return
    with con:
        _delete(con, page.rel)
        con.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?)", (page.rel, page.mtime, page.size, page.title, page.kind,
                                                                   page.summary, page.doc_id, int(matrix is not None)))
        con.executemany("INSERT INTO page_fts(path, w, excerpt, body) VALUES (?,?,?,?)",
                        [(page.rel, w, excerpt, f"{text} {' '.join(normal_tokens(text))}")
                         for w, (excerpt, text) in enumerate(pieces)])
        if matrix is not None:
            con.executemany("INSERT INTO page_vectors VALUES (?,?,?)",
                            [(page.rel, w, matrix[w].tobytes()) for w in range(len(pieces))])


def _put_broken(con: sqlite3.Connection, page: wiki.Page) -> None:
    """A page whose properties can't be read: remembered (so it isn't read on every search) but never found."""
    with con:
        _delete(con, page.rel)
        con.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?)", (page.rel, page.mtime, page.size, page.title, "", "", "", 1))


def refresh(vault: Vault, con: sqlite3.Connection, embedder) -> bool:
    """Bring the pages in the index up to date: new and changed pages, removed ones, and vectors still missing. Document
    pages are recorded as their documents' pages and their labels go into the search filters; index.md is rewritten
    when pages changed. True when anything changed."""
    current = _stats(vault)
    known = {r[0]: (r[1], r[2], r[3]) for r in con.execute("SELECT path, mtime, size, vectors FROM pages")}
    removed = sorted(set(known) - set(current))
    changed = [rel for rel, (mtime, size, _) in current.items() if rel not in known or known[rel][:2] != (mtime, size)]
    waiting = [rel for rel, row in known.items() if rel in current and rel not in changed and not row[2]]
    if not removed and not changed and not (waiting and embedder is not None):
        return False
    embedder = index._FailFast(embedder) if embedder is not None else None
    for rel in removed:
        with con:
            _delete(con, rel)
    pages = [wiki.read_page(vault, current[rel][2]) for rel in changed]
    for page in pages:
        if page.error:
            _put_broken(con, page)
        else:
            _put(con, page, embedder)
    for rel in (waiting if embedder is not None else []):
        page = wiki.read_page(vault, current[rel][2])
        if not page.error:
            _put(con, page, embedder, only_with_vectors=True)
    good = [p for p in pages if not p.error]
    _, touched = wiki.link_documents(vault, good, removed)
    for doc_id in touched | {p.doc_id for p in good if p.doc_id}:
        doc = store.load(vault, doc_id)
        if doc is not None and doc.status == "read":
            index.set_labels(con, doc)
    if removed or changed:
        wiki.write_index(vault)
    return True


def _keyword(con: sqlite3.Connection, query: str) -> list[tuple[str, int]]:
    from .search import _query_terms

    terms = _query_terms(query)
    if not terms:
        return []
    sql = f"SELECT path, w FROM page_fts WHERE page_fts MATCH ? ORDER BY bm25(page_fts) LIMIT {TOP}"
    return [(path, int(w)) for path, w in con.execute(sql, [" OR ".join(terms)])]


def _meaning(con: sqlite3.Connection, query: str, embedder) -> list[tuple[str, int]]:
    if embedder is None:
        return []
    rows = con.execute("SELECT path, w, vec FROM page_vectors").fetchall()
    if not rows:
        return []
    try:
        q = embedder.embed([query])[0]
    except KbError:
        return []  # the model isn't available: keyword matches still work
    matrix = np.frombuffer(b"".join(r[2] for r in rows), dtype=np.float32).reshape(len(rows), DIM)
    scores = matrix @ q
    return [(rows[i][0], int(rows[i][1])) for i in np.argsort(-scores)[:TOP] if scores[i] > 0]


def search_pages(vault: Vault, con: sqlite3.Connection, query: str, embedder, *, allowed: set[str] | None = None,
                 limit: int = PAGES) -> list[PageHit]:
    """The best pages for the question. With filters (`allowed`: the documents they leave), a document page is shown
    only when its document is allowed; other pages are matched by the question alone."""
    from .search import _fuse

    if limit <= 0:
        return []
    rows = {r[0]: r for r in con.execute("SELECT path, title, kind, summary, doc_id FROM pages WHERE kind != ''")}
    if allowed is not None:
        rows = {path: r for path, r in rows.items() if not r[4] or r[4] in allowed}
    if not rows:
        return []
    best: dict[str, tuple[int, float]] = {}
    for (path, w), score in _fuse(_keyword(con, query), _meaning(con, query, embedder)):
        if path in rows and path not in best:
            best[path] = (w, score)
            if len(best) >= limit:
                break
    hits: list[PageHit] = []
    for path, (w, score) in best.items():
        found = con.execute("SELECT excerpt FROM page_fts WHERE path = ? AND w = ?", (path, w)).fetchone()
        text = found[0] if found else ""
        excerpt = text if len(text) <= EXCERPT else text[:EXCERPT].rstrip() + "…"
        _, title, kind, summary, _ = rows[path]
        hits.append(PageHit(path, title, kind, summary, excerpt, score))
    return hits

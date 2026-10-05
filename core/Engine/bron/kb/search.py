"""Search the knowledge base: words and meaning, merged by rank."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..memory.facts import fold
from ..vault import Vault
from . import index, store
from .embed import DIM
from .passages import normal_tokens
from .store import KbError

RRF_K = 60
TOP = 50
TEXT_LIMIT = 1200
_WORD = re.compile(r"\w+")
_NUMBER_RUN = re.compile(r"\d+(?:[.,]\d+)+")

# One vector matrix per process, reloaded when the index file changes.
_MATRIX: dict = {}


@dataclass
class Hit:
    doc_id: str
    name: str
    labels: dict
    page: int
    section: str
    source: str
    text: str
    score: float
    wiki_page: str = ""  # the title of the document's wiki page, when it has one


def _filtered(con, company, doc_type, after, before) -> set[str]:
    want_company, want_type = fold(company).strip(), fold(doc_type).strip()
    keep = set()
    # `fund`: only rows written by Bron 0.7.0 have one; it counts as the company when there is none
    for doc_id, c, f, t, d in con.execute("SELECT doc_id, company, fund, doc_type, date FROM docs"):
        if want_company and want_company not in fold(c or f or ""):
            continue
        if want_type and want_type != fold(t or ""):
            continue
        if (after or before) and not d:
            continue
        if after and d < after:
            continue
        if before and d > before:
            continue
        keep.add(doc_id)
    return keep


def _query_terms(query: str) -> list[str]:
    """Quoted FTS terms: numeric runs (4.2, 1.500.000,00) stay one phrase; words and normalised amounts/dates are single terms."""
    folded = fold(query)
    runs = _NUMBER_RUN.findall(folded)
    rest = _NUMBER_RUN.sub(" ", folded)
    raw = [" ".join(re.findall(r"\d+", r)) for r in runs] + _WORD.findall(rest) + normal_tokens(query)
    seen: set[str] = set()
    return ['"' + w.replace('"', "") + '"' for w in raw if w and not (w in seen or seen.add(w))]


def _keyword(con, query: str, allowed: set[str] | None) -> list[tuple[str, int]]:
    terms = _query_terms(query)
    if not terms:
        return []
    match = " OR ".join(terms)
    sql = "SELECT doc_id, n FROM fts WHERE fts MATCH ?"
    args: list = [match]
    if allowed is not None:
        sql += " AND doc_id IN (SELECT value FROM json_each(?))"
        args.append(json.dumps(sorted(allowed)))
    sql += f" ORDER BY bm25(fts) LIMIT {TOP}"
    return [(d, int(n)) for d, n in con.execute(sql, args)]


def _read_vectors(con) -> list[tuple[str, int, bytes]]:
    return con.execute("SELECT doc_id, n, vec FROM vectors").fetchall()


def _load_matrix(vault: Vault, con):
    path = index.db_path(vault)
    key = (index.counter(con), path.stat().st_ino)  # the counter changes on every put, drop and rebuild
    cached = _MATRIX.get(str(path))
    if cached and cached[0] == key:
        return cached[1]
    rows = _read_vectors(con)
    if rows:
        matrix = np.frombuffer(b"".join(r[2] for r in rows), dtype=np.float32).reshape(len(rows), DIM)
    else:
        matrix = np.zeros((0, DIM), dtype=np.float32)
    doc_ids = sorted({r[0] for r in rows})
    doc_index = {d: i for i, d in enumerate(doc_ids)}
    pass_keys: dict[tuple[str, int], int] = {}
    doc_of = np.empty(len(rows), dtype=np.int32)
    pass_of = np.empty(len(rows), dtype=np.int32)
    for i, (d, n, _) in enumerate(rows):
        doc_of[i] = doc_index[d]
        pass_of[i] = pass_keys.setdefault((d, n), len(pass_keys))
    data = (matrix, doc_index, doc_of, pass_of, list(pass_keys))
    _MATRIX[str(path)] = (key, data)
    return data


def _meaning(vault: Vault, con, query: str, allowed: set[str] | None, embedder) -> list[tuple[str, int]]:
    matrix, doc_index, doc_of, pass_of, pass_list = _load_matrix(vault, con)
    if not len(matrix):
        return []
    try:
        q = embedder.embed([query])[0]
    except KbError:
        return []  # the model isn't available: keyword search still works
    if allowed is None:
        mask = np.ones(len(matrix), dtype=bool)
    else:
        ok = np.zeros(len(doc_index), dtype=bool)
        for d in allowed:
            if d in doc_index:
                ok[doc_index[d]] = True
        mask = ok[doc_of]
    if not mask.any():
        return []
    scores = matrix[mask] @ q
    best = np.full(len(pass_list), -np.inf, dtype=np.float32)
    np.maximum.at(best, pass_of[mask], scores)
    order = np.argsort(-best)[:TOP]
    return [pass_list[i] for i in order if best[i] > 0]


def _fuse(*rankings: list[tuple[str, int]]) -> list[tuple[tuple[str, int], float]]:
    score: dict[tuple[str, int], float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            score[key] = score.get(key, 0.0) + 1.0 / (RRF_K + rank)
    return sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))


@dataclass
class Results:
    pages: list  # wiki_index.PageHit, best first (at most 3)
    hits: list[Hit]  # document passages, best first


class _Once:
    """Works out the question's meaning once for the whole search, and gives up after the first failure: when the model
    isn't available, nothing else in this search tries it again (each try may be a slow download)."""

    def __init__(self, inner):
        self._inner = inner
        self._seen: dict = {}
        self._error: KbError | None = None

    @property
    def model(self):
        return index._model_name(self._inner)

    def embed(self, texts):
        if self._error is not None:
            raise self._error
        key = tuple(texts)
        if key in self._seen:
            return self._seen[key]
        try:
            result = self._inner.embed(texts)
        except KbError as exc:
            self._error = exc
            raise
        if len(texts) == 1:  # the question; bigger batches (an index rebuild) aren't kept
            self._seen[key] = result
        return result


def _find(vault, query, embedder, company, doc_type, after, before, limit, pages_only) -> Results:
    from . import wiki_index

    embedder = _Once(embedder)
    index.ensure(vault, embedder)
    con = index.open(vault)
    try:
        try:
            wiki_index.refresh(vault, con, embedder)
        except (OSError, UnicodeDecodeError) as exc:  # a page Bron can't open: the rest still works
            from .ingest import _log

            _log(vault, "refreshing the wiki pages", exc)
        filtering = any((company, doc_type, after, before))
        allowed = _filtered(con, company, doc_type, after, before) if filtering else None
        pages = wiki_index.search_pages(vault, con, query, embedder, allowed=allowed)
        if pages_only or limit <= 0 or (allowed is not None and not allowed):
            return Results(pages, [])
        keyword = _keyword(con, query, allowed)
        meaning = _meaning(vault, con, query, allowed, embedder)
    finally:
        con.close()
    hits: list[Hit] = []
    docs: dict[str, tuple] = {}
    for (doc_id, n), score in _fuse(keyword, meaning):
        if doc_id not in docs:
            doc = store.load(vault, doc_id)
            docs[doc_id] = (doc, store.passages(vault, doc_id)) if doc else (None, [])
        doc, passages = docs[doc_id]
        if doc is None or doc.status != "read" or n >= len(passages):
            continue  # the index is out of step with the store (or the last reading failed); skip
        p = passages[n]
        hits.append(Hit(doc_id, doc.name, store.effective_labels(doc), p.get("page") or 0, str(p.get("section") or ""),
                        doc.source, str(p.get("text", "")), score, Path(doc.page).stem if doc.page else ""))
        if len(hits) >= limit:
            break
    return Results(pages, hits)


def find(vault: Vault, query: str, *, embedder, company: str = "", doc_type: str = "", after: str = "",
         before: str = "", limit: int = 8, pages_only: bool = False) -> Results:
    """Wiki pages (at most 3), then document passages (at most `limit`)."""
    return index.with_recovery(
        vault, embedder, lambda: _find(vault, query, embedder, company, doc_type, after, before, limit, pages_only))


def search(vault: Vault, query: str, *, embedder, company: str = "", doc_type: str = "",
           after: str = "", before: str = "", limit: int = 8) -> list[Hit]:
    return find(vault, query, embedder=embedder, company=company, doc_type=doc_type, after=after, before=before,
                limit=limit).hits


def render(hits: list[Hit]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        labels = store.fold_fund(dict(h.labels))  # hits from a helper still running 0.7.0 may carry "fund"
        parts = [labels.get("title") or h.name, labels.get("company"), labels.get("doc_type"), labels.get("date")]
        if h.page:
            parts.append(f"p. {h.page}")
        if h.section:
            parts.append(h.section)
        head = " · ".join(str(p) for p in parts if p)
        text = h.text if len(h.text) <= TEXT_LIMIT else h.text[:TEXT_LIMIT].rstrip() + "…"
        page_line = f"\nPage: [[{h.wiki_page}]]" if h.wiki_page else ""
        blocks.append(f"{i}. {head}\n{h.source}{page_line}\n{text}")
    return "\n\n".join(blocks)


def render_pages(pages) -> str:
    blocks = []
    for i, p in enumerate(pages, start=1):
        head = f"{i}. [[{p.title}]]" + (f" — {p.summary}" if p.summary else "")
        blocks.append(f"{head}\n{p.path}\n{p.excerpt}")
    return "\n\n".join(blocks)


def render_all(results: Results) -> str:
    """Wiki pages first, then the document passages; only passages look exactly as before."""
    if results.pages and results.hits:
        return "Wiki pages:\n" + render_pages(results.pages) + "\n\nDocument passages:\n" + render(results.hits)
    if results.pages:
        return "Wiki pages:\n" + render_pages(results.pages)
    return render(results.hits)

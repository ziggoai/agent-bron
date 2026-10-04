"""Search the knowledge base: words and meaning, merged by rank."""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass

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


def _filtered(con, company, fund, doc_type, after, before) -> set[str]:
    want_company, want_fund, want_type = fold(company).strip(), fold(fund).strip(), fold(doc_type).strip()
    keep = set()
    for doc_id, c, f, t, d in con.execute("SELECT doc_id, company, fund, doc_type, date FROM docs"):
        if want_company and want_company not in fold(c or ""):
            continue
        if want_fund and want_fund not in fold(f or ""):
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


def _search(vault, query, embedder, company, fund, doc_type, after, before, limit) -> list[Hit]:
    if limit <= 0:
        return []
    index.ensure(vault, embedder)
    con = index.open(vault)
    try:
        filtering = any((company, fund, doc_type, after, before))
        allowed = _filtered(con, company, fund, doc_type, after, before) if filtering else None
        if allowed is not None and not allowed:
            return []
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
                        doc.source, str(p.get("text", "")), score))
        if len(hits) >= limit:
            break
    return hits


def search(vault: Vault, query: str, *, embedder, company: str = "", fund: str = "", doc_type: str = "",
           after: str = "", before: str = "", limit: int = 8) -> list[Hit]:
    return index.with_recovery(
        vault, embedder, lambda: _search(vault, query, embedder, company, fund, doc_type, after, before, limit)
    )


def render(hits: list[Hit]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        parts = [h.labels.get("title") or h.name, h.labels.get("company") or h.labels.get("fund"), h.labels.get("doc_type"), h.labels.get("date")]
        if h.page:
            parts.append(f"p. {h.page}")
        if h.section:
            parts.append(h.section)
        head = " · ".join(str(p) for p in parts if p)
        text = h.text if len(h.text) <= TEXT_LIMIT else h.text[:TEXT_LIMIT].rstrip() + "…"
        blocks.append(f"{i}. {head}\n{h.source}\n{text}")
    return "\n\n".join(blocks)

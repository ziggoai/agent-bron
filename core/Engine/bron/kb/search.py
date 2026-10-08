"""Search the knowledge base: words and meaning, merged by rank."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
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
POOL = TOP * 4  # passages each ranking gives: the per-document cap and copies leave fewer to show
MAX_POOL = POOL * 16
PER_DOC = 2  # passages shown from one document at most
TEXT_LIMIT = 600  # characters shown of a passage: its best part
WINDOW_WORDS = 100
SAME_MIN = 200  # passages this long with the same text are shown once, naming the other documents
ALSO_SHOWN = 3
_WORD = re.compile(r"\w+")
_NUMBER_RUN = re.compile(r"\d+(?:[.,]\d+)+")

# Function words (English, Portuguese, Spanish) left out of the keyword ranking. No single letters: "Exhibit A",
# "Schedule B", "Part I".
STOPWORDS = frozenset(fold(w) for w in """
    an the and or but nor of to in on at by for from with without into onto about as than then that this these those
    there here is are was were be been being am do does did has have had it its he she they them their his her we our
    you your me my who whom whose what which when where why how all any each if so not no can could will would should
    os as um uma uns umas de do da dos das em no na nos nas num numa por pelo pela pelos pelas para com sem sob sobre
    entre até ou mas nem que se ao aos às quem qual quais cujo cuja onde quando como porque este esta estes estas
    esse essa esses essas isto isso aquele aquela aquilo ele ela eles elas seu sua seus suas lhe lhes meu minha são
    foi ser ter tem há não
    el la los las unos unas del al pero sus lo le les cuando donde quien cual cuales estos ese esos esas es son
    fue si sí más
""".split())

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
    also_in: list[str] = field(default_factory=list)  # other documents with this same passage
    query: str = ""  # the question, to show the passage's best part


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


def _phrases(query: str) -> list[str]:
    """FTS phrases for the question's numeric runs: with the word before ("section 10 9"), then alone ("10 9")."""
    folded = fold(query)
    out = []
    for m in _NUMBER_RUN.finditer(folded):
        run = " ".join(re.findall(r"\d+", m.group(0)))
        before = _WORD.findall(folded[: m.start()])
        if before:
            out.append(f'"{before[-1]} {run}"')
        out.append(f'"{run}"')
    return list(dict.fromkeys(out))


def _matches(con, match: str, allowed: set[str] | None, pool: int) -> list[tuple[str, int]]:
    sql = "SELECT doc_id, n FROM fts WHERE fts MATCH ?"
    args: list = [match]
    if allowed is not None:
        sql += " AND doc_id IN (SELECT value FROM json_each(?))"
        args.append(json.dumps(sorted(allowed)))
    sql += f" ORDER BY bm25(fts) LIMIT {int(pool)}"
    return [(d, int(n)) for d, n in con.execute(sql, args)]


def _keyword(con, query: str, allowed: set[str] | None, pool: int = POOL) -> list[tuple[str, int]]:
    terms = _query_terms(query)
    terms = [t for t in terms if t[1:-1] not in STOPWORDS] or terms  # only stopwords: search those
    if not terms:
        return []
    return _matches(con, " OR ".join(terms), allowed, pool)


def _phrase(con, query: str, allowed: set[str] | None, pool: int = POOL) -> list[tuple[str, int]]:
    """Passages with the question's numbers as written ("Section 10.9"): the most specific phrase first."""
    found: dict[tuple[str, int], None] = {}
    for phrase in _phrases(query):
        for key in _matches(con, phrase, allowed, pool):
            found.setdefault(key, None)
    return list(found)[:pool]


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


def _meaning(vault: Vault, con, query: str, allowed: set[str] | None, embedder,
             pool: int = POOL) -> list[tuple[str, int]]:
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
    order = np.argsort(-best)[:pool]
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
        pool = POOL
        fused, more = _ranked(vault, con, query, allowed, embedder, pool)
    finally:
        con.close()
    docs: dict[str, tuple] = {}
    hits = _hits(vault, fused, query, limit, docs)
    while len(hits) < limit and more and pool < MAX_POOL:  # the cap left too few: look deeper
        pool *= 4
        con = index.open(vault)
        try:
            fused, more = _ranked(vault, con, query, allowed, embedder, pool)
        finally:
            con.close()
        hits = _hits(vault, fused, query, limit, docs)
    if len(hits) < limit:  # still short (a filter to one document, say): the passages the cap skipped fill the rest
        hits = _hits(vault, fused, query, limit, docs, fill=True)
    return Results(pages, hits)


def _ranked(vault, con, query, allowed, embedder, pool) -> tuple[list, bool]:
    """The passages fused from the three rankings, and whether any ranking filled its `pool` (it may have more)."""
    rankings = (_keyword(con, query, allowed, pool), _meaning(vault, con, query, allowed, embedder, pool),
                _phrase(con, query, allowed, pool))  # the phrase ranking is empty without numbers in the question
    return _fuse(*rankings), any(len(r) >= pool for r in rankings)


def _hits(vault, fused, query: str, limit: int, docs: dict, fill: bool = False) -> list[Hit]:
    """The fused passages to show: at most PER_DOC per document, copies named under the first (`docs`: a cache). With
    `fill`, slots still empty after that take the passages the cap skipped, in ranked order."""
    hits: list[Hit] = []
    shown: dict[str, int] = {}  # passages shown per document
    same: dict[str, Hit] = {}  # a long passage's text (spaces evened out) -> the hit showing it
    named: dict[str, set[str]] = {}  # that text -> the documents already shown or named with it
    skipped: list[tuple] = []  # passages the cap left out, for `fill`

    def place(doc_id, doc, labels, p, text, flat, score) -> None:
        """Shows the passage, or names its document under the copy already shown."""
        first = same.get(flat) if len(flat) >= SAME_MIN else None
        if first is not None:
            if doc_id not in named[flat]:
                named[flat].add(doc_id)
                first.also_in.append(doc.name)  # the document's own name: a set page's title is the same for all
            return
        hit = Hit(doc_id, doc.name, labels, p.get("page") or 0, str(p.get("section") or ""), doc.source, text, score,
                  Path(doc.page).stem if doc.page else "", query=query)
        hits.append(hit)
        if len(flat) >= SAME_MIN:
            same[flat], named[flat] = hit, {doc_id}

    for (doc_id, n), score in fused:
        if doc_id not in docs:
            doc = store.load(vault, doc_id)
            docs[doc_id] = (doc, store.passages(vault, doc_id)) if doc else (None, [])
        doc, passages = docs[doc_id]
        if doc is None or doc.status != "read" or n >= len(passages):
            continue  # the index is out of step with the store (or the last reading failed); skip
        p = passages[n]
        text = str(p.get("text", ""))
        flat = " ".join(text.split())
        entry = (doc_id, doc, store.effective_labels(doc), p, text, flat, score)
        if len(flat) < SAME_MIN or flat not in same:
            if shown.get(doc_id, 0) >= PER_DOC:
                skipped.append(entry)
                continue
            shown[doc_id] = shown.get(doc_id, 0) + 1
        place(*entry)
        if len(hits) >= limit:
            return hits
    for entry in skipped if fill else ():
        place(*entry)
        if len(hits) >= limit:
            break
    return hits


def find(vault: Vault, query: str, *, embedder, company: str = "", doc_type: str = "", after: str = "",
         before: str = "", limit: int = 8, pages_only: bool = False) -> Results:
    """Wiki pages (at most 3), then document passages (at most `limit`)."""
    return index.with_recovery(
        vault, embedder, lambda: _find(vault, query, embedder, company, doc_type, after, before, limit, pages_only))


def search(vault: Vault, query: str, *, embedder, company: str = "", doc_type: str = "",
           after: str = "", before: str = "", limit: int = 8) -> list[Hit]:
    return find(vault, query, embedder=embedder, company=company, doc_type=doc_type, after=after, before=before,
                limit=limit).hits


def _excerpt(text: str, query: str) -> str:
    """The part of a passage with the most of the question's words: windows of up to WINDOW_WORDS words and TEXT_LIMIT
    characters, the best by folded words in common (ties: the first), with "…" where it's cut."""
    spans = [m.span() for m in re.finditer(r"\S+", text)]
    if not spans:
        return ""
    want = set(_WORD.findall(fold(query)))
    want = (want - STOPWORDS) or want
    best, best_score, i = (0, 1), -1, 0
    while True:
        j = i + 1
        while j < len(spans) and j - i < WINDOW_WORDS and spans[j][1] - spans[i][0] <= TEXT_LIMIT:
            j += 1
        score = len(want & set(_WORD.findall(fold(text[spans[i][0]:spans[j - 1][1]]))))
        if score > best_score:
            best, best_score = (i, j), score
        if j >= len(spans):
            break
        i += max(1, (j - i) * 4 // 5)
    i, j = best
    part = text[spans[i][0]:spans[j - 1][1]]
    cut = j < len(spans)
    if len(part) > TEXT_LIMIT:  # one very long word
        part, cut = part[:TEXT_LIMIT].rstrip(), True
    return ("…" if i else "") + part + ("…" if cut else "")


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
        also = ""
        if h.also_in:
            more = len(h.also_in) - ALSO_SHOWN
            also = "\nAlso in: " + ", ".join(h.also_in[:ALSO_SHOWN]) + (f" and {more} more" if more > 0 else "")
        page_line = f"\nPage: [[{h.wiki_page}]]" if h.wiki_page else ""
        blocks.append(f"{i}. {head}\n{h.source}{also}{page_line}\n{_excerpt(h.text, h.query)}")
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

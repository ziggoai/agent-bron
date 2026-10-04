"""The search index: words (SQLite full-text) and meaning vectors, rebuilt from the stored documents when needed.

Vectors are also saved with each document (docs/<id>/vectors.npy + vectors.json), so a rebuild is fast and
only re-reads the model for documents whose text, labels or model changed."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

import numpy as np

from ..vault import Vault
from . import embed as embed_mod
from . import store
from .embed import DIM
from .passages import normal_tokens, windows
from .store import Doc, KbError

SCHEMA_VERSION = 1
EMBED_BATCH = 256
BUSY_MS = 10000


class IndexOutdated(sqlite3.DatabaseError):
    """The index was written by a different version of Bron."""


def db_path(vault: Vault) -> Path:
    return store.kb_dir(vault) / "index.db"


def _sidecars(path: Path):
    return [path.with_name(path.name + s) for s in ("", "-wal", "-shm", "-journal")]


def _create_schema(con: sqlite3.Connection) -> None:
    con.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5("
        "doc_id UNINDEXED, n UNINDEXED, body, tokenize='unicode61 remove_diacritics 2')"
    )
    con.execute("CREATE TABLE IF NOT EXISTS vectors (doc_id TEXT, n INTEGER, w INTEGER, vec BLOB)")
    con.execute("CREATE INDEX IF NOT EXISTS vectors_doc ON vectors(doc_id)")
    con.execute("CREATE TABLE IF NOT EXISTS docs (doc_id TEXT PRIMARY KEY, company TEXT, fund TEXT, doc_type TEXT, date TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, val INTEGER)")
    con.execute("INSERT OR IGNORE INTO meta VALUES ('counter', 0)")
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    con.commit()


def _connect(path: Path, *, wal: bool = True) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        con.execute(f"PRAGMA busy_timeout={int(BUSY_MS)}")
        if wal:
            con.execute("PRAGMA journal_mode=WAL")
        has_tables = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 0
        if has_tables:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise IndexOutdated(f"index version {version}, expected {SCHEMA_VERSION}")
        else:
            _create_schema(con)  # user_version is written only here, when the index is created
        return con
    except sqlite3.DatabaseError:
        con.close()
        raise


def open(vault: Vault) -> sqlite3.Connection:  # noqa: A001 - the plan names it index.open
    return _connect(db_path(vault))


def delete_files(vault: Vault) -> None:
    for f in _sidecars(db_path(vault)):
        try:
            f.unlink()
        except OSError:
            pass


def _bump(con: sqlite3.Connection) -> None:
    con.execute("UPDATE meta SET val = val + 1 WHERE key = 'counter'")


def counter(con: sqlite3.Connection) -> int:
    return con.execute("SELECT val FROM meta WHERE key = 'counter'").fetchone()[0]


def _is_corrupt(exc: sqlite3.DatabaseError) -> bool:
    if isinstance(exc, sqlite3.OperationalError):
        text = str(exc).lower()
        return "malformed" in text or "not a database" in text
    return True  # a real database error, or an index from another version


def _plain(exc: sqlite3.DatabaseError) -> KbError:
    text = str(exc).lower()
    if isinstance(exc, sqlite3.OperationalError) and ("locked" in text or "busy" in text):
        return KbError("Bron's knowledge base is busy right now; try again in a moment.")
    return KbError(f"Bron's knowledge base couldn't be opened ({str(exc)[:80]}). Your documents are safe. Try again in a moment.")


def with_recovery(vault: Vault, embedder, fn):
    """Run fn(). Only a damaged or outdated index is thrown away and rebuilt once; busy or full disks are just reported."""
    try:
        return fn()
    except sqlite3.DatabaseError as exc:
        if not _is_corrupt(exc):
            raise _plain(exc) from exc
    delete_files(vault)
    try:
        rebuild(vault, embedder)
        return fn()
    except sqlite3.DatabaseError as exc:
        if not _is_corrupt(exc):
            raise _plain(exc) from exc
        raise KbError("Bron's document search index couldn't be rebuilt; your documents are safe. Try again in a moment.") from exc


def ensure(vault: Vault, embedder, *, skip: str = "") -> None:
    """If the index file is missing but documents exist, rebuild it; then finish documents left "indexing"."""
    if not db_path(vault).exists() and store.all_docs(vault):
        rebuild(vault, embedder)
    _finish_indexing(vault, embedder, skip)


def _finish_indexing(vault: Vault, embedder, skip: str = "") -> None:
    """Finish documents an interruption left "indexing", and add the meaning vectors of documents read while the
    meaning model wasn't available. A marker is only dropped when its document is done, failed or gone."""
    waiting = [d for d in store.indexing_ids(vault) if d != skip]  # skip: the document being indexed right now
    if not waiting:
        return
    embedder = _FailFast(embedder)
    con = open(vault)
    try:
        for doc_id in waiting:
            doc = store.load(vault, doc_id)
            if doc is None:
                if not store.exists(vault, doc_id):
                    store.clear_indexing(vault, doc_id)  # forgotten
                continue  # its meta.json is being written right now; look again next time
            if doc.status == "read" and doc.vectors_pending:
                try:
                    _put(con, vault, doc, store.passages(vault, doc_id), embedder)
                except KbError:
                    continue  # the meaning model still isn't available: keyword search meanwhile
                if store.load(vault, doc_id) == doc:  # unless it was read again meanwhile
                    doc.vectors_pending = False
                    store.save_meta(vault, doc)
                    store.clear_indexing(vault, doc_id)
                continue
            if doc.status != "indexing":
                store.clear_indexing(vault, doc_id)  # failed, or already finished by its reader
                continue
            passages = store.passages(vault, doc_id)
            try:
                _put(con, vault, doc, passages, embedder)
                pending = False
            except KbError:  # the meaning model isn't available: searchable by words now, vectors later
                _put(con, vault, doc, passages, embedder, words_only=True)
                pending = True
            if store.load(vault, doc_id) == doc:  # unless it was read again meanwhile
                doc.status, doc.vectors_pending = "read", pending
                store.save_meta(vault, doc)
                if not pending:
                    store.clear_indexing(vault, doc_id)
    finally:
        con.close()


def finish_pending(vault: Vault, embedder) -> None:
    """Index the documents an interruption left half-done (for runners and `bron kb status`)."""
    if store.indexing_ids(vault):
        with_recovery(vault, embedder, lambda: ensure(vault, embedder))


# ---- vectors saved with the document ----

def _folder(vault: Vault, doc_id: str) -> Path:
    return store.kb_dir(vault) / "docs" / doc_id


def _model_name(embedder) -> str:
    return str(getattr(embedder, "model", embed_mod.MODEL))


class _FailFast:
    """Once the meaning model has failed, the rest of this pass doesn't try it again (each try may be a slow download)."""

    def __init__(self, inner):
        self._inner = inner
        self._error: KbError | None = None

    @property
    def model(self) -> str:
        return _model_name(self._inner)

    def embed(self, texts):
        if self._error is not None:
            raise self._error
        try:
            return self._inner.embed(texts)
        except KbError as exc:
            self._error = exc
            raise


def _digest(texts: list[str]) -> str:
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()


def _save_vectors(vault: Vault, doc: Doc, texts: list[str], matrix: np.ndarray, embedder) -> None:
    folder = _folder(vault, doc.doc_id)
    if not folder.is_dir():  # only for documents that are in the store
        return
    tmp = folder / ".vectors.tmp.npy"
    np.save(tmp, matrix)
    os.replace(tmp, folder / "vectors.npy")
    store._write(folder / "vectors.json",
                 json.dumps({"model": _model_name(embedder), "count": len(texts), "hash": _digest(texts)}))


def _vectors_for(vault: Vault, doc: Doc, texts: list[str], embedder, *, keep: bool = True) -> np.ndarray:
    folder = _folder(vault, doc.doc_id)
    try:
        meta = json.loads((folder / "vectors.json").read_text(encoding="utf-8"))
        saved = np.load(folder / "vectors.npy")
        if meta.get("model") == _model_name(embedder) and meta.get("count") == len(texts) \
                and meta.get("hash") == _digest(texts) and saved.shape == (len(texts), DIM) and saved.dtype == np.float32:
            return saved
    except Exception:  # noqa: BLE001 - missing or damaged files (empty, truncated, wrong shape): work them out again
        pass
    parts = [embedder.embed(texts[i : i + EMBED_BATCH]) for i in range(0, len(texts), EMBED_BATCH)]
    matrix = np.vstack(parts).astype(np.float32) if parts else np.zeros((0, DIM), dtype=np.float32)
    if keep:
        _save_vectors(vault, doc, texts, matrix, embedder)
    return matrix


def _pieces(passages: list[dict]) -> list[tuple[int, int, str]]:
    pieces: list[tuple[int, int, str]] = []
    for n, p in enumerate(passages):
        header = str(p.get("header", ""))
        for w, window in enumerate(windows(str(p.get("text", "")))):
            pieces.append((n, w, f"{header} {window}".strip()))
    return pieces


def vectors(vault: Vault, doc: Doc, passages: list[dict], embedder) -> np.ndarray:
    """The meaning vectors for these passages, worked out before anything is saved (the slow part)."""
    return _vectors_for(vault, doc, [t for _, _, t in _pieces(passages)], embedder, keep=False)


# ---- writing ----

def _body(p: dict) -> str:
    text = str(p.get("text", ""))
    return " ".join(x for x in (str(p.get("header", "")), text, " ".join(normal_tokens(text))) if x)


def _put(con: sqlite3.Connection, vault: Vault, doc: Doc, passages: list[dict], embedder, vectors=None, *,
         words_only: bool = False) -> None:
    """words_only: the meaning model isn't available, so only the words go in (meaning search skips the document)."""
    pieces = _pieces(passages)
    texts = [t for _, _, t in pieces]
    if words_only:
        matrix = None
    elif vectors is not None and getattr(vectors, "shape", None) == (len(texts), DIM):
        matrix = vectors
        _save_vectors(vault, doc, texts, matrix, embedder)
    else:
        matrix = _vectors_for(vault, doc, texts, embedder)
    labels = store.effective_labels(doc)
    with con:  # one transaction
        con.execute("DELETE FROM fts WHERE doc_id = ?", (doc.doc_id,))
        con.execute("DELETE FROM vectors WHERE doc_id = ?", (doc.doc_id,))
        con.execute("DELETE FROM docs WHERE doc_id = ?", (doc.doc_id,))
        con.execute(
            "INSERT INTO docs VALUES (?,?,?,?,?)",
            (doc.doc_id, str(labels.get("company", "")), str(labels.get("fund", "")),
             str(labels.get("doc_type", "")), str(labels.get("date", ""))),
        )
        con.executemany("INSERT INTO fts(doc_id, n, body) VALUES (?,?,?)",
                        [(doc.doc_id, n, _body(p)) for n, p in enumerate(passages)])
        if matrix is not None:
            con.executemany("INSERT INTO vectors VALUES (?,?,?,?)",
                            [(doc.doc_id, n, w, matrix[i].tobytes()) for i, (n, w, _) in enumerate(pieces)])
        _bump(con)


def put(vault: Vault, doc: Doc, passages: list[dict], embedder, *, vectors=None, words_only: bool = False) -> bool:
    """Index one document. False when the meaning model wasn't available: its words are in, its vectors aren't
    (the caller marks it `vectors_pending` so the next search adds them)."""
    def run():
        ensure(vault, embedder, skip=doc.doc_id)
        con = open(vault)
        try:
            if not words_only:
                try:
                    _put(con, vault, doc, passages, embedder, vectors)
                    return True
                except KbError:
                    pass  # the meaning model isn't available
            _put(con, vault, doc, passages, embedder, words_only=True)
            return False
        finally:
            con.close()

    return with_recovery(vault, embedder, run)


class _Lazy:
    """Only loads the real model if the index has to be rebuilt."""

    def __init__(self, vault: Vault):
        self.vault = vault

    @property
    def model(self):
        return embed_mod.MODEL

    def embed(self, texts):
        return embed_mod.get(self.vault).embed(texts)


def drop(vault: Vault, doc_id: str, embedder=None) -> None:
    def run():
        ensure(vault, embedder)
        con = open(vault)
        try:
            with con:
                for table in ("fts", "vectors", "docs"):
                    con.execute(f"DELETE FROM {table} WHERE doc_id = ?", (doc_id,))
                _bump(con)
        finally:
            con.close()

    embedder = embedder or _Lazy(vault)
    with_recovery(vault, embedder, run)


def rebuild(vault: Vault, embedder) -> None:
    """Build a complete index beside the old one and swap it in only when it is finished."""
    final = db_path(vault)
    tmp = final.with_name(final.name + ".tmp")
    for f in _sidecars(tmp):
        try:
            f.unlink()
        except OSError:
            pass
    try:
        con = _connect(tmp, wal=False)
        embedder = _FailFast(embedder)
        try:
            for doc in store.all_docs(vault):
                passages = store.passages(vault, doc.doc_id)
                if passages and doc.status == "read":
                    try:
                        _put(con, vault, doc, passages, embedder)
                    except KbError:  # no meaning model and no saved vectors: words now, vectors on a later search
                        _put(con, vault, doc, passages, embedder, words_only=True)
                        if not doc.vectors_pending:
                            doc.vectors_pending = True
                            store.save_meta(vault, doc)
                        store.mark_indexing(vault, doc.doc_id)
            with con:
                con.execute("UPDATE meta SET val = ? WHERE key = 'counter'", (time.time_ns(),))
        finally:
            con.close()
        for f in _sidecars(final):
            if f != final:
                try:
                    f.unlink()
                except OSError:
                    pass
        os.replace(tmp, final)
    except BaseException:
        for f in _sidecars(tmp):
            try:
                f.unlink()
            except OSError:
                pass
        raise

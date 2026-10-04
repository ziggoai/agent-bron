"""Documents the knowledge base has read, kept under .bron/kb/docs/<doc-id>/. Originals stay where they are."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..vault import Vault


class KbError(RuntimeError):
    """A knowledge-base problem, in plain words."""


# Written into every meta.json, so a later Bron can tell which documents were cut or read by older rules.
PASSAGES_VERSION = 1
READER_VERSION = 1


@dataclass
class Doc:
    doc_id: str
    identity: str
    kind: str
    source: str
    name: str
    path: str
    labels: dict = field(default_factory=dict)
    user_labels: dict = field(default_factory=dict)
    read_at: str = ""
    pages: int = 0
    status: str = "read"
    error: str = ""
    scanned: int = 0  # pages read by Mac text recognition
    model_pages: int = 0  # pages read by the model
    source_size: int = -1  # the original's size and modification time when it was read (not for web pages)
    source_mtime: float = 0.0
    vectors_pending: bool = False  # read without the meaning model: keyword search only until it downloads
    passages_version: int = PASSAGES_VERSION
    reader_version: int = READER_VERSION


def kb_dir(vault: Vault) -> Path:
    return vault.bron_dir / "kb"


def doc_id_for(identity: str) -> str:
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _folder(vault: Vault, doc_id: str) -> Path:
    return kb_dir(vault) / "docs" / doc_id


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _jsonl(rows) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


USER_LABELS = "user-labels.json"


def user_labels(vault: Vault, doc_id: str) -> dict:
    """The user's corrections, kept in their own file so a crash while re-saving a document never loses them."""
    try:
        data = json.loads((_folder(vault, doc_id) / USER_LABELS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in data.items() if v} if isinstance(data, dict) else {}


def save_user_labels(vault: Vault, doc_id: str, labels: dict) -> None:
    path = _folder(vault, doc_id) / USER_LABELS
    labels = {k: v for k, v in labels.items() if v}
    if labels:
        _write(path, json.dumps(labels, ensure_ascii=False, indent=2))
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def save(vault: Vault, doc: Doc, pages: list[str], passages: list[dict]) -> None:
    folder = _folder(vault, doc.doc_id)
    save_user_labels(vault, doc.doc_id, doc.user_labels)  # first: they survive whatever happens below
    try:
        (folder / "meta.json").unlink()  # a crash below must never leave the old meta beside new pages
    except FileNotFoundError:
        pass
    _write(folder / "pages.jsonl", _jsonl({"page": i + 1, "text": t} for i, t in enumerate(pages)))
    _write(folder / "passages.jsonl", _jsonl(passages))
    _write(folder / "meta.json", json.dumps(asdict(doc), ensure_ascii=False, indent=2))  # last: marks the document complete


def save_meta(vault: Vault, doc: Doc) -> None:
    """Only the description (a document that couldn't be read has no pages)."""
    save_user_labels(vault, doc.doc_id, doc.user_labels)
    _write(_folder(vault, doc.doc_id) / "meta.json", json.dumps(asdict(doc), ensure_ascii=False, indent=2))


def load(vault: Vault, doc_id: str) -> Doc | None:
    try:
        data = json.loads((_folder(vault, doc_id) / "meta.json").read_text(encoding="utf-8"))
        doc = Doc(**{k: v for k, v in data.items() if k in Doc.__dataclass_fields__})  # fields from a newer Bron are ignored
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if (_folder(vault, doc_id) / USER_LABELS).exists():
        doc.user_labels = user_labels(vault, doc_id)
    return doc


def _read_jsonl(path: Path) -> list[dict]:
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return []


def pages(vault: Vault, doc_id: str) -> list[str]:
    return [str(r.get("text", "")) for r in _read_jsonl(_folder(vault, doc_id) / "pages.jsonl")]


def passages(vault: Vault, doc_id: str) -> list[dict]:
    return _read_jsonl(_folder(vault, doc_id) / "passages.jsonl")


def all_docs(vault: Vault) -> list[Doc]:
    root = kb_dir(vault) / "docs"
    if not root.is_dir():
        return []
    found = [load(vault, p.name) for p in sorted(root.iterdir()) if p.is_dir()]
    return [d for d in found if d is not None]


def exists(vault: Vault, doc_id: str) -> bool:
    """The document's folder is there (its meta.json may be missing for a moment while it is being saved)."""
    return _folder(vault, doc_id).is_dir()


def forget(vault: Vault, doc_id: str) -> None:
    shutil.rmtree(_folder(vault, doc_id), ignore_errors=True)
    clear_indexing(vault, doc_id)


# A document is saved with status "indexing" and a marker here until the search index has it; whoever opens
# the index next finishes the job (so an interruption never leaves the index out of step with the text).

def _indexing_dir(vault: Vault) -> Path:
    return kb_dir(vault) / "indexing"


def mark_indexing(vault: Vault, doc_id: str) -> None:
    _indexing_dir(vault).mkdir(parents=True, exist_ok=True)
    (_indexing_dir(vault) / doc_id).touch()


def clear_indexing(vault: Vault, doc_id: str) -> None:
    try:
        (_indexing_dir(vault) / doc_id).unlink()
    except OSError:
        pass


def indexing_ids(vault: Vault) -> list[str]:
    try:
        return sorted(p.name for p in _indexing_dir(vault).iterdir() if not p.name.startswith("."))
    except OSError:
        return []


def effective_labels(doc: Doc) -> dict:
    return {**doc.labels, **{k: v for k, v in doc.user_labels.items() if v}}

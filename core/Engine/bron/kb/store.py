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
    page: str = ""  # its wiki page (vault-relative), from page.json; never written into meta.json
    page_labels: dict = field(default_factory=dict)  # the labels its page's properties give it
    text_hash: str = ""  # its text, whitespace aside, hashed: a copy of a document already read has the same one
    duplicate_of: str = ""  # status "duplicate": the document already read with the same text (never saved)


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


PAGE_FILE = "page.json"
_NOT_META = ("page", "page_labels", "duplicate_of")


def _meta_json(doc: Doc) -> str:
    data = asdict(doc)
    for key in _NOT_META:
        data.pop(key, None)
    return json.dumps(data, ensure_ascii=False, indent=2)


def page_of(vault: Vault, doc_id: str) -> dict:
    """{"page": <vault-relative path>, "labels": {...}} for a document that has a wiki page, else {}. Kept in its own
    file, like the user's labels, so reading the document again never loses it."""
    try:
        data = json.loads((_folder(vault, doc_id) / PAGE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and isinstance(data.get("page"), str) and data["page"] else {}


def set_page(vault: Vault, doc_id: str, page: str, labels: dict) -> None:
    _write(_folder(vault, doc_id) / PAGE_FILE, json.dumps({"page": page, "labels": labels}, ensure_ascii=False, indent=2))


def clear_page(vault: Vault, doc_id: str) -> None:
    try:
        (_folder(vault, doc_id) / PAGE_FILE).unlink()
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
    _write(folder / "meta.json", _meta_json(doc))  # last: marks the document complete


def save_meta(vault: Vault, doc: Doc) -> None:
    """Only the description (a document that couldn't be read has no pages)."""
    save_user_labels(vault, doc.doc_id, doc.user_labels)
    _write(_folder(vault, doc.doc_id) / "meta.json", _meta_json(doc))


def load(vault: Vault, doc_id: str) -> Doc | None:
    try:
        data = json.loads((_folder(vault, doc_id) / "meta.json").read_text(encoding="utf-8"))
        doc = Doc(**{k: v for k, v in data.items() if k in Doc.__dataclass_fields__})  # fields from a newer Bron are ignored
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if (_folder(vault, doc_id) / USER_LABELS).exists():
        doc.user_labels = user_labels(vault, doc_id)
    linked = page_of(vault, doc_id)
    doc.page = str(linked.get("page") or "")
    doc.page_labels = linked["labels"] if isinstance(linked.get("labels"), dict) else {}
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


def text_hash(pages: list[str]) -> str:
    return hashlib.sha256("\n".join(" ".join(p.split()) for p in pages).encode("utf-8")).hexdigest()[:24]


def same_text(vault: Vault, digest: str, *, but: str) -> Doc | None:
    """A document already read whose text is this one's. Documents read before Bron checked for copies get their
    hash now, once."""
    for doc in all_docs(vault):
        if doc.doc_id == but or doc.status != "read":
            continue
        if not doc.text_hash:
            texts = pages(vault, doc.doc_id)
            if not texts:
                continue
            doc.text_hash = text_hash(texts)
            save_meta(vault, doc)
        if doc.text_hash == digest:
            return doc
    return None


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
    """The labels worked out when it was read; once the document has a wiki page, that page's properties on top;
    before that, the user's 0.7 corrections on top."""
    base = doc.labels if isinstance(doc.labels, dict) else {}
    page = doc.page_labels if isinstance(doc.page_labels, dict) else {}
    if page:
        return fold_fund({**base, **{k: v for k, v in page.items() if v}})
    user = doc.user_labels if isinstance(doc.user_labels, dict) else {}
    return fold_fund({**base, **{k: v for k, v in user.items() if v}})


def fold_fund(labels: dict) -> dict:
    """Bron 0.7.0 had a separate "fund" label; it now counts as the company (when there is no company)."""
    fund = labels.pop("fund", "")
    if fund and not labels.get("company"):
        labels["company"] = fund
    return labels

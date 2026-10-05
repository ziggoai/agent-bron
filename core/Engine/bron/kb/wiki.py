"""The wiki in Knowledge/: its pages, their links and properties, the document each document page stands for, and the
two files Bron's code writes (index.md, log.md). Agents write the pages; this module only reads them.

A page is any .md file under Knowledge/ except Schema.md, index.md, log.md and what's in Inbox/ and Files/; its type
is its first folder."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .. import frontmatter as fm
from .. import statefile
from ..vault import Vault
from . import schema, store

RESERVED = {schema.SCHEMA, schema.INDEX, schema.LOG}
OTHER = "Other"  # pages directly in Knowledge/, outside any type folder
LINK = re.compile(r"!?\[\[([^\[\]|#]*)(?:#[^\[\]|]*)?(?:\|[^\[\]]*)?\]\]")
LOG_KINDS = ("ingest", "update", "save", "check", "forget")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def property_text(value) -> str:
    """A property as plain text: "[[Acme Ltda|Acme]]" → "Acme Ltda", a YAML date → "2025-01-21", and [[Acme]] written
    without quotes (YAML reads it as a list in a list) → "Acme"."""
    while isinstance(value, list) and value:
        value = value[0]
    if value is None or isinstance(value, (list, dict)):
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    text = " ".join(str(value).split())
    found = LINK.fullmatch(text)
    return found.group(1).strip() if found else text


def _property_links(value) -> list[str]:
    if isinstance(value, str):
        return [m.group(1).strip() for m in LINK.finditer(value)]
    if isinstance(value, list):
        if len(value) == 1 and isinstance(value[0], list) and len(value[0]) == 1 and isinstance(value[0][0], str):
            return [value[0][0].strip()]  # [[Name]] without quotes: YAML reads it as a list in a list
        return [name for item in value for name in _property_links(item)]
    if isinstance(value, dict):
        return [name for item in value.values() for name in _property_links(item)]
    return []


def name_of(target: str) -> str:
    """A link target or a page title, folded for comparing: "Knowledge/Organisations/Acme.md" and "acme" are the same."""
    return target.strip().rsplit("/", 1)[-1].removesuffix(".md").strip().casefold()


@dataclass
class Page:
    path: Path
    rel: str  # vault-relative, like "Knowledge/Organisations/Acme Ltda.md"
    title: str  # the file name without .md
    kind: str  # the type folder ("Organisations"), or OTHER
    meta: dict = field(default_factory=dict)
    body: str = ""
    mtime: float = 0.0
    size: int = 0
    error: str = ""  # why its properties can't be read ("" when they can)

    @property
    def summary(self) -> str:
        return property_text(self.meta.get("summary"))

    @property
    def doc_id(self) -> str:
        return property_text(self.meta.get("doc"))

    @property
    def is_document(self) -> bool:
        return bool(self.doc_id) or self.kind == "Documents"

    @property
    def aliases(self) -> list[str]:
        raw = self.meta.get("aliases")
        items = raw if isinstance(raw, list) else [raw] if raw else []
        return [t for t in (property_text(a) for a in items) if t]

    def links(self) -> list[str]:
        """The pages this one links to (body and properties), by name: no "#heading", no "|label"."""
        found = [m.group(1).strip() for m in LINK.finditer(self.body)] + _property_links(self.meta)
        return [name for name in found if name]


def page_paths(vault: Vault) -> list[Path]:
    root = vault.knowledge_dir
    if not root.is_dir():
        return []
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        top = here == root
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and not (top and d in schema.NOT_PAGE_FOLDERS))
        for name in filenames:
            if name.startswith(".") or not name.endswith(".md") or (top and name in RESERVED):
                continue
            out.append(here / name)
    return sorted(out)


def read_page(vault: Vault, path: Path) -> Page:
    rel = path.relative_to(vault.root).as_posix()
    parts = path.relative_to(vault.knowledge_dir).parts
    page = Page(path, rel, path.stem, parts[0] if len(parts) > 1 else OTHER)
    try:
        st = path.stat()
        page.mtime, page.size = st.st_mtime, st.st_size
        parsed = fm.parse(path.read_text(encoding="utf-8"))
        page.meta, page.body = parsed.meta, parsed.body
    except fm.FrontmatterError as exc:
        page.error = str(exc).replace("the settings block at the top", "the properties block")
    except ValueError:  # YAML reads an impossible date (2025-02-30) as a plain ValueError
        page.error = "the properties block is not valid YAML (a date that doesn't exist, say)"
    except (OSError, UnicodeDecodeError) as exc:
        page.error = f"it can't be opened ({exc.__class__.__name__})"
    return page


def all_pages(vault: Vault) -> list[Page]:
    return [read_page(vault, path) for path in page_paths(vault)]


def page_labels(page: Page) -> dict:
    """The search labels a document page gives its document."""
    when = property_text(page.meta.get("date"))
    return {"company": property_text(page.meta.get("organisation")), "doc_type": property_text(page.meta.get("doc_type")),
            "date": when if _DATE.fullmatch(when) else "", "title": page.title}


def link_documents(vault: Vault, pages: list[Page], removed=()) -> tuple[list[str], set[str]]:
    """Record each document page among `pages` as its document's page, with the labels its properties give; forget the
    record of pages that were removed or no longer name their document. Returns (plain lines about pages whose doc Bron
    doesn't have, ids of the documents whose record changed)."""
    unknown: list[str] = []
    touched: set[str] = set()
    claimed = {p.doc_id: p for p in pages if not p.error and p.doc_id}
    looked_at = set(removed) | {p.rel for p in pages if not p.error}
    for doc in store.all_docs(vault):
        if doc.page in looked_at and doc.doc_id not in claimed:
            store.clear_page(vault, doc.doc_id)
            touched.add(doc.doc_id)
    for doc_id, page in claimed.items():
        if not store.exists(vault, doc_id):
            unknown.append(f"{page.title}: its doc {doc_id} isn't in the knowledge base (forgotten, or never read).")
            continue
        wanted = {"page": page.rel, "labels": page_labels(page)}
        if store.page_of(vault, doc_id) != wanted:
            store.set_page(vault, doc_id, page.rel, wanted["labels"])
            touched.add(doc_id)
    return unknown, touched


# ---- index.md ----

def type_folders(vault: Vault) -> list[str]:
    """The schema's page types that are plain folders directly under Knowledge/ (a hand-edited "../x" is ignored)."""
    root = vault.knowledge_dir.resolve()
    out = []
    for name in schema.page_types(vault):
        if "/" in name or "\\" in name or ".." in name:
            continue
        if (root / name).resolve().parent != root:
            continue
        out.append(name)
    return out


def _kinds_in_order(kinds: set[str], order: list[str]) -> list[str]:
    def key(kind: str):
        if kind in order:
            return (0, order.index(kind), "")
        return (2 if kind == OTHER else 1, 0, kind.casefold())

    return sorted(kinds, key=key)


def _sources(pages: list[Page]) -> dict[str, set[str]]:
    """Page name → the titles of the document pages that link to it."""
    out: dict[str, set[str]] = {}
    for page in pages:
        if page.is_document:
            for target in page.links():
                name = name_of(target)
                if name != name_of(page.title):
                    out.setdefault(name, set()).add(page.title)
    return out


def index_text(vault: Vault, pages: list[Page] | None = None) -> str:
    """index.md: one section per page type (the schema's order, then others alphabetically, then Other), one line per
    page. Pages whose properties can't be read are left out (the check reports them)."""
    pages = [p for p in (all_pages(vault) if pages is None else pages) if not p.error]
    if not pages:
        return schema.EMPTY_INDEX
    sources = _sources(pages)
    lines = [schema.INDEX_HEADER.rstrip("\n")]
    for kind in _kinds_in_order({p.kind for p in pages}, type_folders(vault)):
        lines += ["", f"## {kind}"]
        for page in sorted((p for p in pages if p.kind == kind), key=lambda p: p.title.casefold()):
            updated = time.strftime("%Y-%m-%d", time.localtime(page.mtime))
            if page.is_document:
                when = page_labels(page)["date"]
                tail = f"({when}, updated {updated})" if when else f"(updated {updated})"
            else:
                n = len(sources.get(name_of(page.title), set()))
                tail = f"({n} source{'' if n == 1 else 's'}, updated {updated})"
            lines.append(f"- [[{page.title}]] — {page.summary or 'no summary yet'} {tail}")
    return "\n".join(lines) + "\n"


def write_index(vault: Vault, pages: list[Page] | None = None) -> bool:
    """Rewrite index.md when it would change; True when it did."""
    path = vault.knowledge_dir / schema.INDEX
    text = index_text(vault, pages)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    store._write(path, text)
    return True


# ---- log.md ----

def parse_log_text(text: str) -> tuple[str, str]:
    """"check | 3 pages fixed" → ("check", "3 pages fixed"); text without a known kind is an update."""
    kind, sep, rest = text.partition("|")
    if sep and kind.strip().lower() in LOG_KINDS and rest.strip():
        return kind.strip().lower(), rest.strip()
    return "update", text.strip()


def append_log(vault: Vault, entries: list[tuple[str, str]], *, now: str | None = None) -> None:
    """Add `## [YYYY-MM-DD HH:MM] <kind> | <text>` entries to log.md (started with its header when missing)."""
    entries = [(kind, " ".join(text.split())) for kind, text in entries if text.strip()]
    if not entries:
        return
    path = vault.knowledge_dir / schema.LOG
    stamp = now or time.strftime("%Y-%m-%d %H:%M")
    with statefile.locked(store.kb_dir(vault) / "wiki-log"):  # the lock file lives in .bron/kb, not in the vault
        try:
            text = path.read_text(encoding="utf-8")
        except (FileNotFoundError, UnicodeDecodeError):
            text = schema.LOG_HEADER
        if not text.endswith("\n"):
            text += "\n"
        text += "".join(f"\n## [{stamp}] {kind} | {line}\n" for kind, line in entries)
        store._write(path, text)

"""The wiki's rules file, Knowledge/Schema.md, and the headers of the two files Bron's code writes (index.md, log.md).

Schema.md's properties hold two lists: `page_types` (the page folders, in index order) is what code reads; `doc_types` is
for the agents (code only writes it, in the 0.8.0 migration). Its body is plain English for the agents. It's the user's file: Bron only reads it (the 0.8.0 migration creates it once)."""
from __future__ import annotations

from pathlib import Path

from .. import frontmatter as fm
from ..vault import Vault

SCHEMA = "Schema.md"
INDEX = "index.md"
LOG = "log.md"
PAGE_TYPES = ["Documents", "Organisations", "People", "Topics"]
NOT_PAGE_FOLDERS = ("Inbox", "Files")
MAX_ITEMS = 50
INDEX_HEADER = "# Index\n\nEvery page in the wiki, by type. Bron writes this file; don't edit it.\n"
EMPTY_INDEX = INDEX_HEADER + "\nNo pages yet.\n"
LOG_HEADER = "# Log\n\nWhat happened in the wiki, newest last. Bron writes this file; don't edit it.\n"


def schema_path(vault: Vault) -> Path:
    return vault.knowledge_dir / SCHEMA


def template_text(vault: Vault) -> str:
    """The Schema.md Bron ships (System/Core/Templates/Schema.md, replaced on every update)."""
    return (vault.core_templates / SCHEMA).read_text(encoding="utf-8")


def _meta(vault: Vault) -> dict:
    try:
        return fm.read(schema_path(vault)).meta
    except (OSError, UnicodeDecodeError, fm.FrontmatterError):
        return {}


def clean_list(value, *, limit: int = MAX_ITEMS) -> list[str]:
    """A list of plain names (or one line split at commas): no brackets or pipes, no repeats, at most `limit`."""
    if value is None or value == "" or value == []:
        return []
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return []
    found: list[str] = []
    for item in value:
        if not isinstance(item, (str, int, float)) or isinstance(item, bool):
            continue
        name = " ".join("".join(" " if c in "[]|" or not c.isprintable() else c for c in str(item)).split())[:60]
        if name and name.lower() not in {t.lower() for t in found}:
            found.append(name)
    return found[:limit]


def page_types(vault: Vault) -> list[str]:
    """The page-type folders in the schema's order (the default four when Schema.md is missing or names none)."""
    chosen = [t.strip("/ ") for t in clean_list(_meta(vault).get("page_types"))]
    return [t for t in chosen if t and t not in NOT_PAGE_FOLDERS] or list(PAGE_TYPES)


def with_doc_types(text: str, types: list[str]) -> str:
    """Schema.md's text with its doc_types property replaced; every other line stays as written."""
    from ..fmedit import edit_meta

    return edit_meta(text, {"doc_types": list(types)})

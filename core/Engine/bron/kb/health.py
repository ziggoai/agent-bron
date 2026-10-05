"""Health check items for the knowledge base."""
from __future__ import annotations

import sqlite3

from ..loader import Config
from ..model import Issue
from . import store


def _index_unreadable(vault) -> bool:
    from .index import db_path

    path = db_path(vault)
    if not path.is_file():
        return False
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
            return con.execute("PRAGMA quick_check").fetchone()[0] != "ok"
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        text = str(exc).lower()
        return not ("locked" in text or "busy" in text)  # a busy index is fine; a damaged one isn't


def issues(cfg: Config) -> list[Issue]:
    vault = cfg.vault
    out: list[Issue] = []
    failed = sum(1 for d in store.all_docs(vault) if d.status == "failed")
    if failed:
        out.append(Issue("warning", "kb.failed-documents",
                         f"{failed} document{'s' if failed != 1 else ''} couldn't be read; run `bron kb list --failed`"))
    if _index_unreadable(vault):
        out.append(Issue("warning", "kb.index-unreadable",
                         "The knowledge base search index can't be read; it will be rebuilt on the next search."))
    try:
        from . import wiki_check

        problems = wiki_check.run(vault)
    except Exception:  # noqa: BLE001 - the wiki never breaks the health check, but a crash is said out loud
        out.append(Issue("warning", "wiki.unchecked", "The wiki couldn't be checked; run `bron wiki check` for details."))
        return out
    for code in (wiki_check.ORDER if problems else ()):
        found = [p for p in problems if p.code == code]
        if found:
            first = "; ".join(p.text.rstrip(".") for p in found[:3])
            more = f"; …and {len(found) - 3} more" if len(found) > 3 else ""
            out.append(Issue("warning", f"wiki.{code}", f"{wiki_check.TITLES[code]} ({len(found)}): {first}{more}. "
                                                         "Run `bron wiki check --all` for the list."))
    return out

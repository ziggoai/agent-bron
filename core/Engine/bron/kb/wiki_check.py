"""Mechanical checks of the wiki (free: no model). Links to pages that don't exist, pages nothing links to, pages
missing `type` or `summary`, documents read without a page, pages naming a document Bron doesn't have, probable
duplicates, pages too long to read in one go, and pages whose properties can't be read."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..memory.facts import fold
from ..vault import Vault
from . import store, wiki

MAX_CHARS = 30_000
SUFFIXES = {"ltda", "llc", "inc", "sa", "lp"}  # folded away when looking for duplicates ("Acme Ltda." = "Acme")
ORDER = ("bad-properties", "broken-link", "missing-properties", "unknown-doc", "no-page-yet", "duplicate", "orphan",
         "too-long")
TITLES = {
    "bad-properties": "Pages whose properties can't be read",
    "broken-link": "Links to pages that don't exist",
    "missing-properties": "Pages missing type or summary",
    "unknown-doc": "Document pages whose document Bron doesn't have",
    "no-page-yet": "Documents read but no page yet",
    "duplicate": "Pages that look like duplicates",
    "orphan": "Pages nothing links to",
    "too-long": "Pages over 30,000 characters",
}


@dataclass
class Problem:
    code: str
    where: str  # the page's vault-relative path, or the document's id
    text: str  # one plain sentence


def _targets(vault: Vault) -> set[str]:
    """Every name a link can point to: a file's name or any trailing part of its vault-relative path (Obsidian resolves
    "Organisations/Acme" to Knowledge/Organisations/Acme.md), with and without .md, folded."""
    names: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(vault.root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        here = Path(dirpath).relative_to(vault.root)
        for name in filenames:
            if name.startswith("."):
                continue
            rel = (here / name).as_posix()
            parts = rel.split("/")
            for i in range(len(parts)):
                tail = "/".join(parts[i:]).casefold()
                names.add(tail)
                if tail.endswith(".md"):
                    names.add(tail[:-3])
    return names


def _exists(target: str, names: set[str]) -> bool:
    folded = target.strip().strip("/").casefold()
    return folded in names


def _key(name: str) -> str:
    """A name folded for spotting duplicates: no case, accents, punctuation or company suffix."""
    words = re.findall(r"\w+", fold(name).replace(".", ""))
    while words and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words)


def _duplicates(pages: list[wiki.Page], mine) -> list[Problem]:
    groups: dict[tuple[str, str], dict[str, wiki.Page]] = {}
    for page in pages:
        for name in {page.title, *page.aliases}:
            key = _key(name)
            if key:
                groups.setdefault((page.kind, key), {})[page.rel] = page
    out: list[Problem] = []
    seen: set[tuple[str, str]] = set()
    for group in groups.values():
        same = sorted(group.values(), key=lambda p: p.title.casefold())
        for i, a in enumerate(same):
            for b in same[i + 1:]:
                pair = (a.rel, b.rel)
                if pair in seen or not (mine(a) or mine(b)):
                    continue
                seen.add(pair)
                out.append(Problem("duplicate", a.rel, f"[[{a.title}]] and [[{b.title}]] look like the same page."))
    return out


def run(vault: Vault, *, only: set[str] | None = None, pages: list[wiki.Page] | None = None) -> list[Problem]:
    """Every problem, or (only=) those of these pages: `wiki done` checks the pages that changed and the pages linking
    to them, and leaves out the store-wide "read but no page yet" check."""
    pages = wiki.all_pages(vault) if pages is None else pages
    good = [p for p in pages if not p.error]

    def mine(page: wiki.Page) -> bool:
        return only is None or page.rel in only

    out: list[Problem] = [Problem("bad-properties", p.rel, f"{p.title}: its properties can't be read ({p.error}).")
                          for p in pages if p.error and mine(p)]
    names = _targets(vault)
    linked: dict[str, set[str]] = {}  # page name → the pages that link to it
    for page in good:
        for target in dict.fromkeys(page.links()):  # a link in the body and in a property counts once
            linked.setdefault(wiki.name_of(target), set()).add(page.rel)
            if mine(page) and not _exists(target, names):
                out.append(Problem("broken-link", page.rel, f"{page.title}: links to [[{target}]], which doesn't exist."))
    for page in good:
        if not mine(page):
            continue
        missing = [key for key in ("type", "summary") if not wiki.property_text(page.meta.get(key))]
        if missing:
            out.append(Problem("missing-properties", page.rel,
                               f"{page.title}: no {' or '.join(missing)} in its properties."))
        if page.doc_id and not store.exists(vault, page.doc_id):
            out.append(Problem("unknown-doc", page.rel, f"{page.title}: its doc {page.doc_id} isn't in the knowledge "
                                                        "base (forgotten, or never read)."))
        if len(page.body) > MAX_CHARS:
            out.append(Problem("too-long", page.rel,
                               f"{page.title}: {len(page.body):,} characters; split it into smaller pages."))
        if not (linked.get(wiki.name_of(page.title), set()) - {page.rel}):
            out.append(Problem("orphan", page.rel, f"{page.title}: no other page links to it."))
    out += _duplicates(good, mine)
    if only is None:
        with_pages = {p.doc_id for p in good if p.doc_id}
        for doc in store.all_docs(vault):
            # a page whose properties can't be read is still its document's page (reported above, never written twice)
            recorded = bool(doc.page) and (vault.root / doc.page).is_file()
            if doc.status == "read" and doc.doc_id not in with_pages and not recorded:
                out.append(Problem("no-page-yet", doc.doc_id, f"{doc.name} (doc {doc.doc_id}): read but no page yet."))
    return sorted(out, key=lambda p: (ORDER.index(p.code), p.where, p.text))


def render(problems: list[Problem], *, everything: bool) -> str:
    if not problems:
        return "The wiki has no problems Bron can find."
    lines: list[str] = []
    for code in ORDER:
        found = [p for p in problems if p.code == code]
        if not found:
            continue
        shown = found if everything else found[:3]
        lines.append(f"{TITLES[code]} ({len(found)}):")
        lines += [f"- {p.text}" for p in shown]
        if len(found) > len(shown):
            lines.append(f"- …and {len(found) - len(shown)} more; run `.bron/bin/bron wiki check --all`.")
    return "\n".join(lines)

"""Mechanical checks of the wiki (free: no model). Links to pages that don't exist, pages nothing links to, pages
missing `type` or `summary`, documents read without a page, pages naming a document Bron doesn't have, probable
duplicates, two pages answering to one name, pages too long to read in one go, summaries too long for index.md and
pages whose properties can't be read. `review` is a second list that never blocks: things worth a second look."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..memory.facts import fold
from ..vault import Vault
from . import store, wiki

MAX_CHARS = 20_000  # a page every later run reads again (an organisation, a person, a topic)
MAX_DOCUMENT_CHARS = 30_000  # a document page follows one long document
TIDY_TO = 15_000  # what a page over the limit is told to shrink to: well under it, so it doesn't come straight back
SUMMARY_MAX = 300  # a summary is one line: index.md and search show it
SUFFIXES = {"ltda", "llc", "inc", "sa", "lp"}  # folded away when looking for duplicates ("Acme Ltda." = "Acme")
ORDER = ("bad-properties", "broken-link", "missing-properties", "long-summary", "unknown-doc",
         "doc-on-two-pages", "no-page-yet",
         "duplicate", "same-name", "orphan", "too-long")
TITLES = {
    "bad-properties": "Pages whose properties can't be read",
    "broken-link": "Links to pages that don't exist",
    "missing-properties": "Pages missing type or summary",
    "long-summary": "Summaries too long to list",
    "unknown-doc": "Document pages whose document Bron doesn't have",
    "doc-on-two-pages": "Documents claimed by two pages",
    "no-page-yet": "Documents read but no page yet",
    "duplicate": "Pages that look like duplicates",
    "same-name": "Names two pages answer to",
    "orphan": "Pages nothing links to",
    "too-long": "Pages over 20,000 characters (document pages 30,000)",
}


REVIEW_ORDER = ("not-checked", "raw-number", "timeline-order")
REVIEW_TITLES = {
    "not-checked": "Notes saying something isn't checked yet",
    "raw-number": "Numbers in spreadsheet form",
    "timeline-order": "Timelines out of order",
}
NOT_CHECKED = re.compile(r"\b(not (yet )?(checked|compared|verified|confirmed)|to (be )?confirm(ed)?"
                         r"|pending (check|confirmation))\b", re.IGNORECASE)
BLANKED = re.compile(r"\[\[.*?\]\]|`[^`\n]*`|https?://\S+|[?&]\w+=\S+|\d{4}-\d{2}-\d{2}|\+\d[\d\s().-]{6,}\d")
# 7 to 10 digits: longer runs are accounts, phones and tax ids
WHOLE_NUMBER = re.compile(r"(?<![\w.,/-])\d{7,10}(?![\w,/-]|\.\d|\d)")
LONG_DECIMAL = re.compile(r"(?<![\w.,/-])\d{4,}\.\d{3,}(?!\w)")
IDENTIFIER = re.compile(r"(\bno\b\.?|number|#|\bid|ref|reference|invoice|tax|account|order|ticket|policy|reg|registration"
                        r"|code|version|cnpj|cpf)\W{0,3}$", re.IGNORECASE)
DATED_LINE = re.compile(r"^\s*[-*]\s*\[?(\d{4}-\d{2}-\d{2})\b")


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


def _same_names(pages: list[wiki.Page], mine) -> list[Problem]:
    """A title or alias that two pages of different types answer to (a document page whose alias is the round's page
    title, say): a link with that name can't tell them apart. Pages of one type are the duplicate check's."""
    owners: dict[str, dict[str, wiki.Page]] = {}
    for page in pages:
        for name in {page.title, *page.aliases}:
            key = " ".join(name.casefold().split())
            if key:
                owners.setdefault(key, {})[page.rel] = page
    out: list[Problem] = []
    for key, group in sorted(owners.items()):
        same = sorted(group.values(), key=lambda p: p.rel)
        if len({p.kind for p in same}) < 2 or not any(mine(p) for p in same):
            continue
        name = next(n for n in (same[0].title, *same[0].aliases) if " ".join(n.casefold().split()) == key)
        listed = " and ".join(f"[[{p.title}]]" for p in same)
        out.append(Problem("same-name", same[0].rel, f'"{name}" is a name of {listed}; keep it on one of them.'))
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
        summary = wiki.property_text(page.meta.get("summary"))
        if len(summary) > SUMMARY_MAX:
            out.append(Problem("long-summary", page.rel, f"{page.title}: its summary is {len(summary)} characters; "
                                                         "keep it to one line under 300."))
        for doc_id in page.doc_ids:
            if not store.exists(vault, doc_id):
                out.append(Problem("unknown-doc", page.rel, f"{page.title}: its doc {doc_id} isn't in the knowledge "
                                                            "base (forgotten, or never read)."))
        if page.is_document and len(page.body) > MAX_DOCUMENT_CHARS:
            out.append(Problem("too-long", page.rel,
                               f"{page.title}: {len(page.body):,} characters; split it into smaller pages."))
        elif not page.is_document and len(page.body) > MAX_CHARS:
            out.append(Problem("too-long", page.rel,
                               f"{page.title}: {len(page.body):,} characters; tidy it to about {TIDY_TO:,}: one "
                               "line per fact (merge lines that repeat it), roles instead of a line per document, "
                               "and move lists and detail to the pages they are about."))
        if not (linked.get(wiki.name_of(page.title), set()) - {page.rel}):
            out.append(Problem("orphan", page.rel, f"{page.title}: no other page links to it."))
    out += _duplicates(good, mine)
    out += _same_names(good, mine)
    first: dict[str, wiki.Page] = {}
    for page in sorted(good, key=lambda p: p.rel):
        for doc_id in page.doc_ids:
            other = first.setdefault(doc_id, page)
            if other is not page and (mine(other) or mine(page)):
                doc = store.load(vault, doc_id)
                out.append(Problem("doc-on-two-pages", other.rel,
                                   f"{doc.name if doc else doc_id} (doc {doc_id}) is named by [[{other.title}]] "
                                   f"and [[{page.title}]]; keep it on one page."))
    if only is None:
        with_pages = set(first)
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


def _is_date(digits: str) -> bool:
    """Eight digits that read as YYYYMMDD (20250301)."""
    if len(digits) != 8:
        return False
    year, month, day = int(digits[:4]), int(digits[4:6]), int(digits[6:])
    return 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31


def _raw_numbers(body: str) -> list[str]:
    """Numbers written the way a spreadsheet stores them (12192630, 19389341.05263158), not identifiers or prices."""
    found: list[str] = []
    for line in body.splitlines():
        blank = BLANKED.sub(lambda m: " " * len(m.group()), line)
        for pattern in (WHOLE_NUMBER, LONG_DECIMAL):
            for m in pattern.finditer(blank):
                before = blank[max(0, m.start() - 12):m.start()]
                if m.group() not in found and not IDENTIFIER.search(before) and not _is_date(m.group()):
                    found.append(m.group())
    return found


def _timeline_order(body: str) -> tuple[str, str] | None:
    """The first full date in a Timeline section that comes before the one above it: (later, earlier)."""
    in_timeline, previous = False, ""
    for line in body.splitlines():
        if line.startswith("#"):
            in_timeline, previous = "timeline" in line.casefold(), ""
            continue
        m = DATED_LINE.match(line) if in_timeline else None
        if not m:
            continue
        if previous and m.group(1) < previous:
            return previous, m.group(1)
        previous = m.group(1)
    return None


def review(vault: Vault, *, only: set[str] | None = None, pages: list[wiki.Page] | None = None) -> list[Problem]:
    """Things worth a second look: often a false alarm, never a reason to hold `wiki done`."""
    pages = wiki.all_pages(vault) if pages is None else pages
    out: list[Problem] = []
    for page in pages:
        if page.error or page.is_document or (only is not None and page.rel not in only):
            continue
        for line in page.body.splitlines():
            if NOT_CHECKED.search(line) and sum(p.code == "not-checked" and p.where == page.rel for p in out) < 3:
                snippet = line.strip()
                snippet = snippet if len(snippet) <= 80 else snippet[:79].rstrip() + "…"
                out.append(Problem("not-checked", page.rel, f"{page.title}: says something isn't checked yet "
                                                            f"(\"{snippet}\"); if it has been since, update it."))
        if examples := _raw_numbers(page.body)[:3]:
            out.append(Problem("raw-number", page.rel, f"{page.title}: numbers written as a spreadsheet stores them "
                                                       f"({', '.join(examples)}); write them the way the schema says."))
        if bad := _timeline_order(page.body):
            out.append(Problem("timeline-order", page.rel, f"{page.title}: its timeline is out of date order "
                                                           f"({bad[1]} comes before {bad[0]})."))
    return sorted(out, key=lambda p: (REVIEW_ORDER.index(p.code), p.where, p.text))


def render_review(items: list[Problem], *, everything: bool) -> str:
    """The same grouping as `render`, under its own header; empty when there is nothing to look at."""
    if not items:
        return ""
    lines = ["Worth a look (fix what's real; these don't block `wiki done`):"]
    for code in REVIEW_ORDER:
        found = [p for p in items if p.code == code]
        if not found:
            continue
        shown = found if everything else found[:3]
        lines.append(f"{REVIEW_TITLES[code]} ({len(found)}):")
        lines += [f"- {p.text}" for p in shown]
        if len(found) > len(shown):
            lines.append(f"- …and {len(found) - len(shown)} more; run `.bron/bin/bron wiki check --all`.")
    return "\n".join(lines)

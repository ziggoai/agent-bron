"""Facts.md: lasting facts as one line each under four fixed headings. The user may edit it freely."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

SECTIONS: list[tuple[str, str]] = [
    ("about-you", "About you"),
    ("firm", "Your firm"),
    ("decisions", "Decisions"),
    ("how", "How you like things done"),
]
LIMITS = {"shared": 4000, "mine": 2500}
MAX_FACT = 300
_HEADING = re.compile(r"^##\s+(.+?)\s*$")
_FACT = re.compile(r"^\s*[-*]\s+(.+?)\s*$")
_SOURCE = re.compile(r"^(.*?)\s*\((\d{4}-\d{2}-\d{2}),\s*([^)]+)\)\s*$")


@dataclass(frozen=True)
class Fact:
    text: str
    date: str
    by: str
    section: str  # a SECTIONS key, or "other" under any other heading / before the first heading
    index: int


def fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def clean(text: str) -> str:
    one = " ".join(text.split())
    if not one:
        raise ValueError("There's nothing to remember.")
    if one[-1] not in ".!?":
        one += "."
    if len(one) > MAX_FACT:
        raise ValueError("Keep a fact to one or two sentences.")
    return one


def _section_key(heading: str) -> str:
    for key, title in SECTIONS:
        if fold(heading) == fold(title):
            return key
    return "other"


def parse(lines: list[str]) -> list[Fact]:
    found: list[Fact] = []
    section = "other"
    for i, line in enumerate(lines):
        heading = _HEADING.match(line)
        if heading:
            section = _section_key(heading.group(1))
            continue
        item = _FACT.match(line)
        if not item:
            continue
        body = item.group(1)
        source = _SOURCE.match(body)
        if source:
            found.append(Fact(source.group(1).strip(), source.group(2), source.group(3).strip(), section, i))
        else:
            found.append(Fact(body, "", "", section, i))
    return found


def _line(text: str, date: str, by: str) -> str:
    return f"- {text} ({date}, {by})"


def _heading_index(lines: list[str], key: str) -> int | None:
    for i, line in enumerate(lines):
        heading = _HEADING.match(line)
        if heading and _section_key(heading.group(1)) == key:
            return i
    return None


def add(lines: list[str], text: str, section: str, date: str, by: str) -> list[str]:
    clean_text = clean(text)
    out = list(lines)
    at = _heading_index(out, section)
    if at is None:
        # Insert the heading before the first later canonical heading, or at the end.
        order = [key for key, _ in SECTIONS]
        later = [_heading_index(out, k) for k in order[order.index(section) + 1:]]
        later = [i for i in later if i is not None]
        title = dict(SECTIONS)[section]
        block = [f"## {title}", _line(clean_text, date, by), ""]
        if later:
            out[min(later):min(later)] = block
        else:
            if out and out[-1].strip():
                out.append("")
            out += block[:-1]
        return out
    end = at + 1
    while end < len(out) and not _HEADING.match(out[end]):
        end += 1
    last_fact = max((i for i in range(at + 1, end) if _FACT.match(out[i])), default=at)
    out.insert(last_fact + 1, _line(clean_text, date, by))
    return out


def matches(lines: list[str], query: str) -> list[Fact]:
    needle = fold(" ".join(query.split()).rstrip("."))
    return [f for f in parse(lines) if needle and needle in fold(f.text)]


def remove(lines: list[str], fact: Fact) -> list[str]:
    return [line for i, line in enumerate(lines) if i != fact.index]


def replace(lines: list[str], old: Fact, text: str, date: str, by: str) -> list[str]:
    clean_text = clean(text)
    out = list(lines)
    out[old.index] = _line(clean_text, date, by)
    return out


def size(lines: list[str]) -> int:
    return sum(len(f.text) for f in parse(lines))

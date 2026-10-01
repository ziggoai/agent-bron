"""Markdown files with a YAML frontmatter block: the format of every Bron file."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

FENCE = "---"


class FrontmatterError(ValueError):
    """The frontmatter block exists but cannot be read."""


@dataclass
class Document:
    meta: dict = field(default_factory=dict)
    body: str = ""


def parse(text: str) -> Document:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].lstrip("﻿").strip() != FENCE:
        return Document({}, text)
    for i in range(1, len(lines)):
        if lines[i].strip() == FENCE:
            raw = "".join(lines[1:i])
            try:
                meta = yaml.safe_load(raw) if raw.strip() else {}
            except yaml.YAMLError as exc:
                detail = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
                raise FrontmatterError(f"the settings block at the top is not valid YAML ({detail})") from exc
            if meta is None:
                meta = {}
            if not isinstance(meta, dict):
                raise FrontmatterError("the settings block at the top must be 'key: value' lines")
            return Document(meta, "".join(lines[i + 1 :]))
    raise FrontmatterError("the settings block at the top is missing its closing '---' line")


def dump(doc: Document) -> str:
    if not doc.meta:
        return doc.body
    raw = yaml.safe_dump(doc.meta, sort_keys=False, allow_unicode=True, default_flow_style=None, width=1000)
    return f"{FENCE}\n{raw}{FENCE}\n{doc.body}"


def read(path: Path) -> Document:
    return parse(path.read_text(encoding="utf-8"))


def write(path: Path, doc: Document) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(doc), encoding="utf-8")

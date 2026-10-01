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


class _Dumper(yaml.SafeDumper):
    """Block-style mappings; short lists of plain values stay on one line."""


def _represent_list(dumper: yaml.SafeDumper, data: list):
    flow = all(isinstance(v, (str, int, float, bool)) or v is None for v in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_Dumper.add_representer(list, _represent_list)


def dump(doc: Document) -> str:
    if not doc.meta:
        return doc.body
    raw = yaml.dump(doc.meta, Dumper=_Dumper, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1000)
    return f"{FENCE}\n{raw}{FENCE}\n{doc.body}"


def read(path: Path) -> Document:
    return parse(path.read_text(encoding="utf-8"))


def write(path: Path, doc: Document) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(doc), encoding="utf-8")

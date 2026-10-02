"""Change a few settings at the top of a Markdown file, keeping every other line (and its comments) exactly as written."""
from __future__ import annotations

import json
import re

from . import frontmatter as fm

_PLAIN = re.compile(r"^[A-Za-z][A-Za-z0-9 _.()'&+/-]*$")
_RESERVED = {"true", "false", "yes", "no", "on", "off", "null", "y", "n"}


class EditError(ValueError):
    """The settings block can't be changed safely."""


def scalar(value) -> str:
    """One value as YAML text: plain when that's safe, otherwise double-quoted."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if _PLAIN.match(text) and text.lower() not in _RESERVED and not text.endswith(" "):
        return text
    return json.dumps(text, ensure_ascii=False)


def _value_lines(key: str, value) -> list[str]:
    if isinstance(value, list):
        return [f"{key}: [" + ", ".join(scalar(v) for v in value) + "]\n"]
    if isinstance(value, dict):
        if not value:
            return [f"{key}: {{}}\n"]
        return [f"{key}:\n"] + [f"  {k}: {scalar(v)}\n" for k, v in value.items()]
    return [f"{key}: {scalar(value)}\n"]


def _bounds(lines: list[str]) -> int:
    if not lines or lines[0].strip() != fm.FENCE:
        raise EditError("the file has no settings block at the top")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == fm.FENCE), None)
    if end is None:
        raise EditError("the settings block has no closing '---' line")
    return end


def edit_meta(text: str, changes: dict) -> str:
    """The file's text with `changes` applied to its settings block (None removes a key)."""
    lines = text.splitlines(keepends=True)
    end = _bounds(lines)
    try:
        before = fm.parse(text).meta
    except fm.FrontmatterError as exc:
        raise EditError(str(exc)) from exc
    for key, value in changes.items():
        index = next((i for i in range(1, end) if re.match(rf"^{re.escape(key)}\s*:", lines[i])), None)
        new = [] if value is None else _value_lines(key, value)
        if index is None:
            if value is not None:
                lines[end:end] = new
                end += len(new)
            continue
        stop, comments = index + 1, []
        while stop < end:
            line = lines[stop]
            if line.lstrip().startswith("#"):
                comments.append(line)  # comments inside the old value stay in the file, just above the new one
            elif not (line.strip() and (line[0] in " \t" or line.startswith("- "))):
                break
            stop += 1
        lines[index:stop] = comments + new
        end += len(comments) + len(new) - (stop - index)
    new_text = "".join(lines)
    try:
        after = fm.parse(new_text).meta
    except fm.FrontmatterError as exc:
        raise EditError(f"the change would make the settings unreadable ({exc})") from exc
    for key, value in changes.items():
        ok = key not in after if value is None else after.get(key) == value
        if not ok:
            raise EditError(f"Bron couldn't change '{key}' safely")
    for key, value in before.items():
        if key not in changes and after.get(key) != value:
            raise EditError(f"changing the settings would also change '{key}'")
    return new_text


def replace_body(text: str, body: str) -> str:
    """The file's text with everything after the settings block replaced by `body`."""
    lines = text.splitlines(keepends=True)
    end = _bounds(lines)
    head = "".join(lines[: end + 1])
    if not head.endswith("\n"):
        head += "\n"
    return head + "\n" + body.strip() + "\n"

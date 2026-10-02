"""Change a few settings at the top of a Markdown file, keeping every other line (and its comments) exactly as written."""
from __future__ import annotations

import json
import re

import yaml

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


def _key_pattern(key: str) -> str:
    return rf"^[\"']?{re.escape(key)}[\"']?\s*:"


def _extract_trailing_comment(line: str, key: str) -> str:
    """The comment at the end of a key's line, with the whitespace before it ("" when there is none).

    For a value on the same line, the comment starts at the first `#` after whitespace
    where reading the line up to that point gives the same value as reading the whole line.
    For a key whose value is on the lines below, it is the `#...` part after whitespace.
    """
    line = line.rstrip("\n")
    match = re.match(_key_pattern(key), line)
    if not match:
        return ""
    head, rest = line[: match.end()], line[match.end():]
    if rest.lstrip().startswith("#"):
        return rest if rest[:1] in (" ", "\t") else ""
    try:
        whole = yaml.safe_load(head + rest)
    except yaml.YAMLError:
        return ""
    if not isinstance(whole, dict) or key not in whole:
        return ""
    for i, char in enumerate(rest):
        if char != "#" or i == 0 or rest[i - 1] not in " \t":
            continue
        try:
            part = yaml.safe_load(head + rest[:i])
        except yaml.YAMLError:
            continue
        if isinstance(part, dict) and key in part and part[key] == whole[key]:
            start = len(rest[:i].rstrip(" \t"))
            return rest[start:]
    return ""


def _value_line_comment(line: str) -> str:
    """The `# ...` at the end of a line inside a block value, like `  - CFO  # note` ("" when there is none)."""
    text = line.strip()
    try:
        whole = yaml.safe_load(text)
    except yaml.YAMLError:
        return ""
    for i, char in enumerate(text):
        if char != "#" or i == 0 or text[i - 1] not in " \t":
            continue
        try:
            part = yaml.safe_load(text[:i])
        except yaml.YAMLError:
            continue
        if part == whole:
            return text[i:]
    return ""


def _value_lines(key: str, value, trailing_comment: str = "") -> list[str]:
    if isinstance(value, list):
        return [f"{key}: [" + ", ".join(scalar(v) for v in value) + "]" + trailing_comment + "\n"]
    if isinstance(value, dict):
        if not value:
            return [f"{key}: {{}}" + trailing_comment + "\n"]
        return [f"{key}:" + trailing_comment + "\n"] + [f"  {k}: {scalar(v)}\n" for k, v in value.items()]
    return [f"{key}: {scalar(value)}" + trailing_comment + "\n"]


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
        # Match quoted or unquoted keys
        index = next((i for i in range(1, end) if re.match(_key_pattern(key), lines[i])), None)
        comment = "" if index is None else _extract_trailing_comment(lines[index], key)
        new = [] if value is None else _value_lines(key, value, comment)

        if index is None:
            # Check if key is in before dict but no line matched (unusual form)
            if key in before:
                raise EditError(f"the key '{key}' exists but has an unusual form and can't be changed safely")
            if value is not None:
                lines[end:end] = new
                end += len(new)
            continue

        # Scan for content lines and comments that are part of this value
        stop, comments = index + 1, []
        while stop < end:
            line = lines[stop]
            # Check if it's a comment line
            if line.lstrip().startswith("#"):
                # Look ahead to see if this comment is part of the value or belongs to the next key
                scan = stop + 1
                # Skip further comment lines
                while scan < end and lines[scan].lstrip().startswith("#"):
                    scan += 1
                # If next non-comment line is indented or continuation, comment is part of value
                if scan < end:
                    next_line = lines[scan]
                    if next_line.strip() and (next_line[0] in " \t" or next_line.startswith("- ")):
                        # Indented continuation, so comment is part of value: kept, above the key, at column 0
                        comments.append(line.lstrip())
                        stop += 1
                        continue
                    else:
                        # Next line is not indented (likely a key or closing fence), comment stays
                        break
                else:
                    # Reached end (likely before closing fence), comment stays
                    break
            elif not (line.strip() and (line[0] in " \t" or line.startswith("- "))):
                break
            elif trailing := _value_line_comment(line):
                comments.append(trailing + "\n")  # a comment at the end of a replaced item: kept above the key
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
    # Validate that settings block parses
    try:
        fm.parse(text)
    except fm.FrontmatterError as exc:
        raise EditError(str(exc)) from exc
    head = "".join(lines[: end + 1])
    if not head.endswith("\n"):
        head += "\n"
    return head + "\n" + body.strip("\n") + "\n"

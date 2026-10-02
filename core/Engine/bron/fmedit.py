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


def _extract_trailing_comment(line: str, key: str) -> tuple[str, str]:
    """Extract a trailing comment from a line using YAML parsing.

    Returns (line_without_comment, trailing_comment_with_spacing_and_hash).

    Strategy: Split into head (key:) and rest. If rest is empty or starts with #,
    the comment is from the first # preceded by whitespace (or rest itself when it starts with #).
    Otherwise, try parsing at each # position to find where the actual value ends.
    """
    line = line.rstrip("\n")

    # Find the colon after the key
    colon_idx = line.find(":")
    if colon_idx == -1:
        return line, ""

    head = line[:colon_idx + 1]
    rest = line[colon_idx + 1:]

    # Check if rest is empty or is just whitespace + comment
    if not rest.strip():
        # Only whitespace; if there's a #, find it
        if "#" in rest:
            hash_idx = rest.find("#")
            # Verify there's whitespace before the #
            if hash_idx > 0 and rest[hash_idx - 1] in " \t":
                ws_start = hash_idx - 1
                while ws_start > 0 and rest[ws_start - 1] in " \t":
                    ws_start -= 1
                return head, rest[ws_start:]
            elif hash_idx == 0:
                # Hash at the start of rest (after spaces)
                return head, rest.lstrip()
        return line, ""

    # If rest starts with # after optional spaces
    if rest.lstrip().startswith("#"):
        stripped_start = len(rest) - len(rest.lstrip())
        return head, rest[stripped_start:]

    # Otherwise, look for # positions that could be comment boundaries
    # Try each position where we see # preceded by whitespace
    for i, char in enumerate(rest):
        if char == "#" and i > 0 and rest[i - 1] in " \t":
            # Found a # preceded by whitespace
            # Try parsing up to this point
            try:
                candidate = head + rest[:i]
                parsed = yaml.safe_load(candidate)
                if isinstance(parsed, dict) and key in parsed:
                    # Get the value from parsing the full line and the candidate
                    full_parsed = yaml.safe_load(head + rest)
                    if isinstance(full_parsed, dict) and full_parsed.get(key) == parsed.get(key):
                        # This is the comment boundary
                        ws_start = i - 1
                        while ws_start > 0 and rest[ws_start - 1] in " \t":
                            ws_start -= 1
                        return head + rest[:ws_start], rest[ws_start:]
            except (yaml.YAMLError, ValueError):
                # This position doesn't parse; continue
                continue

    return line, ""


def _value_lines(key: str, value, trailing_comment: str = "") -> list[str]:
    if isinstance(value, list):
        return [f"{key}: [" + ", ".join(scalar(v) for v in value) + "]" + trailing_comment + "\n"]
    if isinstance(value, dict):
        if not value:
            return [f"{key}: {{}}" + trailing_comment + "\n"]
        return [f"{key}:\n"] + [f"  {k}: {scalar(v)}\n" for k, v in value.items()]
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
        index = next((i for i in range(1, end) if re.match(rf"^[\"']?{re.escape(key)}[\"']?\s*:", lines[i])), None)
        new = [] if value is None else _value_lines(key, value)

        if index is None:
            # Check if key is in before dict but no line matched (unusual form)
            if key in before:
                raise EditError(f"the key '{key}' exists but has an unusual form and can't be changed safely")
            if value is not None:
                lines[end:end] = new
                end += len(new)
            continue

        # Extract trailing comment from the old first line
        old_line = lines[index]
        _, trailing_comment = _extract_trailing_comment(old_line, key)

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
                        # Indented continuation, so comment is part of value
                        comments.append(line)
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
            stop += 1

        # Update the new lines with trailing comment (pass to _value_lines, not appended after)
        if new and trailing_comment:
            # Recreate new lines with the trailing comment
            new = _value_lines(key, value, trailing_comment)

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

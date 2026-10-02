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


def _extract_trailing_comment(line: str, parsed_value) -> tuple[str, str]:
    """Extract a trailing comment from a line, respecting quotes and parsed value.

    Returns (value_text_without_comment, trailing_comment_with_spacing_and_hash).
    Only returns a comment if it's not part of the quoted value.
    """
    line = line.rstrip("\n")

    # Find the colon that separates key from value
    colon_idx = line.find(":")
    if colon_idx == -1:
        return line, ""

    # Value part is everything after the colon
    value_part = line[colon_idx + 1:].lstrip(" \t")
    if not value_part:
        return line, ""

    # For dict/list values, no trailing comment on the key line
    if value_part.startswith(("[", "{")):
        return line, ""

    # Convert parsed_value to string for comparison
    str_parsed = str(parsed_value) if parsed_value is not None else ""

    # Scan for the last # outside of quotes that is preceded by whitespace
    in_single = False
    in_double = False
    hash_pos = -1

    for i, char in enumerate(value_part):
        if char == "'" and (i == 0 or value_part[i - 1] != "\\"):
            in_single = not in_single
        elif char == '"' and (i == 0 or value_part[i - 1] != "\\"):
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            hash_pos = i

    # If we found a # preceded by whitespace, it's a trailing comment
    if hash_pos > 0 and value_part[hash_pos - 1] in " \t":
        # Find where the whitespace starts (preserving spacing)
        ws_start = hash_pos - 1
        while ws_start > 0 and value_part[ws_start - 1] in " \t":
            ws_start -= 1

        # Extract value without the comment and spacing
        value_without = value_part[:ws_start]
        trailing = value_part[ws_start:]

        # Only treat as trailing comment if parsed value is found in the value part
        if not str_parsed or str_parsed in value_without:
            # Reconstruct the line without comment
            prefix = line[:colon_idx + 1]
            # Add back any leading spaces that were in the original
            original_value_start = colon_idx + 1
            while original_value_start < len(line) and line[original_value_start] in " \t":
                prefix += line[original_value_start]
                original_value_start += 1
            return prefix + value_without, trailing

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
        _, trailing_comment = _extract_trailing_comment(old_line, before.get(key))

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

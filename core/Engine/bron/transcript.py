"""The last few exchanges of a chat, read from the CLI's own transcript file (context for @-mentions)."""
from __future__ import annotations

import json
from pathlib import Path

MAX_EXCHANGES = 3
MAX_MESSAGE = 1500
MAX_TOTAL = 6000
TAIL_BYTES = 1_000_000
NO_HISTORY = "(no earlier chat available)"
# User-side text the CLIs or Bron inject, which the user didn't type.
_INJECTED = ("<", "# AGENTS.md instructions", "Base directory for this skill")


def _claude_text(entry: dict) -> tuple[str, str] | None:
    if entry.get("type") not in ("user", "assistant") or entry.get("isMeta") or entry.get("isSidechain") or entry.get("isCompactSummary"):
        return None  # isCompactSummary: the summary Claude Code writes when it compacts a long chat, not something the user typed
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    role, content = message.get("role"), message.get("content")
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):
        texts = [str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    else:
        return None
    text = "\n".join(t for t in texts if t.strip()).strip()
    if role not in ("user", "assistant") or not text:
        return None
    return role, text


def _codex_text(entry: dict) -> tuple[str, str] | None:
    payload = entry.get("payload")
    if entry.get("type") != "response_item" or not isinstance(payload, dict) or payload.get("type") != "message":
        return None
    role, content = payload.get("role"), payload.get("content")
    if role not in ("user", "assistant") or not isinstance(content, list):
        return None
    parts = [str(c.get("text") or "") for c in content if isinstance(c, dict) and c.get("type") in ("input_text", "output_text")]
    kept = [p for p in parts if p.strip() and not (role == "user" and p.lstrip().startswith(_INJECTED))]
    text = "\n".join(kept).strip()
    return (role, text) if text else None


def _tail_lines(path: str | Path) -> list[str]:
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - TAIL_BYTES))
        data = fh.read()
    if size > TAIL_BYTES:
        data = data.split(b"\n", 1)[-1]  # the first line is probably cut
    return data.decode("utf-8", "replace").splitlines()


def messages(cli: str, path: str | Path) -> list[tuple[str, str]]:
    """(role, text) pairs in order: what the user typed and what the assistant said. [] if unreadable."""
    pick = _claude_text if cli == "claude" else _codex_text
    try:
        lines = _tail_lines(path)
    except (OSError, ValueError):
        return []
    out: list[tuple[str, str]] = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        found = pick(entry)
        if found is None:
            continue
        role, text = found
        if role == "user" and text.lstrip().startswith(_INJECTED):
            continue
        if out and out[-1][0] == role:
            out[-1] = (role, out[-1][1] + "\n" + text)
        else:
            out.append((role, text))
    return out


def recent_exchanges(cli: str, path: str | Path | None, current_prompt: str = "", *, assistant: str = "Assistant") -> str:
    """Up to the last 3 exchanges before the current message, newest kept when cutting."""
    if not path:
        return NO_HISTORY
    items = messages(cli, path)
    if items and items[-1][0] == "user" and items[-1][1].strip() == current_prompt.strip():
        items = items[:-1]
    items = items[-2 * MAX_EXCHANGES:]
    labels = {"user": "User", "assistant": assistant}
    blocks: list[str] = []
    total = 0
    for role, text in reversed(items):
        if len(text) > MAX_MESSAGE:
            text = text[: MAX_MESSAGE - 1] + "…"
        block = f"{labels[role]}: {text}"
        if total + len(block) > MAX_TOTAL:
            break
        blocks.append(block)
        total += len(block)
    return "\n\n".join(reversed(blocks)) if blocks else NO_HISTORY

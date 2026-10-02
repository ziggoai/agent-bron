"""Ticket updates waiting to be shown to whoever asked for the work."""
from __future__ import annotations

import json
import time

from .model import slug
from .statefile import append_line, locked, read_json, read_lines, write_json
from .vault import Vault

FILE = "notifications.jsonl"
SEEN = "notifications-seen.json"


def record(vault: Vault, ticket) -> None:
    entry = {
        "id": ticket.id,
        "title": ticket.title,
        "status": ticket.status,
        "assignee": ticket.assignee,
        "requested_by": ticket.requested_by,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    append_line(vault.state_dir / FILE, json.dumps(entry, ensure_ascii=False))


def take(vault: Vault, agent_key: str, default_key: str) -> list[dict]:
    """Unseen updates for this agent (tickets it asked for; the user's own tickets go to the default agent)."""
    seen_path = vault.state_dir / SEEN
    with locked(vault.state_dir / FILE), locked(seen_path):
        lines = read_lines(vault.state_dir / FILE)
        seen = read_json(seen_path, {})
        start = int(seen.get(agent_key, 0)) if str(seen.get(agent_key, 0)).isdigit() else 0
        updates: list[dict] = []
        for line in lines[start:]:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            requester = entry.get("requested_by") or "you"
            if slug(str(requester)) == slug(agent_key) or (requester == "you" and agent_key == default_key):
                updates.append(entry)
        seen[agent_key] = len(lines)
        write_json(seen_path, seen)
    return updates


def describe(entry: dict) -> str:
    return f'{entry.get("id")} "{entry.get("title", "")}" is now {entry.get("status")} ({entry.get("assignee")})'

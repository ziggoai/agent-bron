"""Ticket updates waiting to be shown to whoever asked for the work."""
from __future__ import annotations

import json
import time

from .model import slug
from .statefile import append_line, locked, read_json, read_lines, write_json
from .vault import Vault

FILE = "notifications.jsonl"
SEEN = "notifications-seen.json"


def record(vault: Vault, ticket, *, shown: bool = False) -> None:
    """Note a ticket update for its requester. `shown`: the requester already saw it (it waited for the run)."""
    entry = {
        "id": ticket.id,
        "title": ticket.title,
        "status": ticket.status,
        "assignee": ticket.assignee,
        "requested_by": ticket.requested_by,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    if shown:
        entry["shown"] = True
    append_line(vault.state_dir / FILE, json.dumps(entry, ensure_ascii=False))


def acknowledge(vault: Vault, ticket_id: str) -> None:
    """Someone waiting for the run printed this ticket's outcome: its updates so far aren't announced again."""
    append_line(vault.state_dir / FILE, json.dumps({"ack": ticket_id}))


def _parse(line: str) -> dict | None:
    try:
        entry = json.loads(line)
    except ValueError:
        return None
    return entry if isinstance(entry, dict) else None


def take(vault: Vault, agent_key: str, default_key: str) -> list[dict]:
    """Unseen updates for this agent (tickets it asked for; the user's own tickets go to the default agent).

    An update is skipped when an acknowledgement for its ticket comes after it (a wait already printed it)."""
    seen_path = vault.state_dir / SEEN
    with locked(vault.state_dir / FILE), locked(seen_path):
        lines = read_lines(vault.state_dir / FILE)
        seen = read_json(seen_path, {})
        start = int(seen.get(agent_key, 0)) if str(seen.get(agent_key, 0)).isdigit() else 0
        entries = [(index, _parse(line)) for index, line in enumerate(lines) if index >= start]
        last_ack = {str(entry["ack"]): index for index, entry in entries if entry is not None and "ack" in entry}
        updates: list[dict] = []
        for index, entry in entries:
            if entry is None or "ack" in entry or entry.get("shown"):
                continue
            if last_ack.get(str(entry.get("id")), -1) > index:
                continue
            requester = entry.get("requested_by") or "you"
            if slug(str(requester)) == slug(agent_key) or (slug(str(requester)) == "you" and agent_key == default_key):
                # One update per ticket: its latest ("in-review" then "done" is told once, as done).
                updates = [u for u in updates if u.get("id") != entry.get("id")]
                updates.append(entry)
        new_cursor = len(lines)
        if new_cursor != start:
            seen[agent_key] = new_cursor
            write_json(seen_path, seen)
    return updates


def describe(entry: dict) -> str:
    return f'{entry.get("id")} "{entry.get("title", "")}" is now {entry.get("status")} ({entry.get("assignee")})'

"""Tickets: the notes in Tickets/ that agents and the user use to hand each other work."""
from __future__ import annotations

import contextlib
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter as fm
from .statefile import locked, update_json
from .vault import Vault

STATUSES = ("backlog", "todo", "in-progress", "blocked", "in-review", "done", "cancelled")
OPEN = ("backlog", "todo", "in-progress", "blocked", "in-review")
KINDS = ("task", "chat")
PRIORITIES = ("low", "normal", "high", "urgent")
_SECTION = re.compile(r"^## (Request|Context|Thread|Result)[ \t]*$", re.M)
_ID = re.compile(r"^[Tt]?-?(\d+)$")
_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]')


class TicketError(ValueError):
    """A ticket problem to show the user as it is."""


@dataclass
class Ticket:
    id: str
    title: str
    path: Path
    status: str = "todo"
    kind: str = "task"
    assignee: str = ""
    requested_by: str = "you"
    parent: str = ""
    project: str = ""
    priority: str = "normal"
    due: str = ""
    created: str = ""
    request: str = ""
    context: str = ""
    thread: list[str] = field(default_factory=list)
    result: str = ""
    problems: list[str] = field(default_factory=list)
    extra_meta: dict = field(default_factory=dict)
    preamble: str = ""
    invalid: dict[str, str] = field(default_factory=dict)


def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def normalize_id(text: str) -> str:
    match = _ID.match(text.strip())
    if not match:
        raise TicketError(f"'{text}' isn't a ticket id (like T-0042)")
    return f"T-{int(match.group(1)):04d}"


def _safe_title(title: str) -> str:
    # Replace control characters and newlines with space
    title = re.sub(r'[\x00-\x1f\x7f\n\r]', ' ', title)
    # Replace unsafe filename chars with dash
    title = _UNSAFE.sub("-", title).strip().strip(".")[:60].rstrip(" .") or "Untitled"
    return title


def _highest_existing(vault: Vault) -> int:
    best = 0
    if vault.tickets_dir.is_dir():
        for path in vault.tickets_dir.glob("T-*.md"):
            match = re.match(r"^T-(\d+)", path.name)
            if match:
                best = max(best, int(match.group(1)))
    return best


def _next_id(vault: Vault) -> str:
    holder: dict = {}

    def bump(data: dict) -> dict:
        try:
            next_val = int(data.get("next", 1))
        except (ValueError, TypeError):
            next_val = 1
        number = max(next_val, _highest_existing(vault) + 1)
        holder["n"] = number
        data["next"] = number + 1
        return data

    update_json(vault.state_dir / "tickets.json", {}, bump)
    return f"T-{holder['n']:04d}"


def _check(value: str, allowed: tuple, what: str) -> str:
    if value not in allowed:
        raise TicketError(f"'{value}' isn't a ticket {what} ({', '.join(allowed)})")
    return value


def new_ticket(
    vault: Vault,
    *,
    title: str,
    assignee: str,
    request: str,
    requested_by: str = "you",
    context: str = "",
    kind: str = "task",
    project: str = "",
    parent: str = "",
    priority: str = "normal",
    due: str = "",
    status: str = "todo",
    extra_meta: dict | None = None,
) -> Ticket:
    if not title.strip():
        raise TicketError("A ticket needs a title")
    _check(kind, KINDS, "kind")
    _check(priority, PRIORITIES, "priority")
    _check(status, STATUSES, "status")
    ticket_id = _next_id(vault)
    vault.tickets_dir.mkdir(parents=True, exist_ok=True)
    ticket = Ticket(
        id=ticket_id,
        title=title.strip(),
        path=vault.tickets_dir / f"{ticket_id} {_safe_title(title)}.md",
        status=status,
        kind=kind,
        assignee=assignee,
        requested_by=requested_by,
        parent=normalize_id(parent) if parent else "",
        project=project,
        priority=priority,
        due=due,
        created=time.strftime("%Y-%m-%dT%H:%M"),
        request=request.strip(),
        context=context.strip(),
        extra_meta=dict(extra_meta or {}),
    )
    add_message(ticket, requested_by, f"created for {assignee}")
    save_ticket(ticket)
    return ticket


def find_ticket(vault: Vault, ticket_id: str) -> Path:
    tid = normalize_id(ticket_id)
    if vault.tickets_dir.is_dir():
        matches = sorted(vault.tickets_dir.glob(f"{tid} *.md")) + sorted(vault.tickets_dir.glob(f"{tid}.md"))
        if matches:
            return matches[0]
    raise TicketError(f"There's no ticket {tid} in Tickets/")


def _sections(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    marks = list(_SECTION.finditer(body))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(body)
        section_name = mark.group(1)
        section_text = body[mark.end():end].strip("\n")
        # Join repeated sections with blank line between
        if section_name in out:
            out[section_name] = out[section_name] + "\n\n" + section_text
        else:
            out[section_name] = section_text
    return out


def _thread(text: str) -> list[str]:
    entries: list[str] = []
    for line in text.splitlines():
        if line.startswith("- "):
            entries.append(line.rstrip())
        elif line.startswith("#"):
            # Raw heading lines: keep as-is
            entries.append(line.rstrip())
        elif line.strip() and entries and (line.startswith(" ") or line.startswith("\t")):
            # Continuation of previous entry: append with proper indentation
            entries[-1] += "\n  " + line.strip()
        elif line.strip():
            # Other non-empty lines: convert to bullet format
            entries.append("- " + line.strip())
    return entries


def load_ticket(path: Path) -> Ticket:
    try:
        doc = fm.read(path)
    except fm.FrontmatterError as exc:
        raise TicketError(f"{path.name} can't be read: {exc}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise TicketError(f"{path.name} can't be opened ({exc.__class__.__name__})") from exc
    meta = doc.meta
    problems: list[str] = []
    invalid: dict[str, str] = {}

    # Extract ID from filename, check against frontmatter ID
    file_id = path.name.split(" ")[0]
    try:
        file_ticket_id = normalize_id(file_id)
    except TicketError:
        file_ticket_id = None

    raw_id = str(meta.get("id") or file_id)
    try:
        ticket_id = normalize_id(raw_id)
    except TicketError:
        ticket_id = file_ticket_id or "T-0000"
        problems.append(f"Invalid ticket id '{raw_id}'")

    # If file name and frontmatter id differ, use file name id
    if file_ticket_id and file_ticket_id != ticket_id:
        problems.append(f"the file name says {file_ticket_id} but the id inside says {ticket_id}; using {file_ticket_id}")
        ticket_id = file_ticket_id

    def choice(key: str, allowed: tuple, default: str) -> str:
        raw_value = str(meta.get(key) or default).strip()
        value = raw_value.lower()
        if value not in allowed:
            problems.append(f"{key} '{raw_value}' isn't one of {', '.join(allowed)}; treated as {default}")
            invalid[key] = raw_value
            return default
        return value

    # Known keys
    known_keys = {"id", "title", "kind", "status", "assignee", "requested_by", "parent", "project", "due", "priority", "created"}

    # Extract extra_meta (unknown keys)
    extra_meta = {}
    for key, value in meta.items():
        if key not in known_keys:
            extra_meta[key] = value

    # Extract preamble (text before first section)
    preamble = ""
    first_section_pos = _SECTION.search(doc.body)
    if first_section_pos:
        preamble = doc.body[:first_section_pos.start()].strip("\n")
    else:
        preamble = doc.body.strip("\n")

    sections = _sections(doc.body)
    return Ticket(
        id=ticket_id,
        title=str(meta.get("title") or path.stem[len(ticket_id):].strip() or ticket_id),
        path=path,
        status=choice("status", STATUSES, "todo"),
        kind=choice("kind", KINDS, "task"),
        assignee=str(meta.get("assignee") or ""),
        requested_by=str(meta.get("requested_by") or "you"),
        parent=str(meta.get("parent") or ""),
        project=str(meta.get("project") or ""),
        priority=choice("priority", PRIORITIES, "normal"),
        due=str(meta.get("due") or ""),
        created=str(meta.get("created") or ""),
        request=sections.get("Request", "").strip(),
        context=sections.get("Context", "").strip(),
        thread=_thread(sections.get("Thread", "")),
        result=sections.get("Result", "").strip(),
        problems=problems,
        extra_meta=extra_meta,
        preamble=preamble,
        invalid=invalid,
    )


def render(ticket: Ticket) -> str:
    meta: dict = {
        "id": ticket.id,
        "title": ticket.title,
        "kind": ticket.kind if "kind" not in ticket.invalid else ticket.invalid["kind"],
        "status": ticket.status if "status" not in ticket.invalid else ticket.invalid["status"],
        "assignee": ticket.assignee,
        "requested_by": ticket.requested_by,
    }
    for key in ("parent", "project", "due"):
        value = getattr(ticket, key)
        if value:
            meta[key] = value
    meta["priority"] = ticket.priority if "priority" not in ticket.invalid else ticket.invalid["priority"]
    meta["created"] = ticket.created

    # Add extra_meta keys in their original order
    for key, value in ticket.extra_meta.items():
        meta[key] = value

    # Build body with preamble and sections
    thread = "".join(entry + "\n" for entry in ticket.thread)
    body = ""
    if ticket.preamble:
        body += ticket.preamble + "\n\n"
    body += (
        f"## Request\n{ticket.request}\n\n## Context\n{ticket.context}\n\n"
        f"## Thread\n{thread}## Result\n{ticket.result}\n"
    )
    return fm.dump(fm.Document(meta, body))


def save_ticket(ticket: Ticket) -> None:
    ticket.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ticket.path.with_name(f"{ticket.path.name}.{os.getpid()}.bron-tmp")
    tmp.write_text(render(ticket), encoding="utf-8")
    tmp.replace(ticket.path)


@contextlib.contextmanager
def editing(vault: Vault, ticket_id: str):
    """Load a ticket under its lock, yield it, save it on success."""
    path = find_ticket(vault, ticket_id)
    with locked(path):
        ticket = load_ticket(path)
        yield ticket
        save_ticket(ticket)


def add_message(ticket: Ticket, author: str, text: str) -> None:
    lines = text.strip().splitlines() or [""]
    entry = f"- {_stamp()} · {author}: {lines[0]}" + "".join(f"\n  {line.strip()}" for line in lines[1:])
    ticket.thread.append(entry)


def set_status(ticket: Ticket, status: str, author: str, note: str = "") -> None:
    ticket.status = _check(status.strip().lower(), STATUSES, "status")
    # Remove status from invalid if it was there
    ticket.invalid.pop("status", None)
    add_message(ticket, author, f"status → {ticket.status}" + (f": {note.strip()}" if note.strip() else ""))


def set_result(ticket: Ticket, text: str, author: str) -> None:
    ticket.result = text.strip()
    set_status(ticket, "in-review", author, "result added")


def list_tickets(vault: Vault) -> tuple[list[Ticket], list[str]]:
    tickets: list[Ticket] = []
    problems: list[str] = []
    if vault.tickets_dir.is_dir():
        for path in sorted(vault.tickets_dir.glob("T-*.md")):
            try:
                tickets.append(load_ticket(path))
            except TicketError as exc:
                problems.append(str(exc))
    return tickets, problems

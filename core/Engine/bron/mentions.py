"""@-mentions: which agents a message tags, and the chat tickets that carry those conversations."""
from __future__ import annotations

import os
import re
import time

from .model import Agent, slug
from .tickets import Ticket, TicketError, add_message, editing, list_tickets, new_ticket, set_status
from .vault import Vault

# '@' not preceded by a letter, digit, '.', '@' or '/', so emails and URL paths aren't tags.
_TAG = re.compile(r"(?<![\w.@/])@([A-Za-z][\w-]*)")
CONTINUABLE = ("blocked", "in-review")  # a chat whose agent has answered (or is waiting for an OK)
STALE_HOURS = 12
_BRON_CLOSES = (" · bron: status → done: chat ended", f" · bron: status → done: chat ended (no activity for {STALE_HOURS} hours)")
TITLE_MAX = 60


def resumable(ticket: Ticket) -> bool:
    """Answered chats, plus chats Bron itself closed (session end or 12 quiet hours). Chats a person or agent closed stay closed."""
    if ticket.status in CONTINUABLE:
        return True
    return ticket.status == "done" and bool(ticket.thread) and ticket.thread[-1].endswith(_BRON_CLOSES)


class _StaleChat(Exception):
    """Raised when a chat's status changed before we could edit it; prevents saving."""
    pass


def tagged_agents(text: str, agents: dict[str, Agent], self_key: str) -> list[Agent]:
    """Agents tagged in the message, in order, each once; never the session's own agent."""
    found: list[Agent] = []
    for match in _TAG.finditer(text):
        agent = agents.get(slug(match.group(1)))
        if agent is not None and agent.key != self_key and all(a.key != agent.key for a in found):
            found.append(agent)
    return found


def _session_of(ticket: Ticket) -> str:
    return str(ticket.extra_meta.get("chat_session") or "")


def open_chat(vault: Vault, session: str, agent_key: str) -> Ticket | None:
    if not session:
        return None
    tickets, _ = list_tickets(vault)
    for ticket in reversed(tickets):
        if ticket.kind == "chat" and ticket.assignee == agent_key and resumable(ticket) and _session_of(ticket) == session:
            return ticket
    return None


def chat_title(agent: Agent, message: str) -> str:
    title = f"Chat with {agent.name}: {' '.join(message.split())}"
    return title if len(title) <= TITLE_MAX else title[: TITLE_MAX - 1].rstrip() + "…"


def start_chat(vault: Vault, *, agent: Agent, requester: str, session: str, message: str, context: str) -> tuple[Ticket, bool]:
    """Continue this session's open chat with the agent, or start a new one. Returns (ticket, is_follow_up)."""
    existing = open_chat(vault, session, agent.key)
    if existing is not None:
        try:
            with editing(vault, existing.id) as ticket:
                # Re-check status under the ticket's lock: a run may have started it (leave the file untouched).
                if not resumable(ticket):
                    raise _StaleChat
                add_message(ticket, "you", message)
                # Back to todo without a Thread line: `ticket wait` then waits for the new run.
                ticket.status = "todo"
                ticket.invalid.pop("status", None)
            return ticket, True
        except (_StaleChat, TicketError, OSError):
            pass
    ticket = new_ticket(
        vault,
        title=chat_title(agent, message),
        assignee=agent.key,
        request=message,
        requested_by=requester,
        context=context,
        kind="chat",
        extra_meta={"chat_session": session} if session else None,
    )
    return ticket, False


def close_session_chats(vault: Vault, session: str) -> list[str]:
    """When a session ends: its answered chats are done. Chats still running or about to run are left.

    A chat closed here (or by close_stale_chats) is reopened if the same session tags that agent again, since a
    resumed session is the same conversation. Chats closed by the user or an agent stay closed."""
    if not session:
        return []
    closed: list[str] = []
    tickets, _ = list_tickets(vault)
    for ticket in tickets:
        if ticket.kind != "chat" or ticket.status not in CONTINUABLE or _session_of(ticket) != session:
            continue
        try:
            with editing(vault, ticket.id) as current:
                if current.status in CONTINUABLE:
                    set_status(current, "done", "bron", "chat ended")
            closed.append(ticket.id)
        except (TicketError, OSError):
            continue
    return closed


def close_stale_chats(vault: Vault, *, now: float | None = None) -> list[str]:
    """Fallback when a session end was missed: chats untouched for 12 hours are done."""
    cutoff = (time.time() if now is None else now) - STALE_HOURS * 3600
    closed: list[str] = []
    tickets, _ = list_tickets(vault)
    for ticket in tickets:
        if ticket.kind != "chat" or ticket.status not in ("todo", *CONTINUABLE):
            continue
        try:
            if ticket.path.stat().st_mtime >= cutoff:
                continue
            with editing(vault, ticket.id) as current:
                if current.status in ("todo", *CONTINUABLE):
                    set_status(current, "done", "bron", f"chat ended (no activity for {STALE_HOURS} hours)")
            closed.append(ticket.id)
        except (TicketError, OSError):
            continue
    return closed


def route(vault: Vault, *, cli: str, prompt: str, session_id: str, transcript_path: str) -> str:
    """Start every agent the message tags and tell the session's agent what to do ('' when nothing is tagged)."""
    from . import runner
    from .loader import load
    from .transcript import recent_exchanges

    cfg = load(vault)
    self_key = slug(os.environ.get("BRON_AGENT") or cfg.settings.default_agent)
    agents = tagged_agents(prompt, cfg.agents, self_key)
    if not agents:
        return ""
    session = f"{cli}:{session_id}" if session_id else ""
    requester = self_key if self_key in cfg.agents else "you"
    speaker = cfg.agents[self_key].name if self_key in cfg.agents else "Assistant"
    context: str | None = None
    started: list[tuple[Agent, Ticket]] = []
    failed: list[str] = []
    for agent in agents:
        try:
            if context is None and open_chat(vault, session, agent.key) is None:
                context = recent_exchanges(cli, transcript_path, prompt, assistant=speaker)
            ticket, follow_up = start_chat(vault, agent=agent, requester=requester, session=session, message=prompt, context=context or "")
        except (TicketError, OSError) as exc:
            failed.append(f"Couldn't pass the message to @{agent.name} ({exc}); tell the user.")
            continue
        try:
            runner.start_background(vault, ticket.id, caller_cli=cli, resume=follow_up, shown=True)
        except OSError as exc:
            try:
                with editing(vault, ticket.id) as current:
                    set_status(current, "blocked", "runner", f"Bron couldn't start {agent.name} ({exc})")
            except (TicketError, OSError):
                pass
            failed.append(f"Couldn't start @{agent.name} ({exc}); tell the user.")
            continue
        started.append((agent, ticket))
    return routing_note(started, failed)


def routing_note(started: list[tuple[Agent, Ticket]], failed: list[str]) -> str:
    lines: list[str] = []
    if started:
        names = ", ".join(f"@{agent.name}" for agent, _ in started)
        ids = " ".join(ticket.id for _, ticket in started)
        one = len(started) == 1
        lines += [
            f"{names} {'is' if one else 'are'} answering this message (chat {'ticket' if one else 'tickets'} {ids}). Don't answer it yourself.",
            f"Run `.bron/bin/bron ticket wait {ids}` as an ordinary command and wait for it (give it a 10-minute timeout if your command tool takes one). "
            f"Then show each reply word for word, starting with the agent's name in bold, like **{started[0][0].name}:**. "
            "You may add one short note of your own after the replies if it helps.",
            "If a reply says a ticket is blocked with 'Needs your OK', follow the delegate skill. If an agent couldn't run, tell the user plainly what the note says.",
        ]
    lines += failed
    return "\n".join(lines) + "\n" if lines else ""

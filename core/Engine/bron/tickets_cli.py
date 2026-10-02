"""`bron ticket …`: how agents and the user create and update tickets."""
from __future__ import annotations

import sys
from pathlib import Path


def add_parser(sub) -> None:
    parser = sub.add_parser("ticket", help="create and update tickets")
    commands = parser.add_subparsers(dest="ticket_command", required=True)

    new = commands.add_parser("new", help="create a ticket")
    new.add_argument("--to", required=True, help="the agent who should do the work")
    new.add_argument("--title", required=True)
    request = new.add_mutually_exclusive_group(required=True)
    request.add_argument("--request")
    request.add_argument("--request-file")
    context = new.add_mutually_exclusive_group()
    context.add_argument("--context")
    context.add_argument("--context-file")
    new.add_argument("--from", dest="requested_by", default="you")
    new.add_argument("--project", default="")
    new.add_argument("--parent", default="")
    new.add_argument("--priority", default="normal")
    new.add_argument("--due", default="")

    show = commands.add_parser("show", help="print a ticket")
    show.add_argument("id")

    say = commands.add_parser("say", help="add a message to a ticket's thread")
    say.add_argument("id")
    say.add_argument("text")
    say.add_argument("--as", dest="author", default="you")

    status = commands.add_parser("status", help="change a ticket's status")
    status.add_argument("id")
    status.add_argument("status")
    status.add_argument("--as", dest="author", default="you")
    status.add_argument("--note", default="")

    result = commands.add_parser("result", help="record the result and mark the ticket in-review")
    result.add_argument("id")
    given = result.add_mutually_exclusive_group(required=True)
    given.add_argument("--text")
    given.add_argument("--file")
    result.add_argument("--as", dest="author", default="you")

    listing = commands.add_parser("list", help="list tickets")
    listing.add_argument("--for", dest="for_agent", default="")
    listing.add_argument("--open", action="store_true")


def _read(value: str | None, file: str | None) -> str:
    if file:
        return Path(file).read_text(encoding="utf-8")
    return value or ""


def _agent_key(cfg, name: str) -> str:
    from .model import slug
    from .tickets import TicketError

    key = slug(name)
    if key not in cfg.agents:
        names = ", ".join(agent.name for agent in cfg.agents.values())
        raise TicketError(f"There's no agent called '{name}'. Agents: {names}")
    return key


def _author(name: str) -> str:
    from .model import slug

    return "you" if slug(name) in ("", "you") else slug(name)


def handle(args, vault) -> int:
    from .loader import load
    from .model import slug
    from .tickets import (
        OPEN,
        TicketError,
        add_message,
        editing,
        find_ticket,
        list_tickets,
        load_ticket,
        new_ticket,
        save_ticket,
        set_result,
        set_status,
    )

    try:
        command = args.ticket_command
        if command == "new":
            cfg = load(vault)
            assignee = _agent_key(cfg, args.to)
            requester = "you" if slug(args.requested_by) in ("", "you") else _agent_key(cfg, args.requested_by)
            if requester != "you" and assignee not in {slug(a) for a in cfg.agents[requester].can_assign_to}:
                boss, worker = cfg.agents[requester].name, cfg.agents[assignee].name
                raise TicketError(f"{boss} can't hand work to {worker}: add {worker} to {boss}'s can_assign_to first.")
            ticket = new_ticket(
                vault,
                title=args.title,
                assignee=assignee,
                requested_by=requester,
                request=_read(args.request, args.request_file),
                context=_read(args.context, args.context_file),
                project=args.project,
                parent=args.parent,
                priority=args.priority,
                due=args.due,
            )
            print(f"Created {ticket.id}: {ticket.path.relative_to(vault.root)}")
            return 0
        if command == "list":
            tickets, problems = list_tickets(vault)
            wanted = slug(args.for_agent) if args.for_agent else ""
            for ticket in tickets:
                if wanted and ticket.assignee != wanted:
                    continue
                if args.open and ticket.status not in OPEN:
                    continue
                print(f"{ticket.id} [{ticket.status}] {ticket.assignee} — {ticket.title}")
            for problem in problems:
                print(f"! {problem}")
            return 0
        if command == "show":
            ticket = load_ticket(find_ticket(vault, args.id))
            print(ticket.path.read_text(encoding="utf-8"), end="")
            for problem in ticket.problems:
                print(f"! {problem}", file=sys.stderr)
            return 0
        if command == "say":
            with editing(vault, args.id) as ticket:
                add_message(ticket, _author(args.author), args.text)
            for problem in ticket.problems:
                print(f"! {problem}", file=sys.stderr)
            print(f"{ticket.id} is now {ticket.status}.")
            return 0
        if command == "status":
            with editing(vault, args.id) as ticket:
                set_status(ticket, args.status, _author(args.author), args.note)
            for problem in ticket.problems:
                print(f"! {problem}", file=sys.stderr)
            print(f"{ticket.id} is now {ticket.status}.")
            return 0
        if command == "result":
            with editing(vault, args.id) as ticket:
                set_result(ticket, _read(args.text, args.file), _author(args.author))
            for problem in ticket.problems:
                print(f"! {problem}", file=sys.stderr)
            print(f"{ticket.id} is now {ticket.status}.")
            return 0
    except (TicketError, OSError) as exc:
        print(f"bron: {exc}", file=sys.stderr)
        return 1

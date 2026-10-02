"""`bron agent …`, `bron project new`, `bron skill new`, `bron settings set`, `bron connections add`: setup commands."""
from __future__ import annotations

from pathlib import Path

from .model import RUNS_IN


def split_list(text: str | None) -> list[str]:
    return [part.strip() for part in (text or "").split(",") if part.strip()]


def read_file(path: str | None) -> str:
    from .setup import SetupError

    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SetupError(f"Couldn't read {path} ({exc.__class__.__name__}).") from exc


def _preview_flags(parser, *, files: bool = True) -> None:
    parser.add_argument("--preview", action="store_true", help="show what would change, without changing anything")
    if files:
        parser.add_argument("--show-files", action="store_true", help="with --preview: also show the exact file text")


def add_agent_parser(sub) -> None:
    parser = sub.add_parser("agent", help="create, change, rename, retire or bring back a team member")
    commands = parser.add_subparsers(dest="agent_command", required=True)
    create = commands.add_parser("create", help="create a team member")
    create.add_argument("--name", required=True)
    create.add_argument("--role", required=True)
    create.add_argument("--reports-to", default="")
    create.add_argument("--model", action="append", default=[], help="claude=<model>, codex=<model>, or a model name")
    create.add_argument("--runs-in", choices=RUNS_IN, default="")
    create.add_argument("--connections", default="", help="comma-separated connection names")
    create.add_argument("--ask-before", default="", help="comma-separated ask-first entries")
    create.add_argument("--helpers", default=None, help="comma-separated helper names")
    create.add_argument("--instructions-file", default="")
    create.add_argument("--no-defaults", action="store_true", help="don't add the usual ask-first safety entries")
    _preview_flags(create)
    change = commands.add_parser("set", help="change a team member")
    change.add_argument("name")
    change.add_argument("--role")
    change.add_argument("--reports-to")
    change.add_argument("--model", action="append", default=[])
    change.add_argument("--runs-in", choices=RUNS_IN)
    change.add_argument("--add-connection", action="append", default=[])
    change.add_argument("--remove-connection", action="append", default=[])
    change.add_argument("--add-ask", action="append", default=[])
    change.add_argument("--remove-ask", action="append", default=[])
    change.add_argument("--instructions-file", default="")
    change.add_argument("--no-defaults", action="store_true")
    _preview_flags(change)
    rename = commands.add_parser("rename", help="rename a team member (or Bron)")
    rename.add_argument("name")
    rename.add_argument("new_name")
    _preview_flags(rename)
    retire = commands.add_parser("retire", help="retire a team member; its files are archived")
    retire.add_argument("name")
    retire.add_argument("--hand-to", default="", help="who takes over its open work (default: its boss)")
    _preview_flags(retire)
    restore = commands.add_parser("restore", help="bring back a retired team member")
    restore.add_argument("name")
    _preview_flags(restore)


def run_change(vault, build, args) -> int:
    """Build the change; with --preview print its summary, otherwise apply it."""
    from .setup import SetupError, apply, preview

    try:
        change = build()
        if getattr(args, "preview", False):
            for line in preview(vault, change):
                print(line)
            if getattr(args, "show_files", False):
                for path, text in change.writes.items():
                    print(f"\n--- {path}")
                    print(text, end="" if text.endswith("\n") else "\n")
            return 0
        for line in apply(vault, change):
            print(line)
        return 0
    except SetupError as exc:
        print(exc)
        return 1


def handle(args, vault) -> int:
    from . import agent_setup as agents
    from .loader import load

    cfg = load(vault)
    if args.command == "agent":
        if args.agent_command == "create":
            return run_change(vault, lambda: agents.create_agent(
                cfg,
                name=args.name,
                role=args.role,
                reports_to=args.reports_to,
                models=agents.parse_models(cfg, args.model),
                runs_in=args.runs_in,
                connections=split_list(args.connections),
                ask_before=split_list(args.ask_before),
                helpers=None if args.helpers is None else split_list(args.helpers),
                instructions=read_file(args.instructions_file),
                defaults=not args.no_defaults,
            ), args)
        if args.agent_command == "set":
            return run_change(vault, lambda: agents.set_agent(
                cfg,
                args.name,
                role=args.role,
                reports_to=args.reports_to,
                models=agents.parse_models(cfg, args.model),
                runs_in=args.runs_in,
                add_connections=args.add_connection,
                remove_connections=args.remove_connection,
                add_ask=args.add_ask,
                remove_ask=args.remove_ask,
                instructions=read_file(args.instructions_file) or None,
                defaults=not args.no_defaults,
            ), args)
        if args.agent_command == "rename":
            return run_change(vault, lambda: agents.rename_agent(cfg, args.name, args.new_name), args)
        if args.agent_command == "retire":
            return run_change(vault, lambda: agents.retire_agent(cfg, args.name, args.hand_to), args)
        if args.agent_command == "restore":
            return run_change(vault, lambda: agents.restore_agent(cfg, args.name), args)
    raise SystemExit(f"bron: unknown setup command {args.command}")

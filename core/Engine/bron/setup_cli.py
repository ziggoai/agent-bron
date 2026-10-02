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


def add_work_parsers(sub) -> None:
    project = sub.add_parser("project", help="start a project")
    projects = project.add_subparsers(dest="project_command", required=True)
    new = projects.add_parser("new", help="create Projects/<Name>/ with a README")
    new.add_argument("name")
    new.add_argument("--goal", default="")
    _preview_flags(new)
    skill = sub.add_parser("skill", help="save a reusable skill")
    skills = skill.add_subparsers(dest="skill_command", required=True)
    make = skills.add_parser("new", help="create a skill from a written description and steps")
    make.add_argument("name")
    make.add_argument("--description", required=True)
    make.add_argument("--file", required=True, help="the skill's steps, in Markdown")
    make.add_argument("--agent", default="", help="only for this agent")
    _preview_flags(make)
    settings = sub.add_parser("settings", help="change your settings")
    sets = settings.add_subparsers(dest="settings_command", required=True)
    put = sets.add_parser("set", help="change one or more settings")
    put.add_argument("--name")
    put.add_argument("--role")
    put.add_argument("--company")
    put.add_argument("--default-cli")
    put.add_argument("--tone")
    put.add_argument("--preferences")
    _preview_flags(put)


def add_connection_parser(commands) -> None:
    add = commands.add_parser("add", help="add a connector that runs on this Mac or at a web address")
    add.add_argument("--name", required=True)
    add.add_argument("--command", dest="connector_command", default="")
    add.add_argument("--args", default="")
    add.add_argument("--url", default="")
    add.add_argument("--description", default="")
    _preview_flags(add)


def run_change(vault, build, args) -> int:
    """Build the change from the setup as it is now; with --preview print its summary, otherwise apply it."""
    from .setup import SetupError, run

    built = []

    def builder(cfg):
        built.append(build(cfg))
        return built[-1]

    preview = bool(getattr(args, "preview", False))
    try:
        lines = run(vault, builder, preview_only=preview)
    except SetupError as exc:
        print(exc)
        return 1
    for line in lines:
        print(line)
    if preview and getattr(args, "show_files", False):
        for path, text in built[-1].writes.items():
            print(f"\n--- {path}")
            print(text, end="" if text.endswith("\n") else "\n")
    return 0


def handle(args, vault) -> int:
    from . import agent_setup as agents

    if args.command == "agent":
        if args.agent_command == "create":
            return run_change(vault, lambda cfg: agents.create_agent(
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
            return run_change(vault, lambda cfg: agents.set_agent(
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
            return run_change(vault, lambda cfg: agents.rename_agent(cfg, args.name, args.new_name), args)
        if args.agent_command == "retire":
            return run_change(vault, lambda cfg: agents.retire_agent(cfg, args.name, args.hand_to), args)
        if args.agent_command == "restore":
            return run_change(vault, lambda cfg: agents.restore_agent(cfg, args.name), args)
    from . import work_setup as work

    if args.command == "project":
        return run_change(vault, lambda cfg: work.new_project(cfg, args.name, args.goal), args)
    if args.command == "skill":
        return run_change(vault, lambda cfg: work.new_skill(cfg, args.name, args.description, read_file(args.file), args.agent), args)
    if args.command == "settings":
        return run_change(vault, lambda cfg: work.set_settings(
            cfg, user_name=args.name, user_role=args.role, company=args.company, default_cli=args.default_cli, tone=args.tone, preferences=args.preferences,
        ), args)
    if args.command == "connections":
        return run_change(vault, lambda cfg: work.add_connection(
            cfg, name=args.name, command=args.connector_command, args=args.args, url=args.url, description=args.description,
        ), args)
    raise SystemExit(f"bron: unknown setup command {args.command}")

"""The `bron` command."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .hookconfig import HOOK_NAMES
from .model import CLIS


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for bron commands."""
    parser = argparse.ArgumentParser(prog="bron", description="Bron keeps your agents' setup in sync across Claude Code and Codex.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_sync = sub.add_parser("sync", help="regenerate the Claude Code and Codex setup from System/")
    p_sync.add_argument("--dry-run", action="store_true", help="check and report, without writing anything")
    sub.add_parser("check", help="run the health check")
    p_hook = sub.add_parser("hook", help="entry point for the CLIs' automatic triggers")
    p_hook.add_argument("event", choices=HOOK_NAMES)
    p_hook.add_argument("--cli", choices=CLIS, required=True)
    sub.add_parser("version", help="show the framework version")
    p_update = sub.add_parser("update", help="update Bron to the newest release (shows what's new first with --preview)")
    update_mode = p_update.add_mutually_exclusive_group()
    update_mode.add_argument("--preview", action="store_true", help="show what's new without changing anything")
    update_mode.add_argument("--undo", action="store_true", help="go back to the version before the last update")
    p_update.add_argument("--from", dest="from_folder", type=Path, help="update from a Bron project folder instead of GitHub (development)")
    p_after = sub.add_parser("_after-update")
    p_after.add_argument("--previous", required=True)
    p_after.add_argument("--tree", type=Path)
    p_conn = sub.add_parser("connections", help="find connectors set up in Claude Code and Codex, or add one")
    conn_commands = p_conn.add_subparsers(dest="action", required=True)
    conn_commands.add_parser("scan", help="find the connectors set up in Claude Code and Codex")
    p_run = sub.add_parser("run", help="have a ticket's assignee work it")
    p_run.add_argument("id")
    p_run.add_argument("--resume", action="store_true", help="continue the same conversation after new messages")
    when = p_run.add_mutually_exclusive_group()
    when.add_argument("--background", action="store_true", help="start it and return straight away")
    when.add_argument("--wait", action="store_true", help="wait for the answer and print it (you will show it, so it isn't announced again)")
    p_run.add_argument("--caller-cli", choices=CLIS, help="the CLI asking (used when the agent can run in either)")
    p_chat = sub.add_parser("chat", help="open a session as one agent")
    p_chat.add_argument("agent", nargs="?", default="")
    p_chat.add_argument("--cli", choices=CLIS)
    from . import routines_cli, setup_cli, tickets_cli
    from .kb import cli as kb_cli
    from .memory import cli as memory_cli

    tickets_cli.add_parser(sub)
    routines_cli.add_parser(sub)
    memory_cli.add_parser(sub)
    kb_cli.add_parser(sub)
    setup_cli.add_agent_parser(sub)
    setup_cli.add_work_parsers(sub)
    setup_cli.add_connection_parser(conn_commands)
    # The usage line lists the real commands; internal ones (named with a leading _) stay hidden.
    sub.metavar = "{" + ",".join(name for name in sub.choices if not name.startswith("_")) + "}"
    return parser


def main(argv: list[str] | None = None) -> int:
    from . import tickets_cli

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "hook":
        from .hooks import main as hook_main

        return hook_main(args.event, args.cli)

    from .vault import Vault, VaultNotFound

    try:
        vault = Vault.find()
    except VaultNotFound as exc:
        print(f"bron: {exc}", file=sys.stderr)
        return 2
    if args.command == "version":
        print(vault.version())
        return 0
    if args.command == "check":
        return _check(vault)
    if args.command == "update":
        from . import update
        from .releases import select_source

        if args.undo and args.from_folder is not None:
            print("--undo doesn't take --from.")
            return 2
        try:
            code, healed = update.heal(vault)  # an interrupted update is finished first
            if healed:
                print(healed)
            if code != 0:
                return code
            if args.undo:
                code, message = update.undo(vault)
            else:
                source = select_source(vault, args.from_folder)
                code, message = (update.preview if args.preview else update.apply)(vault, source)
        except KeyboardInterrupt as exc:
            if not getattr(exc, "bron_reported", False):  # stopped outside the swap of System/Core
                print("Stopped; nothing was changed.")
            return 130
        print(message)
        return code
    if args.command == "_after-update":
        from .update import finish

        return finish(vault, args.previous, args.tree)
    if args.command == "connections" and args.action == "add":
        from . import setup_cli

        return setup_cli.handle(args, vault)
    if args.command == "connections":
        from .scan import scan
        from .sync import run_sync

        print(scan(vault).render())
        result = run_sync(vault)
        if not result.ok:
            print("The setup couldn't be refreshed yet; run `bron check` for details.")
        return 0
    if args.command == "memory":
        from .memory import cli as memory_cli

        return memory_cli.handle(args, vault)
    if args.command == "kb":
        from .kb import cli as kb_cli

        return kb_cli.handle(args, vault)
    if args.command == "run":
        return _run(vault, args)
    if args.command == "chat":
        return _chat(vault, args.agent, args.cli)
    if args.command == "ticket":
        return tickets_cli.handle(args, vault)
    if args.command == "routine":
        from . import routines_cli

        return routines_cli.handle(args, vault)
    if args.command in ("agent", "project", "skill", "settings"):
        from . import setup_cli

        return setup_cli.handle(args, vault)
    return _sync(vault, dry_run=args.dry_run)


def _run(vault, args) -> int:
    import signal

    from .runner import refusal, run_ticket, start_background
    from .tickets import TicketError, find_ticket, load_ticket

    if args.background:
        try:
            ticket = load_ticket(find_ticket(vault, args.id))
            why = refusal(ticket, args.resume)
            if why:
                print(why)
                return 0
            start_background(vault, args.id, caller_cli=args.caller_cli, resume=args.resume)
        except (TicketError, OSError) as exc:
            print(f"Couldn't start {args.id} in the background ({exc}). Check that .bron/bin/bron exists: run `.bron/bin/bron check`.")
            return 1
        print(f"Started {args.id} in the background. The update will show up in your next message or session.")
        return 0
    # A SIGTERM should unwind through run_ticket so the ticket is never left in-progress.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    outcome = run_ticket(vault, args.id, caller_cli=args.caller_cli, resume=args.resume, shown=args.wait)
    print(outcome.message)
    return 1 if outcome.status == "error" else 0


def _print_issues(vault, issues) -> None:
    for issue in issues:
        print("  " + issue.render(vault.root))


def _check(vault) -> int:
    from .check import has_errors, run_checks
    from .loader import load
    from .model import Issue
    from .sync import drift_issues, output_issues, plan_files

    cfg = load(vault)
    issues = run_checks(cfg)
    if not has_errors(issues):
        try:
            issues += output_issues(plan_files(cfg))
        except (OSError, KeyError, ValueError) as exc:
            issues.append(Issue("error", "sync.failed", f"Bron couldn't build the CLI setup ({exc.__class__.__name__}: {exc})"))
    issues += drift_issues(vault)
    if not issues:
        print("Bron health check: all good.")
        return 0
    errors = sum(issue.level == "error" for issue in issues)
    print(f"Bron health check: {errors} problem(s), {len(issues) - errors} warning(s)")
    _print_issues(vault, issues)
    return 1 if errors else 0


def _sync(vault, *, dry_run: bool) -> int:
    from .sync import run_sync

    result = run_sync(vault, dry_run=dry_run)
    if not result.ok:
        print("Sync stopped. Fix these first; your last working setup is still in place:")
        _print_issues(vault, result.issues)
        return 1
    if dry_run:
        print("Dry run: the setup is valid and would be regenerated.")
    else:
        report = result.report
        print(f"Synced: {len(report.written)} file(s) written, {len(report.deleted)} removed.")
        if report.backup_dir:
            print(f"Hand-edited files were backed up to {report.backup_dir.relative_to(vault.root)}.")
    _print_issues(vault, result.issues)
    return 0


def _chat(vault, name: str, cli: str | None) -> int:
    import os
    import shutil

    from .launch import chat_spec
    from .loader import load
    from .model import CLI_NAMES, slug
    from .sync import needs_sync, run_sync

    cfg = load(vault)
    key = slug(name) if name else (cfg.default_agent.key if cfg.default_agent else "")
    agent = cfg.agents.get(key)
    if agent is None:
        if key:
            names = ", ".join(a.name for a in cfg.agents.values())
            print(f"bron: There's no agent called '{name}'. Agents: {names}")
        else:
            if cfg.agents:
                names = ", ".join(a.name for a in cfg.agents.values())
                print(f"bron: No default agent is set in System/Settings.md. Agents: {names}")
            else:
                print("bron: No agents are set up yet.")
        return 1
    pinned = agent.runs_in if agent.runs_in in CLIS else None
    if cli and pinned and cli != pinned:
        print(f"bron: {agent.name} only runs in {CLI_NAMES[pinned]}.")
        return 1
    chosen = cli or pinned or cfg.settings.default_cli
    if shutil.which(chosen) is None:
        print(f"bron: {CLI_NAMES[chosen]} isn't installed on this Mac.")
        return 1
    if needs_sync(vault):
        result = run_sync(vault)
        if not result.ok:
            print(f"bron: Bron's setup has problems, so {agent.name} can't start; run `.bron/bin/bron check`.")
            return 1
    spec = chat_spec(cfg, agent, chosen)
    os.chdir(vault.root)
    try:
        os.execvpe(spec.argv[0], spec.argv, {**os.environ, **spec.env})
    except OSError as exc:
        print(f"bron: Couldn't start {CLI_NAMES[chosen]} ({exc}).")
        return 1
    return 0  # not reached

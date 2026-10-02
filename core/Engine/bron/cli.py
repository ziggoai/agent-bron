"""The `bron` command."""
from __future__ import annotations

import argparse
import sys

from .hookconfig import HOOK_NAMES
from .model import CLIS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bron", description="Bron keeps your agents' setup in sync across Claude Code and Codex.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_sync = sub.add_parser("sync", help="regenerate the Claude Code and Codex setup from System/")
    p_sync.add_argument("--dry-run", action="store_true", help="check and report, without writing anything")
    sub.add_parser("check", help="run the health check")
    p_hook = sub.add_parser("hook", help="entry point for the CLIs' automatic triggers")
    p_hook.add_argument("event", choices=HOOK_NAMES)
    p_hook.add_argument("--cli", choices=CLIS, required=True)
    sub.add_parser("version", help="show the framework version")
    sub.add_parser("update", help="update the framework from the Bron project this vault came from")
    p_conn = sub.add_parser("connections", help="find the connectors set up in Claude Code and Codex")
    p_conn.add_argument("action", choices=["scan"])
    from . import tickets_cli

    tickets_cli.add_parser(sub)
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
        from .update import run_update

        code, message = run_update(vault)
        print(message)
        return code
    if args.command == "connections":
        from .scan import scan
        from .sync import run_sync

        print(scan(vault).render())
        result = run_sync(vault)
        if not result.ok:
            print("The setup couldn't be refreshed yet; run `bron check` for details.")
        return 0
    if args.command == "ticket":
        return tickets_cli.handle(args, vault)
    return _sync(vault, dry_run=args.dry_run)


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

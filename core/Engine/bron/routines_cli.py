"""`bron routine …`: look after repeating work."""
from __future__ import annotations

from pathlib import Path

from . import frontmatter as fm


def add_parser(sub) -> None:
    parser = sub.add_parser("routine", help="routines: repeating work tracked per period")
    commands = parser.add_subparsers(dest="routine_command", required=True)
    commands.add_parser("list", help="each routine's periods, progress and due dates")
    start = commands.add_parser("start", help="start a period: create its folder and Tracking note")
    start.add_argument("name")
    start.add_argument("--period", default="")
    start.add_argument("--list", dest="lists", action="append", default=[], metavar="NAME=FILE")
    refresh = commands.add_parser("refresh", help="recount progress in the Tracking notes")
    refresh.add_argument("name", nargs="?", default="")


def handle(args, vault) -> int:
    from . import routines

    runbooks, issues = routines.load_runbooks(vault)
    try:
        if args.routine_command == "list":
            if not runbooks and not issues:
                print("No routines yet. Each routine is a folder in Routines/ with a Runbook.md.")
            for line in routines.status_lines(runbooks, routines.today()):
                print(line)
            for issue in issues:
                print("  " + issue.render(vault.root))
            return 0
        if args.routine_command == "refresh":
            chosen = [routines.find_runbook(runbooks, args.name)] if args.name else runbooks
            for runbook in chosen:
                for path in routines.tracking_notes(runbook):
                    try:
                        state = routines.refresh_tracking(path, runbook)
                    except (fm.FrontmatterError, OSError, UnicodeDecodeError):
                        print(f"{runbook.name} {path.parent.name}: its Tracking note can't be read (Routines/{runbook.folder.name}/{path.parent.name}/{routines.TRACKING})")
                        continue
                    print(f"{runbook.name} {path.parent.name} [{state.status}] {state.progress}")
            return 0
        runbook = routines.find_runbook(runbooks, args.name)
        period = args.period.strip() or routines.last_ended(runbook.cadence, routines.today())
        lists = {}
        for spec in args.lists:
            name, sep, file = spec.partition("=")
            if not sep or not name.strip() or not file.strip():
                raise routines.RoutineError(f"--list needs NAME=FILE, like companies=companies.txt (got '{spec}')")
            raw = Path(file.strip()).read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1")
            lists[name.strip()] = routines.parse_list_items(text)
        path = routines.start_period(vault, runbook, period, lists)
    except routines.RoutineError as exc:
        print(exc)
        return 1
    except OSError as exc:
        print(f"Couldn't read a list file ({exc})")
        return 1
    print(f"Started {runbook.name} {period}: {path.relative_to(vault.root)}")
    return 0

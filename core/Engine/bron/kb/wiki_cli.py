"""`bron wiki …`: what agents run after writing wiki pages, and the mechanical checks."""
from __future__ import annotations

import time
import traceback

CRASHED = "Something went wrong in the wiki ({}). Details are in .bron/logs/kb-errors.log."


def add_parser(sub) -> None:
    parser = sub.add_parser("wiki", help="the wiki in Knowledge/: finish after writing pages, and check it")
    commands = parser.add_subparsers(dest="wiki_command", required=True)
    done = commands.add_parser("done", help="after writing pages: index them, update index.md and log.md, check them")
    done.add_argument("--log", default="", help="a line for log.md, like 'save | <title>' or 'check | <what you found>'")
    check = commands.add_parser("check", help="links, orphans, missing properties, documents without a page, duplicates")
    check.add_argument("--all", action="store_true", help="list every problem, not just the first three of each kind")


def _log_crash(vault, args, exc: BaseException) -> None:
    try:
        path = vault.bron_dir / "logs" / "kb-errors.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} bron wiki {args.wiki_command}: "
                     f"{''.join(traceback.format_exception(exc))}\n")
    except OSError:
        pass


def handle(args, vault) -> int:
    from .store import KbError

    try:
        if args.wiki_command == "done":
            from . import wiki_done

            print(wiki_done.done(vault, log_text=args.log))
            return 0
        if args.wiki_command == "check":
            from . import wiki_check

            print(wiki_check.render(wiki_check.run(vault), everything=args.all))
            items = wiki_check.review(vault)
            if args.all and items:
                print("\n" + wiki_check.render_review(items, everything=True))
            elif items:
                print("\n`wiki check --all` also lists what's worth a look.")
            return 0
    except KbError as exc:
        print(exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - never a traceback for the user (Ctrl-C still stops it)
        _log_crash(vault, args, exc)
        print(CRASHED.format(exc.__class__.__name__))
        return 1
    print("Not available yet.")
    return 1

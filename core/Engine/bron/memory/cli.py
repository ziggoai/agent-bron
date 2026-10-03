"""`bron memory …`: remember, forget, search, tidy, and the background summarizer."""
from __future__ import annotations

from .facts import SECTIONS


def add_parser(sub) -> None:
    parser = sub.add_parser("memory", help="lasting facts and conversation summaries")
    commands = parser.add_subparsers(dest="memory_command", required=True)
    remember = commands.add_parser("remember", help="save a lasting fact")
    remember.add_argument("text", nargs="?", default="")
    remember.add_argument("--file", default="", help="read the fact from a file (for text with single quotes)")
    remember.add_argument("--as", dest="as_agent", required=True)
    scope = remember.add_mutually_exclusive_group()
    scope.add_argument("--shared", dest="scope", action="store_const", const="shared")
    scope.add_argument("--mine", dest="scope", action="store_const", const="mine")
    remember.add_argument("--section", choices=[key for key, _ in SECTIONS], default="decisions")
    remember.add_argument("--replaces", default="")
    forget = commands.add_parser("forget", help="remove a fact, or a conversation's summary")
    forget.add_argument("text", nargs="?", default="")
    forget.add_argument("--conversation", default="")
    forget.add_argument("--as", dest="as_agent", required=True)
    search = commands.add_parser("search", help="search facts and conversation summaries")
    search.add_argument("query")
    search.add_argument("--as", dest="as_agent", required=True)
    search.add_argument("--all", action="store_true")
    search.add_argument("--limit", type=int, default=8)
    tidy = commands.add_parser("tidy", help="replace a facts file with a reviewed draft")
    tidy.add_argument("--as", dest="as_agent", required=True)
    tidy_scope = tidy.add_mutually_exclusive_group()
    tidy_scope.add_argument("--shared", dest="scope", action="store_const", const="shared")
    tidy_scope.add_argument("--mine", dest="scope", action="store_const", const="mine")
    tidy.add_argument("--file", required=True)
    tidy.add_argument("--preview", action="store_true")
    summarize = commands.add_parser("summarize", help="write conversation summaries (runs in the background)")
    summarize.add_argument("--pending", action="store_true")
    summarize.add_argument("--session", default="")


def handle(args, vault) -> int:
    from ..loader import load
    from . import commands

    cfg = load(vault)
    try:
        if args.memory_command == "remember":
            text = args.text
            if args.file:
                if text.strip():
                    print("Give the fact's words or --file, not both.")
                    return 1
                text = commands.read_text_file(args.file)
            elif not text.strip():
                print("Say what to remember: the fact's words, or --file with a file that holds them.")
                return 1
            print(commands.remember(vault, cfg, as_agent=args.as_agent, text=text, scope=args.scope or "shared",
                                    section=args.section, replaces=args.replaces))
            return 0
        if args.memory_command == "forget":
            has_text = args.text and args.text.strip()
            has_conversation = args.conversation and args.conversation.strip()
            if has_text and has_conversation:
                print("Say either the fact's words or --conversation, not both.")
                return 1
            if has_conversation:
                print(commands.forget_conversation(vault, cfg, as_agent=args.as_agent, query=args.conversation.strip()))
            elif has_text:
                print(commands.forget(vault, cfg, as_agent=args.as_agent, text=args.text.strip()))
            else:
                print("Say what to forget: a fact's words, or --conversation with its title or date.")
                return 1
            return 0
        if args.memory_command == "search":
            from . import index

            hits = index.search(vault, cfg, as_agent=args.as_agent, query=args.query, all_agents=args.all, limit=args.limit)
            print(index.render(hits, vault.root) if hits else f'Nothing in memory matches "{args.query}".')
            return 0
        if args.memory_command == "summarize":
            from . import summaries

            summaries.run(vault, session_id=args.session, pending=args.pending or not args.session)
            return 0
        if args.memory_command == "tidy":
            from ..setup_cli import read_file, run_change
            from ..statefile import locked

            seen: dict = {}

            def build(c):
                return commands.tidy_change(vault, c, as_agent=args.as_agent, scope=args.scope or "shared",
                                            draft=read_file(args.file), preview=args.preview, seen=seen)

            if args.preview:
                code = run_change(vault, build, args)
                if code == 0:
                    commands.save_tidy_preview(vault, seen)
                return code
            # No fact can be saved between the check against the preview and the replacement.
            with locked(vault.state_dir / commands.WRITE_LOCK):
                code = run_change(vault, build, args)
            if code == 0:
                commands.clear_tidy_preview(seen)
            return code
    except commands.MemoryError as exc:
        print(exc)
        return 1
    print("Not available yet.")
    return 1

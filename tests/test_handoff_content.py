import re
import shlex
import yaml

from bron.agents_md import render_agents_md
from bron.cli import build_parser
from bron.loader import load


def test_delegate_and_connections_skills_are_published(vault):
    skills = load(vault).skills
    assert {"delegate", "connections"} <= set(skills)


def test_agents_md_has_the_ticket_protocol_and_stays_small(vault):
    text = render_agents_md(load(vault))
    assert "## Tickets" in text
    assert ".bron/bin/bron ticket" in text
    assert "Needs your OK:" in text
    assert len(text.encode()) < 8 * 1024
    assert "(also in $BRON_TICKET)" in text
    assert "in the environment" not in text


def test_free_text_is_single_quoted_with_a_file_fallback(vault):
    from bron.runner import RESUME_PROMPT, TASK_PROMPT

    texts = {
        "delegate skill": (vault.core_skills / "delegate" / "SKILL.md").read_text(encoding="utf-8"),
        "tickets manual": (vault.core_manual / "tickets.md").read_text(encoding="utf-8"),
        "AGENTS.md": render_agents_md(load(vault)),
        "task prompt": TASK_PROMPT,
        "resume prompt": RESUME_PROMPT,
    }
    for where, text in texts.items():
        for flag in ("--note", "--text", "--request", "--title", "--context"):
            assert f'{flag} "' not in text, f"{where} double-quotes {flag}"
        assert re.search(r'ticket say \S+ (--as \S+ )?"', text) is None, f"{where} double-quotes a ticket say"
    for where in ("delegate skill", "tickets manual", "AGENTS.md", "task prompt"):
        text = texts[where]
        assert "if the text contains a single quote, write it to a file and use `--file` (result) or `--note-file` (status)" in text, where


def test_codex_notes_in_the_skill_and_manual(vault):
    skill = (vault.core_skills / "delegate" / "SKILL.md").read_text(encoding="utf-8")
    assert "if Codex asks for permission to run it outside the sandbox, approve it" in skill
    permissions = (vault.core_manual / "permissions.md").read_text(encoding="utf-8")
    assert "## Codex notes" in permissions and "every agent in Codex" in permissions


def test_tickets_board_is_valid_and_hides_chats(vault):
    board = yaml.safe_load((vault.tickets_dir / "Board.base").read_text(encoding="utf-8"))
    names = [view["name"] for view in board["views"]]
    assert names == ["By status", "By assignee", "Chats"]
    assert 'kind != "chat"' in str(board["views"][0]["filters"])
    assert board["views"][0]["groupBy"]["property"] == "status"


def test_manual_index_links_resolve(vault):
    index = (vault.core_manual / "index.md").read_text(encoding="utf-8")
    for page in ("models.md", "permissions.md", "connections.md", "tickets.md"):
        assert f"]({page})" in index
        assert (vault.core_manual / page).is_file()


def test_quoted_commands_parse(vault):
    """Extract and verify all .bron/bin/bron commands from the documentation."""
    # Collect all command text from the three files
    skill_text = (vault.core_skills / "delegate" / "SKILL.md").read_text(encoding="utf-8")
    manual_text = (vault.core_manual / "tickets.md").read_text(encoding="utf-8")
    agents_text = render_agents_md(load(vault))

    # Find all `.bron/bin/bron` commands
    pattern = r"\.bron/bin/bron\s+[^\n`]+"
    commands = re.findall(pattern, skill_text + "\n" + manual_text + "\n" + agents_text)

    # Normalize and parse each command
    parser = build_parser()
    placeholders = {
        "<ticket id>": "T-0001",
        "<id>": "T-0001",
        "<Agent>": "bron",
        "<you>": "bron",
        "<your name>": "bron",
        "<your key>": "bron",
        "<requester>": "bron",
        "<claude|codex>": "claude",
        "<your-cli>": "claude",
        "<name>": "bron",
        "<agent>": "bron",
        "<status>": "done",
        "<text>": "x",
        "<answer>": "x",
        "<what you did>": "x",
        "<path>": "x",
        "<Project or Routine>": "x",
    }

    for cmd in commands:
        # Remove leading `.bron/bin/bron` and strip whitespace
        normalized = cmd.replace(".bron/bin/bron", "").strip()

        # Remove trailing ellipsis
        normalized = re.sub(r"\s+\.\.\.$", "", normalized)

        # Remove optional parts (contents of brackets)
        normalized = re.sub(r"\s*\[.*?\]\s*", " ", normalized)

        # Remove pipe alternatives
        normalized = re.sub(r"\s+\|.*$", "", normalized)

        # Replace quoted ellipsis and placeholders
        normalized = normalized.replace('"…"', '"x"')
        normalized = normalized.replace('…', 'x')

        # Replace placeholders (in order of specificity: longer first)
        for placeholder, replacement in sorted(placeholders.items(), key=lambda x: -len(x[0])):
            normalized = normalized.replace(placeholder, replacement)

        # Clean up extra spaces
        normalized = " ".join(normalized.split())

        # Split into argv and parse
        try:
            argv = shlex.split(normalized)
            if argv:  # Only parse if there's content
                parser.parse_args(argv)
        except SystemExit:
            raise AssertionError(f"Failed to parse command: {cmd}\nNormalized: {normalized}")
        except Exception as e:
            raise AssertionError(f"Failed to parse command: {cmd}\nNormalized: {normalized}\nError: {e}")


def test_the_delegate_skill_waits_for_the_answer_in_both_clis(vault):
    skill = (vault.core_skills / "delegate" / "SKILL.md").read_text(encoding="utf-8")
    assert "--run --caller-cli <claude|codex>" in skill
    assert "**Quick work" in skill and "run it as an ordinary command and wait" in skill
    assert "`run_in_background: true`" in skill and "Never poll or sleep" in skill
    assert "--resume --wait" in skill
    assert "give the user the answer first" in skill
    rules = render_agents_md(load(vault))
    assert "your final reply becomes its Result" in rules


def test_the_rules_say_when_to_hand_off_and_how_to_ask_quickly(vault):
    rules = render_agents_md(load(vault))
    assert "Hand work to a team member only when it needs their connections, their model or work they own" in rules
    assert "--run --caller-cli <claude|codex>" in rules
    assert "give the user the answer first" in rules
    assert len(rules.encode()) < 8 * 1024

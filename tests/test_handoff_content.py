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

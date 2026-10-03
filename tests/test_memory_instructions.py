"""Every agent may save and forget memory without asking first (0.6.0), in new vaults and after an update."""
import re
from pathlib import Path

import pytest

from bron import migrations
from bron.agent_setup import MEMORY_EXCEPTION, default_instructions
from bron.agents_md import render_agents_md
from bron.loader import load
from bron.migrations import apply_pending
from vaultkit import add_agent

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "template" / "System" / "Agents" / "Bron" / "Agent.md"
OLD_BRON = ("The one exception: when the user tells you their name, role and company, save them straight away with "
            "`.bron/bin/bron settings set` and say so.")
OLD_DEFAULT = "Never change anything in `System/` without showing the user the change first and getting a yes."


def old_bron_text() -> str:
    """Bron's Agent.md as 0.5.0 shipped it: the current template without the memory sentence."""
    return TEMPLATE.read_text(encoding="utf-8").replace(OLD_BRON + " " + MEMORY_EXCEPTION, OLD_BRON)


def migration():
    [found] = [m for m in migrations.MIGRATIONS if m.id == "memory-saves-without-asking"]
    return found


def test_all_three_places_carry_the_memory_exception(vault):
    assert "remember" in MEMORY_EXCEPTION and "forget" in MEMORY_EXCEPTION and "without asking first" in MEMORY_EXCEPTION
    assert MEMORY_EXCEPTION in TEMPLATE.read_text(encoding="utf-8")
    assert MEMORY_EXCEPTION in default_instructions()
    assert OLD_DEFAULT + " " + MEMORY_EXCEPTION in default_instructions()
    rule_1 = re.search(r"^1\. .*$", render_agents_md(load(vault)), re.M).group(0)
    assert "memory" in rule_1 and "forget" in rule_1 and "without asking first" in rule_1


def test_agents_md_memory_rules_cover_mine_preview_and_files(vault):
    text = render_agents_md(load(vault))
    assert "memory tidy --as <your key> [--mine] --file <draft> --preview" in text
    assert "the preview names the file it replaces" in text
    assert "If the fact contains a single quote, write it to a file and use `--file" in text


def test_the_migration_is_registered_for_0_6_0():
    m = migration()
    assert m.version == "0.6.0" and m.summary == "Agents save what you tell them to remember without asking first."
    assert m.summary in (REPO / "CHANGELOG.md").read_text(encoding="utf-8").split("## 0.5.0")[0]


def test_old_bron_and_default_agents_get_the_exception(vault):
    bron = vault.agents_dir / "Bron" / "Agent.md"
    bron.write_text(old_bron_text(), encoding="utf-8")
    cfo = add_agent(vault, "CFO")
    head = cfo.read_bytes().split(b"Instructions for CFO.")[0]
    cfo.write_bytes(head + ("# Boundaries\n- " + OLD_DEFAULT + "\n- Ask before anything.\n").encode("utf-8"))
    lines = apply_pending(vault, "0.5.0", "0.6.0")
    assert bron.read_text(encoding="utf-8") == TEMPLATE.read_text(encoding="utf-8")
    assert cfo.read_bytes() == head + ("# Boundaries\n- " + OLD_DEFAULT + " " + MEMORY_EXCEPTION + "\n- Ask before anything.\n").encode("utf-8")
    assert lines and all(line.strip() for line in lines)
    assert any("remember" in line for line in lines)


def test_frontmatter_and_line_endings_are_kept(vault):
    bron = vault.agents_dir / "Bron" / "Agent.md"
    crlf = old_bron_text().replace("\n", "\r\n").encode("utf-8")
    bron.write_bytes(crlf)
    change = migration().build(load(vault))
    new = change.writes["System/Agents/Bron/Agent.md"].encode("utf-8")
    assert new == crlf.replace(OLD_BRON.encode(), (OLD_BRON + " " + MEMORY_EXCEPTION).encode())
    end = crlf.index(b"---\r\n", 4)
    assert new[:end] == crlf[:end]


def test_an_edited_sentence_is_left_alone(vault):
    bron = vault.agents_dir / "Bron" / "Agent.md"
    edited = old_bron_text().replace(OLD_BRON, OLD_BRON.replace("and say so.", "and tell me."))
    bron.write_text(edited, encoding="utf-8")
    cfo = add_agent(vault, "CFO")
    cfo.write_text(cfo.read_text().replace("Instructions for CFO.", "- " + OLD_DEFAULT + " Even memory."), encoding="utf-8")
    before = cfo.read_bytes()
    assert apply_pending(vault, "0.5.0", "0.6.0") == []
    assert bron.read_text(encoding="utf-8") == edited and cfo.read_bytes() == before


def test_running_twice_changes_nothing(vault):
    (vault.agents_dir / "Bron" / "Agent.md").write_text(old_bron_text(), encoding="utf-8")
    assert migration().build(load(vault)).writes
    apply_pending(vault, "0.5.0", "0.6.0")
    after = (vault.agents_dir / "Bron" / "Agent.md").read_bytes()
    change = migration().build(load(vault))
    assert change.writes == {} and change.summary == [] and change.done == ""
    (vault.state_dir / "migrations.json").unlink()
    assert apply_pending(vault, "0.5.0", "0.6.0") == []
    assert (vault.agents_dir / "Bron" / "Agent.md").read_bytes() == after


def test_nothing_to_do_prints_nothing(vault, capsys):
    assert apply_pending(vault, "0.5.0", "0.6.0") == []


def test_a_retired_agent_gets_it_too(vault):
    archived = vault.system / "Archive" / "Agents" / "Analyst" / "Agent.md"
    archived.parent.mkdir(parents=True)
    archived.write_text("---\nname: Analyst\nrole: Analyst\n---\n# Boundaries\n- " + OLD_DEFAULT + "\n", encoding="utf-8")
    change = migration().build(load(vault))
    assert MEMORY_EXCEPTION in change.writes["System/Archive/Agents/Analyst/Agent.md"]


@pytest.mark.parametrize("blank", ["", "  "])
def test_apply_pending_drops_blank_lines(vault, blank):
    from bron.migrations import Migration
    from bron.setup import Change

    registry = [Migration("quiet", "0.6.0", "Quiet", lambda cfg: Change(done=blank))]
    assert apply_pending(vault, "0.5.0", "0.6.0", registry) == []

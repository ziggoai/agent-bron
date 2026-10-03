import json

from bron.check import run_checks
from bron.loader import load
from bron.memory import commands


def codes(vault):
    return {i.code: i for i in run_checks(load(vault))}


def test_long_facts_file_warns(vault):
    cfg = load(vault)
    for i in range(40):
        commands.remember(vault, cfg, as_agent="Bron", text=f"Fact {i} " + "x" * 90)
    found = codes(vault)
    assert found["memory.long"].level == "warning" and "tidy" in found["memory.long"].message


def test_unreadable_facts_file_is_an_error(vault):
    vault.memory_dir.mkdir(parents=True, exist_ok=True)
    (vault.memory_dir / "Facts.md").write_bytes(b"\xff\xfe\x00bad")
    assert codes(vault)["memory.unreadable"].level == "error"


def test_failed_summaries_warn(vault):
    folder = vault.bron_dir / "memory"
    folder.mkdir(parents=True)
    (folder / "summaries.json").write_text(json.dumps({"s1": {"status": "failed", "attempts": 3}, "s2": {"status": "failed", "attempts": 1}}))
    issue = codes(vault)["memory.summaries-failed"]
    assert issue.level == "warning" and "1 conversation" in issue.message


def test_template_ships_an_empty_shared_facts_file():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "template" / "System" / "Memory" / "Facts.md").read_text()
    for heading in ("## About you", "## Your firm", "## Decisions", "## How you like things done"):
        assert heading in text

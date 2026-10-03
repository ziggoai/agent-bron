import json
import time

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
    now = time.time()
    (folder / "summaries.json").write_text(json.dumps({"s1": {"status": "failed", "attempts": 3, "when": now},
                                                       "s2": {"status": "failed", "attempts": 1, "when": now}}))
    issue = codes(vault)["memory.summaries-failed"]
    assert issue.level == "warning" and "1 conversation" in issue.message


def test_template_ships_an_empty_shared_facts_file():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "template" / "System" / "Memory" / "Facts.md").read_text()
    for heading in ("## About you", "## Your firm", "## Decisions", "## How you like things done"):
        assert heading in text


# ---- final review fixes ----

def test_bad_summary_entries_never_hide_other_memory_issues(vault):
    cfg = load(vault)
    for i in range(40):
        commands.remember(vault, cfg, as_agent="Bron", text=f"Fact {i} " + "x" * 90)
    folder = vault.bron_dir / "memory"
    folder.mkdir(parents=True, exist_ok=True)
    now = time.time()
    (folder / "summaries.json").write_text(json.dumps({
        "bad": {"status": "failed", "attempts": "three", "when": now},
        "worse": {"status": "failed", "attempts": 5, "when": "yesterday"},
        "list": [1, 2],
        "s1": {"status": "failed", "attempts": 3, "when": now},
    }))
    found = codes(vault)
    assert "memory.long" in found and "1 conversation " in found["memory.summaries-failed"].message


def test_only_recent_given_up_summaries_warn(vault):
    folder = vault.bron_dir / "memory"
    folder.mkdir(parents=True)
    old = time.time() - 15 * 86400
    (folder / "summaries.json").write_text(json.dumps({
        "old": {"status": "failed", "attempts": 3, "when": old},
        "undated": {"status": "failed", "attempts": 3},
    }))
    assert "memory.summaries-failed" not in codes(vault)
    state = json.loads((folder / "summaries.json").read_text())
    state["new"] = {"status": "failed", "attempts": 3, "when": time.time() - 13 * 86400}
    (folder / "summaries.json").write_text(json.dumps(state))
    assert "1 conversation " in codes(vault)["memory.summaries-failed"].message


def test_the_old_summary_file_gets_a_notice(vault):
    assert "memory.old-summary" not in codes(vault)
    vault.memory_dir.mkdir(parents=True, exist_ok=True)
    (vault.memory_dir / "Summary.md").write_text("# What Bron knows\n- old notes\n")
    issue = codes(vault)["memory.old-summary"]
    assert issue.level == "warning"
    assert issue.message == "System/Memory/Summary.md is no longer read; ask Bron to move what matters into Facts.md."
    assert issue.path is None

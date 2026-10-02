import pytest

from bron import frontmatter as fm
from bron.agents_md import render_agents_md
from bron.cli import main
from bron.loader import load
from bron.setup import SetupError, apply
from bron.work_setup import add_connection, create_routine, new_project, new_skill, set_settings
from vaultkit import add_agent

DRAFT = """---
cadence: quarterly
owner: bron
due: 45 days after period end
lists:
  funds: [Fund I, Fund II]
steps:
  - name: Collect numbers
    for: funds
  - name: One-pager
    for: funds
    after: [Collect numbers]
---

## How to do each step
Collect, then write.
"""


def test_a_project_gets_its_folder_and_readme(vault):
    change = new_project(load(vault), "Fund III audit", goal="Close the audit by March.")
    assert change.summary == ["New project: Fund III audit.", "Goal: Close the audit by March."]
    apply(vault, change)
    readme = fm.read(vault.projects_dir / "Fund III audit" / "README.md")
    assert readme.meta["status"] == "active" and "## Goal\nClose the audit by March." in readme.body
    with pytest.raises(SetupError, match="already"):
        new_project(load(vault), "fund iii audit")
    with pytest.raises(SetupError):
        new_project(load(vault), "a/b")


def test_a_routine_is_validated_summarised_and_written(vault):
    change = create_routine(load(vault), "LP Reports", DRAFT)
    assert change.summary == [
        "New routine: LP Reports (quarterly), looked after by Bron.",
        "Due: 45 days after period end.",
        "List 'funds': 2 fixed items.",
        "Step 1: Collect numbers, for each of 'funds'.",
        "Step 2: One-pager, for each of 'funds', after Collect numbers.",
    ]
    apply(vault, change)
    assert (vault.routines_dir / "LP Reports" / "Runbook.md").read_text() == DRAFT
    with pytest.raises(SetupError, match="cadence"):
        create_routine(load(vault), "Weekly", DRAFT.replace("quarterly", "weekly"))
    with pytest.raises(SetupError, match="already"):
        create_routine(load(vault), "lp reports", DRAFT)


def test_a_skill_is_shared_or_for_one_agent(vault):
    add_agent(vault, "CFO")
    change = new_skill(load(vault), "lp-report", "Use when preparing the quarterly LP report: steps and checks.", "# LP report\n1. Pull numbers.")
    assert change.summary == ["New skill: lp-report (for every agent).", "Used when: Use when preparing the quarterly LP report: steps and checks."]
    apply(vault, change)
    skill = fm.read(vault.skills_dir / "lp-report" / "SKILL.md")
    assert skill.meta == {"name": "lp-report", "description": "Use when preparing the quarterly LP report: steps and checks."}
    apply(vault, new_skill(load(vault), "close-books", "Closing the books.", "Steps.", agent="cfo"))
    assert (vault.agents_dir / "CFO" / "Skills" / "close-books" / "SKILL.md").is_file()
    assert "cfo-close-books" in load(vault).skills
    for bad in ("LP Report", "x" * 65, "lp_report"):
        with pytest.raises(SetupError, match="lower-case"):
            new_skill(load(vault), bad, "x", "y")
    with pytest.raises(SetupError, match="already"):
        new_skill(load(vault), "lp-report", "x", "y")
    assert "replaces Bron's built-in" in new_skill(load(vault), "check", "My own check.", "y").summary[-1]


def test_a_connection_that_runs_on_the_mac_or_on_the_web(vault):
    change = add_connection(load(vault), name="Time", command="uvx", args="mcp-server-time --local-timezone 'America/Sao_Paulo'")
    assert change.summary[0] == "New connection: Time."
    assert change.summary[1] == "Runs on this Mac: uvx mcp-server-time --local-timezone 'America/Sao_Paulo'."
    apply(vault, change)
    meta = fm.read(vault.connections_dir / "Time.md").meta
    assert meta["type"] == "mcp-stdio" and meta["args"] == ["mcp-server-time", "--local-timezone", "America/Sao_Paulo"]
    assert "time" in load(vault).connections
    apply(vault, add_connection(load(vault), name="Docs", url="https://docs.example.com/mcp"))
    assert fm.read(vault.connections_dir / "Docs.md").meta["type"] == "mcp-http"
    for kwargs in ({"name": "X"}, {"name": "X", "command": "a", "url": "https://b"}, {"name": "X", "url": "ftp://b"}, {"name": "time", "command": "uvx"}):
        with pytest.raises(SetupError):
            add_connection(load(vault), **kwargs)


def test_settings_and_about_the_user(vault):
    change = set_settings(load(vault), user_name="Alex", user_role="Head of Finance", company="Example Capital", tone="brief and direct")
    assert change.summary == ["Update your settings:", "- Your name: Alex", "- Your role: Head of Finance", "- Company: Example Capital", "- Tone: brief and direct"]
    apply(vault, change)
    cfg = load(vault)
    assert cfg.settings.user_role == "Head of Finance" and cfg.settings.tone == "brief and direct"
    rules = render_agents_md(cfg)
    assert "## About the user\n\n- Name: Alex\n- Role: Head of Finance\n- Company: Example Capital\n- Tone: brief and direct\n" in rules
    with pytest.raises(SetupError, match="claude or codex"):
        set_settings(load(vault), default_cli="cursor")
    with pytest.raises(SetupError, match="Nothing to change"):
        set_settings(load(vault), company="Example Capital")


def test_about_the_user_before_onboarding(vault):
    assert "## About the user\n\nNot set up yet: the onboarding skill asks.\n" in render_agents_md(load(vault))


def test_the_commands(vault, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(vault.root)
    draft = tmp_path / "draft.md"
    draft.write_text(DRAFT, encoding="utf-8")
    body = tmp_path / "skill.md"
    body.write_text("Steps.\n", encoding="utf-8")
    assert main(["project", "new", "Fund III audit", "--goal", "Close the audit."]) == 0
    assert main(["routine", "create", "--name", "LP Reports", "--file", str(draft), "--preview"]) == 0
    assert capsys.readouterr().out.splitlines()[-1].startswith("Step 2: One-pager")
    assert main(["routine", "create", "--name", "LP Reports", "--file", str(draft)]) == 0
    assert main(["skill", "new", "lp-report", "--description", "Quarterly LP report.", "--file", str(body)]) == 0
    assert main(["connections", "add", "--name", "Time", "--command", "uvx", "--args", "mcp-server-time"]) == 0
    assert main(["settings", "set", "--name", "Alex", "--company", "Example Capital"]) == 0
    assert fm.read(vault.settings_file).meta["user_name"] == "Alex"
    assert main(["connections", "add", "--name", "Time", "--command", "uvx"]) == 1

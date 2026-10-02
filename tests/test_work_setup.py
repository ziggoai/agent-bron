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
    assert change.summary[1] == "Runs on this Mac. Command: uvx. Arguments: mcp-server-time --local-timezone America/Sao_Paulo."
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
    change = set_settings(load(vault), user_name="Alex", user_role="Finance lead", company="Example Capital", tone="brief and direct")
    assert change.summary == ["Update your settings:", "- Your name: Alex", "- Your role: Finance lead", "- Company: Example Capital", "- Tone: brief and direct"]
    apply(vault, change)
    cfg = load(vault)
    assert cfg.settings.user_role == "Finance lead" and cfg.settings.tone == "brief and direct"
    rules = render_agents_md(cfg)
    assert "## About the user\n\n- Name: Alex\n- Role: Finance lead\n- Company: Example Capital\n- Tone: brief and direct\n" in rules
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


def test_long_names_are_refused_plainly(vault):
    long = "x" * 81
    for build in (lambda: new_project(load(vault), long), lambda: create_routine(load(vault), long, DRAFT), lambda: add_connection(load(vault), name=long, command="uvx")):
        with pytest.raises(SetupError, match="under 80 characters"):
            build()
    with pytest.raises(SetupError):
        add_connection(load(vault), name=".hidden", command="uvx")
    new_project(load(vault), "y" * 80)


def test_settings_have_length_limits_and_agents_md_stays_small(vault):
    with pytest.raises(SetupError, match="Keep Preferences under 400 characters"):
        set_settings(load(vault), preferences="p" * 401)
    with pytest.raises(SetupError, match="Keep Your name under 100 characters"):
        set_settings(load(vault), user_name="n" * 101)
    apply(vault, set_settings(load(vault), user_name="n" * 100, user_role="r" * 100, company="c" * 100, tone="t" * 400, preferences="p" * 400))
    assert len(render_agents_md(load(vault)).encode()) < 8 * 1024


@pytest.mark.parametrize("kwargs", [
    {"url": "https://docs.example.com/mcp?api_key=abc"},
    {"url": "https://user:pw@docs.example.com/mcp"},
    {"command": "uvx", "args": "tool --api-key abc123"},
    {"command": "uvx", "args": "tool --token=abc123"},
    {"command": "uvx", "args": "tool TOKEN=abc123"},
    {"command": "uvx", "args": "tool sk-abcdef123456"},
    {"command": "uvx", "args": "tool ghp_abcdef"},
])
def test_secrets_are_never_written(vault, kwargs):
    with pytest.raises(SetupError, match="looks like a password or key") as err:
        add_connection(load(vault), name="Secretive", **kwargs)
    assert "abc" not in str(err.value)


def test_settings_file_missing_is_plain(vault):
    cfg = load(vault)
    vault.settings_file.unlink()
    with pytest.raises(SetupError, match="missing"):
        set_settings(cfg, company="Example Capital")


def test_web_address_message_mentions_both(vault):
    with pytest.raises(SetupError, match=r"https:// or http://"):
        add_connection(load(vault), name="X", url="ftp://b")


@pytest.mark.parametrize("args", [
    "tool --auth-token abc123",
    "tool --access-token=abc123",
    "tool --client-secret abc123",
    "tool --github-token abc123",
    "tool --api-key abc123",
    "tool --api_key=abc123",
    "tool --apikey abc123",
    "tool --key abc123",
    "tool --db-password abc123",
    "tool --header 'Authorization: Bearer abc123'",
    "tool --header 'authorization:abc123'",
    "tool 'Bearer abc123'",
    "tool bearer abc123",
])
def test_common_secret_forms_are_refused(vault, args):
    with pytest.raises(SetupError, match="looks like a password or key") as err:
        add_connection(load(vault), name="Secretive", command="uvx", args=args)
    assert "abc" not in str(err.value)


@pytest.mark.parametrize("args", ["tool --keyboard us", "tool --key-file /a", "tool --max-tokens 5", "tool --local-timezone America/Sao_Paulo", "tool --token"])
def test_harmless_flags_are_accepted(vault, args):
    add_connection(load(vault), name="Harmless", command="uvx", args=args)


def test_a_command_with_spaces_is_split(vault):
    apply(vault, add_connection(load(vault), name="Foo", command="npx -y foo", args="--bar 'a b'"))
    meta = fm.read(vault.connections_dir / "Foo.md").meta
    assert meta["command"] == "npx" and meta["args"] == ["-y", "foo", "--bar", "a b"]
    with pytest.raises(SetupError, match="looks like a password or key"):
        add_connection(load(vault), name="Bar", command="npx -y foo --token abc123")


@pytest.mark.parametrize("owner", ["you", "Ghost"])
def test_a_routine_for_you_or_an_unknown_owner_is_looked_after_by_the_main_agent(vault, owner):
    change = create_routine(load(vault), "LP Reports", DRAFT.replace("owner: bron", f"owner: {owner}"))
    assert change.summary[0] == "New routine: LP Reports (quarterly), looked after by Bron (the main agent)."


def test_show_files_on_settings_and_routines(vault, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(vault.root)
    draft = tmp_path / "draft.md"
    draft.write_text(DRAFT, encoding="utf-8")
    assert main(["settings", "set", "--tone", "brief", "--preview", "--show-files"]) == 0
    out = capsys.readouterr().out
    assert "--- System/Settings.md" in out and "tone: brief" in out
    assert main(["routine", "create", "--name", "LP Reports", "--file", str(draft), "--preview", "--show-files"]) == 0
    out = capsys.readouterr().out
    assert "--- Routines/LP Reports/Runbook.md" in out and "cadence: quarterly" in out
    assert not (vault.routines_dir / "LP Reports").exists() and fm.read(vault.settings_file).meta.get("tone") != "brief"


@pytest.mark.parametrize("args", [
    "tool --accessToken abc123",
    "tool --clientSecret=abc123",
    "tool --authToken abc123",
    "tool --githubToken abc123",
    "tool --apiKey abc123",
    "tool --apiKey=abc123",
    "tool --header 'X-API-Key: abc123'",
    "tool --header 'x-apikey: abc123'",
    "tool --header 'X-Auth-Token: abc123'",
    "tool --header=\"X-Secret: abc123\"",
    "tool --env=MY_API_KEY=abc123",
    "tool --env MY_TOKEN=abc123",
    "tool DB_PASSWORD=abc123",
    "tool --SECRET_KEY=abc123",
    "tool --ssh-key abc123",
    "tool --public-key abc123",
])
def test_more_secret_forms_are_refused(vault, args):
    with pytest.raises(SetupError, match="looks like a password or key") as err:
        add_connection(load(vault), name="Secretive", command="uvx", args=args)
    assert "abc" not in str(err.value)


@pytest.mark.parametrize("args", [
    "tool --token-file /a/token.txt",
    "tool --secret-name my-secret",
    "tool --auth-scheme basic",
    "tool --key-id 42",
    "tool --tokenPath /a",
    "tool --public-key /home/me/key.pub",
    "tool --ssh-key ~/.ssh/id_ed25519",
    "tool --private-key=./id_rsa",
    "tool --sort-key name",
    "tool --header 'Accept: application/json'",
    "tool --env=MODE=fast",
])
def test_more_harmless_forms_are_accepted(vault, args):
    add_connection(load(vault), name="Harmless", command="uvx", args=args)


def test_a_command_path_with_spaces_is_kept_whole(vault, tmp_path):
    tool = tmp_path / "My Tool.app" / "bin" / "server"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    change = add_connection(load(vault), name="Spacey", command=str(tool), args="--port 80")
    apply(vault, change)
    meta = fm.read(vault.connections_dir / "Spacey.md").meta
    assert meta["command"] == str(tool) and meta["args"] == ["--port", "80"]
    assert f"Command: {tool}" in "\n".join(change.summary) and "Arguments: --port 80" in "\n".join(change.summary)
    # a path that doesn't exist is split on spaces, as before
    other = add_connection(load(vault), name="Spacey2", command=str(tmp_path / "Not There" / "server"))
    apply(vault, other)
    assert fm.read(vault.connections_dir / "Spacey2.md").meta["command"] == str(tmp_path / "Not")

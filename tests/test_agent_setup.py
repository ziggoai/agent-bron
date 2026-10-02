import pytest

from bron import frontmatter as fm
from bron.agent_setup import create_agent, parse_models, safety_defaults, set_agent
from bron.cli import main
from bron.loader import load
from bron.setup import SetupError, apply
from vaultkit import add_agent, add_connection


def native(vault, name, **ids):
    add_connection(vault, name, type="native", **ids)


@pytest.fixture
def team(vault):
    native(vault, "Gmail", claude="claude_ai_Gmail", codex="gmail")
    native(vault, "Google Drive", claude="claude_ai_Google_Drive")
    native(vault, "Carta", claude="claude_ai_Carta", codex="carta")
    return vault


def meta(vault, name):
    return fm.read(vault.agents_dir / name / "Agent.md").meta


def test_create_infers_the_app_reports_to_bron_and_adds_safety_defaults(team):
    change = create_agent(load(team), name="COO", role="Chief Operating Officer", models=parse_models(load(team), ["Opus 5.5"]), connections=["google drive", "Carta"])
    assert change.summary == [
        "New agent: COO (Chief Operating Officer).",
        "Runs in Claude Code on Opus 5.5.",
        "Reports to Bron. Bron can hand it work.",
        "Can use: Google Drive, Carta.",
        "Asks you before: deleting files, pushing to git, sharing files.",
    ]
    apply(team, change)
    coo = meta(team, "COO")
    assert coo["runs_in"] == "claude" and coo["models"] == {"claude": "Opus 5.5"}
    assert coo["reports_to"] == "Bron" and coo["connections"] == ["Google Drive", "Carta"]
    assert coo["ask_before"] == ["delete-files", "git-push", "share-file"]
    assert coo["helpers"] == ["reader", "researcher", "reviewer"] and coo["can_assign_to"] == [] and coo["always_allow"] == []
    assert "COO" in meta(team, "Bron")["can_assign_to"]
    assert (team.agents_dir / "COO" / "Memory").is_dir()
    assert "# Who you are" in fm.read(team.agents_dir / "COO" / "Agent.md").body
    assert (team.root / ".claude" / "agents" / "coo.md").is_file()


def test_a_gpt_model_pins_codex_and_no_model_means_any(team):
    cfg = load(team)
    assert parse_models(cfg, ["gpt-6.1-sol"]) == {"codex": "gpt-6.1-sol"}
    assert parse_models(cfg, ["claude=sonnet-5.5", "codex=default"]) == {"claude": "sonnet-5.5", "codex": "default"}
    with pytest.raises(SetupError, match="which app"):
        parse_models(cfg, ["mystery-model"])
    change = create_agent(cfg, name="CCO", role="Chief Compliance Officer")
    assert change.summary[1] == "Runs in whichever app hands it work (Claude Code: its default model; Codex: its default model)."


def test_safety_defaults_follow_the_connections(team):
    cfg = load(team)
    assert safety_defaults(cfg, []) == ["delete-files", "git-push"]
    assert safety_defaults(cfg, ["Gmail"]) == ["delete-files", "git-push", "send-email"]
    assert safety_defaults(cfg, ["Carta"]) == ["delete-files", "git-push"]
    change = create_agent(cfg, name="Ops", role="Operations", connections=["Gmail"], defaults=False, ask_before=["shell:curl"])
    assert change.summary[-1] == "Asks you before: running `curl`."


def test_names_with_spaces_and_accents_work_and_unsafe_ones_are_refused(team):
    cfg = load(team)
    assert create_agent(cfg, name="Finanças", role="Finance").summary[0] == "New agent: Finanças (Finance)."
    assert create_agent(cfg, name="Chief  Finance", role="Finance").summary[0] == "New agent: Chief Finance (Finance)."
    for bad in ("a/b", "Head: Finance", ".hidden", "you", "Bron", "reader", "   "):
        with pytest.raises(SetupError):
            create_agent(cfg, name=bad, role="x")


def test_unknown_connections_bosses_and_helpers_are_refused(team):
    cfg = load(team)
    with pytest.raises(SetupError, match="Connections: Carta, Gmail, Google Drive"):
        create_agent(cfg, name="COO", role="x", connections=["Notion"])
    with pytest.raises(SetupError, match="no such agent"):
        create_agent(cfg, name="COO", role="x", reports_to="Ghost")
    with pytest.raises(SetupError, match="helper"):
        create_agent(cfg, name="COO", role="x", helpers=["nobody"])


def test_set_changes_only_what_was_asked_and_keeps_hand_edits(team):
    add_agent(team, "CFO", runs_in="claude", connections=["Carta"], models={"claude": "default"})
    path = team.agents_dir / "CFO" / "Agent.md"
    path.write_text(path.read_text().replace("name: CFO\n", "name: CFO\n# written by hand\n"), encoding="utf-8")
    change = set_agent(load(team), "cfo", models=parse_models(load(team), ["gpt-6.1-sol"]), add_connections=["Gmail"])
    assert change.summary == [
        "Change CFO:",
        "- Model: Codex gpt-6.1-sol.",
        "- Runs in Codex.",
        "- Can now use: Gmail.",
        "- Asks you before: deleting files, pushing to git, sending email.",
    ]
    apply(team, change)
    cfo = meta(team, "CFO")
    assert cfo["runs_in"] == "codex" and cfo["models"] == {"claude": "default", "codex": "gpt-6.1-sol"}
    assert cfo["connections"] == ["Carta", "Gmail"] and cfo["ask_before"] == ["delete-files", "git-push", "send-email"]
    assert "# written by hand\n" in path.read_text() and "Instructions for CFO." in path.read_text()


def test_set_moves_the_agent_between_bosses_and_can_replace_instructions(team):
    add_agent(team, "CFO")
    add_agent(team, "COO")
    apply(team, create_agent(load(team), name="Analyst", role="Analyst", reports_to="CFO"))
    assert meta(team, "CFO")["can_assign_to"] == ["Analyst"]
    apply(team, set_agent(load(team), "Analyst", reports_to="COO", instructions="# Who you are\nAn analyst."))
    assert meta(team, "CFO")["can_assign_to"] == [] and meta(team, "COO")["can_assign_to"] == ["Analyst"]
    assert fm.read(team.agents_dir / "Analyst" / "Agent.md").body.strip() == "# Who you are\nAn analyst."
    with pytest.raises(SetupError, match="Nothing to change"):
        set_agent(load(team), "Analyst", reports_to="COO")


def test_an_unusual_hand_edited_boss_file_is_a_plain_error(team):
    path = team.agents_dir / "Bron" / "Agent.md"
    text = path.read_text(encoding="utf-8")
    assert "can_assign_to:" in text
    path.write_text(text.replace("can_assign_to:", "? can_assign_to\n:", 1), encoding="utf-8")
    with pytest.raises(SetupError, match="Bron couldn't update System/Agents/Bron/Agent.md"):
        create_agent(load(team), name="COO", role="Chief Operating Officer")


def test_the_agent_command(team, monkeypatch, capsys, tmp_path):
    monkeypatch.chdir(team.root)
    assert main(["agent", "create", "--name", "COO", "--role", "Chief Operating Officer", "--model", "opus-5.5", "--connections", "Google Drive", "--preview"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("New agent: COO (Chief Operating Officer).") and not (team.agents_dir / "COO").exists()
    assert main(["agent", "create", "--name", "COO", "--role", "Chief Operating Officer", "--preview", "--show-files"]) == 0
    assert "--- System/Agents/COO/Agent.md" in capsys.readouterr().out
    assert main(["agent", "create", "--name", "COO", "--role", "Chief Operating Officer"]) == 0
    assert capsys.readouterr().out == "Created COO. Say hi with @coo.\n"
    body = tmp_path / "body.md"
    body.write_text("# Who you are\nThe COO.\n", encoding="utf-8")
    assert main(["agent", "set", "COO", "--add-ask", "shell:curl", "--instructions-file", str(body)]) == 0
    assert meta(team, "COO")["ask_before"][-1] == "shell:curl"
    assert main(["agent", "create", "--name", "COO", "--role", "x"]) == 1
    assert "already an agent called COO" in capsys.readouterr().out

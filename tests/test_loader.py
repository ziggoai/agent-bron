from bron.loader import load
from bron.model import conn_key, slug
from vaultkit import add_agent, add_connection, write_md


def test_template_loads_cleanly(vault):
    cfg = load(vault)
    assert cfg.issues == []
    assert list(cfg.agents) == ["bron"]
    assert cfg.default_agent.name == "Bron"
    assert cfg.default_agent.models == {"claude": "default", "codex": "default"}
    assert set(cfg.helpers) == {"reader", "researcher", "reviewer"}
    assert cfg.helpers["reader"].read_only is True
    assert "check" in cfg.skills


def test_keys_handle_spaces_case_and_accents():
    assert slug("Chief Finance") == "chief-finance"
    assert slug("Contábil") == "contabil"
    assert conn_key("Google Drive") == "google_drive"
    assert conn_key("google-drive") == "google_drive"


def test_broken_yaml_is_reported_not_raised(vault):
    (vault.agents_dir / "CFO").mkdir()
    (vault.agents_dir / "CFO" / "Agent.md").write_text("---\nname: [CFO\n---\n", encoding="utf-8")
    cfg = load(vault)
    assert "cfo" not in cfg.agents
    assert any(i.code == "file.unreadable" and i.path.parent.name == "CFO" for i in cfg.issues)


def test_agent_file_without_frontmatter_reports_missing_fields(vault):
    (vault.agents_dir / "CFO").mkdir()
    (vault.agents_dir / "CFO" / "Agent.md").write_text("Just some notes\n", encoding="utf-8")
    cfg = load(vault)
    assert any(i.code == "field.missing" and "'name'" in i.message for i in cfg.issues)


def test_folder_without_agent_file_is_reported(vault):
    (vault.agents_dir / "COO").mkdir()
    assert any(i.code == "agent.file-missing" for i in load(vault).issues)


def test_plain_text_lists_are_accepted(vault):
    add_agent(vault, "CFO", connections="carta, google-drive", helpers="reader")
    agent = load(vault).agents["cfo"]
    assert agent.connections == ["carta", "google-drive"]
    assert agent.helpers == ["reader"]


def test_wrong_types_become_friendly_problems(vault):
    add_agent(vault, "CFO", helpers={"a": 1}, runs_in="gpt", models={"gemini": "x"})
    cfg = load(vault)
    messages = [i.message for i in cfg.issues if i.path and i.path.parent.name == "CFO"]
    assert any("should be a list" in m for m in messages)
    assert any("runs_in" in m for m in messages)
    assert any("only takes 'claude' and 'codex'" in m for m in messages)
    assert cfg.agents["cfo"].runs_in == "any"


def test_name_must_match_folder(vault):
    path = add_agent(vault, "CFO")
    write_md(path, {"name": "Finance", "role": "x", "reports_to": "Bron"})
    assert any(i.code == "agent.name-mismatch" for i in load(vault).issues)


def test_names_that_collide_after_normalising_are_rejected(vault):
    add_agent(vault, "Chief Finance")
    add_agent(vault, "Chief-Finance")
    cfg = load(vault)
    assert any(i.code == "agent.duplicate" for i in cfg.issues)
    assert list(cfg.agents).count("chief-finance") == 1


def test_user_helper_replaces_core_helper(vault):
    write_md(vault.helpers_dir / "reader.md", {"name": "reader", "description": "My reader"}, "Mine.\n")
    helper = load(vault).helpers["reader"]
    assert helper.source == "user"
    assert helper.description == "My reader"


def test_user_skill_replaces_core_and_agent_skills_are_prefixed(vault):
    write_md(vault.skills_dir / "check" / "SKILL.md", {"name": "check", "description": "My check"}, "x\n")
    write_md(vault.agents_dir / "Bron" / "Skills" / "brief" / "SKILL.md", {"name": "brief", "description": "Daily brief"}, "x\n")
    cfg = load(vault)
    assert cfg.skills["check"].source == "user"
    skill = cfg.skills["bron-brief"]
    assert skill.rewrite is True
    assert skill.description == "(For Bron only) Daily brief"


def test_bad_skill_name_is_an_error(vault):
    write_md(vault.skills_dir / "My Skill" / "SKILL.md", {"name": "My Skill", "description": "x"})
    assert any(i.code == "skill.bad-name" for i in load(vault).issues)


def test_connections_load_with_keys(vault):
    add_connection(vault, "Google Drive", args="--port 9 --verbose")
    conn = load(vault).connections["google_drive"]
    assert conn.command == "uvx"
    assert conn.args == ["--port", "9", "--verbose"]


def test_http_connection_needs_a_url(vault):
    write_md(vault.connections_dir / "x.md", {"name": "x", "type": "mcp-http"})
    assert any("'url' is missing" in i.message for i in load(vault).issues)


def test_missing_settings_is_an_error_with_safe_defaults(vault):
    vault.settings_file.unlink()
    cfg = load(vault)
    assert any(i.code == "settings.missing" for i in cfg.issues)
    assert cfg.settings.default_agent == "Bron"
    assert cfg.settings.max_parallel == 3


def test_unclosed_quote_in_args_is_a_problem_not_a_crash(vault):
    add_connection(vault, "Broken", args="--name 'foo")
    cfg = load(vault)
    assert cfg is not None  # load() returns successfully, doesn't crash
    assert any(i.code == "field.type" and "unclosed quote" in i.message for i in cfg.issues)
    assert cfg.connections["broken"].args == []


def test_connection_name_without_letters_is_bad_name(vault):
    from vaultkit import add_connection

    add_connection(vault, "!!!")
    cfg = load(vault)
    assert any(i.code == "connection.bad-name" and "'!!!' needs at least one letter or number" in i.message for i in cfg.issues)
    assert not any(i.code == "connection.duplicate" for i in cfg.issues)

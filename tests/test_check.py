from bron.check import codex_trusts, has_errors, run_checks
from bron.loader import load
from vaultkit import add_agent, add_connection, set_meta


def codes(vault):
    return {i.code for i in run_checks(load(vault), include_environment=False)}


def test_template_passes(vault):
    assert run_checks(load(vault), include_environment=False) == []


def test_unknown_references_are_errors(vault):
    add_agent(vault, "CFO", reports_to="Nobody", helpers=["ghost"], connections=["carta"], can_assign_to=["COO", "CFO"])
    found = codes(vault)
    assert {
        "agent.reports-to-unknown",
        "agent.helper-unknown",
        "agent.connection-unknown",
        "agent.assign-unknown",
        "agent.assign-self",
    } <= found


def test_references_are_matched_loosely(vault):
    add_connection(vault, "Google Drive")
    add_agent(vault, "CFO", reports_to="bron", connections=["google-drive"], helpers=["Reader"])
    assert codes(vault) == set()


def test_reporting_cycle_is_reported_once(vault):
    add_agent(vault, "CFO", reports_to="COO")
    add_agent(vault, "COO", reports_to="CFO")
    cycles = [i for i in run_checks(load(vault), include_environment=False) if i.code == "agent.reports-cycle"]
    assert len(cycles) == 1
    assert "CFO" in cycles[0].message and "COO" in cycles[0].message


def test_default_agent_must_exist(vault):
    set_meta(vault.settings_file, default_agent="Atlas")
    assert "settings.default-agent-unknown" in codes(vault)


def test_agent_named_like_a_helper_is_an_error(vault):
    add_agent(vault, "Reader")
    assert "agent.name-taken" in codes(vault)


def test_unknown_action_is_only_a_warning(vault):
    add_agent(vault, "CFO", ask_before=["launch-rockets"])
    issues = run_checks(load(vault), include_environment=False)
    assert [i.level for i in issues if i.code == "agent.action-unknown"] == ["warning"]
    assert not has_errors(issues)


def test_secret_in_connection_env_is_an_error(vault):
    add_connection(vault, "Carta", env={"CARTA_API_KEY": "sk-123", "CARTA_TOKEN": "${CARTA_TOKEN}", "REGION": "us"})
    secrets = [i for i in run_checks(load(vault), include_environment=False) if i.code == "connection.secret-in-vault"]
    assert len(secrets) == 1
    assert "CARTA_API_KEY" in secrets[0].message


def test_helper_connection_must_exist(vault):
    from vaultkit import write_md

    write_md(vault.helpers_dir / "scout.md", {"name": "scout", "description": "x", "connections": ["nowhere"]})
    assert "helper.connection-unknown" in codes(vault)


def test_missing_cli_is_a_warning(vault, monkeypatch):
    monkeypatch.setattr("bron.check.shutil.which", lambda name: None)
    issues = run_checks(load(vault))
    assert any(i.code == "cli.missing" and i.level == "warning" for i in issues)


def test_codex_trust_is_read_from_codex_home(vault, tmp_path, monkeypatch):
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    assert not codex_trusts(vault.root)
    (home / "config.toml").write_text(f'[projects."{vault.root}"]\ntrust_level = "trusted"\n', encoding="utf-8")
    assert codex_trusts(vault.root)


def test_untrusted_codex_vault_is_a_warning(vault, tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr("bron.check.shutil.which", lambda name: f"/usr/bin/{name}")
    issues = run_checks(load(vault))
    assert any(i.code == "codex.untrusted" and i.level == "warning" for i in issues)

import pytest

from bron.check import run_checks
from bron.cli import main
from bron.loader import load
from vaultkit import add_agent


@pytest.fixture
def launched(vault, monkeypatch):
    add_agent(vault, "CFO", runs_in="codex", models={"codex": "gpt-6.1-sol"})
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    monkeypatch.chdir(vault.root)  # bron chat changes folder; this restores it after the test
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    calls = {}

    def fake_exec(file, argv, env):
        calls.update(file=file, argv=argv, env=env)
        raise SystemExit(0)

    monkeypatch.setattr("os.execvpe", fake_exec)
    return calls


def test_chat_with_the_default_agent_in_the_default_cli(launched, vault):
    with pytest.raises(SystemExit):
        main(["chat"])
    assert launched["file"] == "claude"
    assert launched["argv"][launched["argv"].index("--agent") + 1] == "bron"
    assert launched["env"]["BRON_AGENT"] == "Bron"


def test_chat_with_a_pinned_agent_uses_its_cli(launched):
    with pytest.raises(SystemExit):
        main(["chat", "cfo"])
    assert launched["file"] == "codex"
    assert launched["env"]["BRON_AGENT"] == "CFO"


def test_chat_refuses_the_wrong_cli_for_a_pinned_agent(launched, capsys):
    assert main(["chat", "CFO", "--cli", "claude"]) == 1
    assert "CFO only runs in Codex" in capsys.readouterr().out


def test_chat_explains_unknown_agent_and_missing_cli(launched, capsys, monkeypatch):
    assert main(["chat", "Nobody"]) == 1
    assert "There's no agent called 'Nobody'" in capsys.readouterr().out
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert main(["chat"]) == 1
    assert "Claude Code isn't installed" in capsys.readouterr().out


def test_pinned_agent_without_a_model_for_its_cli_is_a_warning(vault):
    add_agent(vault, "COO", runs_in="claude", models={"codex": "gpt-6.1-sol"})
    issues = [i for i in run_checks(load(vault), include_environment=False) if i.code == "agent.model-missing"]
    assert [i.level for i in issues] == ["warning"]
    assert "COO" in issues[0].message and "Claude Code" in issues[0].message

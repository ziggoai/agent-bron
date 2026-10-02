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


def test_unpinned_agent_without_models_has_no_model_missing_warning(vault):
    add_agent(vault, "Assistant", runs_in="any", models={})
    issues = [i for i in run_checks(load(vault), include_environment=False) if i.code == "agent.model-missing"]
    assert issues == []


def test_pinned_agent_with_a_model_for_its_cli_has_no_warning(vault):
    add_agent(vault, "COO", runs_in="claude", models={"claude": "claude-opus-4"})
    issues = [i for i in run_checks(load(vault), include_environment=False) if i.code == "agent.model-missing"]
    assert issues == []


def test_sync_is_run_before_launching(launched, vault, monkeypatch):
    from bron.sync import run_sync as original_run_sync

    sync_called = []

    def fake_run_sync(v):
        sync_called.append(True)
        return original_run_sync(v)

    monkeypatch.setattr("bron.sync.run_sync", fake_run_sync)
    with pytest.raises(SystemExit):
        main(["chat"])
    assert sync_called
    assert (vault.root / ".claude" / "bron" / "agents" / "bron.settings.json").exists()


def test_chat_fails_if_sync_is_not_ok(launched, monkeypatch, capsys):
    from dataclasses import dataclass

    @dataclass
    class FailedResult:
        ok: bool = False

    monkeypatch.setattr("bron.sync.run_sync", lambda v: FailedResult())
    assert main(["chat"]) == 1
    output = capsys.readouterr().out
    assert "Bron's setup has problems" in output
    assert "bron check" in output


def test_chat_execvpe_oserror(launched, capsys, monkeypatch):
    def fake_exec(file, argv, env):
        raise OSError("Permission denied")

    monkeypatch.setattr("os.execvpe", fake_exec)
    assert main(["chat"]) == 1
    output = capsys.readouterr().out
    assert "Couldn't start Claude Code" in output

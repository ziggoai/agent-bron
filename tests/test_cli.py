from pathlib import Path

import pytest

from bron.cli import main
from vaultkit import add_agent

VERSION = (Path(__file__).resolve().parents[1] / "core" / "VERSION").read_text().strip()


@pytest.fixture
def run(vault, monkeypatch, capsys):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    monkeypatch.setattr("bron.check.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("bron.check.codex_trusts", lambda root: True)

    def _run(*args):
        code = main(list(args))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


def test_sync_then_check(run):
    code, out, _ = run("sync")
    assert code == 0 and "Synced:" in out
    code, out, _ = run("check")
    assert code == 0 and "all good" in out


def test_check_explains_problems_with_the_file(run, vault):
    add_agent(vault, "CFO", reports_to="Nobody")
    code, out, _ = run("check")
    assert code == 1
    assert "problem" in out
    assert "reports to 'Nobody'" in out
    assert "System/Agents/CFO/Agent.md" in out


def test_check_warns_about_drift(run, vault):
    run("sync")
    (vault.root / "AGENTS.md").write_text("edited\n")
    code, out, _ = run("check")
    assert code == 0 and "changed or removed by hand" in out


def test_failed_sync_says_the_old_setup_is_kept(run, vault):
    add_agent(vault, "CFO", reports_to="Nobody")
    code, out, _ = run("sync")
    assert code == 1 and "last working setup is still in place" in out


def test_dry_run(run, vault):
    code, out, _ = run("sync", "--dry-run")
    assert code == 0 and "Dry run" in out
    assert not (vault.root / "AGENTS.md").exists()


def test_version(run):
    assert run("version")[:2] == (0, f"{VERSION}\n")


def test_outside_a_vault(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("BRON_VAULT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["check"]) == 2
    assert "No Bron vault" in capsys.readouterr().err


def test_the_after_update_command_is_hidden_but_parses(capsys):
    from bron.cli import build_parser

    with pytest.raises(SystemExit):
        build_parser().parse_args(["--help"])
    out = capsys.readouterr().out
    assert "_after-update" not in out and "SUPPRESS" not in out
    assert build_parser().parse_args(["_after-update", "--previous", "0.4.1"]).previous == "0.4.1"

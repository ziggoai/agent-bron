import stat

import pytest

from bron.cli import main


@pytest.fixture
def run(vault, monkeypatch, capsys):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))

    def _run(*args):
        code = main(list(args))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


def fake_project(tmp_path, body: str):
    """A stand-in for the Bron project folder with a scripts/dev-vault.sh that runs `body`."""
    project = tmp_path / "Bron Project"
    script = project / "scripts" / "dev-vault.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return project


def remember_source(vault, project):
    vault.bron_dir.mkdir(parents=True, exist_ok=True)
    (vault.bron_dir / "source").write_text(f"{project}\n", encoding="utf-8")


def test_update_without_a_known_source_explains_what_to_do(run):
    code, out, _ = run("update")
    assert code == 1
    assert "doesn't know which Bron project" in out


def test_update_when_the_project_moved(run, vault, tmp_path):
    remember_source(vault, tmp_path / "gone")
    code, out, _ = run("update")
    assert code == 1
    assert "can't find the Bron project" in out


def test_update_runs_the_project_script_for_this_vault_and_reports_the_version(run, vault, tmp_path):
    project = fake_project(
        tmp_path,
        'printf "0.3.0\\n" > "$1/System/Core/VERSION"\n'
        'echo "Synced: 3 file(s) written, 0 removed."\n'
        'echo "Bron health check: all good."\n',
    )
    remember_source(vault, project)
    code, out, _ = run("update")
    assert code == 0
    assert "Updated Bron from version 0.2.1 to 0.3.0." in out
    assert "Bron health check: all good." in out
    assert "Your own files were kept." in out
    assert "Start a new session" in out


def test_update_with_no_new_version_still_refreshes(run, vault, tmp_path):
    project = fake_project(tmp_path, 'echo "Bron health check: all good."\n')
    remember_source(vault, project)
    code, out, _ = run("update")
    assert code == 0
    assert "already on the latest version (0.2.1)" in out


def test_failed_update_reports_the_reason(run, vault, tmp_path):
    project = fake_project(tmp_path, 'echo "uv: command not found" >&2\nexit 127\n')
    remember_source(vault, project)
    code, out, _ = run("update")
    assert code == 1
    assert "The update didn't finish" in out
    assert "uv: command not found" in out

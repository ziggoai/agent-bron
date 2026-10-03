import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from bron import update
from bron.cli import main
from bron.releases import LocalReleases, ProjectFolder
from releasekit import REPO, make_release, write_tags

CURRENT = (REPO / "core" / "VERSION").read_text().strip()
CHANGELOG = f"""# Changelog

## 9.1.0
- Newest thing.

## 9.0.0
- Big thing.

## {CURRENT}
- What you have.
"""


@pytest.fixture
def releases(tmp_path, monkeypatch):
    folder = tmp_path / "releases"
    make_release(folder, "9.0.0", changelog=CHANGELOG, extra={"core/Manual/new-page.md": "new\n"})
    write_tags(folder, [CURRENT, "9.0.0"])
    monkeypatch.setenv("BRON_RELEASE_SOURCE", str(folder))
    return folder


@pytest.fixture
def run(vault, monkeypatch, capsys):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))

    def _run(*args):
        code = main(list(args))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture
def engine(monkeypatch):
    """No real uv: record engine installs; run the 'new engine' finishing step in this process."""
    calls = []
    monkeypatch.setattr(update, "install_engine", lambda vault: calls.append(vault.version()))

    def in_process(vault, previous, tree):
        out = io.StringIO()
        with redirect_stdout(out):
            code = update.finish(vault, previous, tree)
        return code, out.getvalue()

    monkeypatch.setattr(update, "after_update", in_process)
    return calls


def test_preview_lists_whats_new(run, releases):
    code, out, _ = run("update", "--preview")
    assert code == 0
    assert f"Bron 9.0.0 is available (you have {CURRENT})" in out
    assert "Big thing." in out
    assert "Newest thing." not in out
    assert "What you have." not in out


def test_preview_when_up_to_date(run, tmp_path, monkeypatch):
    folder = tmp_path / "r"
    write_tags(folder, [CURRENT])
    monkeypatch.setenv("BRON_RELEASE_SOURCE", str(folder))
    code, out, _ = run("update", "--preview")
    assert code == 0
    assert f"Bron is up to date (version {CURRENT})." in out


def test_preview_offline(run):
    code, out, _ = run("update", "--preview")
    assert code == 1
    assert "GitHub didn't answer" in out


def test_apply_updates_backs_up_and_keeps_your_files(run, vault, releases, engine):
    mine = vault.system / "Agents" / "Bron" / "Agent.md"
    before = mine.read_text()
    code, out, _ = run("update")
    assert code == 0, out
    assert f"Updated Bron from version {CURRENT} to 9.0.0." in out
    assert "Start a new session" in out
    assert vault.version() == "9.0.0"
    assert (vault.core / "Manual" / "new-page.md").is_file()
    assert mine.read_text() == before
    assert [b.name.startswith(f"core-{CURRENT}-") for b in update.backups(vault)] == [True]
    assert engine == ["9.0.0"]


def test_a_download_with_the_wrong_version_changes_nothing(run, vault, tmp_path, monkeypatch, engine):
    folder = tmp_path / "bad"
    make_release(folder, "9.0.0", core_version="8.9.9")
    write_tags(folder, ["9.0.0"])
    monkeypatch.setenv("BRON_RELEASE_SOURCE", str(folder))
    code, out, _ = run("update")
    assert code == 1
    assert "doesn't contain that version" in out
    assert vault.version() == CURRENT
    assert update.backups(vault) == []


def test_failed_engine_install_rolls_back(run, vault, releases, monkeypatch):
    attempts = []

    def flaky(v):
        attempts.append(v.version())
        if v.version() == "9.0.0":
            raise RuntimeError("the engine couldn't be installed: no network")

    monkeypatch.setattr(update, "install_engine", flaky)
    code, out, _ = run("update")
    assert code == 1
    assert "didn't finish" in out and "no network" in out
    assert f"went back to version {CURRENT}" in out
    assert vault.version() == CURRENT
    assert not (vault.core / "Manual" / "new-page.md").exists()
    assert attempts == ["9.0.0", CURRENT]


def test_failed_finishing_step_rolls_back(run, vault, releases, monkeypatch):
    monkeypatch.setattr(update, "install_engine", lambda v: None)
    monkeypatch.setattr(update, "after_update", lambda v, previous, tree: (1, "Sync stopped. Fix these first"))
    code, out, _ = run("update")
    assert code == 1
    assert "Sync stopped" in out
    assert vault.version() == CURRENT


def test_undo_goes_back_and_uses_up_the_backup(run, vault, releases, engine):
    run("update")
    code, out, _ = run("update", "--undo")
    assert code == 0, out
    assert f"Went back from version 9.0.0 to {CURRENT}." in out
    assert vault.version() == CURRENT
    assert update.backups(vault) == []


def test_undo_without_a_backup(run):
    code, out, _ = run("update", "--undo")
    assert code == 1
    assert "no earlier version" in out


def test_only_three_backups_are_kept(vault):
    for i in range(5):
        update.backup_core(vault, stamp=f"2026010{i}-000000")
    assert [b.name for b in update.backups(vault)] == [f"core-{CURRENT}-2026010{i}-000000" for i in (2, 3, 4)]


def test_update_from_a_project_folder_refreshes_and_remembers_it(run, vault, engine, monkeypatch):
    monkeypatch.delenv("BRON_RELEASE_SOURCE")
    code, out, _ = run("update", "--from", str(REPO))
    assert code == 0, out
    assert f"already on the latest version ({CURRENT})" in out
    assert (vault.bron_dir / "source").read_text().strip() == str(REPO)


def test_finish_restores_missing_starting_files(vault, tmp_path, capsys):
    (vault.root / "Tickets" / "Board.base").unlink()
    tree = ProjectFolder(REPO).fetch(CURRENT, tmp_path / "work")
    assert update.finish(vault, CURRENT, tree) == 0
    assert (vault.root / "Tickets" / "Board.base").is_file()
    assert "Bron health check" in capsys.readouterr().out


def test_a_project_folder_that_cant_be_read_changes_nothing(run, vault, tmp_path, engine, monkeypatch):
    monkeypatch.delenv("BRON_RELEASE_SOURCE")
    folder = tmp_path / "half"
    (folder / "core").mkdir(parents=True)
    (folder / "core" / "VERSION").write_text("9.0.0\n")
    code, out, err = run("update", "--from", str(folder))
    assert code == 1
    assert "couldn't be prepared" in out and "nothing was changed" in out
    assert "Traceback" not in out + err
    assert vault.version() == CURRENT
    assert update.backups(vault) == []

import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from bron import update
from bron.obsidian import RESTART_NOTE, install_bundle
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
    attempts = []
    monkeypatch.setattr(update, "install_engine", lambda v: attempts.append(v.version()))
    monkeypatch.setattr(update, "after_update", lambda v, previous, tree: (1, "Sync stopped. Fix these first"))
    code, out, _ = run("update")
    assert code == 1
    assert "Sync stopped" in out
    assert f"went back to version {CURRENT}" in out
    assert vault.version() == CURRENT
    assert not (vault.core / "Manual" / "new-page.md").exists()
    assert attempts == ["9.0.0", CURRENT]


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


def test_undo_after_a_failed_update_has_nothing_to_go_back_to(run, vault, releases, monkeypatch):
    monkeypatch.setattr(update, "install_engine", lambda v: None)
    monkeypatch.setattr(update, "after_update", lambda v, previous, tree: (1, "boom"))
    run("update")
    assert update.backups(vault) == []
    code, out, _ = run("update", "--undo")
    assert code == 1 and "no earlier version" in out


def test_undo_after_a_failed_update_goes_to_the_last_good_version(run, vault, releases, engine):
    run("update")  # succeeds: backup of CURRENT
    assert vault.version() == "9.0.0"
    stale = update.backup_core(vault)  # a leftover of the live version, as a failed attempt used to leave
    assert update._version_of(stale) == "9.0.0"
    code, out, _ = run("update", "--undo")
    assert code == 0, out
    assert f"Went back from version 9.0.0 to {CURRENT}." in out


def test_a_crashing_rollback_gives_a_plain_message(run, vault, releases, monkeypatch):
    monkeypatch.setattr(update, "install_engine", lambda v: (_ for _ in ()).throw(RuntimeError("no network")))

    def broken(root, src):
        if src.name != "core":
            raise OSError("disk full")
        return real(root, src)

    real = update.replace_core
    monkeypatch.setattr(update, "replace_core", broken)
    code, out, err = run("update")
    assert code == 1
    assert "didn't work either" in out and ".bron/backups/core-" in out
    assert "Traceback" not in out + err


def test_finish_never_shows_a_traceback(vault, tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise OSError("disk exploded")

    monkeypatch.setattr("bron.obsidian.refresh_bundle", boom)
    tree = ProjectFolder(REPO).fetch(CURRENT, tmp_path / "work")
    assert update.finish(vault, CURRENT, tree) == 1
    out = capsys.readouterr().out
    assert "couldn't finish setting up (OSError: disk exploded)" in out
    assert "Traceback" not in out


def test_a_same_version_refresh_makes_no_backup(run, vault, engine, monkeypatch):
    monkeypatch.delenv("BRON_RELEASE_SOURCE")
    code, out, _ = run("update", "--from", str(REPO))
    assert code == 0, out
    assert update.backups(vault) == []


def test_a_failed_backup_changes_nothing(run, vault, releases, engine, monkeypatch):
    def full(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(update.shutil, "copytree", full)
    code, out, _ = run("update")
    assert code == 1 and "backup" in out and "nothing was changed" in out
    assert vault.version() == CURRENT
    assert update.backups(vault) == []


def test_undo_does_not_take_from(run, tmp_path):
    code, out, _ = run("update", "--undo", "--from", str(tmp_path))
    assert code == 2 and "--undo doesn't take --from" in out


def rename_bron(vault, new="Ava"):
    from vaultkit import set_meta

    (vault.agents_dir / "Bron").rename(vault.agents_dir / new)
    set_meta(vault.agents_dir / new / "Agent.md", name=new)
    set_meta(vault.settings_file, default_agent=new)


def test_an_update_never_brings_back_a_renamed_main_agent(run, vault, releases, engine):
    rename_bron(vault)
    code, out, _ = run("update")
    assert code == 0, out
    assert vault.version() == "9.0.0"
    assert not (vault.agents_dir / "Bron").exists()
    assert (vault.agents_dir / "Ava" / "Agent.md").is_file()


def test_finish_twice_keeps_a_renamed_agent_and_a_deleted_board_away(vault, tmp_path, capsys):
    tree = ProjectFolder(REPO).fetch(CURRENT, tmp_path / "work")
    assert update.finish(vault, CURRENT, tree) == 0  # records the starting files
    rename_bron(vault)
    (vault.root / "Tickets" / "Board.base").unlink()
    assert update.finish(vault, CURRENT, tree) == 0, capsys.readouterr().out
    assert not (vault.agents_dir / "Bron").exists()
    assert not (vault.root / "Tickets" / "Board.base").exists()


# An interrupted update: the marker, Ctrl-C and signals roll back; the next `bron update` heals.

def marker(vault):
    return vault.state_dir / "update-in-progress.json"


def test_ctrl_c_during_the_engine_install_rolls_back_and_still_stops(vault, releases, monkeypatch, capsys):
    from bron.releases import select_source

    seen = []

    def interrupted(v):
        seen.append(marker(v).is_file())
        if v.version() == "9.0.0":
            raise KeyboardInterrupt

    monkeypatch.setattr(update, "install_engine", interrupted)
    with pytest.raises(KeyboardInterrupt):
        update.apply(vault, select_source(vault, None))
    out = capsys.readouterr().out
    assert seen[0] is True  # the marker was there while Bron's files were being swapped
    assert f"Bron went back to version {CURRENT}" in out and "stopped" in out
    assert vault.version() == CURRENT
    assert not (vault.core / "Manual" / "new-page.md").exists()
    assert not marker(vault).exists()
    assert update.backups(vault) == []


def test_ctrl_c_through_the_command_exits_130_without_a_traceback(run, vault, releases, monkeypatch):
    monkeypatch.setattr(update, "install_engine", lambda v: (_ for _ in ()).throw(KeyboardInterrupt()) if v.version() == "9.0.0" else None)
    code, out, err = run("update")
    assert code == 130
    assert f"Bron went back to version {CURRENT}" in out
    assert "Traceback" not in out + err
    assert vault.version() == CURRENT


def test_sigterm_during_the_update_rolls_back(run, vault, releases, monkeypatch):
    import os
    import signal

    before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGHUP)

    def killed(v):
        if v.version() == "9.0.0":
            os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(update, "install_engine", killed)
    code, out, _ = run("update")
    assert code == 143
    assert f"Bron went back to version {CURRENT}" in out
    assert vault.version() == CURRENT and not marker(vault).exists()
    assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGHUP)) == before


def test_a_leftover_marker_is_healed_by_the_next_update(run, vault, releases, engine):
    import json

    copy = update.backup_core(vault)
    (vault.core / "VERSION").write_text("9.0.0\n")  # the new core was already swapped in
    (vault.core / "Manual" / "new-page.md").write_text("new\n")
    marker(vault).parent.mkdir(parents=True, exist_ok=True)
    marker(vault).write_text(json.dumps({"previous": CURRENT, "restore_from": copy.relative_to(vault.root).as_posix()}))
    code, out, _ = run("update", "--preview")
    assert out.splitlines()[0] == f"A previous update was interrupted; Bron went back to version {CURRENT}."
    assert code == 0 and "Bron 9.0.0 is available" in out  # then the preview goes on
    assert vault.version() == CURRENT
    assert not (vault.core / "Manual" / "new-page.md").exists()
    assert not marker(vault).exists() and not copy.exists()
    assert engine == [CURRENT]


def test_ctrl_c_during_undo_stays_on_the_current_version(run, vault, releases, engine, monkeypatch, capsys):
    run("update")
    assert vault.version() == "9.0.0"

    def stop(v, previous, tree):
        raise KeyboardInterrupt

    monkeypatch.setattr(update, "after_update", stop)
    with pytest.raises(KeyboardInterrupt):
        update.undo(vault)
    assert "Bron stayed on version 9.0.0" in capsys.readouterr().out
    assert vault.version() == "9.0.0" and not marker(vault).exists()
    assert not [p for p in vault.backups_dir.iterdir() if p.name.startswith("safety-")]
    assert len(update.backups(vault)) == 1  # the undo point is still there


def test_a_leftover_marker_from_an_undo_is_healed(run, vault, releases, engine):
    import json

    run("update")
    safety = update._safety_copy(vault)  # what undo keeps while it runs
    (vault.core / "VERSION").write_text(f"{CURRENT}\n")  # undo had swapped the old core in, then died
    marker(vault).write_text(json.dumps({"previous": "9.0.0", "restore_from": safety.relative_to(vault.root).as_posix()}))
    code, out, _ = run("update", "--preview")
    assert out.splitlines()[0] == "A previous update was interrupted; Bron went back to version 9.0.0."
    assert vault.version() == "9.0.0" and not marker(vault).exists() and not safety.exists()


def test_a_refresh_keeps_its_safety_copy_in_backups_while_it_runs(run, vault, engine, monkeypatch):
    import json

    monkeypatch.delenv("BRON_RELEASE_SOURCE")
    seen = {}

    def look(v):
        seen.update(json.loads(marker(v).read_text()))

    monkeypatch.setattr(update, "install_engine", look)
    code, out, _ = run("update", "--from", str(REPO))
    assert code == 0, out
    assert seen["previous"] == CURRENT and seen["restore_from"].startswith(f".bron/backups/safety-{CURRENT}-")
    assert not (vault.root / seen["restore_from"]).exists()  # removed when done
    assert not marker(vault).exists()


def test_a_failed_restore_keeps_the_copy_and_names_it(run, vault, engine, monkeypatch):
    monkeypatch.delenv("BRON_RELEASE_SOURCE")
    real = update.replace_core

    def broken(root, src):
        if src.name != "core":
            raise OSError("disk full")
        return real(root, src)

    monkeypatch.setattr(update, "replace_core", broken)
    monkeypatch.setattr(update, "after_update", lambda v, previous, tree: (1, "boom"))
    code, out, _ = run("update", "--from", str(REPO))
    assert code == 1
    kept = [p for p in vault.backups_dir.iterdir() if p.name.startswith("safety-")]
    assert len(kept) == 1 and f".bron/backups/{kept[0].name}" in out
    assert "run the install command again to repair it (it installs the newest version)" in out
    assert marker(vault).exists()  # the next `bron update` tries again


def test_check_reports_an_engine_that_doesnt_match_its_files(run, vault, monkeypatch):
    import bron

    monkeypatch.setattr(bron, "__version__", "9.9.9")
    code, out, _ = run("check")
    assert code == 1
    assert f"Bron's engine (version 9.9.9) doesn't match its files (version {CURRENT}). Say 'Bron, update yourself' or run the install command again." in out


def test_check_reports_an_interrupted_update(run, vault):
    marker(vault).parent.mkdir(parents=True, exist_ok=True)
    marker(vault).write_text("{}")
    code, out, _ = run("check")
    assert "An update was interrupted; run `.bron/bin/bron update` to finish going back." in out


# Follow-up: no false "interrupted" warning, heal re-checks under the lock, Ctrl-C outside the swap.

def test_a_successful_update_refresh_and_undo_never_say_interrupted(run, vault, releases, engine, monkeypatch):
    # The engine fixture runs the finishing step (and its health check) while apply still holds the
    # update lock, as the real `bron _after-update` subprocess does.
    code, out, _ = run("update")
    assert code == 0, out
    assert "Bron health check" in out and "was interrupted" not in out
    code, out, _ = run("update", "--undo")
    assert code == 0, out
    assert "Bron health check" in out and "was interrupted" not in out
    monkeypatch.delenv("BRON_RELEASE_SOURCE")
    code, out, _ = run("update", "--from", str(REPO))
    assert code == 0, out
    assert "Bron health check" in out and "was interrupted" not in out


def test_a_marker_with_an_update_running_elsewhere_is_not_reported(run, vault):
    import fcntl

    marker(vault).parent.mkdir(parents=True, exist_ok=True)
    marker(vault).write_text("{}")
    with open(vault.state_dir / "update.json.lock", "a+") as handle:  # another process's update
        fcntl.flock(handle, fcntl.LOCK_EX)
        _, out, _ = run("check")
        fcntl.flock(handle, fcntl.LOCK_UN)
    assert "was interrupted" not in out
    _, out, _ = run("check")  # nothing running: the leftover marker is reported
    assert "An update was interrupted" in out


def test_heal_does_nothing_when_the_marker_goes_while_it_waits_for_the_lock(vault, monkeypatch):
    import contextlib

    marker(vault).parent.mkdir(parents=True, exist_ok=True)
    marker(vault).write_text('{"previous": "0.0.1", "restore_from": ".bron/backups/gone"}')

    @contextlib.contextmanager
    def other_update_finishes_first(path):
        marker(vault).unlink()
        yield

    monkeypatch.setattr(update, "locked", other_update_finishes_first)
    assert update.heal(vault) == (0, None)


def test_ctrl_c_before_anything_changed_says_so(run, vault, releases, engine, monkeypatch):
    def interrupted(v, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(update, "backup_core", interrupted)
    code, out, err = run("update")
    assert code == 130
    assert out.strip() == "Stopped; nothing was changed."
    assert "Traceback" not in out + err
    assert vault.version() == CURRENT


def test_ctrl_c_during_the_swap_says_only_what_happened(run, vault, releases, monkeypatch):
    monkeypatch.setattr(update, "install_engine", lambda v: (_ for _ in ()).throw(KeyboardInterrupt()) if v.version() == "9.0.0" else None)
    code, out, _ = run("update")
    assert code == 130
    assert f"Bron went back to version {CURRENT}" in out and "nothing was changed" not in out


@pytest.mark.parametrize("make_copy", ["_safety_copy", "backup_core"])
def test_ctrl_c_while_copying_leaves_no_partial_copy(vault, monkeypatch, make_copy):
    real = update.shutil.copytree

    def interrupted_copy(src, dest, **kwargs):
        Path(dest).mkdir(parents=True)
        (Path(dest) / "VERSION").write_text("half\n")
        raise KeyboardInterrupt

    monkeypatch.setattr(update.shutil, "copytree", interrupted_copy)
    with pytest.raises(KeyboardInterrupt):
        getattr(update, make_copy)(vault)
    monkeypatch.setattr(update.shutil, "copytree", real)
    assert not vault.backups_dir.exists() or list(vault.backups_dir.iterdir()) == []


def test_an_update_that_changes_the_obsidian_plugins_ends_with_the_restart_note(run, vault, tmp_path, monkeypatch, engine):
    install_bundle(vault.root, vault.core, None)
    folder = tmp_path / "plugin-release"
    make_release(folder, "9.0.0", changelog=CHANGELOG, extra={"core/Obsidian/plugins/colored-tags/main.js": "new plugin code\n"})
    write_tags(folder, [CURRENT, "9.0.0"])
    monkeypatch.setenv("BRON_RELEASE_SOURCE", str(folder))
    code, out, _ = run("update")
    assert code == 0, out
    assert out.strip().splitlines()[-1] == RESTART_NOTE


def test_an_update_that_leaves_obsidian_alone_has_no_restart_note(run, vault, releases, engine):
    install_bundle(vault.root, vault.core, None)
    code, out, _ = run("update")
    assert code == 0, out
    assert RESTART_NOTE not in out

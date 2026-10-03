"""install.sh end to end, against a local release tarball, a temporary HOME and scripted answers."""
import json
import os
import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path

import pytest
from vaultkit import set_meta

REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "install.sh"
IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info", ".pytest_cache", ".DS_Store")

pytestmark = pytest.mark.skipif(shutil.which("uv") is None, reason="needs uv")


@pytest.fixture(scope="module")
def tarball(tmp_path_factory):
    stage = tmp_path_factory.mktemp("release") / "agent-bron-test"
    shutil.copytree(REPO / "core", stage / "core", ignore=IGNORE)
    shutil.copytree(REPO / "template", stage / "template", ignore=IGNORE)
    path = stage.parent / "release.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        tar.add(stage, arcname=stage.name)
    return path


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".codex" / "config.toml").write_text('model = "gpt-5"\n')
    return home


def run(home, tarball, *args, cwd=None, answers=None, yes=False, tty=None):
    env = {
        "HOME": str(home),
        "PATH": f"{Path(shutil.which('uv')).parent}:/usr/bin:/bin:/usr/sbin:/sbin",
        "BRON_INSTALL_SOURCE": str(tarball),
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv")),
        "UV_PYTHON_INSTALL_DIR": os.environ.get("UV_PYTHON_INSTALL_DIR", str(Path.home() / ".local" / "share" / "uv" / "python")),
    }
    if answers is not None:
        answer_file = home.parent / "answers.txt"
        answer_file.write_text(answers)
        env["BRON_TTY"] = str(answer_file)
    elif tty is not None:
        env["BRON_TTY"] = tty
    else:
        env["BRON_TTY"] = str(home.parent / "no-terminal")
    if yes:
        env["BRON_YES"] = "1"
    done = subprocess.run(["bash", str(INSTALLER), *args], cwd=cwd or home, env=env, capture_output=True, text=True, timeout=600)
    return done.returncode, done.stdout + done.stderr


def test_installs_into_an_empty_folder_given_on_the_command_line(home, tarball, tmp_path):
    target = tmp_path / "Meu Cofre Ágora"
    code, out = run(home, tarball, str(target))
    assert code == 0, out
    assert (target / "System" / "Core" / "VERSION").is_file()
    assert (target / ".bron" / "source").read_text().strip() == "github"
    assert (target / ".obsidian" / "themes" / "Bron" / "theme.css").is_file()
    assert (home / ".local" / "bin" / "bron").is_file()
    assert (home / ".zprofile").read_text().count("added by the Bron installer") == 1
    trusted = tomllib.loads((home / ".codex" / "config.toml").read_text())["projects"]
    assert trusted[str(target)]["trust_level"] == "trusted"
    assert f"Your Bron vault is ready at {target}." in out
    assert "say hi to Bron" in out
    assert "Obsidian" in out


def test_rerun_repairs_and_changes_nothing_of_yours(home, tarball, tmp_path):
    target = tmp_path / "Bron"
    assert run(home, tarball, str(target))[0] == 0
    (target / "Projects" / "My note.md").write_text("mine")
    (target / "Tickets" / "Board.base").unlink()
    agents = target / "System" / "Agents"
    (agents / "Bron").rename(agents / "Ava")
    set_meta(agents / "Ava" / "Agent.md", name="Ava")
    set_meta(target / "System" / "Settings.md", default_agent="Ava")
    code, out = run(home, tarball, str(target))
    assert code == 0, out
    assert "repairing" in out
    assert (target / "Projects" / "My note.md").read_text() == "mine"
    assert not (target / "Tickets" / "Board.base").exists()  # seeded once; deleting it was the user's choice
    assert not (agents / "Bron").exists()  # the renamed main agent doesn't come back
    assert (agents / "Ava" / "Agent.md").is_file()
    assert (home / ".zprofile").read_text().count("added by the Bron installer") == 1
    assert (home / ".codex" / "config.toml").read_text().count(str(target)) == 1


def test_a_folder_with_other_files_needs_a_yes(home, tarball, tmp_path):
    target = tmp_path / "Notes"
    target.mkdir()
    (target / "old.md").write_text("mine")
    code, out = run(home, tarball, str(target), answers="n\n")
    assert code == 1
    assert "Nothing was changed" in out
    assert sorted(p.name for p in target.iterdir()) == ["old.md"]
    code, out = run(home, tarball, str(target), answers="y\n")
    assert code == 0, out
    assert (target / "old.md").read_text() == "mine"
    assert (target / "System" / "Core" / "VERSION").is_file()


def test_home_folder_asks_and_defaults_to_documents_bron(home, tarball):
    code, out = run(home, tarball, cwd=home, answers="\n")
    assert code == 0, out
    assert "~/Documents/Bron" in out
    assert (home / "Documents" / "Bron" / "System" / "Core" / "VERSION").is_file()
    assert not (home / "System").exists()


def test_no_terminal_to_ask_explains_how_to_pass_a_folder(home, tarball):
    code, out = run(home, tarball, cwd=home)
    assert code == 1
    assert "bash -s --" in out
    assert not (home / "Documents" / "Bron").exists()


def test_system_folders_are_not_used(home, tarball):
    code, out = run(home, tarball, "/Library")
    assert code == 1
    assert "bash -s --" in out


def test_icloud_folder_warns_and_can_be_declined(home, tarball):
    target = home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "Bron"
    code, out = run(home, tarball, str(target), answers="n\n")
    assert code == 1
    assert "iCloud" in out
    assert not target.exists()


def test_existing_obsidian_settings_are_kept(home, tarball, tmp_path):
    target = tmp_path / "Vault"
    (target / ".obsidian").mkdir(parents=True)
    (target / ".obsidian" / "appearance.json").write_text('{"cssTheme": "Minimal"}')
    (target / ".obsidian" / "community-plugins.json").write_text('["dataview"]')
    code, out = run(home, tarball, str(target), yes=True)
    assert code == 0, out
    assert (target / ".obsidian" / "appearance.json").read_text() == '{"cssTheme": "Minimal"}'
    assert json.loads((target / ".obsidian" / "community-plugins.json").read_text()) == ["dataview", "bron-terminal", "bron-workspace"]
    assert "Bron theme" in out


def icloud_desktop_and_documents(home, folder="Documents"):
    (home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / folder).mkdir(parents=True)


def test_documents_synced_by_icloud_warns_and_can_be_declined(home, tarball):
    icloud_desktop_and_documents(home)
    target = home / "Documents" / "Bron"
    code, out = run(home, tarball, str(target), answers="n\n")
    assert code == 1
    assert "is synced with iCloud Drive" in out and "Nothing was changed" in out
    assert 'bash -s -- "' in out  # how to choose another folder
    assert not target.exists()


def test_the_default_folder_warns_when_documents_is_in_icloud(home, tarball):
    icloud_desktop_and_documents(home)
    code, out = run(home, tarball, cwd=home, answers="\n\n")  # Enter for the folder, Enter (no) for iCloud
    assert code == 1
    assert "iCloud" in out
    assert not (home / "Documents" / "Bron").exists()


def test_desktop_synced_by_icloud_proceeds_with_bron_yes(home, tarball):
    icloud_desktop_and_documents(home, "Desktop")
    target = home / "Desktop" / "Bron"
    code, out = run(home, tarball, str(target), yes=True)
    assert code == 0, out
    assert "iCloud" in out
    assert (target / "System" / "Core" / "VERSION").is_file()


def test_documents_without_icloud_sync_has_no_warning(home, tarball):
    target = home / "Documents" / "Bron"
    code, out = run(home, tarball, str(target))
    assert code == 0, out
    assert "iCloud" not in out


def test_a_folder_that_cant_be_opened_stops_with_a_reason(home, tarball, tmp_path):
    target = tmp_path / "Locked"
    target.mkdir()
    target.chmod(0o000)
    try:
        code, out = run(home, tarball, str(target))
    finally:
        target.chmod(0o700)
    assert code == 1
    assert f"the folder {target} couldn't be opened" in out


def test_the_engine_steps_never_read_the_script_or_the_terminal():
    text = INSTALLER.read_text()
    lines = [line for line in text.splitlines() if line.startswith('"$UV" ') or line.startswith('"$VAULT/.bron/venv/bin/python"')]
    assert len(lines) == 3
    assert all("</dev/null 3<&-" in line for line in lines), lines
    assert subprocess.run(["bash", "-n", str(INSTALLER)]).returncode == 0


def test_piping_the_script_into_bash_works(home, tarball, tmp_path):
    target = tmp_path / "Piped"
    env = {
        "HOME": str(home),
        "PATH": f"{Path(shutil.which('uv')).parent}:/usr/bin:/bin:/usr/sbin:/sbin",
        "BRON_INSTALL_SOURCE": str(tarball),
        "BRON_TTY": str(home.parent / "no-terminal"),
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(Path.home() / ".cache" / "uv")),
        "UV_PYTHON_INSTALL_DIR": os.environ.get("UV_PYTHON_INSTALL_DIR", str(Path.home() / ".local" / "share" / "uv" / "python")),
    }
    done = subprocess.run(["bash", "-s", "--", str(target)], input=INSTALLER.read_text(), cwd=home, env=env, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"Your Bron vault is ready at {target}." in done.stdout

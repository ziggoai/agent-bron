import os
import subprocess
import tomllib
from pathlib import Path

from bron import install
from bron.install import (
    LAUNCHER, PATH_LINE, copy_template, ensure_path, install_launcher, install_vault,
    replace_core, trust_codex, write_shim,
)

REPO = Path(__file__).resolve().parents[1]


def test_copy_template_never_overwrites_and_skips_obsidian(tmp_path):
    vault = tmp_path / "v"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "Settings.md").write_text("mine")
    copy_template(vault, REPO / "template")
    assert (vault / "System" / "Settings.md").read_text() == "mine"
    assert (vault / "Tickets" / "Board.base").is_file()
    assert not (vault / ".obsidian").exists()


def test_replace_core_is_exact_and_keeps_user_files(vault):
    (vault.core / "stale.md").write_text("old")
    (vault.system / "Agents" / "note.md").write_text("mine")
    replace_core(vault.root, REPO / "core")
    assert not (vault.core / "stale.md").exists()
    assert (vault.core / "VERSION").is_file()
    assert not list(vault.core.rglob("__pycache__"))
    assert (vault.system / "Agents" / "note.md").read_text() == "mine"
    assert not [p for p in vault.system.iterdir() if p.name.startswith(".Core")]


def test_shim_runs_the_vault_engine(tmp_path):
    write_shim(tmp_path)
    shim = tmp_path / ".bron" / "bin" / "bron"
    assert os.access(shim, os.X_OK)
    assert '.bron/venv/bin/python" -m bron' in shim.read_text()


def make_fake_vault(root: Path) -> Path:
    (root / "System" / "Core").mkdir(parents=True)
    (root / "System" / "Core" / "VERSION").write_text("0.5.0\n")
    shim = root / ".bron" / "bin" / "bron"
    shim.parent.mkdir(parents=True)
    shim.write_text('#!/bin/sh\necho "vault bron: $*"\n')
    shim.chmod(0o755)
    return root


def test_launcher_finds_the_vault_from_a_subfolder(tmp_path):
    home = tmp_path / "home"
    assert install_launcher(home) is None
    launcher = home / ".local" / "bin" / "bron"
    vault = make_fake_vault(tmp_path / "Meu Cofre Ágora")
    inside = vault / "Projects" / "Deep"
    inside.mkdir(parents=True)
    done = subprocess.run([str(launcher), "check"], cwd=inside, capture_output=True, text=True)
    assert done.stdout.strip() == "vault bron: check"


def test_launcher_outside_a_vault(tmp_path):
    home = tmp_path / "home"
    install_launcher(home)
    done = subprocess.run([str(home / ".local" / "bin" / "bron"), "check"], cwd=tmp_path, capture_output=True, text=True)
    assert done.returncode == 2
    assert "isn't inside a Bron vault" in done.stderr


def test_someone_elses_bron_command_is_kept(tmp_path):
    home = tmp_path / "home"
    other = home / ".local" / "bin" / "bron"
    other.parent.mkdir(parents=True)
    other.write_text("#!/bin/sh\necho other\n")
    note = install_launcher(home)
    assert "already a different `bron` command" in note
    assert other.read_text() == "#!/bin/sh\necho other\n"


def test_our_launcher_is_updated_in_place(tmp_path):
    home = tmp_path / "home"
    install_launcher(home)
    (home / ".local" / "bin" / "bron").write_text("# installed by Bron's installer\nold")
    assert install_launcher(home) is None
    assert (home / ".local" / "bin" / "bron").read_text() == LAUNCHER


def test_path_line_added_once_on_its_own_line(tmp_path):
    (tmp_path / ".zprofile").write_text("export FOO=1")  # no trailing newline
    assert "~/.zprofile" in ensure_path(tmp_path, "/usr/bin:/bin")
    assert ensure_path(tmp_path, "/usr/bin:/bin") is None
    text = (tmp_path / ".zprofile").read_text()
    assert text == "export FOO=1\n" + PATH_LINE + "\n"


def test_no_path_line_when_already_on_path(tmp_path):
    assert ensure_path(tmp_path, f"/usr/bin:{tmp_path}/.local/bin") is None
    assert not (tmp_path / ".zprofile").exists()


def test_trust_codex_adds_the_vault_once_with_a_backup(tmp_path):
    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('model = "gpt-5"')  # no trailing newline
    vault = tmp_path / "Bron"
    assert "trusts this vault" in trust_codex(home, vault, codex_installed=True)
    assert trust_codex(home, vault, codex_installed=True) is None
    data = tomllib.loads(config.read_text())
    assert data["model"] == "gpt-5"
    assert data["projects"][str(vault)]["trust_level"] == "trusted"
    assert len(list(config.parent.glob("config.toml.bron-backup-*"))) == 1


def test_trust_codex_with_an_accented_path_parses(tmp_path):
    home = tmp_path / "home"
    vault = tmp_path / 'Meu Cofre Ágora "x"'
    trust_codex(home, vault, codex_installed=True)
    data = tomllib.loads((home / ".codex" / "config.toml").read_text())
    assert data["projects"][str(vault)]["trust_level"] == "trusted"


def test_trust_codex_respects_an_existing_entry(tmp_path):
    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    vault = tmp_path / "Bron"
    original = f'[projects."{vault}"]\ntrust_level = "untrusted"\n'
    config.write_text(original)
    assert trust_codex(home, vault, codex_installed=True) is None
    assert config.read_text() == original


def test_trust_codex_leaves_a_file_it_cant_extend(tmp_path):
    home = tmp_path / "home"
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    original = 'projects = { other = { trust_level = "trusted" } }\n'
    config.write_text(original)
    note = trust_codex(home, tmp_path / "Bron", codex_installed=True)
    assert "Codex will ask" in note
    assert config.read_text() == original


def test_trust_codex_skips_when_codex_isnt_there(tmp_path):
    assert trust_codex(tmp_path, tmp_path / "Bron", codex_installed=False) is None
    assert not (tmp_path / ".codex").exists()


def test_install_vault_end_to_end(tmp_path, monkeypatch, capsys):
    root = tmp_path / "Meu Cofre Ágora"
    home = tmp_path / "home"
    monkeypatch.setattr(install.shutil, "which", lambda name: None)
    code = install_vault(root, REPO, source="github", home=home)
    out = capsys.readouterr().out
    assert code == 0, out
    assert (root / "System" / "Core" / "VERSION").is_file()
    assert (root / ".bron" / "source").read_text().strip() == "github"
    assert (root / ".bron" / "bin" / "bron").is_file()
    assert (root / ".obsidian" / "themes" / "Bron" / "theme.css").is_file()
    assert (root / "AGENTS.md").is_file()  # first sync ran
    assert (home / ".local" / "bin" / "bron").is_file()
    assert "Bron health check" in out

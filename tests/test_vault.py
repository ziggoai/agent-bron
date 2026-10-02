from pathlib import Path

import pytest

import bron
from bron.vault import Vault, VaultNotFound

REPO = Path(__file__).resolve().parents[1]


def test_find_walks_up_from_a_subfolder(vault):
    sub = vault.root / "Projects" / "Deep" / "Er"
    sub.mkdir(parents=True)
    assert Vault.find(sub).root == vault.root.resolve()


def test_find_prefers_the_bron_vault_variable(vault, monkeypatch, tmp_path):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    assert Vault.find(tmp_path).root == vault.root.resolve()


def test_find_rejects_a_variable_pointing_elsewhere(monkeypatch, tmp_path):
    monkeypatch.setenv("BRON_VAULT", str(tmp_path))
    with pytest.raises(VaultNotFound, match="not a Bron vault"):
        Vault.find(tmp_path)


def test_find_outside_any_vault_fails(monkeypatch, tmp_path):
    monkeypatch.delenv("BRON_VAULT", raising=False)
    with pytest.raises(VaultNotFound, match="No Bron vault"):
        Vault.find(tmp_path)


def test_paths_and_version(vault):
    assert vault.agents_dir == vault.root / "System" / "Agents"
    assert vault.core_manual == vault.root / "System" / "Core" / "Manual"
    assert vault.state_dir == vault.root / ".bron" / "state"
    assert vault.bron_command == vault.root / ".bron" / "bin" / "bron"
    assert vault.version() == "0.4.0"


def test_engine_version_matches_core_version():
    assert bron.__version__ == (REPO / "core" / "VERSION").read_text().strip()


def test_template_has_exactly_the_approved_top_level(vault):
    visible = sorted(p.name for p in vault.root.iterdir() if not p.name.startswith("."))
    assert visible == ["Knowledge", "Projects", "Routines", "System", "Tickets"]
    system = sorted(p.name for p in vault.system.iterdir() if not p.name.startswith("."))
    assert system == ["Agents", "Connections", "Core", "Helpers", "Memory", "Settings.md", "Skills"]

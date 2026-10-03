import shutil
from pathlib import Path

import pytest

from bron.vault import Vault

REPO = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info", "uv.lock", ".pytest_cache")


@pytest.fixture(autouse=True)
def _private_codex_home(request, tmp_path_factory, monkeypatch):
    """Unit tests never read the user's own Codex config (live tests need the real one)."""
    if "live" in request.node.path.parts:
        return
    monkeypatch.setenv("CODEX_HOME", str(tmp_path_factory.mktemp("codex-home")))
    # Unit tests never reach GitHub: releases come from an empty folder unless a test makes some.
    monkeypatch.setenv("BRON_RELEASE_SOURCE", str(tmp_path_factory.mktemp("no-releases")))


@pytest.fixture
def vault(tmp_path, monkeypatch) -> Vault:
    """A fresh vault from template/ + core/, in a folder whose name has a space and an accent."""
    root = tmp_path / "Cofre Ágora"
    shutil.copytree(REPO / "template", root, ignore=IGNORE)
    shutil.copytree(REPO / "core", root / "System" / "Core", ignore=IGNORE)
    monkeypatch.delenv("BRON_VAULT", raising=False)
    monkeypatch.delenv("BRON_AGENT", raising=False)
    monkeypatch.delenv("BRON_TICKET", raising=False)
    return Vault(root)

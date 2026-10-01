import shutil
from pathlib import Path

import pytest

from bron.vault import Vault

REPO = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info", "uv.lock", ".pytest_cache")


@pytest.fixture
def vault(tmp_path, monkeypatch) -> Vault:
    """A fresh vault from template/ + core/, in a folder whose name has a space and an accent."""
    root = tmp_path / "Cofre Ágora"
    shutil.copytree(REPO / "template", root, ignore=IGNORE)
    shutil.copytree(REPO / "core", root / "System" / "Core", ignore=IGNORE)
    monkeypatch.delenv("BRON_VAULT", raising=False)
    monkeypatch.delenv("BRON_AGENT", raising=False)
    return Vault(root)

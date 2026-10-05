import os
import tempfile
import shutil
from pathlib import Path

import pytest

from bron.vault import Vault

REPO = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info", "uv.lock", ".pytest_cache")


@pytest.fixture(autouse=True)
def _private_kb_socket_folder(request, monkeypatch):
    """Long vault paths put the search helper's socket in a folder under the user's home; unit tests use a private one."""
    if "live" in request.node.path.parts:
        yield
        return
    folder = tempfile.mkdtemp(prefix="bk", dir="/tmp")  # short: socket paths are limited to about 104 bytes
    os.chmod(folder, 0o700)
    monkeypatch.setenv("BRON_KB_SOCKET_DIR", folder)
    yield
    shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(autouse=True)
def _private_codex_home(request, tmp_path_factory, monkeypatch):
    """Unit tests never read the user's own Codex config (live tests need the real one)."""
    if "live" in request.node.path.parts:
        return
    monkeypatch.setenv("CODEX_HOME", str(tmp_path_factory.mktemp("codex-home")))
    # Unit tests never reach GitHub: releases come from an empty folder unless a test makes some.
    monkeypatch.setenv("BRON_RELEASE_SOURCE", str(tmp_path_factory.mktemp("no-releases")))


@pytest.fixture(autouse=True)
def desktop_notices(request, monkeypatch) -> list[str]:
    """Unit tests never show a real Mac notification; a test can read what would have been shown."""
    shown: list[str] = []
    if "live" not in request.node.path.parts:
        from bron import desktop

        monkeypatch.setattr(desktop, "notify", shown.append)
    return shown


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


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: needs real OCR or the meaning model; run with BRON_SLOW=1")


def pytest_collection_modifyitems(config, items):
    import os
    if os.environ.get("BRON_SLOW"):
        return
    skip = pytest.mark.skip(reason="slow; set BRON_SLOW=1")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip)

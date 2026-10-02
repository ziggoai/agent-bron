"""Live setup: create an agent through the command and have it answer. Run with: BRON_LIVE=1 uv run --project core/Engine pytest tests/live/test_setup.py -q -s"""
import os
import subprocess
from pathlib import Path

import pytest

from bron import frontmatter as fm

pytestmark = pytest.mark.skipif(os.environ.get("BRON_LIVE") != "1", reason="live CLI test: set BRON_LIVE=1")

REPO = Path(__file__).resolve().parents[2]


def bron(vault: Path, *args: str) -> str:
    done = subprocess.run([str(vault / ".bron" / "bin" / "bron"), *args], cwd=vault, capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@pytest.fixture(scope="module")
def vault(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("setup") / "Setup Vault"
    subprocess.run([str(REPO / "scripts" / "dev-vault.sh"), str(root)], check=True)
    return root.resolve()


def test_create_a_codex_agent_and_hear_from_it(vault):
    preview = bron(vault, "agent", "create", "--name", "Opsy", "--role", "Operations test agent", "--model", "codex=default", "--runs-in", "codex", "--preview")
    assert preview.startswith("New agent: Opsy (Operations test agent).")
    assert not (vault / "System" / "Agents" / "Opsy").exists()
    assert bron(vault, "agent", "create", "--name", "Opsy", "--role", "Operations test agent", "--model", "codex=default", "--runs-in", "codex").startswith("Created Opsy.")
    out = bron(vault, "ticket", "new", "--to", "Opsy", "--from", "Bron", "--title", "Introduce yourself", "--request", "Introduce yourself in one sentence and include your name.", "--run", "--caller-cli", "claude")
    assert "Opsy" in out.split("Result:", 1)[-1], out


def test_retire_and_bring_back(vault):
    assert "Retired Opsy" in bron(vault, "agent", "retire", "Opsy")
    assert (vault / "System" / "Archive" / "Agents" / "Opsy" / "Agent.md").is_file()
    assert "Opsy is back" in bron(vault, "agent", "restore", "Opsy")
    assert fm.read(vault / "System" / "Agents" / "Bron" / "Agent.md").meta["can_assign_to"] == ["Opsy"]
    assert "all good" in bron(vault, "check") or "0 problem(s)" in bron(vault, "check")

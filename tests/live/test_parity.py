"""Real Claude Code and Codex sessions in a fresh dev vault. Run with: BRON_LIVE=1 uv run --project core/Engine pytest tests/live -q"""
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("BRON_LIVE") != "1", reason="live CLI test: set BRON_LIVE=1")

REPO = Path(__file__).resolve().parents[2]
CODEX_HOOK_FLAG = "--dangerously-bypass-hook-trust"  # from Task 1 Step 2; None if there is no such flag
QUESTION = "Answer in one line and nothing else: your name, then the exact first line of your Bron briefing, then the names of the helpers you can use."


@pytest.fixture(scope="module")
def dev_vault(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("live") / "Live Vault"
    subprocess.run([str(REPO / "scripts" / "dev-vault.sh"), str(root)], check=True)
    return root.resolve()


def check_answer(text: str) -> None:
    assert "Bron" in text
    assert "Bron briefing" in text or "in the user's Bron vault" in text, text
    assert "reader" in text.lower()


def test_claude_session_is_bron(dev_vault):
    done = subprocess.run(["claude", "-p", QUESTION, "--output-format", "json"], cwd=dev_vault, capture_output=True, text=True, timeout=300, check=True)
    check_answer(json.loads(done.stdout)["result"])


def test_codex_session_is_bron(dev_vault):
    command = ["codex", "exec", "--skip-git-repo-check"]  # a `-c projects...trust_level` override is ignored (verification R2)
    if CODEX_HOOK_FLAG:
        command.append(CODEX_HOOK_FLAG)
    done = subprocess.run([*command, QUESTION], cwd=dev_vault, capture_output=True, text=True, timeout=300, check=True)
    check_answer(done.stdout)


def test_claude_cannot_spawn_a_team_member_but_can_use_a_helper(dev_vault):
    bron = str(dev_vault / ".bron" / "bin" / "bron")
    other = dev_vault / "System" / "Agents" / "Otherbot" / "Agent.md"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("---\nname: Otherbot\nrole: Test member\nreports_to: Bron\nruns_in: any\n---\nYour name is Otherbot.\n", encoding="utf-8")
    subprocess.run([bron, "sync"], check=True)
    try:
        ask = "Try to use the otherbot subagent to say hello. Reply with exactly YES if it ran, or NO if you could not use it."
        done = subprocess.run(["claude", "-p", ask, "--output-format", "json"], cwd=dev_vault, capture_output=True, text=True, timeout=300, check=True)
        assert "NO" in json.loads(done.stdout)["result"].upper()
        ask = "Use the reader subagent to read AGENTS.md and tell me its first heading. Reply with the heading text only."
        done = subprocess.run(["claude", "-p", ask, "--output-format", "json"], cwd=dev_vault, capture_output=True, text=True, timeout=300, check=True)
        assert "Bron vault" in json.loads(done.stdout)["result"]
    finally:
        other.unlink()
        other.parent.rmdir()
        subprocess.run([bron, "sync"], check=True)

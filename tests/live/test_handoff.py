"""Real ticket handoffs between Claude Code and Codex. Run with: BRON_LIVE=1 uv run --project core/Engine pytest tests/live/test_handoff.py -q"""
import os
import subprocess
from pathlib import Path

import pytest

from bron.tickets import find_ticket, load_ticket
from bron.vault import Vault

pytestmark = pytest.mark.skipif(os.environ.get("BRON_LIVE") != "1", reason="live CLI test: set BRON_LIVE=1")

REPO = Path(__file__).resolve().parents[2]


def bron(vault: Path, *args: str) -> str:
    done = subprocess.run([str(vault / ".bron" / "bin" / "bron"), *args], cwd=vault, capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@pytest.fixture(scope="module")
def vault(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("handoff") / "Handoff Vault"
    subprocess.run([str(REPO / "scripts" / "dev-vault.sh"), str(root)], check=True)
    root = root.resolve()
    for name, runs_in, extra in (
        ("Gpt", "codex", ""),
        ("Claudia", "claude", "ask_before: [delete-files]\n"),
    ):
        folder = root / "System" / "Agents" / name
        folder.mkdir(parents=True)
        (folder / "Agent.md").write_text(
            f"---\nname: {name}\nrole: Test member\nreports_to: Bron\nruns_in: {runs_in}\n{extra}---\nYou are {name}, a careful test agent. Keep answers short.\n",
            encoding="utf-8",
        )
    agent = root / "System" / "Agents" / "Bron" / "Agent.md"
    agent.write_text(agent.read_text(encoding="utf-8").replace("can_assign_to: []", "can_assign_to: [Gpt, Claudia]"), encoding="utf-8")
    bron(root, "sync")
    return root


def ticket(vault: Path, ticket_id: str):
    return load_ticket(find_ticket(Vault(vault), ticket_id))


def new(vault: Path, to: str, request: str) -> str:
    out = bron(vault, "ticket", "new", "--to", to, "--from", "bron", "--title", f"Test for {to}", "--request", request)
    return out.split()[1].rstrip(":")


def test_claude_hands_a_ticket_to_an_agent_pinned_to_codex(vault):
    tid = new(vault, "Gpt", "What is 17 + 25? Record only the number as the ticket result.")
    bron(vault, "run", tid, "--caller-cli", "claude")
    t = ticket(vault, tid)
    assert t.status == "in-review" and "42" in t.result
    assert "started in Codex" in "\n".join(t.thread)


def test_codex_hands_a_ticket_to_an_agent_pinned_to_claude(vault):
    tid = new(vault, "Claudia", "What is 6 times 7? Record only the number as the ticket result.")
    bron(vault, "run", tid, "--caller-cli", "codex")
    t = ticket(vault, tid)
    assert t.status == "in-review" and "42" in t.result
    assert "started in Claude Code" in "\n".join(t.thread)


def test_question_then_resume_in_the_same_conversation(vault):
    tid = new(vault, "Claudia", "Before doing anything, ask me (mark the ticket blocked with your question) which number to double. After I answer, record the doubled number as the result.")
    bron(vault, "run", tid)
    assert ticket(vault, tid).status == "blocked"
    bron(vault, "ticket", "say", tid, "Double 21.", "--as", "bron")
    bron(vault, "run", tid, "--resume")
    t = ticket(vault, tid)
    assert t.status == "in-review" and "42" in t.result


def test_an_ask_before_action_becomes_needs_your_ok(vault):
    keep = vault / "Projects" / "keep.txt"
    keep.write_text("keep\n", encoding="utf-8")
    tid = new(vault, "Claudia", "Run this exact shell command: rm Projects/keep.txt  Then record what happened as the result.")
    bron(vault, "run", tid)
    t = ticket(vault, tid)
    assert keep.exists()
    assert t.status == "blocked" and "Needs your OK" in "\n".join(t.thread)


def test_connector_scan_registers_existing_connectors(vault):
    out = bron(vault, "connections", "scan")
    assert "Connectors found:" in out
    files = list((vault / "System" / "Connections").glob("*.md"))
    assert files, "no connector files were written"
    assert all("type: native" in f.read_text(encoding="utf-8") for f in files)

"""Live @-mentions between Claude Code and Codex. Run with: BRON_LIVE=1 uv run --project core/Engine pytest tests/live/test_mentions.py -q -s"""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from bron import frontmatter as fm
from bron.tickets import find_ticket, list_tickets, load_ticket
from bron.vault import Vault

pytestmark = pytest.mark.skipif(os.environ.get("BRON_LIVE") != "1", reason="live CLI test: set BRON_LIVE=1")

REPO = Path(__file__).resolve().parents[2]


def bron(vault: Path, *args: str, stdin: str | None = None) -> str:
    done = subprocess.run([str(vault / ".bron" / "bin" / "bron"), *args], cwd=vault, input=stdin, capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@pytest.fixture(scope="module")
def vault(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("mentions") / "Mention Vault"
    subprocess.run([str(REPO / "scripts" / "dev-vault.sh"), str(root)], check=True)
    root = root.resolve()
    for name, runs_in, extra in (("Gpt", "codex", "connections: []\n"), ("Claudia", "claude", "")):
        folder = root / "System" / "Agents" / name
        folder.mkdir(parents=True)
        (folder / "Agent.md").write_text(
            f"---\nname: {name}\nrole: Test member\nreports_to: Bron\nruns_in: {runs_in}\n{extra}---\nYou are {name}, a careful test agent. Keep answers short.\n",
            encoding="utf-8",
        )
    settings = root / "System" / "Settings.md"
    doc = fm.read(settings)
    doc.meta.update(user_name="Tester", company="Test Co")
    fm.write(settings, doc)
    bron(root, "sync")
    return root


def claude(vault: Path, prompt: str, session: str | None = None) -> tuple[dict, float]:
    argv = ["claude", "-p", prompt, "--output-format", "json", "--permission-mode", "acceptEdits", "--allowedTools", "Bash"]
    if session:
        argv += ["--resume", session]
    started = time.time()
    done = subprocess.run(argv, cwd=vault, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(done.stdout), time.time() - started


def chats(vault: Path):
    return [t for t in list_tickets(Vault(vault))[0] if t.kind == "chat"]


def test_a_tag_in_claude_code_reaches_a_codex_agent_and_follow_ups_continue(vault):
    first, seconds = claude(vault, "@gpt What is 17 + 25? Reply with only the number.")
    assert "42" in first["result"] and "Gpt" in first["result"], first["result"]
    found = chats(vault)
    assert len(found) == 1 and found[0].assignee == "gpt"
    assert "started in Codex" in "\n".join(found[0].thread)
    second, _ = claude(vault, "@gpt Now double that number. Reply with only the number.", session=first["session_id"])
    assert "84" in second["result"], second["result"]
    found = chats(vault)
    assert len(found) == 1 and any(" · you: @gpt Now double" in entry for entry in found[0].thread)
    print(f"\n@gpt from Claude Code: first answer {seconds:.1f}s end to end")


def test_a_tag_from_a_codex_session_reaches_a_claude_agent(vault):
    # Codex runs Bron's triggers only after the user approves them (/hooks), so call the trigger as Codex would.
    payload = json.dumps({"prompt": "@claudia What is 6 times 7? Reply with only the number.", "session_id": "live-codex-1", "transcript_path": ""})
    started = time.time()
    note = bron(vault, "hook", "user-prompt", "--cli", "codex", stdin=payload)
    assert "@Claudia is answering this message" in note, note
    tid = note.split("chat ticket ")[1].split(")")[0]
    out = bron(vault, "ticket", "wait", tid)
    assert out.startswith("Claudia:") and "42" in out, out
    assert "started in Claude Code" in "\n".join(load_ticket(find_ticket(Vault(vault), tid)).thread)
    print(f"\n@claudia from Codex: answer {time.time() - started:.1f}s from the trigger")

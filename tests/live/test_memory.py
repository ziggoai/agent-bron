"""Live memory: a real session saves a fact, the summarizer writes a note, search finds it.
Run with: BRON_LIVE=1 uv run --project core/Engine pytest tests/live/test_memory.py -q -s"""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("BRON_LIVE") != "1", reason="live CLI test: set BRON_LIVE=1")

REPO = Path(__file__).resolve().parents[2]
ASK = "Remember that our quarterly reports only include companies with FMV above zero."


def bron(vault: Path, *args: str) -> str:
    done = subprocess.run([str(vault / ".bron" / "bin" / "bron"), *args], cwd=vault, capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def markers(vault: Path) -> list[dict]:
    path = vault / ".bron" / "state" / "markers.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def run_session(cli: str, vault: Path) -> str:
    """One headless session; returns its session id."""
    if cli == "claude":
        done = subprocess.run(["claude", "-p", ASK, "--output-format", "json", "--permission-mode", "acceptEdits", "--allowedTools", "Bash"],
                              cwd=vault, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
        assert done.returncode == 0, done.stdout + done.stderr
        return json.loads(done.stdout)["session_id"]
    done = subprocess.run(["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", ASK],
                          cwd=vault, capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stdout + done.stderr
    found = re.search(r"session id: (\S+)", done.stdout + done.stderr)
    assert found, "codex printed no session id"
    return found.group(1)


def transcript_for(cli: str, session_id: str) -> str:
    root = Path.home() / (".claude/projects" if cli == "claude" else ".codex/sessions")
    hits = list(root.rglob(f"*{session_id}*.jsonl"))
    assert hits, f"no {cli} transcript for {session_id}"
    return str(hits[0])


@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_remember_summarize_and_search(cli, tmp_path):
    if not shutil.which(cli):
        pytest.skip(f"{cli} is not installed")
    root = tmp_path / f"Memory Vault {cli}"
    subprocess.run([str(REPO / "scripts" / "dev-vault.sh"), str(root)], check=True)
    vault = root.resolve()
    bron(vault, "sync")

    started = time.time()
    sid = run_session(cli, vault)
    session_seconds = time.time() - started
    facts = (vault / "System" / "Memory" / "Facts.md").read_text(encoding="utf-8")
    assert "FMV" in facts, facts

    # Codex runs Bron's triggers only once the user approves them, so when no end marker exists, write the one a trigger would.
    if not any(m.get("session_id") == sid and m.get("transcript_path") for m in markers(vault)):
        record = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": "session-end", "cli": cli, "agent": "Bron",
                  "ticket": "", "session_id": sid, "transcript_path": transcript_for(cli, sid)}
        with open(vault / ".bron" / "state" / "markers.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")

    started = time.time()
    bron(vault, "memory", "summarize", "--session", sid)
    # The session-end trigger may already have started a summarizer in the background; then this call quietly yields to it
    # (only one runs at a time), so wait for the note rather than expecting it the moment the call returns.
    folder = vault / "System" / "Agents" / "Bron" / "Memory" / "Conversations"
    while time.time() - started < 240 and not list(folder.rglob("*.md")):
        time.sleep(1)
    summary_seconds = time.time() - started
    notes = list(folder.rglob("*.md"))
    assert len(notes) == 1, (notes, (vault / ".bron" / "logs" / "memory.log").read_text(encoding="utf-8") if (vault / ".bron" / "logs" / "memory.log").exists() else "no log")

    started = time.time()
    found = bron(vault, "memory", "search", "fmv", "--as", "Bron")
    search_seconds = time.time() - started
    assert "FMV" in found, found
    print(f"\n[{cli}] session {session_seconds:.1f}s, summary {summary_seconds:.1f}s, search {search_seconds:.1f}s\n--- note ---\n{notes[0].read_text(encoding='utf-8')}\n--- search ---\n{found}")

"""Live knowledge base: real sessions search documents Bron read and cite the document and page.
Downloads the meaning model (about 220 MB) and installs the reading tools into the temp vault on first use.
The vault, the samples and the search helper's socket folder are temporary, and the helper is stopped at the end.
The CLI sessions themselves log to the real home (~/.claude/projects, ~/.codex/sessions), because both apps need their real login.
Run with: BRON_LIVE=1 uv run --project core/Engine pytest tests/live/test_knowledge.py -q -s"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("BRON_LIVE") != "1", reason="live CLI test: set BRON_LIVE=1")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))

SPA = ["Share Purchase Agreement between Acme Ltda and Example Fund I. Signed in Sao Paulo on January 21, 2025.",
       "Clause 2.1. The purchase price for the shares is USD 2,350,000.00, payable in full at closing by wire transfer.",
       "Clause 3.4. Closing is subject to the delivery of the board approval and the updated cap table."]
CONTRATO = ["Acordo de Acionistas da Acme Ltda. Celebrado em 21 de janeiro de 2025 entre os fundadores e o Fundo.",
            "Cláusula 9.2. O fundador não poderá concorrer com a Companhia pelo prazo de 18 (dezoito) meses após o seu desligamento.",
            "Cláusula 11.1. Qualquer alteração deste acordo exige aprovação escrita de todos os acionistas."]
QUESTIONS = {
    "clause": ("In the Acme shareholders agreement, how long can a founder not compete after leaving the company? "
               "Answer in English.", r"18|eighteen", "acme-acordo-de-acionistas", 2),
    "amount": ("What is the purchase price in the Acme share purchase agreement?", r"2,350,000", "acme-spa", 2),
}


def bron(vault: Path, *args: str, env=None) -> str:
    done = subprocess.run([str(vault / ".bron" / "bin" / "bron"), *args], cwd=vault, capture_output=True, text=True,
                          timeout=1800, env=env)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def stop_helper(vault: Path) -> None:
    """Stop the warm search helper this vault started (the one whose working folder is the vault)."""
    found = subprocess.run(["pgrep", "-f", "kb serve"], capture_output=True, text=True).stdout.split()
    for pid in found:
        where = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
        if f"n{vault}" in where.splitlines():
            subprocess.run(["kill", pid])


@pytest.fixture(scope="module")
def vault(tmp_path_factory):
    from kbkit import make_text_pdf

    socket_dir = tempfile.mkdtemp(prefix="bk", dir="/tmp")  # private, short: socket paths are limited in length
    os.chmod(socket_dir, 0o700)
    before = os.environ.get("BRON_KB_SOCKET_DIR")
    os.environ["BRON_KB_SOCKET_DIR"] = socket_dir
    root = tmp_path_factory.mktemp("knowledge") / "Knowledge Vault"
    try:
        subprocess.run([str(REPO / "scripts" / "dev-vault.sh"), str(root)], check=True)
        root = root.resolve()
        bron(root, "sync")
        samples = root.parent / "samples"
        samples.mkdir()
        make_text_pdf(samples / "acme-spa.pdf", SPA)
        make_text_pdf(samples / "acme-acordo-de-acionistas.pdf", CONTRATO)
        started = time.time()
        out = bron(root, "kb", "add", str(samples / "acme-spa.pdf"), str(samples / "acme-acordo-de-acionistas.pdf"))
        print(f"\n[add] {time.time() - started:.1f}s\n{out}")
        if "in the background" in out:  # the first add sets the tools up in the background, then reads
            status = wait_for_reading(root, started)
            print(f"[background] {time.time() - started:.1f}s\n{status}")
        yield root
    finally:
        stop_helper(root)
        if before is None:
            os.environ.pop("BRON_KB_SOCKET_DIR", None)
        else:
            os.environ["BRON_KB_SOCKET_DIR"] = before
        shutil.rmtree(socket_dir, ignore_errors=True)


def wait_for_reading(vault: Path, started: float, limit: float = 1800) -> str:
    """Wait for the background reading to finish (the first one installs the tools and downloads the model)."""
    while True:
        status = bron(vault, "kb", "status")
        if "Nothing is being read." in status and "Last batch" in status:
            return status
        assert time.time() - started < limit, status
        time.sleep(5)


def ask(cli: str, vault: Path, question: str) -> str:
    prompt = question
    if cli == "claude":
        done = subprocess.run(["claude", "-p", prompt, "--permission-mode", "acceptEdits", "--allowedTools", "Bash(.bron/bin/bron kb *)"],
                              cwd=vault, capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout
    last = vault.parent / "last-answer.txt"
    last.unlink(missing_ok=True)
    done = subprocess.run(["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "-o", str(last), prompt],
                          cwd=vault, capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stdout + done.stderr
    return last.read_text(encoding="utf-8") if last.exists() else done.stdout


def test_the_samples_were_read_and_search_finds_them(vault):
    listing = bron(vault, "kb", "list")
    assert "acme-spa.pdf" in listing and "acme-acordo-de-acionistas.pdf" in listing
    started = time.time()
    found = bron(vault, "kb", "search", "non-compete period after a founder leaves")
    print(f"[search] {time.time() - started:.1f}s\n{found}")
    assert "18" in found and "p. 2" in found


@pytest.mark.parametrize("cli", ["claude", "codex"])
@pytest.mark.parametrize("which", ["clause", "amount"])
def test_an_agent_searches_and_cites_document_and_page(cli, which, vault):
    if not shutil.which(cli):
        pytest.skip(f"{cli} is not installed")
    question, number, doc, page = QUESTIONS[which]
    started = time.time()
    answer = ask(cli, vault, question)
    seconds = time.time() - started
    print(f"\n[{cli}/{which}] {seconds:.1f}s\n{answer}")
    assert re.search(number, answer, re.I), answer
    assert doc in answer.lower().replace(" ", "-").replace(".pdf", "") or doc.replace("-", " ") in answer.lower(), answer
    assert re.search(rf"(p\.|pp\.|page|p[aá]gina)\s*{page}\b", answer, re.I), answer

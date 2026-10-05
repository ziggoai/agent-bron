"""Live knowledge wiki, in each CLI: a session reads a Drive file shared with the user into the wiki, a folder is
written into the wiki in the background, and a question is answered from the pages with a citation.
Downloads the meaning model (about 220 MB) and installs the reading tools into each temporary vault on first use.
The vaults, the fake Google Drive folder and the search helper's socket folder are temporary, and the helper is stopped
at the end. The CLI sessions themselves log to the real home (~/.claude/projects, ~/.codex/sessions), because both apps
need their real login.
Run with: BRON_LIVE=1 uv run --project core/Engine pytest tests/live/test_knowledge.py -q -s"""
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

LEASE = ["Lease agreement between Northwind Properties Ltd (landlord) and Harbor Bakery LLC (tenant) for shop 4, "
         "12 Example Street. Signed on March 1, 2025.",
         "Clause 3. The monthly rent is USD 4,200.00, due on the first day of each month. The lease runs for three "
         "years from March 1, 2025."]
FOLDER = {
    "invoice-2025-04.pdf": ["Invoice 1042 from Northwind Properties Ltd to Harbor Bakery LLC, dated April 1, 2025.",
                            "Rent for April 2025 for shop 4: USD 4,200.00. Payment due April 10, 2025."],
    "rent-increase-2026.pdf": ["Letter from Northwind Properties Ltd to Harbor Bakery LLC, dated January 10, 2026.",
                               "From March 1, 2026 the monthly rent for shop 4 is USD 4,450.00, as clause 3 of the "
                               "lease allows."],
    "insurance-2025.pdf": ["Insurance policy for Harbor Bakery LLC, shop 4, 12 Example Street, from May 1, 2025.",
                           "Cover: fire and water damage up to USD 250,000.00. Yearly premium: USD 1,180.00."],
}


def bron(vault: Path, *args: str, timeout: int = 1800) -> str:
    done = subprocess.run([str(vault / ".bron" / "bin" / "bron"), *args], cwd=vault, capture_output=True, text=True,
                          timeout=timeout)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def stop_helper(vault: Path) -> None:
    """Stop the warm search helper this vault started (the one whose working folder is the vault)."""
    found = subprocess.run(["pgrep", "-f", "kb serve"], capture_output=True, text=True).stdout.split()
    for pid in found:
        where = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
        if f"n{vault}" in where.splitlines():
            subprocess.run(["kill", pid])


def fake_drive(account: Path) -> Path:
    """Google Drive for desktop's layout: My Drive with a folder, and a file in a folder shared with the user."""
    from kbkit import make_text_pdf, set_drive_id

    my_drive = account / "My Drive"
    shared = account / ".shortcut-targets-by-id" / "SHAREDLEASE" / "Shared with me"
    shared.mkdir(parents=True)
    my_drive.mkdir(parents=True)
    set_drive_id(make_text_pdf(shared / "lease.pdf", LEASE), "LEASE1")
    folder = my_drive / "Shop 4"
    folder.mkdir()
    set_drive_id(folder, "SHOP4")
    for i, (name, pages) in enumerate(FOLDER.items()):
        set_drive_id(make_text_pdf(folder / name, pages), f"SHOPFILE{i}")
    return my_drive


@pytest.fixture(scope="module", params=["claude", "codex"])
def vault(request, tmp_path_factory):
    from vaultkit import set_meta

    cli = request.param
    if not shutil.which(cli):
        pytest.skip(f"{cli} is not installed")
    socket_dir = tempfile.mkdtemp(prefix="bk", dir="/tmp")  # private, short: socket paths are limited in length
    os.chmod(socket_dir, 0o700)
    before = {key: os.environ.get(key) for key in ("BRON_KB_SOCKET_DIR", "BRON_DRIVE_ROOT")}
    base = tmp_path_factory.mktemp(f"wiki-{cli}")
    root = base / "Wiki Vault"
    try:
        os.environ["BRON_KB_SOCKET_DIR"] = socket_dir
        os.environ["BRON_DRIVE_ROOT"] = str(fake_drive(base / "GoogleDrive-test"))
        subprocess.run([str(REPO / "scripts" / "dev-vault.sh"), str(root)], check=True)
        root = root.resolve()
        set_meta(root / "System" / "Settings.md", default_cli=cli)  # the background run uses this CLI
        bron(root, "sync")
        started = time.time()
        bron(root, "kb", "search", "warm up")  # installs the tools and loads the model, outside the timings
        print(f"\n[{cli} setup] {time.time() - started:.0f}s")
        yield cli, root
    finally:
        stop_helper(root)
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(socket_dir, ignore_errors=True)


def ask(cli: str, vault: Path, prompt: str) -> str:
    if cli == "claude":
        done = subprocess.run(["claude", "-p", prompt, "--permission-mode", "acceptEdits",
                               "--allowedTools", "Bash(.bron/bin/bron *)"],
                              cwd=vault, capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout
    last = vault.parent / "last-answer.txt"
    last.unlink(missing_ok=True)
    done = subprocess.run(["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "-o", str(last), prompt],
                          cwd=vault, capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stdout + done.stderr
    return last.read_text(encoding="utf-8") if last.exists() else done.stdout


def wait_until_idle(vault: Path, started: float, limit: float = 1800) -> str:
    while True:
        status = bron(vault, "kb", "status")
        if "Nothing is being read." in status and "Last batch" in status:
            return status
        assert time.time() - started < limit, status
        time.sleep(10)


def pages(vault: Path, folder: str) -> list[Path]:
    return sorted((vault / "Knowledge" / folder).glob("*.md"))


def test_reading_a_shared_drive_file_takes_seconds(vault):
    cli, root = vault
    started = time.time()
    out = bron(root, "kb", "add", "https://drive.google.com/file/d/LEASE1/view")
    seconds = time.time() - started
    print(f"\n[{cli} extract] {seconds:.1f}s\n{out}")
    assert out.startswith("Read lease.pdf (2 pages, 0 scanned) — doc ") and seconds < 5


def test_one_document_is_read_into_the_wiki_in_a_conversation(vault):
    cli, root = vault
    started = time.time()
    answer = ask(cli, root, "Read this document into the wiki: https://drive.google.com/file/d/LEASE1/view")
    seconds = time.time() - started
    print(f"\n[{cli} one document] {seconds:.1f}s\n{answer}")
    found = pages(root, "Documents")
    assert found, "no document page was written"
    text = found[0].read_text(encoding="utf-8")
    assert "doc:" in text and re.search(r"p\. ?2", text) and "[[" in text
    assert "] ingest | [[" in (root / "Knowledge" / "log.md").read_text(encoding="utf-8")
    assert f"[[{found[0].stem}]]" in (root / "Knowledge" / "index.md").read_text(encoding="utf-8")
    assert seconds < 60


def test_a_folder_is_written_into_the_wiki_in_the_background(vault):
    cli, root = vault
    started = time.time()
    out = bron(root, "kb", "add", "https://drive.google.com/drive/folders/SHOP4")
    print(f"\n[{cli} folder] {out}")
    assert out.startswith("Reading 3 documents into the wiki in the background")
    status = wait_until_idle(root, started)
    print(f"[{cli} folder done] {time.time() - started:.0f}s\n{status}")
    assert len(pages(root, "Documents")) >= 4 and pages(root, "Organisations")
    assert "Read the Shop 4 folder into the wiki" in bron(root, "ticket", "list")
    assert "] check | " in (root / "Knowledge" / "log.md").read_text(encoding="utf-8")
    print(bron(root, "wiki", "check"))


def test_nothing_from_drive_was_copied_into_the_vault(vault):
    _, root = vault
    assert [p for p in root.rglob("*.pdf") if ".bron" not in p.parts] == []


def test_a_question_is_answered_from_the_wiki_with_a_citation(vault):
    cli, root = vault
    started = time.time()
    answer = ask(cli, root, "What is the monthly rent for shop 4 now, and what was it before? Cite your sources.")
    print(f"\n[{cli} question] {time.time() - started:.1f}s\n{answer}")
    assert "4,450" in answer and "4,200" in answer
    assert re.search(r"(p\.|page|p[aá]gina)\s*2\b", answer, re.I), answer

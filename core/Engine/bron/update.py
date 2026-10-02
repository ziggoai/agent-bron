"""`bron update`: refresh this vault's framework from the Bron project it was installed from.

Interim version: it re-runs the project's scripts/dev-vault.sh, which replaces System/Core,
reinstalls the engine and re-syncs, while never overwriting the user's own files. Plan 4
replaces this with GitHub releases, a backup and "undo the update", behind the same command.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .vault import Vault

SOURCE_FILE = "source"  # in .bron/: the project folder this vault was installed from
TAIL_LINES = 12


def source_project(vault: Vault) -> Path | None:
    try:
        text = (vault.bron_dir / SOURCE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return Path(text) if text else None


def run_update(vault: Vault) -> tuple[int, str]:
    project = source_project(vault)
    if project is None:
        return 1, (
            "Bron doesn't know which Bron project this vault was installed from. "
            "Run scripts/dev-vault.sh from the Bron project once for this vault; after that, `bron update` works."
        )
    script = project / "scripts" / "dev-vault.sh"
    if not script.is_file():
        return 1, (
            f"Bron can't find the Bron project at {project} any more. "
            "If it moved, run scripts/dev-vault.sh from its new place once for this vault."
        )
    before = vault.version()
    try:
        done = subprocess.run(["bash", str(script), str(vault.root)], capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"The update didn't finish ({exc.__class__.__name__}). Nothing of yours was changed by it."
    output = (done.stdout + done.stderr).strip()
    tail = "\n".join(output.splitlines()[-TAIL_LINES:])
    if done.returncode != 0:
        return 1, f"The update didn't finish (exit code {done.returncode}). Your own files were not touched. Details:\n{tail}"
    after = vault.version()
    if after != before:
        headline = f"Updated Bron from version {before} to {after}."
    else:
        headline = f"Bron is already on the latest version ({after}); its setup was refreshed."
    scan_note = ""
    if vault.bron_command.is_file():
        try:
            scanned = subprocess.run([str(vault.bron_command), "connections", "scan"], capture_output=True, text=True, timeout=300)
            scan_note = "\n" + scanned.stdout.strip() if scanned.stdout.strip() else ""
        except (OSError, subprocess.TimeoutExpired):
            scan_note = "\nConnectors weren't re-checked this time."
    return 0, f"{headline} Your own files were kept.\n{tail}{scan_note}\nStart a new session so every change applies."

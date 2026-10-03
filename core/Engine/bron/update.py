"""`bron update`: the newest release from GitHub (or a Bron project folder), previewed, backed up and undoable.

The running (old) engine downloads and checks the release, backs up System/Core, swaps it in and
reinstalls the engine; then the new engine finishes in a fresh process (`bron _after-update`):
starting files, migrations, Obsidian, sync, health check. Any failure puts the backup back.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .install import copy_template, replace_core, write_source
from .releases import ProjectFolder, ReleaseError, changes_between, is_newer
from .statefile import locked
from .vault import Vault

KEEP_BACKUPS = 3
TAIL_LINES = 15
_BACKUP = re.compile(r"^core-(\d+\.\d+\.\d+)-(\d{8}-\d{6})(?:-(\d+))?$")
NEW_SESSION = "Start a new session so every change applies."


def find_uv() -> str | None:
    home = Path.home()
    for candidate in (shutil.which("uv"), home / ".local/bin/uv", home / ".cargo/bin/uv", "/opt/homebrew/bin/uv", "/usr/local/bin/uv"):
        if candidate and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def install_engine(vault: Vault) -> None:
    """Reinstall the engine in .bron/venv from System/Core/Engine. Raises RuntimeError with a plain reason."""
    uv = find_uv()
    if uv is None:
        raise RuntimeError("uv (the tool Bron uses to install its engine) wasn't found")
    venv = vault.bron_dir / "venv"
    for command in (
        [uv, "venv", "--quiet", "--allow-existing", "--python", "3.12", str(venv)],
        [uv, "pip", "install", "--quiet", "--python", str(venv / "bin" / "python"), "--reinstall-package", "bron-engine", str(vault.core / "Engine")],
    ):
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"the engine couldn't be installed ({exc.__class__.__name__})") from exc
        if done.returncode != 0:
            raise RuntimeError("the engine couldn't be installed: " + (done.stderr or done.stdout).strip()[-400:])


def after_update(vault: Vault, previous: str, tree: Path | None) -> tuple[int, str]:
    """Let the newly installed engine finish, in a fresh process."""
    command = [str(vault.bron_command), "_after-update", "--previous", previous]
    if tree is not None:
        command += ["--tree", str(tree)]
    try:
        done = subprocess.run(command, cwd=vault.root, capture_output=True, text=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"The new version couldn't finish setting up ({exc.__class__.__name__})."
    return done.returncode, (done.stdout + done.stderr).strip()


def finish(vault: Vault, previous: str, tree: Path | None) -> int:
    """Run by the new engine: starting files, migrations, Obsidian, sync, health check. Prints what happened."""
    try:
        return _finish(vault, previous, tree)
    except Exception as exc:  # noqa: BLE001 - never show a traceback to the user
        print(f"Bron's new version couldn't finish setting up ({exc.__class__.__name__}: {exc})")
        return 1


def _finish(vault: Vault, previous: str, tree: Path | None) -> int:
    from .cli import _check, _sync
    from .migrations import apply_pending
    from .obsidian import BundleError, refresh_bundle
    from .setup import SetupError

    if tree is not None:
        copy_template(vault.root, tree / "template")
    try:
        for line in apply_pending(vault, previous, vault.version()):
            print(line)
    except SetupError as exc:
        print(f"A change to your setup that this version needs couldn't be made: {exc}")
        return 1
    try:
        for line in refresh_bundle(vault.root, vault.core):
            print(line)
    except BundleError as exc:
        print(f"Obsidian: {exc}")
    if _sync(vault, dry_run=False) != 0:
        return 1
    _check(vault)
    return 0


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def backups(vault: Vault) -> list[Path]:
    """Core backups, oldest first."""
    if not vault.backups_dir.is_dir():
        return []
    found = []
    for path in vault.backups_dir.iterdir():
        match = _BACKUP.match(path.name)
        if match and path.is_dir():
            found.append(((match.group(2), int(match.group(3) or 0)), path))
    return [path for _, path in sorted(found)]


def prune_backups(vault: Vault) -> None:
    for old in backups(vault)[:-KEEP_BACKUPS]:
        shutil.rmtree(old, ignore_errors=True)


def backup_core(vault: Vault, *, stamp: str | None = None, prune: bool = True) -> Path:
    base = f"core-{vault.version()}-{stamp or _stamp()}"
    dest = vault.backups_dir / base
    n = 1
    while dest.exists():
        n += 1
        dest = vault.backups_dir / f"{base}-{n}"
    try:
        vault.backups_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(vault.core, dest, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
    except OSError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    if prune:
        prune_backups(vault)
    return dest


def _version_of(backup: Path) -> str:
    match = _BACKUP.match(backup.name)
    return match.group(1) if match else "?"


def _tail(text: str) -> str:
    return "\n".join(text.strip().splitlines()[-TAIL_LINES:])


def _restore(vault: Vault, backup: Path) -> tuple[bool, str]:
    """Put a backed-up System/Core back with its engine. Returns (core put back, extra note about problems)."""
    try:
        replace_core(vault.root, backup)
    except Exception:  # noqa: BLE001 - the rollback itself must not crash
        try:
            where = backup.relative_to(vault.root)
        except ValueError:
            where = backup
        return False, f" Putting the old version back didn't work either; a copy of it is in {where}. Run the install command again to repair it."
    try:
        install_engine(vault)
    except RuntimeError as exc:
        return True, f" Its engine couldn't be reinstalled ({exc}); run the install command again to repair it."
    try:
        subprocess.run([str(vault.bron_command), "sync"], cwd=vault.root, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return True, ""


def _safety_copy(vault: Vault, dest: Path) -> None:
    shutil.copytree(vault.core, dest, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))


def preview(vault: Vault, source) -> tuple[int, str]:
    current = vault.version()
    try:
        latest = source.latest()
        if latest is None:
            return 1, "Bron hasn't published a release yet."
        if not is_newer(latest, current):
            return 0, f"Bron is up to date (version {current})."
        notes = changes_between(source.changelog(latest), current, latest) or "(No release notes were found.)"
    except ReleaseError as exc:
        return 1, str(exc)
    return 0, (
        f"Bron {latest} is available (you have {current}). What's new:\n\n{notes}\n\n"
        "Updating keeps all your own files, and the current version is backed up first so it can be undone."
    )


def apply(vault: Vault, source) -> tuple[int, str]:
    with locked(vault.state_dir / "update.json"):
        current = vault.version()
        try:
            latest = source.latest()
        except ReleaseError as exc:
            return 1, str(exc)
        if latest is None:
            return 1, "Bron hasn't published a release yet."
        refresh = isinstance(source, ProjectFolder) and latest == current
        if not refresh and not is_newer(latest, current):
            return 0, f"Bron is up to date (version {current})."
        with tempfile.TemporaryDirectory(prefix="bron-update-") as work:
            try:
                tree = source.fetch(latest, Path(work))
            except ReleaseError as exc:
                return 1, str(exc)
            except OSError as exc:
                return 1, f"The new version couldn't be prepared ({exc.strerror or exc.__class__.__name__}); nothing was changed."
            # A real update keeps a backup (its undo point). A same-version refresh keeps only a
            # temporary safety copy, so development refreshes never push out real undo points.
            try:
                if refresh:
                    backup = Path(work) / "safety" / "Core"
                    _safety_copy(vault, backup)
                else:
                    backup = backup_core(vault, prune=False)
            except OSError as exc:
                return 1, f"A backup of the current version couldn't be made ({exc.strerror or exc.__class__.__name__}); nothing was changed."
            try:
                replace_core(vault.root, tree / "core")
                install_engine(vault)
                code, output = after_update(vault, current, tree)
                if code != 0:
                    raise RuntimeError("the new version couldn't finish setting up:\n" + _tail(output))
            except Exception as exc:  # noqa: BLE001 - every failure puts the old version back
                restored, note = _restore(vault, backup)
                if restored and not refresh:
                    shutil.rmtree(backup, ignore_errors=True)  # it equals the live version again: not an undo point
                return 1, f"The update to {latest} didn't finish ({exc}). Bron went back to version {current}.{note} Your own files were kept."
    prune_backups(vault)
    if isinstance(source, ProjectFolder):
        write_source(vault.root, str(source.folder))
    if refresh:
        headline = f"Bron is already on the latest version ({current}); its setup was refreshed."
    else:
        headline = f"Updated Bron from version {current} to {latest}."
    return 0, f"{headline} Your own files were kept.\n{_tail(output)}\n{NEW_SESSION}"


def undo(vault: Vault) -> tuple[int, str]:
    with locked(vault.state_dir / "update.json"):
        current = vault.version()
        for stale in [b for b in backups(vault) if _version_of(b) == current]:
            shutil.rmtree(stale, ignore_errors=True)  # a leftover of the version already live
        found = backups(vault)
        if not found:
            return 1, "There's no earlier version of Bron to go back to."
        target = found[-1]
        with tempfile.TemporaryDirectory(prefix="bron-undo-") as work:
            safety = Path(work) / "Core"
            try:
                _safety_copy(vault, safety)
            except OSError as exc:
                return 1, f"Going back couldn't start ({exc.strerror or exc.__class__.__name__}); nothing was changed."
            try:
                replace_core(vault.root, target)
                install_engine(vault)
                code, output = after_update(vault, current, None)
                if code != 0:
                    raise RuntimeError("the earlier version couldn't finish setting up:\n" + _tail(output))
            except Exception as exc:  # noqa: BLE001
                _, note = _restore(vault, safety)
                return 1, f"Going back didn't work ({exc}). Bron stayed on version {current}.{note}"
        shutil.rmtree(target, ignore_errors=True)
    return 0, f"Went back from version {current} to {_version_of(target)}. Your own files were kept.\n{_tail(output)}\n{NEW_SESSION}"

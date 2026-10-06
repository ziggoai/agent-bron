"""`bron update`: the newest release from GitHub (or a Bron project folder), previewed, backed up and undoable.

The running (old) engine downloads and checks the release, backs up System/Core, swaps it in and
reinstalls the engine; then the new engine finishes in a fresh process (`bron _after-update`):
starting files, migrations, Obsidian, sync, health check. Any failure puts the backup back.

While System/Core is being swapped, .bron/state/update-in-progress.json names the copy to go back
to. Ctrl-C, SIGTERM and SIGHUP roll back like any failure; if the process dies anyway, the next
`bron update` finishes going back first, and `bron check` reports it.
"""
from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterator

from .install import copy_template, replace_core, write_source
from .releases import ProjectFolder, ReleaseError, changes_between, is_newer
from .statefile import locked, read_json, write_json
from .vault import Vault

KEEP_BACKUPS = 3
TAIL_LINES = 15
_BACKUP = re.compile(r"^core-(\d+\.\d+\.\d+)-(\d{8}-\d{6})(?:-(\d+))?$")
NEW_SESSION = "Start a new session so every change applies."
MARKER = "update-in-progress.json"
UPDATE_LOCK = "update.json"  # locked(state_dir / UPDATE_LOCK) while an update, undo or heal runs
REPAIR = "run the install command again to repair it (it installs the newest version)"
STOP_SIGNALS = (signal.SIGTERM, signal.SIGHUP)


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
    _tidy(vault)
    if _sync(vault, dry_run=False) != 0:
        return 1
    _check(vault)
    return 0


def _tidy(vault: Vault) -> None:
    """Leftovers of earlier versions that nothing needs: lock files next to tickets, and system files and zips of
    files already read that were recorded as documents Bron couldn't read."""
    from .kb.ingest import tidy_failed
    from .tickets import clear_old_locks

    for step in (clear_old_locks, tidy_failed):
        try:
            step(vault)
        except Exception:  # noqa: BLE001 - tidying never fails an update
            pass


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
    except BaseException:  # a failure or Ctrl-C never leaves a half copy behind
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


def _result_tail(output: str) -> str:
    """The tail of the output without the Obsidian restart note, then the note once as the very last line if it was there."""
    from .obsidian import RESTART_NOTE

    lines = [line for line in output.strip().splitlines() if line.strip() != RESTART_NOTE]
    found = len(lines) != len(output.strip().splitlines())
    return "\n".join([_tail("\n".join(lines)), NEW_SESSION] + ([RESTART_NOTE] if found else []))


def _where(vault: Vault, path: Path) -> str:
    try:
        return path.relative_to(vault.root).as_posix()
    except ValueError:
        return str(path)


def marker_path(vault: Vault) -> Path:
    return vault.state_dir / MARKER


def _begin(vault: Vault, previous: str, restore_from: Path) -> None:
    write_json(marker_path(vault), {"previous": previous, "restore_from": _where(vault, restore_from)})


def _end(vault: Vault) -> None:
    marker_path(vault).unlink(missing_ok=True)


class Stopped(BaseException):
    """SIGTERM or SIGHUP arrived while Bron's files were being swapped."""

    def __init__(self, signum: int):
        super().__init__(signum)
        self.signum = signum


def _raise_stopped(signum, frame) -> None:
    raise Stopped(signum)


@contextlib.contextmanager
def _signals(handler, signals) -> Iterator[None]:
    """Use `handler` for these signals for a while, then put the previous handlers back."""
    previous = {}
    for sig in signals:
        try:
            previous[sig] = signal.signal(sig, handler)
        except (ValueError, OSError):  # not the main thread
            pass
    try:
        yield
    finally:
        for sig, old in previous.items():
            signal.signal(sig, old)


def _shielded():
    """While the old version is being put back, Ctrl-C, SIGTERM and SIGHUP are held off (uv too)."""
    return _signals(signal.SIG_IGN, (signal.SIGINT, *STOP_SIGNALS))


def _restore(vault: Vault, copy: Path, version: str) -> tuple[bool, str]:
    """Put a copy of System/Core back with its engine. Returns (fully back, one plain sentence)."""
    try:
        replace_core(vault.root, copy)
    except Exception:  # noqa: BLE001 - the rollback itself must not crash
        return False, f"Putting version {version} back didn't work either. A copy of it is kept in {_where(vault, copy)}; {REPAIR}."
    try:
        install_engine(vault)
    except Exception as exc:  # noqa: BLE001
        return False, (
            f"Bron's files went back to version {version}, but its engine couldn't be reinstalled ({exc}); "
            f"a copy of that version is kept in {_where(vault, copy)}; {REPAIR}."
        )
    try:
        subprocess.run([str(vault.bron_command), "sync"], cwd=vault.root, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return True, f"Bron went back to version {version}."


def _how(failure: BaseException, what: str, failed: str) -> str:
    """'<what> was stopped before it finished.' for Ctrl-C and signals, else '<what> <failed> (<reason>).'"""
    if isinstance(failure, (KeyboardInterrupt, Stopped)):
        return f"{what} was stopped before it finished."
    return f"{what} {failed} ({str(failure) or failure.__class__.__name__})."


def _guarded(vault: Vault, previous: str, copy: Path, steps: Callable[[], str]) -> tuple[str | None, BaseException | None, str]:
    """Run the risky steps with the marker set. On any failure (Ctrl-C and SIGTERM/SIGHUP too) put
    `copy` back. Returns (output, None, "") on success or (None, the failure, a plain sentence)."""
    _begin(vault, previous, copy)
    try:
        with _signals(_raise_stopped, STOP_SIGNALS):
            output = steps()
    except BaseException as exc:  # noqa: BLE001 - every failure, even Ctrl-C, puts the old version back
        with _shielded():
            back, sentence = _restore(vault, copy, previous)
            if back:
                _end(vault)
                shutil.rmtree(copy, ignore_errors=True)  # it equals the live version again
        return None, exc, sentence
    _end(vault)
    return output, None, ""


def _failed(exc: BaseException, message: str) -> tuple[int, str]:
    """The result of a failed swap: Ctrl-C prints and stops; SIGTERM/SIGHUP exit as killed."""
    if isinstance(exc, KeyboardInterrupt):
        print(message, flush=True)
        exc.bron_reported = True  # cli.py adds nothing more
        raise exc
    if isinstance(exc, Stopped):
        return 128 + exc.signum, message
    if not isinstance(exc, Exception):
        print(message, flush=True)
        raise exc
    return 1, message


def heal(vault: Vault) -> tuple[int, str | None]:
    """Finish going back after an update that was interrupted (its marker was left behind)."""
    if not marker_path(vault).exists():
        return 0, None
    with locked(vault.state_dir / UPDATE_LOCK):
        if not marker_path(vault).exists():
            return 0, None  # another update finished it while this one waited for the lock
        data = read_json(marker_path(vault), {})
        where = data.get("restore_from")
        copy = vault.root / where if isinstance(where, str) and where else None
        if copy is None or not (copy / "VERSION").is_file():
            return 1, f"A previous update was interrupted, and the copy Bron needs to go back is missing; {REPAIR}."
        previous = str(data.get("previous") or (copy / "VERSION").read_text(encoding="utf-8").strip())
        with _shielded():
            back, sentence = _restore(vault, copy, previous)
        if not back:
            return 1, f"A previous update was interrupted, and going back didn't finish. {sentence}"
        _end(vault)
        shutil.rmtree(copy, ignore_errors=True)
    return 0, f"A previous update was interrupted; Bron went back to version {previous}."


def _safety_dir(vault: Vault) -> Path:
    base = f"safety-{vault.version()}-{_stamp()}"
    dest = vault.backups_dir / base
    n = 1
    while dest.exists():
        n += 1
        dest = vault.backups_dir / f"{base}-{n}"
    return dest


def _safety_copy(vault: Vault) -> Path:
    """A copy of the live System/Core under .bron/backups (not an undo point), kept while the marker is."""
    dest = _safety_dir(vault)
    try:
        vault.backups_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(vault.core, dest, symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
    except BaseException:  # a failure or Ctrl-C never leaves a half copy behind
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return dest


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
    with locked(vault.state_dir / UPDATE_LOCK):
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
            # safety copy, so development refreshes never push out real undo points.
            try:
                backup = _safety_copy(vault) if refresh else backup_core(vault, prune=False)
            except OSError as exc:
                return 1, f"A backup of the current version couldn't be made ({exc.strerror or exc.__class__.__name__}); nothing was changed."

            def steps() -> str:
                replace_core(vault.root, tree / "core")
                install_engine(vault)
                code, output = after_update(vault, current, tree)
                if code != 0:
                    raise RuntimeError("the new version couldn't finish setting up:\n" + _tail(output))
                return output

            output, failure, sentence = _guarded(vault, current, backup, steps)
            if failure is not None:
                head = _how(failure, f"The update to {latest}", "didn't finish")
                return _failed(failure, f"{head} {sentence} Your own files were kept.")
            with _shielded():  # done: a late Ctrl-C mustn't leave the tidy-up half done
                if refresh:
                    shutil.rmtree(backup, ignore_errors=True)
                prune_backups(vault)
                if isinstance(source, ProjectFolder):
                    write_source(vault.root, str(source.folder))
    if refresh:
        headline = f"Bron is already on the latest version ({current}); its setup was refreshed."
    else:
        headline = f"Updated Bron from version {current} to {latest}."
    return 0, f"{headline} Your own files were kept.\n{_result_tail(output)}"


def undo(vault: Vault) -> tuple[int, str]:
    with locked(vault.state_dir / UPDATE_LOCK):
        current = vault.version()
        for stale in [b for b in backups(vault) if _version_of(b) == current]:
            shutil.rmtree(stale, ignore_errors=True)  # a leftover of the version already live
        found = backups(vault)
        if not found:
            return 1, "There's no earlier version of Bron to go back to."
        target = found[-1]
        try:
            safety = _safety_copy(vault)
        except OSError as exc:
            return 1, f"Going back couldn't start ({exc.strerror or exc.__class__.__name__}); nothing was changed."

        def steps() -> str:
            replace_core(vault.root, target)
            install_engine(vault)
            code, output = after_update(vault, current, None)
            if code != 0:
                raise RuntimeError("the earlier version couldn't finish setting up:\n" + _tail(output))
            return output

        output, failure, sentence = _guarded(vault, current, safety, steps)
        if failure is not None:
            if sentence == f"Bron went back to version {current}.":
                sentence = f"Bron stayed on version {current}."
            return _failed(failure, _how(failure, "Going back", "didn't work") + " " + sentence)
        with _shielded():
            shutil.rmtree(safety, ignore_errors=True)
            shutil.rmtree(target, ignore_errors=True)
    return 0, f"Went back from version {current} to {_version_of(target)}. Your own files were kept.\n{_result_tail(output)}"

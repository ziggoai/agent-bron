"""Setup changes: previewed on a copy of System/, then applied in one step that can't leave a broken setup."""
from __future__ import annotations

import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .check import has_errors, run_checks
from .loader import load
from .model import Issue
from .sync import needs_sync, output_issues, plan_files, run_sync
from .vault import Vault

_IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.pyc", ".pytest_cache")


class SetupError(ValueError):
    """A change that can't be made, with the reason in plain words."""


@dataclass
class Change:
    summary: list[str] = field(default_factory=list)  # plain-language lines shown before the user says yes
    writes: dict[str, str] = field(default_factory=dict)  # vault-relative path -> the file's new text
    moves: list[tuple[str, str]] = field(default_factory=list)  # vault-relative (from, to), files or folders
    folders: list[str] = field(default_factory=list)  # vault-relative folders to create
    done: str = "Done."


def _key(issue: Issue, root: Path) -> tuple[str, str, str]:
    where = ""
    if issue.path is not None:
        try:
            where = issue.path.relative_to(root).as_posix()
        except ValueError:
            where = str(issue.path)
    return issue.code, issue.message, where


def _errors(root: Path) -> list[Issue]:
    cfg = load(Vault(root))
    issues = run_checks(cfg, include_environment=False)
    if not has_errors(issues):
        try:
            issues += output_issues(plan_files(cfg))
        except (OSError, KeyError, ValueError) as exc:
            issues.append(Issue("error", "sync.failed", f"Bron couldn't build the setup ({exc})"))
    return [issue for issue in issues if issue.level == "error"]


def _mkdirs(folder: Path, created: list[Path] | None) -> None:
    """Create a folder and its parents, recording only the ones that didn't exist (shallowest first)."""
    missing = []
    probe = folder
    while not probe.exists() and probe != probe.parent:
        missing.append(probe)
        probe = probe.parent
    folder.mkdir(parents=True, exist_ok=True)
    if created is not None:
        created.extend(reversed(missing))


def _write(path: Path, text: str, created: list[Path] | None = None) -> None:
    _mkdirs(path.parent, created)
    tmp = path.with_name(path.name + ".bron-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _move(root: Path, src: str, dst: str, created: list[Path] | None = None) -> None:
    target = root / dst
    if target.exists():
        raise SetupError(f"{dst} already exists")
    _mkdirs(target.parent, created)
    shutil.move(str(root / src), str(target))


def _validate(vault: Vault, change: Change) -> None:
    """Refuse paths outside the vault and moves or writes that can't work, before anything is touched."""
    root = vault.root.resolve()
    every = [p for pair in change.moves for p in pair] + list(change.folders) + list(change.writes)
    for rel in every:
        pure = PurePosixPath(rel)
        if not rel or pure.is_absolute() or ".." in pure.parts or "\\" in rel:
            raise SetupError(f"{rel or '(empty)'} is outside the vault, so Bron won't touch it.")
        try:
            (root / rel).resolve().relative_to(root)
        except ValueError:
            raise SetupError(f"{rel} is outside the vault, so Bron won't touch it.") from None
    for src, dst in change.moves:
        if not (vault.root / src).exists():
            raise SetupError(f"Bron can't move {src}: it doesn't exist.")
        if (vault.root / dst).exists():
            raise SetupError(f"Bron can't move {src} to {dst}: {dst} already exists.")
    for rel in change.writes:
        target = vault.root / rel
        if target.exists() and not target.is_file():
            raise SetupError(f"Bron can't write {rel}: it is a folder.")


def problems(vault: Vault, change: Change) -> list[str]:
    """Errors the change would add to the setup. Checked on a temporary copy of System/; the vault isn't touched."""
    _validate(vault, change)
    try:
        return _problems(vault, change)
    except OSError as exc:
        raise SetupError(f"Bron couldn't check this change: {exc}") from None


def _problems(vault: Vault, change: Change) -> list[str]:
    before = {_key(issue, vault.root) for issue in _errors(vault.root)}
    with tempfile.TemporaryDirectory(prefix="bron-setup-") as tmp:
        root = Path(tmp) / "Vault"
        shutil.copytree(vault.system, root / "System", ignore=_IGNORE, symlinks=True)
        inside = lambda rel: rel.split("/", 1)[0] == "System"  # noqa: E731
        for src, dst in change.moves:
            if inside(src) and inside(dst):
                _move(root, src, dst)
        for rel in change.folders:
            if inside(rel):
                (root / rel).mkdir(parents=True, exist_ok=True)
        for rel, text in change.writes.items():
            if inside(rel):
                _write(root / rel, text)
        found = []
        for issue in _errors(root):
            key = _key(issue, root)
            if key not in before:
                found.append(issue.message + (f" ({key[2]})" if key[2] else ""))
        return found


def preview(vault: Vault, change: Change) -> list[str]:
    found = problems(vault, change)
    if found:
        raise SetupError("This change would break the setup, so Bron won't make it:\n" + "\n".join(f"- {p}" for p in found))
    return list(change.summary)


def apply(vault: Vault, change: Change) -> list[str]:
    """Make the change, refresh the setup, and undo everything if any step fails."""
    preview(vault, change)
    if needs_sync(vault):
        # Pending approvals and generated files are brought up to date first, so the backups below include them.
        try:
            first = run_sync(vault)
        except Exception as exc:  # noqa: BLE001
            raise SetupError(f"Bron's setup couldn't be refreshed before the change ({exc}). Nothing was changed.") from None
        if not first.ok:
            reasons = "; ".join(i.message for i in first.issues if i.level == "error") or "unknown problem"
            raise SetupError(f"Bron's setup couldn't be refreshed before the change ({reasons}). Nothing was changed.")
    root = vault.root
    backup = vault.backups_dir / f"setup-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    moved: list[tuple[str, str]] = []
    saved: list[str] = []
    created_files: list[Path] = []
    created_dirs: list[Path] = []
    try:
        for src, dst in change.moves:
            _move(root, src, dst, created_dirs)
            moved.append((src, dst))
        for rel in change.folders:
            path = root / rel
            if not path.exists():
                _mkdirs(path, created_dirs)
        for rel, text in change.writes.items():
            path = root / rel
            if path.is_file():
                copy = backup / rel
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, copy)
                saved.append(rel)
            elif path.exists():
                raise SetupError(f"Bron can't write {rel}: it is a folder.")
            else:
                created_files.append(path)
            _write(path, text, created_dirs)
        result = run_sync(vault)
        if not result.ok:
            reasons = "; ".join(i.message for i in result.issues if i.level == "error") or "unknown problem"
            raise SetupError(f"Bron's setup couldn't be refreshed after the change ({reasons}).")
    except BaseException as exc:
        failures, refreshed = _rollback(vault, backup, saved, created_files, created_dirs, moved)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        message = str(exc) if isinstance(exc, SetupError) else f"The change failed ({exc.__class__.__name__}: {exc})."
        if failures:
            tail = f" Your original files are in {backup.relative_to(root).as_posix()}."
            if not refreshed:
                tail += " The setup files for Claude Code and Codex also couldn't be refreshed; run `.bron/bin/bron sync`."
            raise SetupError(f"{message} Bron couldn't put everything back: {'; '.join(failures)}.{tail}") from None
        if not refreshed:
            raise SetupError(f"{message} Your files were put back, but the setup files for Claude Code and Codex couldn't be refreshed. Run `.bron/bin/bron sync` to fix that.") from None
        raise SetupError(f"{message} Nothing was changed.") from None
    return [change.done]


def _rollback(vault: Vault, backup: Path, saved: list[str], created_files: list[Path], created_dirs: list[Path], moved: list[tuple[str, str]]) -> tuple[list[str], bool]:
    """Undo as much as possible, step by step. Returns what couldn't be undone and whether the setup was refreshed."""
    root = vault.root
    failures: list[str] = []
    restored = {root / src for src, _ in moved}  # folders put back by undoing a move are the originals, not ours to remove

    def attempt(what: str, action) -> None:
        try:
            action()
        except Exception as exc:  # noqa: BLE001 - one failed step never stops the others
            failures.append(f"{what} ({exc})")

    def remove_folders(final: bool) -> None:
        for path in sorted(created_dirs, key=lambda p: len(p.parts), reverse=True):
            if not path.is_dir() or (final and path in restored):
                continue
            try:
                path.rmdir()  # only removes folders the change created and left empty
            except OSError as exc:
                if final:
                    failures.append(f"{path.relative_to(root).as_posix()} was created by the change and couldn't be removed ({exc})")

    for rel in saved:
        attempt(f"couldn't restore {rel}", lambda rel=rel: shutil.copy2(backup / rel, root / rel))
    for path in created_files:
        if path.is_file() or path.is_symlink():
            attempt(f"couldn't remove {path.relative_to(root).as_posix()}", path.unlink)
    remove_folders(final=False)
    for src, dst in reversed(moved):
        def back(src=src, dst=dst) -> None:
            if (root / src).exists():
                raise SetupError(f"{src} is in the way")
            (root / src).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(root / dst), str(root / src))

        attempt(f"couldn't move {dst} back to {src}", back)
    remove_folders(final=True)
    try:
        refreshed = bool(run_sync(vault).ok)
    except Exception:  # noqa: BLE001
        refreshed = False
    return failures, refreshed

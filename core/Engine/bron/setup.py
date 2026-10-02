"""Setup changes: previewed on a copy of System/, then applied in one step that can't leave a broken setup."""
from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .check import has_errors, run_checks
from .loader import load
from .model import Issue
from .sync import output_issues, plan_files, run_sync
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


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".bron-tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _move(root: Path, src: str, dst: str) -> None:
    target = root / dst
    if target.exists():
        raise SetupError(f"{dst} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(root / src), str(target))


def problems(vault: Vault, change: Change) -> list[str]:
    """Errors the change would add to the setup. Checked on a temporary copy of System/; the vault isn't touched."""
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
    root = vault.root
    backup = vault.backups_dir / f"setup-{time.strftime('%Y%m%d-%H%M%S')}"
    moved: list[tuple[str, str]] = []
    saved: list[str] = []
    created: list[Path] = []
    try:
        for src, dst in change.moves:
            _move(root, src, dst)
            moved.append((src, dst))
        for rel in change.writes:
            path = root / rel
            if path.is_file():
                copy = backup / rel
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, copy)
                saved.append(rel)
            else:
                created.append(path)
        for rel in change.folders:
            path = root / rel
            if not path.exists():
                created.append(path)
                path.mkdir(parents=True, exist_ok=True)
        for rel, text in change.writes.items():
            _write(root / rel, text)
        result = run_sync(vault)
        if not result.ok:
            reasons = "; ".join(i.message for i in result.issues if i.level == "error") or "unknown problem"
            raise SetupError(f"Bron's setup couldn't be refreshed after the change ({reasons}).")
    except BaseException as exc:
        _rollback(vault, backup, saved, created, moved)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        message = str(exc) if isinstance(exc, SetupError) else f"The change failed ({exc.__class__.__name__}: {exc})."
        raise SetupError(f"{message} Nothing was changed.") from None
    return [change.done]


def _rollback(vault: Vault, backup: Path, saved: list[str], created: list[Path], moved: list[tuple[str, str]]) -> None:
    root = vault.root
    for rel in saved:
        shutil.copy2(backup / rel, root / rel)
    for path in reversed(created):
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    for src, dst in reversed(moved):
        if (root / dst).exists() and not (root / src).exists():
            (root / src).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(root / dst), str(root / src))
    for path in sorted({p.parent for p in created}, key=lambda p: len(p.parts), reverse=True):
        while path != root and root in path.parents:
            try:
                path.rmdir()  # only removes folders the change created and left empty
            except OSError:
                break
            path = path.parent
    try:
        run_sync(vault)
    except Exception:  # noqa: BLE001 - best effort: the files are already back
        pass

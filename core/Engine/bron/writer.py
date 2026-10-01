"""Writes Bron-generated files safely.

- Only paths in ALLOWED_ROOTS can be written.
- A manifest records what Bron wrote, so files from other tools are never deleted.
- Anything changed by hand (or present before Bron) is backed up before it is replaced.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .vault import Vault

MANIFEST = "sync.json"
ALLOWED_ROOTS = ("AGENTS.md", "CLAUDE.md", ".mcp.json", ".claude/", ".codex/", ".agents/")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class WriteReport:
    written: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    backed_up: list[str] = field(default_factory=list)
    backup_dir: Path | None = None


class GeneratedWriter:
    def __init__(self, vault: Vault):
        self.vault = vault
        self.manifest_path = vault.state_dir / MANIFEST
        self.manifest = self._load()

    def _safe_target(self, rel: str) -> Path:
        """Validate a target path and return it.

        Raises ValueError if the path goes through a symlink (even inside the vault)
        or if it exists but is not a regular file Bron created.
        """
        target = self.vault.root / rel
        vault_resolved = self.vault.root.resolve()
        rel_path = PurePosixPath(rel)

        # Check that target's resolved parent matches vault root + rel's parent (no symlinks in path)
        try:
            target_parent_resolved = target.parent.resolve()
            expected_parent = vault_resolved / rel_path.parent
            if target_parent_resolved != expected_parent:
                raise ValueError(f"Bron tried to write {rel}, which goes through a link; Bron won't write there")
        except (OSError, RuntimeError):
            raise ValueError(f"Bron tried to write {rel}, which goes through a link; Bron won't write there")

        # Check that if it exists, it's a regular file (not a folder or symlink)
        # Python 3.12 compatible: use is_symlink() and is_file() instead of is_file(follow_symlinks=False)
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError(f"Bron tried to write {rel}, which is a folder or a link, not a file Bron made; move it away and sync again")

        return target

    def _load(self) -> dict:
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"files": {}, "fingerprint": ""}
        if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
            return {"files": {}, "fingerprint": ""}
        data.setdefault("fingerprint", "")
        # Validate manifest keys: keep only entries that pass _check_allowed and have str values
        validated_files = {}
        for rel, digest in data.get("files", {}).items():
            if isinstance(digest, str):
                try:
                    _check_allowed(rel)
                    validated_files[rel] = digest
                except ValueError:
                    pass  # silently drop invalid entries
        data["files"] = validated_files
        return data

    def drift(self) -> list[str]:
        changed = []
        for rel, digest in sorted(self.manifest["files"].items()):
            path = self.vault.root / rel
            if not path.is_file() or sha256(path.read_bytes()) != digest:
                changed.append(rel)
        return changed

    def apply(self, files: dict[str, bytes], fingerprint: str = "") -> WriteReport:
        for rel in files:
            _check_allowed(rel)
        # Validate all incoming targets before writing anything
        for rel in files:
            self._safe_target(rel)
        # Validate all manifest entries to be deleted
        for rel in self.manifest["files"]:
            if rel not in files:
                self._safe_target(rel)

        report = WriteReport()
        backup_root = self.vault.backups_dir / f"sync-{time.strftime('%Y%m%d-%H%M%S')}"
        old: dict[str, str] = self.manifest["files"]
        new: dict[str, str] = {}
        for rel, data in sorted(files.items()):
            target = self._safe_target(rel)
            digest = sha256(data)
            if target.is_file():
                current = target.read_bytes()
                if current == data:
                    new[rel] = digest
                    continue
                if old.get(rel) != sha256(current):
                    self._backup(target, rel, backup_root, report)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".bron-tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
            report.written.append(rel)
            new[rel] = digest
        for rel, digest in sorted(old.items()):
            if rel in files:
                continue
            target = self._safe_target(rel)
            if target.is_file():
                if sha256(target.read_bytes()) != digest:
                    self._backup(target, rel, backup_root, report)
                target.unlink()
                report.deleted.append(rel)
                self._prune(target.parent)
        self.manifest = {"files": new, "fingerprint": fingerprint}
        self.vault.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_name(MANIFEST + ".bron-tmp")
        tmp.write_text(json.dumps(self.manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.manifest_path)
        if report.backed_up:
            report.backup_dir = backup_root
        return report

    def _backup(self, target: Path, rel: str, backup_root: Path, report: WriteReport) -> None:
        destination = backup_root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, destination)
        report.backed_up.append(rel)

    def _prune(self, folder: Path) -> None:
        root = self.vault.root
        while folder != root and root in folder.parents:
            try:
                folder.rmdir()  # only succeeds when empty
            except OSError:
                return
            folder = folder.parent


def _check_allowed(rel: str) -> None:
    path = PurePosixPath(rel)
    if path.is_absolute() or ".." in path.parts or not any(rel == r or (r.endswith("/") and rel.startswith(r)) for r in ALLOWED_ROOTS):
        raise ValueError(f"Bron tried to write {rel}, which is outside the generated files it manages")

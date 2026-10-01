"""Finding a Bron vault and every path inside it."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MARKER = Path("System") / "Core" / "VERSION"


class VaultNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class Vault:
    root: Path

    @classmethod
    def find(cls, start: Path | None = None) -> "Vault":
        env = os.environ.get("BRON_VAULT")
        if env:
            root = Path(env).expanduser().resolve()
            if (root / MARKER).is_file():
                return cls(root)
            raise VaultNotFound(f"BRON_VAULT points to {root}, which is not a Bron vault (no {MARKER}).")
        here = (start or Path.cwd()).resolve()
        for folder in (here, *here.parents):
            if (folder / MARKER).is_file():
                return cls(folder)
        raise VaultNotFound(f"No Bron vault found in {here} or any folder above it.")

    # User-owned
    @property
    def system(self) -> Path:
        return self.root / "System"

    @property
    def agents_dir(self) -> Path:
        return self.system / "Agents"

    @property
    def helpers_dir(self) -> Path:
        return self.system / "Helpers"

    @property
    def skills_dir(self) -> Path:
        return self.system / "Skills"

    @property
    def connections_dir(self) -> Path:
        return self.system / "Connections"

    @property
    def memory_dir(self) -> Path:
        return self.system / "Memory"

    @property
    def settings_file(self) -> Path:
        return self.system / "Settings.md"

    # Framework-owned
    @property
    def core(self) -> Path:
        return self.system / "Core"

    @property
    def core_manual(self) -> Path:
        return self.core / "Manual"

    @property
    def core_skills(self) -> Path:
        return self.core / "Skills"

    @property
    def core_helpers(self) -> Path:
        return self.core / "Helpers"

    @property
    def core_templates(self) -> Path:
        return self.core / "Templates"

    # Work folders
    @property
    def projects_dir(self) -> Path:
        return self.root / "Projects"

    @property
    def routines_dir(self) -> Path:
        return self.root / "Routines"

    @property
    def tickets_dir(self) -> Path:
        return self.root / "Tickets"

    @property
    def knowledge_dir(self) -> Path:
        return self.root / "Knowledge"

    # Machine data
    @property
    def bron_dir(self) -> Path:
        return self.root / ".bron"

    @property
    def state_dir(self) -> Path:
        return self.bron_dir / "state"

    @property
    def backups_dir(self) -> Path:
        return self.bron_dir / "backups"

    @property
    def bin_dir(self) -> Path:
        return self.bron_dir / "bin"

    @property
    def bron_command(self) -> Path:
        return self.bin_dir / "bron"

    def version(self) -> str:
        return (self.root / MARKER).read_text(encoding="utf-8").strip()

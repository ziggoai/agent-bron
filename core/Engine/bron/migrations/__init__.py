"""Changes to the user's own files that a new framework version needs, applied once after an update.

Each migration is built and applied through the setup change runner (setup.run), so it is checked
first and rolled back as a whole if it fails. Its summary also goes in the release's CHANGELOG entry,
so the update preview mentions it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..loader import Config
from ..releases import parse_version
from ..setup import Change, run
from ..statefile import read_json, write_json
from ..vault import Vault

STATE = "migrations.json"


@dataclass(frozen=True)
class Migration:
    id: str  # stable name, recorded once applied
    version: str  # the framework version that introduced it
    summary: str  # one plain line
    build: Callable[[Config], Change]


MIGRATIONS: list[Migration] = []  # oldest first; none yet


def _applied(vault: Vault) -> set[str]:
    data = read_json(vault.state_dir / STATE, {})
    return set(data.get("applied", [])) if isinstance(data, dict) else set()


def _key(version: str) -> tuple[int, int, int]:
    return parse_version(version) or (0, 0, 0)


def pending(vault: Vault, previous: str, current: str, registry: list[Migration] | None = None) -> list[Migration]:
    done = _applied(vault)
    found = registry if registry is not None else MIGRATIONS
    return [m for m in found if _key(previous) < _key(m.version) <= _key(current) and m.id not in done]


def apply_pending(vault: Vault, previous: str, current: str, registry: list[Migration] | None = None) -> list[str]:
    lines: list[str] = []
    for migration in pending(vault, previous, current, registry):
        lines += run(vault, migration.build, preview_only=False)
        write_json(vault.state_dir / STATE, {"applied": sorted(_applied(vault) | {migration.id})})
    return lines

"""Changes to the user's own files that a new framework version needs, applied once after an update.

Each migration is built and applied through the setup change runner (setup.run), so it is checked
first and rolled back as a whole if it fails. Its summary also goes in the release's CHANGELOG entry,
so the update preview mentions it.

.bron/state/migrations.json records what was applied. A fresh install records every registered
migration; a vault without a record counts those up to its previous version as applied.
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


def _applied(vault: Vault) -> set[str] | None:
    """The migrations recorded as applied, or None when the vault has no record yet."""
    data = read_json(vault.state_dir / STATE, {})
    applied = data.get("applied") if isinstance(data, dict) else None
    return {str(item) for item in applied} if isinstance(applied, list) else None


def _key(version: str) -> tuple[int, int, int]:
    return parse_version(version) or (0, 0, 0)


def _done(vault: Vault, previous: str, registry: list[Migration]) -> set[str]:
    """The record; without one, every migration up to the previous version counts as applied (a baseline)."""
    recorded = _applied(vault)
    if recorded is not None:
        return recorded
    return {m.id for m in registry if _key(m.version) <= _key(previous)}


def pending(vault: Vault, previous: str, current: str, registry: list[Migration] | None = None) -> list[Migration]:
    found = registry if registry is not None else MIGRATIONS
    done = _done(vault, previous, found)
    return [m for m in found if _key(m.version) <= _key(current) and m.id not in done]


def record_all(vault: Vault, registry: list[Migration] | None = None) -> None:
    """A fresh install starts with every registered migration already in place."""
    found = registry if registry is not None else MIGRATIONS
    write_json(vault.state_dir / STATE, {"applied": sorted((_applied(vault) or set()) | {m.id for m in found})})


def apply_pending(vault: Vault, previous: str, current: str, registry: list[Migration] | None = None) -> list[str]:
    found = registry if registry is not None else MIGRATIONS
    done = _done(vault, previous, found)
    if _applied(vault) is None:
        write_json(vault.state_dir / STATE, {"applied": sorted(done)})
    lines: list[str] = []
    for migration in pending(vault, previous, current, found):
        lines += run(vault, migration.build, preview_only=False)
        done.add(migration.id)
        write_json(vault.state_dir / STATE, {"applied": sorted(done)})
    return lines

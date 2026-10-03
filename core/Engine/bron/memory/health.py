"""Health check items for memory."""
from __future__ import annotations

import time

from ..loader import Config
from ..model import Issue
from ..statefile import read_json
from . import facts
from .commands import MemoryError, facts_file, read_lines
from .summaries import MAX_AGE_DAYS, MAX_ATTEMPTS, STATE

OLD_SUMMARY = "System/Memory/Summary.md is no longer read; ask Bron to move what matters into Facts.md."


def _given_up(entry, now: float) -> bool:
    """A conversation the summarizer gave up on in the last two weeks; an entry it can't read doesn't count."""
    if not isinstance(entry, dict) or entry.get("status") != "failed":
        return False
    try:
        attempts, when = int(entry.get("attempts", 0)), float(entry["when"])
    except (KeyError, TypeError, ValueError):
        return False
    return attempts >= MAX_ATTEMPTS and now - when <= MAX_AGE_DAYS * 86400


def issues(cfg: Config) -> list[Issue]:
    vault = cfg.vault
    out: list[Issue] = []
    files = [("shared", facts_file(vault, cfg, "shared", ""))] + [("mine", facts_file(vault, cfg, "mine", key)) for key in cfg.agents]
    for scope, path in files:
        if not path.exists():
            continue
        try:
            lines = read_lines(path)
        except MemoryError:
            out.append(Issue("error", "memory.unreadable", f"{path.relative_to(vault.root)} can't be read as text; fix or delete it", path))
            continue
        if facts.size(lines) >= 0.9 * facts.LIMITS[scope]:
            out.append(Issue("warning", "memory.long", f"{path.relative_to(vault.root)} is getting long; ask Bron to tidy it", path))
    if (vault.memory_dir / "Summary.md").is_file():
        out.append(Issue("warning", "memory.old-summary", OLD_SUMMARY))
    state = read_json(vault.bron_dir / "memory" / STATE, {})
    now = time.time()
    given_up = sum(1 for entry in state.values() if _given_up(entry, now))
    if given_up:
        out.append(Issue("warning", "memory.summaries-failed",
                         f"{given_up} conversation{'s' if given_up != 1 else ''} couldn't be summarised after {MAX_ATTEMPTS} tries (see .bron/logs/memory.log)"))
    return out

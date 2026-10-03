"""Health check items for memory."""
from __future__ import annotations

from ..loader import Config
from ..model import Issue
from ..statefile import read_json
from . import facts
from .commands import MemoryError, facts_file, read_lines
from .summaries import MAX_ATTEMPTS, STATE


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
    state = read_json(vault.bron_dir / "memory" / STATE, {})
    given_up = sum(1 for e in state.values() if isinstance(e, dict) and e.get("status") == "failed" and int(e.get("attempts", 0)) >= MAX_ATTEMPTS)
    if given_up:
        out.append(Issue("warning", "memory.summaries-failed",
                         f"{given_up} conversation{'s' if given_up != 1 else ''} couldn't be summarised after {MAX_ATTEMPTS} tries (see .bron/logs/memory.log)"))
    return out

"""The once-a-day "a new Bron is available" line in the session briefing. Never slow, never noisy."""
from __future__ import annotations

import time

from .model import Settings
from .releases import ProjectFolder, ReleaseError, is_newer, select_source
from .statefile import read_json, write_json
from .vault import Vault

CACHE = "update-check.json"
DAY = 24 * 3600
TIMEOUT = 2


def update_notice(vault: Vault, settings: Settings, *, now: float | None = None) -> str:
    if not settings.update_check:
        return ""
    source = select_source(vault, timeout=TIMEOUT)
    if isinstance(source, ProjectFolder):
        return ""  # a development vault follows a project folder; `bron update` handles it
    now = time.time() if now is None else now
    path = vault.state_dir / CACHE
    cache = read_json(path, {})
    if not isinstance(cache, dict):
        cache = {}
    latest = cache.get("latest")
    checked = cache.get("checked_at", 0)
    if not isinstance(checked, (int, float)) or now - checked >= DAY:
        try:
            latest = source.latest()
        except ReleaseError:
            pass  # offline or GitHub busy: stay quiet, try again tomorrow
        write_json(path, {"checked_at": now, "latest": latest})
    if isinstance(latest, str) and is_newer(latest, vault.version()):
        return f"Bron {latest} is available. Say 'update yourself' to see what's new."
    return ""

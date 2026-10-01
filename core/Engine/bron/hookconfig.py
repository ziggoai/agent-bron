"""The fixed trigger configuration both CLIs get.

It only changes if the vault folder moves, so Codex's one-time trigger approval stays valid.
"""
from __future__ import annotations

import shlex

from .vault import Vault

# (CLI event name, Bron event name, timeout in seconds)
EVENTS = (
    ("SessionStart", "session-start", 30),
    ("UserPromptSubmit", "user-prompt", 10),
    ("PreCompact", "pre-compact", 10),
    ("Stop", "stop", 10),
    ("SessionEnd", "session-end", 2),
)
HOOK_NAMES = tuple(name for _, name, _ in EVENTS)


def hooks_block(vault: Vault, cli: str) -> dict:
    command = shlex.quote(str(vault.bron_command))
    return {
        event: [{"hooks": [{"type": "command", "command": f"{command} hook {name} --cli {cli}", "timeout": timeout}]}]
        for event, name, timeout in EVENTS
    }

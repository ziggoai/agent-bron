"""The short briefing injected at the start of every session."""
from __future__ import annotations

import os

from . import frontmatter as fm
from .loader import load
from .model import CLI_NAMES
from .vault import Vault

MAX_CHARS = 6000
MEMORY_CHARS = 2500


def build_briefing(vault: Vault, *, cli: str, notes: list[str] | None = None) -> str:
    cfg = load(vault)
    agent = os.environ.get("BRON_AGENT") or cfg.settings.default_agent
    settings = cfg.settings
    lines = ["# Bron briefing", f"You are {agent}, working in {CLI_NAMES.get(cli, cli)} in the user's Bron vault."]
    if settings.user_name:
        lines.append(f"You're working with {settings.user_name}" + (f" at {settings.company}" if settings.company else "") + ".")
    else:
        lines.append("First-run setup isn't done yet (no name in System/Settings.md). Offer to run it before anything else.")
    if notes:
        lines += ["", *notes]
    summary = vault.memory_dir / "Summary.md"
    if summary.is_file():
        try:
            text = fm.read(summary).body.strip()
        except (fm.FrontmatterError, OSError, UnicodeDecodeError):
            text = ""
        if text:
            lines += ["", "## What you remember", _clip(text, MEMORY_CHARS)]
    return _clip("\n".join(lines).rstrip() + "\n", MAX_CHARS)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 2].rstrip() + "…\n"

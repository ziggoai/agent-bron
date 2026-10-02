"""The short briefing injected at the start of every session."""
from __future__ import annotations

import os

from . import frontmatter as fm
from .loader import load
from .model import CLI_NAMES, slug
from .prompts import agent_prompt
from .vault import Vault

MAX_CHARS = 6000
MEMORY_CHARS = 2500


def build_briefing(vault: Vault, *, cli: str, notes: list[str] | None = None, changed: list[str] | tuple = ()) -> str:
    cfg = load(vault)
    agent = os.environ.get("BRON_AGENT") or cfg.settings.default_agent
    settings = cfg.settings
    lines = ["# Bron briefing", f"You are {agent}, working in {CLI_NAMES.get(cli, cli)} in the user's Bron vault."]
    if settings.user_name:
        lines.append(f"You're working with {settings.user_name}" + (f" at {settings.company}" if settings.company else "") + ".")
    else:
        lines.append(
            "First-run setup isn't done yet (no name in System/Settings.md). Ask the user for their name and company. "
            "As soon as they tell you, save them to `user_name` and `company` in System/Settings.md and confirm in one line: "
            "this is the one change to System/ that needs no separate yes."
        )
    if notes:
        lines += ["", *notes]
    # Each CLI reads its instruction files before the startup trigger regenerates them, so an edit
    # made since the last session would only apply next time. Carry the fresh instructions here.
    key = slug(agent)
    own_file = f".claude/agents/{key}.md" if cli == "claude" else ".codex/config.toml"
    if own_file in changed and key in cfg.agents:
        lines += [
            "",
            "## Your updated instructions",
            "Your setup was just updated. These replace the instructions this session started with:",
            "",
            agent_prompt(cfg.agents[key], cfg).rstrip(),
        ]
    if "AGENTS.md" in changed:
        lines += ["", "The shared rules in AGENTS.md changed since this session loaded them; read AGENTS.md again before relying on them."]
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

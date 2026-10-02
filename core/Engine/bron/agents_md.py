"""AGENTS.md: the shared rules every session loads (CLAUDE.md only imports it)."""
from __future__ import annotations

from string import Template

from .loader import Config
from .model import slug


def _about(settings) -> str:
    rows = [("Name", settings.user_name), ("Role", settings.user_role), ("Company", settings.company), ("Tone", settings.tone), ("Preferences", settings.preferences)]
    lines = [f"- {label}: {value}" for label, value in rows if value]
    return "\n".join(lines) if lines else "Not set up yet: the onboarding skill asks."


def render_agents_md(cfg: Config) -> str:
    template = Template((cfg.vault.core_templates / "AGENTS.md.tmpl").read_text(encoding="utf-8"))
    rows = ["| Agent | Role | Reports to | Tag |", "|---|---|---|---|"]
    for key, agent in sorted(cfg.agents.items()):
        boss = "you" if slug(agent.reports_to) == "you" else agent.reports_to
        rows.append(f"| {agent.name} | {agent.role} | {boss} | `@{key}` |")
    return template.substitute(
        user=cfg.settings.user_name or "the user",
        about=_about(cfg.settings),
        team="\n".join(rows),
        version=cfg.vault.version(),
    )

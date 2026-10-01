"""The instructions each agent and helper actually receives, built from its file."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .model import Agent, Helper, slug

if TYPE_CHECKING:
    from .loader import Config


def agent_prompt(agent: Agent, cfg: "Config") -> str:
    boss_key = slug(agent.reports_to)
    if boss_key in ("", "you"):
        boss = "the user"
    elif boss_key in cfg.agents:
        boss = cfg.agents[boss_key].name
    else:
        boss = agent.reports_to
    lines = [f"# You are {agent.name}", "", f"Role: {agent.role}. You report to {boss}."]
    if agent.can_assign_to:
        lines.append("You can hand work to " + ", ".join(agent.can_assign_to) + " through tickets.")
    else:
        lines.append("You work on your own: you don't hand work to other team members.")
    if agent.helpers:
        lines.append("Helpers you can run as subagents: " + ", ".join(agent.helpers) + ".")
    if agent.instructions:
        lines += ["", agent.instructions]
    return "\n".join(lines).rstrip() + "\n"


def helper_prompt(helper: Helper) -> str:
    lines = [
        f"# You are the {helper.name} helper",
        "",
        "Do the task you were given, then report back clearly. You have no memory of earlier work and you never hand work to anyone else.",
    ]
    if helper.read_only:
        lines.append("You only read and report: never create, change or delete files.")
    if helper.instructions:
        lines += ["", helper.instructions]
    return "\n".join(lines).rstrip() + "\n"

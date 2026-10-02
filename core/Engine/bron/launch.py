"""How to start an agent in each CLI: background ticket runs, resumes, and direct sessions.

The command lines follow the templates verified in docs/superpowers/specs/2026-10-01-bron-plan2-cli-verification.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import tomli_w

from .access import allowed_keys, blocked_claude_servers, codex_server
from .model import CLIS, Agent
from .prompts import agent_prompt
from .vault import Vault

if TYPE_CHECKING:
    from .loader import Config

# No --dangerously-bypass-hook-trust: Bron's trigger config is fixed, so the user approves it once in Codex
# and ticket runs use it from then on (Task 1 ruling). Untrusted triggers simply don't run.
CODEX_EXEC = ["--json", "--skip-git-repo-check"]


@dataclass
class LaunchSpec:
    cli: str
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)


def choose_cli(cfg: "Config", agent: Agent, caller_cli: str | None) -> str:
    if agent.runs_in in CLIS:
        return agent.runs_in
    if caller_cli in CLIS:
        return caller_cli
    return cfg.settings.default_cli


def agent_settings_path(vault: Vault, key: str) -> Path:
    return vault.root / ".claude" / "bron" / "agents" / f"{key}.settings.json"


def toml_string(text: str) -> str:
    """A TOML basic string literal for `-c key=<value>` (escapes quotes, backslashes and newlines)."""
    return tomli_w.dumps({"v": text}).split("=", 1)[1].strip()


def claude_flags(cfg: "Config", agent: Agent) -> list[str]:
    flags = ["--agent", agent.key, "--settings", str(agent_settings_path(cfg.vault, agent.key))]
    model = cfg.catalog.resolve_model("claude", agent.models.get("claude"))
    if model:
        flags += ["--model", model]
    blocked = blocked_claude_servers(cfg, agent.connections)
    if blocked:
        flags += ["--disallowedTools", ",".join(blocked)]
    return flags


def _codex_connection_flags(cfg: "Config", agent: Agent) -> list[str]:
    keep = allowed_keys(cfg, agent.connections)
    default = cfg.default_agent
    default_keep = allowed_keys(cfg, default.connections) if default is not None else set()
    flags: list[str] = []
    for key, conn in sorted(cfg.connections.items()):
        server = codex_server(conn)
        if not server:
            continue
        if key not in keep:
            flags += ["-c", f"mcp_servers.{server}.enabled=false"]
        elif conn.type != "native" and key not in default_keep:
            # The project config switches this server off for the default agent; switch it back on.
            flags += ["-c", f"mcp_servers.{server}.enabled=true"]
    return flags


def codex_flags(cfg: "Config", agent: Agent, *, with_instructions: bool = True) -> list[str]:
    flags: list[str] = []
    if with_instructions:
        flags += ["-c", f"developer_instructions={toml_string(agent_prompt(agent, cfg))}"]
    model = cfg.catalog.resolve_model("codex", agent.models.get("codex"))
    if model:
        flags += ["-m", model]
    return flags + _codex_connection_flags(cfg, agent)


def _env(agent: Agent, ticket_id: str | None) -> dict[str, str]:
    env = {"BRON_AGENT": agent.name}
    if ticket_id:
        env["BRON_TICKET"] = ticket_id
    return env


def run_spec(cfg: "Config", agent: Agent, cli: str, prompt: str, *, session: str | None = None, ticket_id: str | None = None) -> LaunchSpec:
    if cli == "claude":
        argv = ["claude", "-p", prompt]
        if session:
            argv += ["--resume", session]
        argv += claude_flags(cfg, agent)
        argv += ["--output-format", "json", "--permission-mode", "acceptEdits", "--allowedTools", "Bash"]
    else:
        if session:
            # The thread keeps its instructions (verification X2); connection limits are per invocation.
            argv = ["codex", "exec", "resume", *CODEX_EXEC, *codex_flags(cfg, agent, with_instructions=False), session, prompt]
        else:
            argv = ["codex", "exec", *CODEX_EXEC, *codex_flags(cfg, agent), prompt]
    return LaunchSpec(cli, argv, _env(agent, ticket_id))


def chat_spec(cfg: "Config", agent: Agent, cli: str) -> LaunchSpec:
    if cli == "claude":
        argv = ["claude", *claude_flags(cfg, agent)]
    else:
        argv = ["codex", *codex_flags(cfg, agent)]
    return LaunchSpec(cli, argv, _env(agent, None))

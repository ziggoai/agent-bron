"""Claude Code's view of the vault: CLAUDE.md, .claude/ and .mcp.json."""
from __future__ import annotations

import json

from . import frontmatter as fm
from .catalog import Actions
from .hookconfig import hooks_block
from .loader import Config
from .model import Agent, Connection, Helper, conn_key
from .prompts import agent_prompt, helper_prompt
from .skills import skill_files


def generate(cfg: Config) -> dict[str, bytes]:
    files = {
        "CLAUDE.md": b"@AGENTS.md\n",
        ".claude/settings.json": _json(_settings(cfg)),
    }
    if cfg.connections:
        files[".mcp.json"] = _json({"mcpServers": {key: _server(c) for key, c in sorted(cfg.connections.items())}})
    for key, agent in sorted(cfg.agents.items()):
        files[f".claude/agents/{key}.md"] = _agent_file(cfg, agent)
    for key, helper in sorted(cfg.helpers.items()):
        files[f".claude/agents/{key}.md"] = _helper_file(cfg, helper)
    files.update(skill_files(cfg, ".claude/skills"))
    return files


def rules(actions: Actions) -> list[str]:
    out = [f"mcp__{conn}__{tool}" for conn, tools in sorted(actions.mcp.items()) for tool in sorted(tools)]
    for words in actions.shell:
        command = " ".join(words)
        out += [f"Bash({command})", f"Bash({command} *)"]
    return out


def _settings(cfg: Config) -> dict:
    agent = cfg.default_agent
    ask, allow = cfg.catalog.permissions_for(agent)
    return {
        "agent": agent.key,
        "autoMemoryEnabled": False,
        "permissions": {
            "ask": rules(ask),
            "allow": rules(allow),
            # Team members take work through tickets only. A deny rule blocks just these subagents;
            # Agent(x) in an agent's disallowedTools would remove the whole Agent tool (verification R5).
            "deny": [f"Agent({key})" for key in sorted(cfg.agents)],
        },
        "enabledMcpjsonServers": sorted(cfg.connections),
        "hooks": hooks_block(cfg.vault, "claude"),
    }


def _server(conn: Connection) -> dict:
    if conn.type == "mcp-http":
        return {"type": "http", "url": conn.url}
    server: dict = {"type": "stdio", "command": conn.command, "args": list(conn.args)}
    if conn.env:
        server["env"] = dict(conn.env)
    return server


def _blocked_servers(cfg: Config, allowed: list[str]) -> list[str]:
    keep = {conn_key(c) for c in allowed}
    return [f"mcp__{key}" for key in sorted(cfg.connections) if key not in keep]


def _agent_file(cfg: Config, agent: Agent) -> bytes:
    meta: dict = {
        "name": agent.key,
        "description": f"{agent.role}. Bron team member: reach them through a ticket, never as a subagent.",
    }
    model = cfg.catalog.resolve_model("claude", agent.models.get("claude"))
    if model:
        meta["model"] = model
    blocked = _blocked_servers(cfg, agent.connections)
    if blocked:
        meta["disallowedTools"] = ", ".join(blocked)
    return fm.dump(fm.Document(meta, "\n" + agent_prompt(agent, cfg))).encode("utf-8")


def _helper_file(cfg: Config, helper: Helper) -> bytes:
    meta: dict = {"name": helper.key, "description": helper.description}
    model = cfg.catalog.resolve_model("claude", helper.models.get("claude"))
    if model:
        meta["model"] = model
    blocked = _blocked_servers(cfg, helper.connections) + ["Agent"]
    if helper.read_only:
        blocked += ["Write", "Edit", "NotebookEdit"]
    meta["disallowedTools"] = ", ".join(blocked)
    return fm.dump(fm.Document(meta, "\n" + helper_prompt(helper))).encode("utf-8")


def _json(data: dict) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")

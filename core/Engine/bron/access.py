"""Which connections an agent or helper may use, and how each CLI names a connection."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .model import ALL, Connection, conn_key

if TYPE_CHECKING:
    from .loader import Config


def allowed_keys(cfg: "Config", names: list[str]) -> set[str]:
    if any(name.strip().lower() == ALL for name in names):
        return set(cfg.connections)
    return {conn_key(name) for name in names} & set(cfg.connections)


def claude_server(conn: Connection) -> str:
    """The server id Claude Code uses in tool names (mcp__<id>__tool); empty if not in Claude Code."""
    if conn.type == "native":
        return conn.claude
    return conn.key


def codex_server(conn: Connection) -> str:
    """The server name Codex uses; empty if not in Codex."""
    if conn.type == "native":
        return conn.codex
    return conn.key


def blocked_claude_servers(cfg: "Config", names: list[str]) -> list[str]:
    keep = allowed_keys(cfg, names)
    return [
        f"mcp__{claude_server(conn)}"
        for key, conn in sorted(cfg.connections.items())
        if key not in keep and claude_server(conn)
    ]

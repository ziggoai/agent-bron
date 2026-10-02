"""Which connections an agent or helper may use, and how each CLI names a connection."""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from .model import ALL, Connection, conn_key

if TYPE_CHECKING:
    from .loader import Config
    from .vault import Vault

# A server id Bron may put in `-c mcp_servers.<id>.…` without quoting.
BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


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


def allowed_claude_servers(cfg: "Config", names: list[str]) -> list[str]:
    keep = allowed_keys(cfg, names)
    return [
        f"mcp__{claude_server(conn)}"
        for key, conn in sorted(cfg.connections.items())
        if key in keep and claude_server(conn)
    ]


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def _toml(path: Path) -> dict:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def codex_trusts(root: Path) -> bool:
    projects = _toml(codex_home() / "config.toml").get("projects") or {}
    if not isinstance(projects, dict):
        return False
    for candidate in {str(root), str(root.resolve())}:
        entry = projects.get(candidate)
        if isinstance(entry, dict) and entry.get("trust_level") == "trusted":
            return True
    return False


def _server_keys(path: Path) -> set[str]:
    servers = _toml(path).get("mcp_servers")
    return {str(key) for key in servers} if isinstance(servers, dict) else set()


def codex_defined_servers(vault: "Vault") -> set[str]:
    """Servers defined in a Codex config file that Codex loads for this vault.

    Codex refuses to start when `-c mcp_servers.<id>.…` names any other server (plugin servers
    included), so only these can be switched by flag. The vault's own .codex/config.toml only
    counts when Codex trusts the vault; otherwise Codex doesn't load it.
    """
    servers = _server_keys(codex_home() / "config.toml")
    if codex_trusts(vault.root):
        servers |= _server_keys(vault.root / ".codex" / "config.toml")
    return servers


def codex_switchable(conn: Connection, defined: set[str]) -> str:
    """The Codex server id Bron can switch with `-c`, or '' when it can't (or the connection isn't in Codex)."""
    server = codex_server(conn)
    if not server or not BARE_KEY.match(server):
        return ""
    if conn.type == "native" and conn.status == "not found":
        return ""
    return server if server in defined else ""

import json
import tomllib

from bron import frontmatter as fm
from bron.access import allowed_keys, blocked_claude_servers
from bron.check import run_checks
from bron.gen_claude import generate as gen_claude
from bron.gen_codex import generate as gen_codex
from bron.loader import load
from vaultkit import add_agent, add_connection, set_meta, write_md

BRON = ("System", "Agents", "Bron", "Agent.md")


def add_native(vault, name, **meta):
    data = {"name": name, "type": "native", **meta}
    return write_md(vault.connections_dir / f"{name}.md", data)


def test_native_connection_loads_with_both_names(vault):
    add_native(vault, "Carta", claude="claude_ai_Carta", codex="carta", status="connected")
    conn = load(vault).connections["carta"]
    assert (conn.type, conn.claude, conn.codex, conn.status) == ("native", "claude_ai_Carta", "carta", "connected")


def test_native_connection_needs_at_least_one_name(vault):
    add_native(vault, "Mystery")
    cfg = load(vault)
    assert "mystery" not in cfg.connections
    assert any("needs 'claude' or 'codex'" in i.message for i in cfg.issues)


def test_bron_template_uses_all_connections(vault):
    assert load(vault).default_agent.connections == ["all"]


def test_all_is_not_an_unknown_connection(vault):
    add_agent(vault, "CFO", connections=["All"])
    assert not [i for i in run_checks(load(vault), include_environment=False) if i.code == "agent.connection-unknown"]


def test_allowed_keys_expands_all(vault):
    add_native(vault, "Carta", claude="claude_ai_Carta")
    add_connection(vault, "Time")
    cfg = load(vault)
    assert allowed_keys(cfg, ["all"]) == {"carta", "time"}
    assert allowed_keys(cfg, ["Carta"]) == {"carta"}
    assert allowed_keys(cfg, []) == set()


def test_blocked_claude_servers_use_each_cli_name(vault):
    add_native(vault, "Carta", claude="claude_ai_Carta", codex="carta")
    add_native(vault, "Codex Only", codex="paper")
    add_connection(vault, "Time")
    cfg = load(vault)
    assert blocked_claude_servers(cfg, ["Time"]) == ["mcp__claude_ai_Carta"]
    assert blocked_claude_servers(cfg, ["all"]) == []


def test_claude_output_keeps_natives_out_of_mcp_json_and_blocks_them_per_agent(vault):
    add_native(vault, "Carta", claude="claude_ai_Carta", codex="carta")
    add_connection(vault, "Time")
    add_agent(vault, "CFO", connections=["Time"])
    files = gen_claude(load(vault))
    assert list(json.loads(files[".mcp.json"])["mcpServers"]) == ["time"]
    settings = json.loads(files[".claude/settings.json"])
    assert settings["enabledMcpjsonServers"] == ["time"]
    cfo = fm.parse(files[".claude/agents/cfo.md"].decode())
    assert cfo.meta["disallowedTools"] == "mcp__claude_ai_Carta"
    bron = fm.parse(files[".claude/agents/bron.md"].decode())
    assert "disallowedTools" not in bron.meta


def test_no_mcp_json_when_only_natives(vault):
    add_native(vault, "Carta", claude="claude_ai_Carta")
    assert ".mcp.json" not in gen_claude(load(vault))


def test_ask_rules_use_the_claude_tool_name_of_a_native_connection(vault):
    add_native(vault, "Gmail", claude="claude_ai_Gmail")
    set_meta(vault.root.joinpath(*BRON), ask_before=["send-email"])
    ask = json.loads(gen_claude(load(vault))[".claude/settings.json"])["permissions"]["ask"]
    assert "mcp__claude_ai_Gmail__send_message" in ask
    assert not any(rule.startswith("mcp__gmail__") for rule in ask)


def test_codex_project_config_leaves_natives_to_the_users_codex(vault):
    add_native(vault, "Carta", claude="claude_ai_Carta", codex="carta")
    add_connection(vault, "Time")
    config = tomllib.loads(gen_codex(load(vault))[".codex/config.toml"].decode())
    assert list(config["mcp_servers"]) == ["time"]

import json

from bron import frontmatter as fm
from bron.gen_claude import generate
from bron.loader import load
from vaultkit import add_agent, add_connection, set_meta


def settings(vault):
    return json.loads(generate(load(vault))[".claude/settings.json"])


def test_claude_md_only_imports_agents_md(vault):
    assert generate(load(vault))["CLAUDE.md"] == b"@AGENTS.md\n"


def test_settings_set_default_agent_memory_off_and_triggers(vault):
    s = settings(vault)
    assert s["agent"] == "bron"
    assert s["autoMemoryEnabled"] is False
    assert s["hooks"]["SessionStart"][0]["hooks"][0]["command"].endswith("hook session-start --cli claude")
    assert "Bash(git push)" in s["permissions"]["ask"]
    assert "Bash(git push *)" in s["permissions"]["ask"]
    assert "Bash(rm *)" in s["permissions"]["ask"]
    assert s["permissions"]["allow"] == []
    assert s["permissions"]["deny"] == ["Agent(bron)"]


def test_team_members_are_denied_as_subagents_project_wide(vault):
    add_agent(vault, "CFO")
    assert settings(vault)["permissions"]["deny"] == ["Agent(bron)", "Agent(cfo)"]


def test_always_allow_moves_a_rule_from_ask_to_allow(vault):
    set_meta(vault.agents_dir / "Bron" / "Agent.md", always_allow=["git-push"])
    s = settings(vault)
    assert "Bash(git push *)" not in s["permissions"]["ask"]
    assert "Bash(git push *)" in s["permissions"]["allow"]


def test_mcp_tool_rules(vault):
    add_connection(vault, "Gmail")
    set_meta(vault.agents_dir / "Bron" / "Agent.md", connections=["Gmail"], ask_before=["send-email"])
    assert "mcp__gmail__send_message" in settings(vault)["permissions"]["ask"]


def test_team_member_file(vault):
    add_connection(vault, "Carta")
    add_connection(vault, "Gmail")
    add_agent(vault, "CFO", connections=["Carta"], models={"claude": "Opus 5.5"})
    doc = fm.parse(generate(load(vault))[".claude/agents/cfo.md"].decode())
    assert doc.meta["name"] == "cfo"
    assert doc.meta["model"] == "claude-opus-5-5"
    blocked = [x.strip() for x in doc.meta["disallowedTools"].split(",")]
    assert "mcp__gmail" in blocked and "mcp__carta" not in blocked
    assert not any(x.startswith("Agent") for x in blocked)  # Agent(x) here would remove the whole Agent tool (R5)
    assert "never as a subagent" in doc.meta["description"]
    assert doc.body.lstrip().startswith("# You are CFO")


def test_default_model_and_empty_block_list_are_left_out(vault):
    doc = fm.parse(generate(load(vault))[".claude/agents/bron.md"].decode())
    assert doc.meta["model"] == "claude-opus-5-5"
    assert "disallowedTools" not in doc.meta


def test_helpers_cannot_nest_or_write(vault):
    doc = fm.parse(generate(load(vault))[".claude/agents/reader.md"].decode())
    blocked = [x.strip() for x in doc.meta["disallowedTools"].split(",")]
    assert {"Agent", "Write", "Edit", "NotebookEdit"} <= set(blocked)
    assert doc.meta["description"].startswith("Reads the files")


def test_the_reader_helper_runs_on_sonnet_for_speed(vault):
    doc = fm.parse(generate(load(vault))[".claude/agents/reader.md"].decode())
    assert doc.meta["model"] == "sonnet"


def test_mcp_json_only_when_connections_exist(vault):
    assert ".mcp.json" not in generate(load(vault))
    add_connection(vault, "Carta", env={"CARTA_TOKEN": "${CARTA_TOKEN}"})
    add_connection(vault, "Docs", type="mcp-http", url="https://docs.example/mcp", command="")
    files = generate(load(vault))
    servers = json.loads(files[".mcp.json"])["mcpServers"]
    assert servers["carta"] == {"type": "stdio", "command": "uvx", "args": ["mcp-server-time"], "env": {"CARTA_TOKEN": "${CARTA_TOKEN}"}}
    assert servers["docs"] == {"type": "http", "url": "https://docs.example/mcp"}
    assert json.loads(files[".claude/settings.json"])["enabledMcpjsonServers"] == ["carta", "docs"]


def test_skills_are_published(vault):
    assert ".claude/skills/check/SKILL.md" in generate(load(vault))

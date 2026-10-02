import json
import os
import tomllib
from pathlib import Path

from bron.gen_claude import generate
from bron.launch import agent_settings_path, chat_spec, choose_cli, codex_flags, run_spec, toml_string
from bron.loader import load
from bron.prompts import agent_prompt
from bron.sync import run_sync
from vaultkit import add_agent, add_connection, set_meta, write_md


def native(vault, name, **ids):
    write_md(vault.connections_dir / f"{name}.md", {"name": name, "type": "native", **ids})


def codex_config(vault=None, servers=()):
    """The user's Codex config in the test's private CODEX_HOME: these servers, and trust for this vault."""
    lines = []
    for server in servers:
        lines += [f'[mcp_servers."{server}"]', 'command = "x"', ""]
    if vault is not None:
        lines += [f'[projects."{vault.root}"]', 'trust_level = "trusted"', ""]
    (Path(os.environ["CODEX_HOME"]) / "config.toml").write_text("\n".join(lines), encoding="utf-8")


def configs(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]


def team(vault):
    native(vault, "Carta", claude="claude_ai_Carta", codex="carta")
    native(vault, "Gmail", claude="claude_ai_Gmail")
    add_connection(vault, "Time")
    add_agent(vault, "CFO", connections=["Carta"], models={"claude": "Opus 5.5", "codex": "gpt-6.1-sol"}, ask_before=["delete-files"])
    return load(vault)


def test_choose_cli_follows_runs_in_then_caller_then_settings(vault):
    add_agent(vault, "Pinned", runs_in="codex")
    cfg = load(vault)
    assert choose_cli(cfg, cfg.agents["pinned"], "claude") == "codex"
    assert choose_cli(cfg, cfg.agents["bron"], "codex") == "codex"
    assert choose_cli(cfg, cfg.agents["bron"], None) == "claude"


def test_claude_run_command(vault):
    cfg = team(vault)
    spec = run_spec(cfg, cfg.agents["cfo"], "claude", "Work ticket T-0001", ticket_id="T-0001")
    argv = spec.argv
    assert argv[:3] == ["claude", "-p", "Work ticket T-0001"]
    assert argv[argv.index("--agent") + 1] == "cfo"
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    assert argv[argv.index("--settings") + 1] == str(agent_settings_path(vault, "cfo"))
    assert argv[argv.index("--disallowedTools") + 1] == "mcp__claude_ai_Gmail,mcp__time"
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert argv[argv.index("--allowedTools") + 1] == "Bash,mcp__claude_ai_Carta"
    assert "--resume" not in argv
    assert spec.env == {"BRON_AGENT": "CFO", "BRON_TICKET": "T-0001"}


def test_claude_resume_passes_the_session(vault):
    cfg = team(vault)
    argv = run_spec(cfg, cfg.agents["cfo"], "claude", "Continue", session="abc-123").argv
    assert argv[argv.index("--resume") + 1] == "abc-123"


def test_codex_run_command(vault):
    codex_config(vault, ["carta"])
    team(vault)
    assert run_sync(vault).ok
    cfg = load(vault)
    spec = run_spec(cfg, cfg.agents["cfo"], "codex", "Work ticket T-0001", ticket_id="T-0001")
    argv = spec.argv
    assert argv[:7] == ["codex", "exec", "--json", "--skip-git-repo-check", "--sandbox", "workspace-write", "-c"]
    assert "--dangerously-bypass-hook-trust" not in argv  # the user approves Bron's triggers once instead
    assert argv[-1] == "Work ticket T-0001"
    assert argv[argv.index("-m") + 1] == "gpt-6.1-sol"
    configs = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert "mcp_servers.time.enabled=false" in configs
    assert "mcp_servers.carta.enabled=false" not in configs
    assert not any("gmail" in c for c in configs)  # Gmail has no Codex name
    instructions = next(c for c in configs if c.startswith("developer_instructions="))
    assert tomllib.loads(instructions)["developer_instructions"] == agent_prompt(cfg.agents["cfo"], cfg)


def test_codex_resume_keeps_connection_limits_but_not_instructions(vault):
    codex_config(vault)
    team(vault)
    assert run_sync(vault).ok
    cfg = load(vault)
    argv = run_spec(cfg, cfg.agents["cfo"], "codex", "Continue", session="thread-9").argv
    assert argv[:5] == ["codex", "exec", "resume", "--json", "--skip-git-repo-check"]
    assert argv[-2:] == ["thread-9", "Continue"]
    assert "mcp_servers.time.enabled=false" in argv
    assert not any(a.startswith("developer_instructions=") for a in argv)


def test_codex_enables_a_vault_connection_the_default_agent_does_not_use(vault):
    add_connection(vault, "Time")
    set_meta(vault.agents_dir / "Bron" / "Agent.md", connections=[])
    add_agent(vault, "CFO", connections=["Time"])
    codex_config(vault)
    assert run_sync(vault).ok
    cfg = load(vault)
    assert "mcp_servers.time.enabled=true" in codex_flags(cfg, cfg.agents["cfo"])


def test_codex_switches_off_only_servers_codex_itself_defines(vault):
    # Codex refuses to start when -c names a server that no Codex config file defines (C1).
    native(vault, "Carta", codex="carta")
    native(vault, "Computer", codex="cua_repl")  # a plugin server: listed by Codex, but not in its config
    native(vault, "Gone", codex="gone", status="not found")
    native(vault, "Odd", codex="bad id")
    add_agent(vault, "CFO", connections=[])
    codex_config(servers=["carta", "gone", "bad id"])
    cfg = load(vault)
    flags = configs(codex_flags(cfg, cfg.agents["cfo"]))
    assert "mcp_servers.carta.enabled=false" in flags
    assert not any("cua_repl" in f or "gone" in f or "bad id" in f for f in flags)
    flags = configs(run_spec(cfg, cfg.agents["cfo"], "codex", "Go").argv)
    assert "mcp_servers.carta.enabled=false" in flags and not any("cua_repl" in f for f in flags)


def test_vault_servers_are_switched_only_when_codex_loads_the_vault_setup(vault):
    add_connection(vault, "Time")
    add_agent(vault, "CFO", connections=[])
    assert run_sync(vault).ok
    cfg = load(vault)
    assert not any("time" in f for f in configs(codex_flags(cfg, cfg.agents["cfo"])))  # untrusted: Codex ignores .codex/
    codex_config(vault)
    assert "mcp_servers.time.enabled=false" in configs(codex_flags(cfg, cfg.agents["cfo"]))


def test_codex_run_hides_the_agents_ask_before_tools(vault):
    native(vault, "Gmail", claude="claude_ai_Gmail", codex="gmail")
    add_agent(vault, "CFO", runs_in="codex", connections=["Gmail"], ask_before=["send-email", "shell:curl"])
    codex_config(servers=["gmail"])
    cfg = load(vault)
    expected = 'mcp_servers.gmail.disabled_tools=["forward_message", "reply_to_message", "send_email", "send_message"]'
    assert expected in configs(run_spec(cfg, cfg.agents["cfo"], "codex", "Go").argv)
    assert expected in configs(run_spec(cfg, cfg.agents["cfo"], "codex", "Go", session="th-1").argv)
    assert not any("disabled_tools" in c for c in configs(chat_spec(cfg, cfg.agents["cfo"], "codex").argv))


def test_codex_runs_use_the_workspace_sandbox(vault):
    cfg = team(vault)
    fresh = run_spec(cfg, cfg.agents["cfo"], "codex", "Go").argv
    assert fresh[fresh.index("--sandbox") + 1] == "workspace-write"
    resumed = run_spec(cfg, cfg.agents["cfo"], "codex", "Go", session="th-1").argv
    assert "--sandbox" not in resumed  # `codex exec resume` has no --sandbox flag
    assert 'sandbox_mode="workspace-write"' in configs(resumed)


def test_claude_run_allows_only_the_agents_own_connections(vault):
    native(vault, "Carta", claude="claude_ai_Carta", codex="carta")
    native(vault, "Drive", claude="claude_ai_Google_Drive")
    add_connection(vault, "Time")
    add_agent(vault, "CFO", connections=["Drive", "Time"])
    cfg = load(vault)
    argv = run_spec(cfg, cfg.agents["cfo"], "claude", "Go").argv
    assert argv[argv.index("--allowedTools") + 1] == "Bash,mcp__claude_ai_Google_Drive,mcp__time"


def test_tricky_instructions_survive_toml():
    text = 'Quote " and \\ backslash, """triple""", ação, tab\tand\nnew line'
    assert tomllib.loads(f"v={toml_string(text)}")["v"] == text


def test_chat_specs(vault):
    cfg = team(vault)
    claude = chat_spec(cfg, cfg.agents["cfo"], "claude")
    assert claude.argv[0] == "claude" and "-p" not in claude.argv and "--agent" in claude.argv
    codex = chat_spec(cfg, cfg.agents["cfo"], "codex")
    assert codex.argv[0] == "codex" and "exec" not in codex.argv
    assert claude.env == codex.env == {"BRON_AGENT": "CFO"}


def test_sync_writes_per_agent_claude_permissions(vault):
    cfg = team(vault)
    files = generate(cfg)
    data = json.loads(files[".claude/bron/agents/cfo.settings.json"])
    assert "Bash(rm *)" in data["permissions"]["ask"]
    assert ".claude/bron/agents/bron.settings.json" in files


def test_the_default_agents_always_allow_does_not_reach_team_members(vault):
    # Project permissions apply to every agent, so a team member asks for what only Bron may do freely (I5).
    set_meta(vault.agents_dir / "Bron" / "Agent.md", always_allow=["delete-files", "git-push"])
    add_agent(vault, "CFO", always_allow=["git-push"])
    files = generate(load(vault))
    cfo = json.loads(files[".claude/bron/agents/cfo.settings.json"])["permissions"]
    assert "Bash(rm *)" in cfo["ask"] and "Bash(rm)" in cfo["ask"]
    assert "Bash(git push *)" not in cfo["ask"]
    bron = json.loads(files[".claude/bron/agents/bron.settings.json"])["permissions"]
    assert "Bash(rm *)" not in bron["ask"] and "Bash(rm *)" in bron["allow"]

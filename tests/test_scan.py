from bron import frontmatter as fm
from bron.loader import load
from bron.scan import apply_found, merge, parse_claude_list, parse_codex_list, scan
from vaultkit import add_connection, set_meta

CLAUDE_LIST = """Checking MCP server health…

claude.ai Carta: https://mcp.app.carta.com/mcp - ✔ Connected
claude.ai Google Drive: https://drivemcp.googleapis.com/mcp/v1 - ✔ Connected
claude.ai Booking.com: https://demandapi-mcp.booking.com/v1/mcp/8132308 - ✔ Connected
claude.ai HubSpot: https://mcp.hubspot.com/anthropic - ! Needs authentication
plugin:atl-core-skills:affinity-mcp: uvx affinity-mcp - ✔ Connected
plugin:supabase:supabase: https://mcp.supabase.com/mcp (HTTP) - ! Needs authentication
time: uvx mcp-server-time - ✔ Connected
"""

CODEX_LIST = """[
 {"name": "carta", "enabled": true, "transport": {"type": "streamable_http", "url": "https://mcp.app.carta.com/mcp"}},
 {"name": "paper", "enabled": true, "transport": {"type": "stdio", "command": "/x/paper", "args": ["mcp"]}},
 {"name": "computer-use", "enabled": false, "transport": {"type": "stdio", "command": "x"}}
]"""


def names(found):
    return {f.name: f for f in found}


def test_parse_claude_list_names_each_server_like_claude_tool_names():
    found = names(parse_claude_list(CLAUDE_LIST))
    assert found["Carta"].claude == "claude_ai_Carta"
    assert found["Carta"].url == "https://mcp.app.carta.com/mcp"
    assert found["Carta"].status == "connected"
    assert found["Google Drive"].claude == "claude_ai_Google_Drive"
    assert found["Booking.com"].claude == "claude_ai_Booking_com"
    assert found["HubSpot"].status == "needs sign-in"
    assert found["affinity-mcp"].claude == "plugin_atl-core-skills_affinity-mcp"
    assert found["affinity-mcp"].url == ""
    assert found["supabase"].url == "https://mcp.supabase.com/mcp"
    assert found["time"].claude == "time"
    assert "Checking MCP server health…" not in found


def test_parse_codex_list_skips_disabled_and_tolerates_noise():
    found = names(parse_codex_list("warning: something\n" + CODEX_LIST + "\n"))
    assert set(found) == {"carta", "paper"}
    assert found["carta"].codex == "carta" and found["carta"].url == "https://mcp.app.carta.com/mcp"
    assert parse_codex_list("not json") == []


def test_merge_matches_by_url_then_name_and_skips_vault_connections():
    merged = names(merge(parse_claude_list(CLAUDE_LIST), parse_codex_list(CODEX_LIST), skip={"time"}))
    assert merged["Carta"].claude == "claude_ai_Carta" and merged["Carta"].codex == "carta"
    assert merged["paper"].codex == "paper" and merged["paper"].claude == ""
    assert "time" not in merged


def run_scan(vault):
    return scan(vault, claude_text=CLAUDE_LIST, codex_text=CODEX_LIST)


def test_scan_writes_one_file_per_connector_and_reports(vault):
    report = run_scan(vault)
    cfg = load(vault)
    carta = cfg.connections["carta"]
    assert (carta.type, carta.claude, carta.codex, carta.status) == ("native", "claude_ai_Carta", "carta", "connected")
    assert (vault.connections_dir / "Booking.com.md").is_file()
    assert "Carta" in report.created
    assert "HubSpot" in report.needs_sign_in
    text = report.render()
    assert "7 in Claude Code, 2 in Codex" in text
    assert "Needs you to sign in again: HubSpot, supabase" in text


def test_scan_is_idempotent_and_keeps_user_edits(vault):
    run_scan(vault)
    path = vault.connections_dir / "Carta.md"
    doc = fm.read(path)
    doc.meta["description"] = "Fund admin data"
    doc.body += "My note.\n"
    fm.write(path, doc)
    before = sorted(p.name for p in vault.connections_dir.glob("*.md"))
    report = run_scan(vault)
    assert sorted(p.name for p in vault.connections_dir.glob("*.md")) == before
    assert report.created == [] and report.updated == []
    after = fm.read(path)
    assert after.meta["description"] == "Fund admin data" and after.body.endswith("My note.\n")


def test_scan_updates_names_and_marks_missing_connectors(vault):
    run_scan(vault)
    report = scan(vault, claude_text="claude.ai Carta: https://mcp.app.carta.com/mcp - ! Needs authentication\n", codex_text="[]")
    cfg = load(vault)
    assert cfg.connections["carta"].status == "needs sign-in"
    assert cfg.connections["google_drive"].status == "not found"
    assert "Google Drive" in report.missing


def test_scan_does_not_mark_missing_when_a_cli_could_not_be_asked(vault):
    run_scan(vault)
    scan(vault, claude_text=CLAUDE_LIST, codex_text=None, run=lambda *a, **k: (_ for _ in ()).throw(OSError("no codex")))
    assert load(vault).connections["paper"].status != "not found"


def test_scan_never_shadows_a_vault_connection(vault):
    add_connection(vault, "Time")
    run_scan(vault)
    cfg = load(vault)
    assert cfg.connections["time"].type == "mcp-stdio"
    assert not (vault.connections_dir / "time 2.md").exists()


def test_scan_gives_the_default_agent_all_connections(vault):
    set_meta(vault.agents_dir / "Bron" / "Agent.md", connections=[])
    report = run_scan(vault)
    assert load(vault).default_agent.connections == ["all"]
    assert report.opened_for == "Bron"


def test_same_name_twice_in_one_scan_creates_one_file(vault):
    from bron.scan import Found

    apply_found(vault, [Found(name="Notion", claude="claude_ai_Notion"), Found(name="notion", codex="notion")], scanned_claude=True, scanned_codex=True)
    assert [p.name for p in vault.connections_dir.glob("*.md")] == ["Notion.md"]


def test_apply_found_with_nothing_found_changes_nothing(vault):
    report = apply_found(vault, [], scanned_claude=False, scanned_codex=False)
    assert report.created == [] and list(vault.connections_dir.glob("*.md")) == []

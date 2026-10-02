import json

import pytest

from bron import frontmatter as fm
from bron.approvals import append_always_allow, take_notice, to_entry
from bron.briefing import build_briefing
from bron.loader import load
from bron.sync import run_sync
from vaultkit import add_connection, set_meta


def claude_file(vault, local=False):
    return vault.root / ".claude" / ("settings.local.json" if local else "settings.json")


def click_always_allow(vault, *rules, local=False, extra=None):
    """What Claude Code does when the user picks "Yes, and don't ask again"."""
    path = claude_file(vault, local)
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data.update(extra or {})
    data.setdefault("permissions", {}).setdefault("allow", []).extend(rules)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")


def bron_allows(vault):
    return load(vault).agents["bron"].always_allow


@pytest.fixture
def synced(vault):
    add_connection(vault, "Gmail", type="native", claude="claude_ai_Gmail")
    assert run_sync(vault).ok
    return vault


def test_rules_map_to_always_allow_entries(synced):
    cfg = load(synced)
    assert to_entry("Bash(git push:*)", cfg) == "shell:git push"
    assert to_entry("Bash(npm run test *)", cfg) == "shell:npm run test"
    assert to_entry("Bash(rm)", cfg) == "shell:rm"
    assert to_entry("mcp__claude_ai_Gmail__reply", cfg) == "mcp:Gmail:reply"
    assert to_entry("mcp__claude_ai_Gmail", cfg) is None
    assert to_entry("mcp__claude_ai_Unknown__x", cfg) is None
    assert to_entry("WebFetch(domain:carta.com)", cfg) is None
    assert to_entry('Bash(echo "a:b")', cfg) is None


def test_a_click_survives_sync_and_lands_in_bron_always_allow(synced):
    click_always_allow(synced, "Bash(git push:*)", "mcp__claude_ai_Gmail__reply")
    result = run_sync(synced)
    assert result.ok
    assert bron_allows(synced) == ["shell:git push", "mcp:Gmail:reply"]
    allow = json.loads(claude_file(synced).read_text(encoding="utf-8"))["permissions"]["allow"]
    assert "Bash(git push)" in allow and "mcp__claude_ai_Gmail__reply" in allow
    assert result.report.backup_dir is None  # a click isn't a hand edit: no backup, no note
    assert take_notice(synced) == 'Saved your "always allow" choices for Bron: shell git push; Gmail reply.'
    assert take_notice(synced) == ""
    assert run_sync(synced).ok and bron_allows(synced) == ["shell:git push", "mcp:Gmail:reply"]


def test_claude_only_rules_move_to_the_local_settings_file(synced):
    click_always_allow(synced, "WebFetch(domain:carta.com)")
    assert run_sync(synced).ok
    local = json.loads(claude_file(synced, local=True).read_text(encoding="utf-8"))
    assert local == {"permissions": {"allow": ["WebFetch(domain:carta.com)"]}}
    assert bron_allows(synced) == []
    assert run_sync(synced).ok
    assert json.loads(claude_file(synced, local=True).read_text(encoding="utf-8")) == local


def test_local_settings_rules_are_imported_and_removed(synced):
    click_always_allow(synced, "Bash(git status:*)", "Read(~/secrets/**)", local=True, extra={"env": {"X": "1"}})
    assert run_sync(synced).ok
    assert bron_allows(synced) == ["shell:git status"]
    local = json.loads(claude_file(synced, local=True).read_text(encoding="utf-8"))
    assert local == {"env": {"X": "1"}, "permissions": {"allow": ["Read(~/secrets/**)"]}}


def test_an_allow_bron_generated_and_the_user_removed_is_not_reimported(synced):
    bron = synced.agents_dir / "Bron" / "Agent.md"
    set_meta(bron, always_allow=["shell:git status"])
    assert run_sync(synced).ok
    set_meta(bron, always_allow=[])
    assert run_sync(synced).ok
    assert bron_allows(synced) == []
    assert take_notice(synced) == ""


def test_appending_keeps_the_rest_of_agent_md(tmp_path):
    path = tmp_path / "Agent.md"
    path.write_text(
        "---\nname: Bron\n# my note\nalways_allow:\n  - shell:git status\n  - delete-files\nrole: Chief of Staff\n---\nBody stays.\n",
        encoding="utf-8",
    )
    assert append_always_allow(path, ["shell:git status", "shell:git push"]) == ["shell:git push"]
    text = path.read_text(encoding="utf-8")
    assert "# my note\n" in text and text.endswith("---\nBody stays.\n")
    meta = fm.read(path).meta
    assert meta["always_allow"] == ["shell:git status", "delete-files", "shell:git push"] and meta["role"] == "Chief of Staff"
    bare = tmp_path / "Bare.md"
    bare.write_text("---\nname: Bron\nrole: x\n---\nBody.\n", encoding="utf-8")
    assert append_always_allow(bare, ["mcp:Gmail:reply"]) == ["mcp:Gmail:reply"]
    assert fm.read(bare).meta["always_allow"] == ["mcp:Gmail:reply"] and fm.read(bare).body == "Body.\n"
    assert append_always_allow(bare, ["MCP:gmail:reply"]) == []


def test_a_failed_save_keeps_the_click_where_it_is(synced, monkeypatch):
    from bron import approvals

    click_always_allow(synced, "Bash(git push:*)")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    original = approvals.append_always_allow
    monkeypatch.setattr(approvals, "append_always_allow", fail)
    result = run_sync(synced)
    assert result.ok and "approvals.import" in {i.code for i in result.issues}
    assert "Bash(git push:*)" in claude_file(synced).read_text(encoding="utf-8")
    monkeypatch.setattr(approvals, "append_always_allow", original)
    assert run_sync(synced).ok
    assert bron_allows(synced) == ["shell:git push"]


def test_nothing_to_import_in_a_fresh_vault(vault):
    assert run_sync(vault).ok
    assert take_notice(vault) == ""


def test_the_briefing_shows_the_notice_once_and_never_in_a_ticket_run(synced, monkeypatch):
    click_always_allow(synced, "Bash(git push:*)")
    assert run_sync(synced).ok
    monkeypatch.setenv("BRON_TICKET", "T-0001")
    assert "always allow" not in build_briefing(synced, cli="claude")
    monkeypatch.delenv("BRON_TICKET")
    assert 'Saved your "always allow" choices for Bron: shell git push.' in build_briefing(synced, cli="claude")
    assert "always allow" not in build_briefing(synced, cli="claude")

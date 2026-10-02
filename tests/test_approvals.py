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
    assert to_entry("Bash(rm)", cfg) is None  # exact command: must not widen to every "rm ..."
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


def test_an_exact_command_click_stays_exact(synced):
    click_always_allow(synced, "Bash(rm)", "Bash(git push:*)")
    assert run_sync(synced).ok
    assert bron_allows(synced) == ["shell:git push"]
    local = json.loads(claude_file(synced, local=True).read_text(encoding="utf-8"))
    assert local == {"permissions": {"allow": ["Bash(rm)"]}}


def test_import_crash_never_breaks_sync_or_loses_the_click(synced, monkeypatch):
    from bron import approvals

    click_always_allow(synced, "Bash(git push:*)")

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(approvals, "import_approvals", boom)
    result = run_sync(synced)
    assert result.ok and "approvals.import" in {i.code for i in result.issues}
    assert "Bash(git push:*)" in claude_file(synced).read_text(encoding="utf-8")


def test_read_only_local_settings_do_not_lose_the_click(synced):
    click_always_allow(synced, "Bash(git status:*)", "WebFetch(domain:carta.com)", local=True)
    click_always_allow(synced, "Bash(git push:*)")
    local = claude_file(synced, local=True)
    local.chmod(0o444)
    try:
        result = run_sync(synced)
        assert result.ok
        in_agent = "shell:git push" in bron_allows(synced)
        in_settings = "Bash(git push:*)" in claude_file(synced).read_text(encoding="utf-8")
        assert in_agent or in_settings
    finally:
        local.chmod(0o644)


def test_a_non_object_permissions_value_does_not_crash(synced):
    claude_file(synced).write_text(json.dumps({"permissions": "text"}), encoding="utf-8")
    claude_file(synced, local=True).write_text(json.dumps({"permissions": "text"}), encoding="utf-8")
    assert run_sync(synced).ok


def test_comments_inside_a_block_list_survive(tmp_path):
    path = tmp_path / "Agent.md"
    path.write_text(
        "---\nname: Bron\nalways_allow:\n  - shell:git status\n# top comment\n  # inner comment\n  - delete-files\nrole: x\n---\nBody.\n",
        encoding="utf-8",
    )
    assert append_always_allow(path, ["shell:git push"]) == ["shell:git push"]
    text = path.read_text(encoding="utf-8")
    assert "# top comment\n" in text and "  # inner comment\n" in text
    meta = fm.read(path).meta
    assert meta["always_allow"] == ["shell:git status", "delete-files", "shell:git push"] and meta["role"] == "x"


def test_missing_last_record_does_not_treat_generated_rules_as_clicks(synced):
    bron = synced.agents_dir / "Bron" / "Agent.md"
    set_meta(bron, always_allow=["shell:git status"])
    assert run_sync(synced).ok
    (synced.state_dir / "claude-settings.last.json").unlink()
    set_meta(bron, always_allow=[])
    assert run_sync(synced).ok
    assert bron_allows(synced) == []
    assert take_notice(synced) == ""


def test_a_hand_edit_plus_a_click_imports_and_backs_up(synced):
    click_always_allow(synced, "Bash(git push:*)", extra={"env": {"HAND": "1"}})
    result = run_sync(synced)
    assert result.ok and bron_allows(synced) == ["shell:git push"]
    assert result.report.backup_dir is not None


# ---- final review: a failed import never freezes settings.json; hand removals are hand edits ----

def test_an_unreadable_local_file_still_updates_settings_and_keeps_the_click(synced):
    click_always_allow(synced, "Bash(git push:*)")
    claude_file(synced, local=True).write_text("{ broken", encoding="utf-8")
    set_meta(synced.agents_dir / "Bron" / "Agent.md", ask_before=["shell:terraform apply"])
    result = run_sync(synced)
    assert result.ok
    warning = next(i for i in result.issues if i.code == "approvals.import")
    assert warning.level == "warning" and "settings.local.json" in warning.message
    permissions = json.loads(claude_file(synced).read_text(encoding="utf-8"))["permissions"]
    assert any("terraform apply" in rule for rule in permissions["ask"])  # the new ask rule reached Claude Code
    assert "Bash(git push:*)" in permissions["allow"]  # the click that couldn't be imported is still there
    assert result.report.backup_dir is None
    last = json.loads((synced.state_dir / "claude-settings.last.json").read_text(encoding="utf-8"))
    assert "Bash(git push:*)" not in last["permissions"]["allow"]  # so it is still a candidate next time
    assert claude_file(synced, local=True).read_text(encoding="utf-8") == "{ broken"
    claude_file(synced, local=True).write_text("{}", encoding="utf-8")
    assert run_sync(synced).ok
    assert bron_allows(synced) == ["shell:git push"]


def test_a_failed_import_is_mentioned_at_session_start(synced, monkeypatch):
    from bron.hooks import main as hook
    import io

    monkeypatch.setenv("BRON_VAULT", str(synced.root))
    claude_file(synced, local=True).write_text("{ broken", encoding="utf-8")
    set_meta(synced.agents_dir / "Bron" / "Agent.md", ask_before=["shell:terraform apply"])
    out = io.StringIO()
    assert hook("session-start", "claude", stdin=io.StringIO(""), stdout=out) == 0
    notes = [line for line in out.getvalue().splitlines() if "settings.local.json" in line]
    assert len(notes) == 1 and "Tell the user in one line" in notes[0]


def test_a_crashed_import_still_regenerates_settings(synced, monkeypatch):
    from bron import approvals

    click_always_allow(synced, "Bash(git push:*)")
    set_meta(synced.agents_dir / "Bron" / "Agent.md", ask_before=["shell:terraform apply"])
    monkeypatch.setattr(approvals, "import_approvals", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    result = run_sync(synced)
    assert result.ok and "approvals.import" in {i.code for i in result.issues}
    permissions = json.loads(claude_file(synced).read_text(encoding="utf-8"))["permissions"]
    assert any("terraform apply" in rule for rule in permissions["ask"])
    assert "Bash(git push:*)" in permissions["allow"]


def test_a_hand_removal_of_a_generated_allow_rule_is_backed_up(synced):
    bron = synced.agents_dir / "Bron" / "Agent.md"
    set_meta(bron, always_allow=["shell:git status"])
    assert run_sync(synced).ok
    data = json.loads(claude_file(synced).read_text(encoding="utf-8"))
    data["permissions"]["allow"] = [r for r in data["permissions"]["allow"] if "git status" not in r]
    claude_file(synced).write_text(json.dumps(data, indent=2), encoding="utf-8")
    result = run_sync(synced)
    assert result.ok and result.report.backup_dir is not None

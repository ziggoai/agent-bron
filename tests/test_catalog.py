from bron.loader import load
from vaultkit import add_agent, set_meta


def test_model_aliases_resolve_friendly_names(vault):
    catalog = load(vault).catalog
    assert catalog.resolve_model("claude", "Opus 5.5") == "claude-opus-5-5"
    assert catalog.resolve_model("claude", "opus") == "opus"
    assert catalog.resolve_model("claude", "default") is None
    assert catalog.resolve_model("claude", None) is None
    assert catalog.resolve_model("codex", "gpt-6.1-sol") == "gpt-6.1-sol"


def test_actions_resolve_groups_and_raw_entries(vault):
    catalog = load(vault).catalog
    acts = catalog.resolve_actions(["git-push", "send-email", "mcp:carta:mutate", "shell:rm -rf", "nonsense", "mcp:broken"])
    assert ("git", "push") in acts.shell
    assert ("rm", "-rf") in acts.shell
    assert "send_message" in acts.mcp["gmail"]
    assert acts.mcp["carta"] == {"mutate"}
    assert acts.unknown == ["nonsense", "mcp:broken"]


def test_always_allow_wins_over_ask_before(vault):
    add_agent(vault, "CFO", ask_before=["git-push", "send-email"], always_allow=["git-push", "mcp:gmail:send_message"])
    cfg = load(vault)
    ask, allow = cfg.catalog.permissions_for(cfg.agents["cfo"])
    assert ask.shell == []
    assert ("git", "push") in allow.shell
    assert "send_message" not in ask.mcp["gmail"]
    assert "reply_to_message" in ask.mcp["gmail"]


def test_settings_can_add_action_groups(vault):
    set_meta(vault.settings_file, action_groups={"wire-money": {"mcp": {"bank": ["transfer"]}}})
    catalog = load(vault).catalog
    assert catalog.resolve_actions(["wire-money"]).mcp == {"bank": {"transfer"}}


def test_malformed_group_is_reported(vault):
    set_meta(vault.settings_file, action_groups={"bad": {"shell": "git push"}})
    assert any(i.code == "permissions.bad-group" for i in load(vault).issues)

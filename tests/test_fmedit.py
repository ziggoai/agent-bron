import pytest

from bron import frontmatter as fm
from bron.fmedit import EditError, edit_meta, replace_body, scalar

AGENT = """---
name: CFO
# the role line below was written by hand
role: Chief Financial Officer
reports_to: Bron
models:
  claude: default
  codex: default
runs_in: codex
helpers:
  - reader
  # keep me
  - researcher
connections: [Carta]
ask_before: [delete-files]
always_allow: []
---

# Who you are
You are the CFO.
"""


def test_changed_keys_are_rewritten_and_everything_else_is_kept():
    new = edit_meta(AGENT, {"role": "Finance lead", "connections": ["Carta", "Google Drive"], "models": {"claude": "opus-5.5", "codex": "default"}})
    meta = fm.parse(new).meta
    assert meta["role"] == "Finance lead" and meta["connections"] == ["Carta", "Google Drive"]
    assert meta["models"] == {"claude": "opus-5.5", "codex": "default"}
    assert meta["helpers"] == ["reader", "researcher"] and meta["runs_in"] == "codex"
    assert "# the role line below was written by hand\n" in new and "# keep me\n" in new
    assert new.endswith("---\n\n# Who you are\nYou are the CFO.\n")


def test_block_lists_are_replaced_and_their_comments_kept():
    new = edit_meta(AGENT, {"helpers": ["reader"]})
    assert fm.parse(new).meta["helpers"] == ["reader"]
    assert "# keep me\n" in new and "  - researcher\n" not in new


def test_missing_keys_are_added_and_none_removes():
    new = edit_meta(AGENT, {"tone": "brief and direct", "always_allow": None})
    meta = fm.parse(new).meta
    assert meta["tone"] == "brief and direct" and "always_allow" not in meta


def test_values_that_need_quotes_get_them():
    for value in ("Head of: Finance", "yes", "2026-11-14", "#1 analyst", "12", "", "a, b"):
        assert fm.parse(f"---\nx: {scalar(value)}\n---\n").meta["x"] == value
    new = edit_meta(AGENT, {"ask_before": ["delete-files", "mcp:Gmail:send_message", "shell:git push"]})
    assert fm.parse(new).meta["ask_before"] == ["delete-files", "mcp:Gmail:send_message", "shell:git push"]


def test_files_without_a_settings_block_are_refused():
    with pytest.raises(EditError):
        edit_meta("# no settings\n", {"x": "y"})
    with pytest.raises(EditError):
        edit_meta("---\nname: x\n", {"x": "y"})


def test_the_body_can_be_replaced_without_touching_the_settings():
    new = replace_body(AGENT, "# Who you are\nYou are the new CFO.")
    assert new.startswith(AGENT.split("\n---\n")[0] + "\n---\n")
    assert fm.parse(new).body == "\n# Who you are\nYou are the new CFO.\n"

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


def test_column_zero_comment_above_next_key_stays_in_place():
    text = """---
role: Chief Financial Officer
# explains runs_in
runs_in: codex
---

Body
"""
    new = edit_meta(text, {"role": "Finance lead"})
    assert "# explains runs_in\nruns_in: codex" in new


def test_comment_block_before_closing_fence_stays_in_place():
    text = """---
role: Chief Financial Officer
runs_in: codex
# this is important
---

Body
"""
    new = edit_meta(text, {"runs_in": "claude"})
    assert "# this is important\n---" in new


def test_trailing_comment_two_spaces_is_preserved():
    text = """---
role: Chief Financial Officer  # keep
---

Body
"""
    new = edit_meta(text, {"role": "Finance lead"})
    parsed = fm.parse(new)
    assert parsed.meta["role"] == "Finance lead"
    assert "role: Finance lead  # keep\n" in new
    # Verify no blank line after the comment
    assert "# keep\n\n" not in new


def test_trailing_comment_one_space_is_preserved():
    text = """---
role: Chief Financial Officer # keep
---

Body
"""
    new = edit_meta(text, {"role": "Finance lead"})
    parsed = fm.parse(new)
    assert parsed.meta["role"] == "Finance lead"
    assert "role: Finance lead # keep\n" in new
    # Verify spacing is preserved (one space)
    assert "role: Finance lead  # keep" not in new
    assert "# keep\n\n" not in new


def test_quoted_value_with_hash_is_not_treated_as_comment():
    text = """---
role: "Chief: Financial # Officer"
---

Body
"""
    new = edit_meta(text, {"role": "Finance lead"})
    parsed = fm.parse(new)
    assert parsed.meta["role"] == "Finance lead"
    # The hash is part of the quoted value, not a trailing comment
    assert "# Officer" not in new


def test_scalar_with_trailing_comment_not_duplicated():
    text = """---
role: Chief Financial Officer  # keep
runs_in: codex
---

Body
"""
    new = edit_meta(text, {"role": "Finance lead"})
    parsed = fm.parse(new)
    assert parsed.meta["role"] == "Finance lead"
    # The comment should appear exactly once
    assert new.count("# keep") == 1
    # And no blank line after the comment
    assert "# keep\n\n" not in new


def test_quoted_keys_are_matched_and_not_duplicated():
    text = '''---
"role": Chief Financial Officer
---

Body
'''
    new = edit_meta(text, {"role": "Finance lead"})
    meta = fm.parse(new).meta
    assert meta["role"] == "Finance lead"
    # Ensure the key appears only once (not duplicated)
    role_lines = [line for line in new.split("\n") if "role" in line and ":" in line]
    assert len(role_lines) == 1


def test_single_quoted_keys_are_matched():
    text = """---
'role': Chief Financial Officer
---

Body
"""
    new = edit_meta(text, {"role": "Finance lead"})
    meta = fm.parse(new).meta
    assert meta["role"] == "Finance lead"


def test_unusual_yaml_key_form_raises_error():
    # Using YAML's explicit key form: ? key\n: value
    # The key is in parsed meta but doesn't match the regex
    text = """---
? role
: Chief Financial Officer
---

Body
"""
    with pytest.raises(EditError):
        edit_meta(text, {"role": "Finance lead"})


def test_replace_body_preserves_leading_indentation():
    text = """---
name: Test
---

Body
"""
    body = "    code line\n    more code"
    new = replace_body(text, body)
    assert fm.parse(new).body == "\n    code line\n    more code\n"


def test_replace_body_validates_settings_block():
    text = "# no settings block\n"
    with pytest.raises(EditError):
        replace_body(text, "new body")


def _block(*lines):
    return "---\n" + "".join(line + "\n" for line in lines) + "---\n\nBody\n"


def test_trailing_comment_on_a_flow_list_is_kept_exactly():
    new = edit_meta(_block("tags: [a, b]  # c", "runs_in: codex"), {"tags": ["x", "z"]})
    assert new == _block("tags: [x, z]  # c", "runs_in: codex")


def test_trailing_comment_after_a_value_with_an_apostrophe_is_kept_exactly():
    new = edit_meta(_block("role: O'Brien  # keep"), {"role": "Lead"})
    assert new == _block("role: Lead  # keep")


def test_hash_inside_quotes_is_part_of_the_value_exactly():
    assert edit_meta(_block('role: "a  # b"'), {"role": "Lead"}) == _block("role: Lead")
    assert edit_meta(_block('role: "a  # b"  # c'), {"role": "Lead"}) == _block("role: Lead  # c")


def test_comment_on_a_block_dict_key_stays_on_the_key_line_for_a_new_dict():
    new = edit_meta(_block("models:  # c", "  claude: default", "runs_in: codex"), {"models": {"claude": "opus-5.5"}})
    assert new == _block("models:  # c", "  claude: opus-5.5", "runs_in: codex")


def test_comments_moved_out_of_a_replaced_block_go_to_column_0_exactly():
    new = edit_meta(_block("helpers:", "  - reader", "  # keep me", "  - researcher", "runs_in: codex"), {"helpers": ["reader"]})
    assert new == _block("# keep me", "helpers: [reader]", "runs_in: codex")


def test_a_trailing_comment_on_a_replaced_list_item_is_kept_above_the_key_exactly():
    lines = ("can_assign_to:", "  - CFO  # the money person", "  - 'A # B'", "  - Analyst", "runs_in: codex")
    new = edit_meta(_block(*lines), {"can_assign_to": ["CFO", "Ops"]})
    assert new == _block("# the money person", "can_assign_to: [CFO, Ops]", "runs_in: codex")
    new = edit_meta(_block("models:", "  claude: default  # fast one", "runs_in: codex"), {"models": {"claude": "opus-5.5"}})
    assert new == _block("# fast one", "models:", "  claude: opus-5.5", "runs_in: codex")


def test_comment_on_a_block_key_moves_onto_a_new_flow_list():
    new = edit_meta(_block("tags:  # c", "  - a", "runs_in: codex"), {"tags": ["x"]})
    assert new == _block("tags: [x]  # c", "runs_in: codex")
    new = edit_meta(_block("models:  # c", "  claude: default"), {"models": ["p"]})
    assert new == _block("models: [p]  # c")


def test_comment_on_a_block_key_moves_onto_a_new_scalar():
    new = edit_meta(_block("models:  # c", "  claude: default"), {"models": "p"})
    assert new == _block("models: p  # c")
    new = edit_meta(_block("models: # c", "  claude: default"), {"models": "p"})
    assert new == _block("models: p # c")

import pytest

from bron import frontmatter as fm


def test_parse_reads_meta_and_body():
    doc = fm.parse("---\nname: Bron\nhelpers: [reader]\n---\n# Hello\n")
    assert doc.meta == {"name": "Bron", "helpers": ["reader"]}
    assert doc.body == "# Hello\n"


def test_parse_without_frontmatter_keeps_whole_text_as_body():
    doc = fm.parse("# Just a note\n")
    assert doc.meta == {}
    assert doc.body == "# Just a note\n"


def test_parse_tolerates_bom_and_windows_line_endings():
    doc = fm.parse("﻿---\r\nname: Bron\r\n---\r\nBody\r\n")
    assert doc.meta == {"name": "Bron"}
    assert doc.body == "Body\r\n"


def test_parse_rejects_unclosed_block():
    with pytest.raises(fm.FrontmatterError, match="closing"):
        fm.parse("---\nname: Bron\n")


def test_parse_rejects_invalid_yaml():
    with pytest.raises(fm.FrontmatterError, match="not valid YAML"):
        fm.parse("---\nname: [unclosed\n---\n")


def test_parse_rejects_a_list_instead_of_settings():
    with pytest.raises(fm.FrontmatterError, match="key: value"):
        fm.parse("---\n- a\n- b\n---\n")


def test_dump_keeps_order_and_unicode_and_round_trips():
    doc = fm.Document({"name": "Ágora", "b": 1, "a": [1, 2]}, "Corpo\n")
    text = fm.dump(doc)
    assert text.index("name") < text.index("b:") < text.index("a:")
    assert "Ágora" in text
    assert fm.parse(text).meta == doc.meta
    assert fm.parse(text).body == "Corpo\n"


def test_dump_without_meta_is_just_the_body():
    assert fm.dump(fm.Document({}, "x\n")) == "x\n"


def test_write_creates_folders(tmp_path):
    path = tmp_path / "a" / "b" / "note.md"
    fm.write(path, fm.Document({"k": "v"}, "body\n"))
    assert fm.read(path).meta == {"k": "v"}


def test_dump_is_block_style_at_top_level():
    text = fm.dump(fm.Document({"name": "bron", "description": "x"}, ""))
    assert text.startswith("---\nname: bron\ndescription: x\n---\n")


def test_dump_lists_round_trip():
    doc = fm.Document({"name": "bron", "helpers": ["reader", "researcher"]}, "Body\n")
    text = fm.dump(doc)
    assert "helpers: [reader, researcher]" in text
    assert fm.parse(text) == doc

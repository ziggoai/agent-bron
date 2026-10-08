"""The read-documents skill (the wiki maintainer's procedure) and the short rules in AGENTS.md."""
import re
import shlex
from pathlib import Path

from bron import frontmatter as fm
from bron.agents_md import render_agents_md
from bron.cli import build_parser
from bron.loader import load

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "core" / "Skills" / "read-documents" / "SKILL.md"


def commands(text):
    return re.findall(r"\.bron/bin/bron\s+[^\n`]+", text)


def parse(cmd):
    norm = cmd.replace(".bron/bin/bron", "").strip()
    norm = re.sub(r"\s*\[.*?\]\s*", " ", norm)
    norm = re.sub(r"<[^>]*>", "x", norm).replace("…", "x").replace("N-M", "1-2")
    build_parser().parse_args(shlex.split(" ".join(norm.split())))


def knowledge_section(vault):
    return render_agents_md(load(vault)).split("## Knowledge base", 1)[1].split("\n## ", 1)[0]


def test_the_skill_is_a_core_skill_with_the_whole_procedure(vault):
    assert "read-documents" in load(vault).skills
    meta = fm.read(SKILL).meta
    assert meta["name"] == "read-documents" and "Knowledge/" in meta["description"]
    text = SKILL.read_text(encoding="utf-8")
    for must in ("Knowledge/Schema.md", "kb show", "--pages-only", "wiki done", "(see [[", "previously", "**Conflict:**",
                 "two or more documents", "Your edits win", "## Judgement checkup", "Check the wiki", "wiki check --all",
                 "Save this as a page?", "finish the wiki pages", "Never poll", "index.md", "log.md",
                 "never go and fetch", "doc_type", "organisation:", "Background runs",
                 "orphan", "keep `doc` in quotes"):
        assert must in text, must
    found = commands(text)
    assert len(found) >= 6
    for cmd in found:
        parse(cmd)


def test_agents_md_points_to_the_skill_and_the_drive_rules(vault):
    section = knowledge_section(vault)
    assert len(section) <= 1600
    for must in ("read-documents", "Drive link", "Google Doc, Sheet or Slides", "Never download or copy a Drive file",
                 "Never poll", "Save this as a page?", "--organisation", "Knowledge/Schema.md", "wiki done"):
        assert must in section, must
    assert "kb label" not in section


def test_the_skill_quotes_aliases_and_keeps_pages_current(vault):
    text = SKILL.read_text(encoding="utf-8")
    assert "aliases: []\ndoc:" not in text and "aliases: [<other names" not in text  # the page templates quote them
    assert 'aliases: ["<other name>", "<abbreviation>"]' in text
    assert "Put every alias in double quotes" in text
    assert "check that the page's `summary` still holds" in text
    assert "delete the question" in text


def test_the_skill_keeps_growing_pages_short_and_uses_readers_well(vault):
    text = SKILL.read_text(encoding="utf-8")
    assert "own topic page" in text  # long lists move out of a page
    assert "from the readers' notes" in text
    assert "sleep" in text  # never wait with sleep
    assert "stop a background run" not in text  # the old, wrong shell claim
    assert "Claude Code can't check" not in text
    reader = (REPO / "core" / "Helpers" / "reader.md").read_text(encoding="utf-8")
    assert "=====" in reader

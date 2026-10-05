"""Bron is a general framework: the wiki text it ships is domain-neutral and carries no personal data."""
import re
from pathlib import Path

import pytest

from bron.agents_md import render_agents_md
from bron.loader import load

REPO = Path(__file__).resolve().parents[1]
DOMAIN = re.compile(r"\b(funds?|fundo|venture|VC|portfolio|investors?|investments?|LPA|capital calls?|cap tables?|"
                    r"term sheets?|side letters?|K-1)\b", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
SHIPPED = ["core/Skills/read-documents/SKILL.md", "core/Templates/Schema.md", "template/Knowledge/Schema.md",
           "template/Knowledge/index.md", "template/Knowledge/log.md", "core/Manual/knowledge.md"]


@pytest.mark.parametrize("rel", SHIPPED)
def test_shipped_wiki_text_is_domain_neutral(rel):
    text = (REPO / rel).read_text(encoding="utf-8")
    assert DOMAIN.findall(text) == [] and EMAIL.findall(text) == []


def test_the_0_8_0_release_notes_and_the_agents_rules_are_domain_neutral(vault):
    notes = (REPO / "CHANGELOG.md").read_text(encoding="utf-8").split("## 0.8.0", 1)[1].split("\n## ", 1)[0]
    section = render_agents_md(load(vault)).split("## Knowledge base", 1)[1].split("\n## ", 1)[0]
    for text in (notes, section):
        assert DOMAIN.findall(text) == [] and EMAIL.findall(text) == []
    for must in ("wiki", "Schema.md", "bron wiki check", "--organisation", "bron kb label", "Nothing is being read."):
        assert must in notes, must


def test_the_manual_explains_the_wiki():
    text = (REPO / "core" / "Manual" / "knowledge.md").read_text(encoding="utf-8")
    for must in ("Knowledge/Schema.md", "index.md", "log.md", "read-documents", "bron wiki check", "--pages-only",
                 "--organisation", "finish the wiki pages", "Online-only files are downloaded as they're read",
                 "never copies", "two or more documents", "previously", "Karpathy"):
        assert must in text, must
    assert "kb label" not in text and "labels: false" not in text

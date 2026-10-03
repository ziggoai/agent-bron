import time

import pytest

from bron.cli import main
from bron.loader import load
from bron.memory import commands, index
from vaultkit import add_agent


def note(vault, agent, name, body, *, date="2026-10-03 09:15", session="s1"):
    folder = vault.agents_dir / agent / "Memory" / "Conversations" / "2026-10"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.md"
    path.write_text(f"---\ndate: {date}\ncli: claude\nagent: {agent}\nsession_id: {session}\n---\n{body}\n", encoding="utf-8")
    return path


@pytest.fixture
def cfg(vault):
    add_agent(vault, "CFO")
    return load(vault)


def test_finds_shared_and_own_facts_and_conversations(vault, cfg):
    commands.remember(vault, cfg, as_agent="Bron", text="Carta is the source of truth for valuations")
    commands.remember(vault, cfg, as_agent="Bron", text="Valuation memos go to the IC folder", scope="mine")
    note(vault, "Bron", "2026-10-03 09.15 Q3 valuation review", "## Asked\n- Review Q3 valuations\n## Decided\n- Use Carta numbers")
    hits = index.search(vault, cfg, as_agent="Bron", query="valuation")
    kinds = {h.kind for h in hits}
    assert kinds == {"shared", "own", "conversation"}
    conv = next(h for h in hits if h.kind == "conversation")
    assert conv.title == "Q3 valuation review" and conv.date.startswith("2026-10-03")


def test_other_agents_conversations_only_with_all(vault, cfg):
    note(vault, "CFO", "2026-10-03 10.00 Waterfall model", "## Asked\n- Build the waterfall")
    assert index.search(vault, cfg, as_agent="Bron", query="waterfall") == []
    assert [h.agent for h in index.search(vault, cfg, as_agent="Bron", query="waterfall", all_agents=True)] == ["CFO"]


def test_search_ignores_accents_in_both_directions(vault, cfg):
    commands.remember(vault, cfg, as_agent="Bron", text="O relatório trimestral sai no dia 15")
    commands.remember(vault, cfg, as_agent="Bron", text="A decisao foi adiar o fechamento")
    assert index.search(vault, cfg, as_agent="Bron", query="relatorio")
    assert index.search(vault, cfg, as_agent="Bron", query="decisão")


def test_edits_and_deletions_are_seen(vault, cfg):
    path = note(vault, "Bron", "2026-10-03 09.15 Budget", "## Asked\n- Budget for marketing")
    assert index.search(vault, cfg, as_agent="Bron", query="marketing")
    time.sleep(0.01)
    path.write_text(path.read_text().replace("marketing", "travel"), encoding="utf-8")
    assert not index.search(vault, cfg, as_agent="Bron", query="marketing")
    assert index.search(vault, cfg, as_agent="Bron", query="travel")
    path.unlink()
    assert not index.search(vault, cfg, as_agent="Bron", query="travel")


def test_words_in_any_order_and_partial_words(vault, cfg):
    commands.remember(vault, cfg, as_agent="Bron", text="Quarterly reports exclude written-off companies")
    assert index.search(vault, cfg, as_agent="Bron", query="companies quarterly")
    assert index.search(vault, cfg, as_agent="Bron", query="quarter")


def test_odd_queries_never_crash(vault, cfg):
    for query in ['"', "AND OR NOT", "(", "*", "fmv > 0", "-"]:
        index.search(vault, cfg, as_agent="Bron", query=query)


def test_cli_prints_results_and_nothing_found(vault, cfg, monkeypatch, capsys):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    commands.remember(vault, cfg, as_agent="Bron", text="Board meets on Tuesdays")
    assert main(["memory", "search", "board", "--as", "Bron"]) == 0
    out = capsys.readouterr().out
    assert "Board meets on Tuesdays." in out and "System/Memory/Facts.md" in out
    assert main(["memory", "search", "unicorns", "--as", "Bron"]) == 0
    assert 'Nothing in memory matches "unicorns".' in capsys.readouterr().out


def test_search_is_fast(vault, cfg):
    for i in range(300):
        note(vault, "Bron", f"2026-10-03 09.{i:03d} Topic {i}", f"## Asked\n- Discussed item {i} about fund operations", session=f"s{i}")
    index.search(vault, cfg, as_agent="Bron", query="fund")  # first build
    start = time.perf_counter()
    index.search(vault, cfg, as_agent="Bron", query="operations")
    assert time.perf_counter() - start < 0.2

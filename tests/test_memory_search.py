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


def test_corrupt_database_is_rebuilt(vault, cfg):
    commands.remember(vault, cfg, as_agent="Bron", text="Carta is the source of truth")
    hits = index.search(vault, cfg, as_agent="Bron", query="Carta")
    assert hits
    # Corrupt the database with garbage bytes
    db_path = vault.bron_dir / "memory" / "index.db"
    db_path.write_bytes(b"garbage data")
    # Search should still work, having rebuilt the index
    hits = index.search(vault, cfg, as_agent="Bron", query="Carta")
    assert hits and hits[0].excerpt == "Carta is the source of truth."


def test_truncated_database_is_rebuilt(vault, cfg):
    commands.remember(vault, cfg, as_agent="Bron", text="Board meets on Tuesdays")
    hits = index.search(vault, cfg, as_agent="Bron", query="Board")
    assert hits
    # Truncate/zero the database
    db_path = vault.bron_dir / "memory" / "index.db"
    db_path.write_bytes(b"")
    # Search should still work, having rebuilt the index
    hits = index.search(vault, cfg, as_agent="Bron", query="Board")
    assert hits and hits[0].excerpt == "Board meets on Tuesdays."


def test_visibility_filter_in_sql_prevents_crowding(vault, cfg):
    # Create a shared fact
    commands.remember(vault, cfg, as_agent="Bron", text="Budget priorities are set by the board")
    # Create 40 conversations from CFO that match the query but are not visible to Bron
    for i in range(40):
        note(vault, "CFO", f"2026-10-03 10.{i:02d} Budget item {i}", f"## Asked\n- Discuss budget item {i}\n## Decided\n- Budget adjustment needed", session=f"s{i}")
    # Bron's search should return the shared fact despite the 40 CFO conversations
    hits = index.search(vault, cfg, as_agent="Bron", query="budget")
    assert hits
    assert hits[0].kind == "shared"
    assert "Budget priorities" in hits[0].excerpt


def test_same_size_edit_is_detected(vault, cfg):
    import os
    path = note(vault, "Bron", "2026-10-03 09.15 Budget", "## Asked\n- Budget for marketing")
    assert index.search(vault, cfg, as_agent="Bron", query="marketing")
    time.sleep(0.01)
    # Edit with same length (marketing -> publicity, both 9 chars)
    path.write_text(path.read_text().replace("marketing", "publicity"), encoding="utf-8")
    # Set a distinct mtime
    os.utime(path, ns=(time.time_ns() + 1_000_000_000, time.time_ns() + 1_000_000_000))
    assert not index.search(vault, cfg, as_agent="Bron", query="marketing")
    assert index.search(vault, cfg, as_agent="Bron", query="publicity")


def test_partially_damaged_index_is_rebuilt(vault, cfg):
    # Build a real index with ~30 notes first
    for i in range(30):
        note(vault, "Bron", f"2026-10-03 09.{i:02d} Item {i}", f"## Asked\n- Item {i} about funding", session=f"s{i}")
    index.search(vault, cfg, as_agent="Bron", query="funding")  # build index
    # Now corrupt it: valid page 1, garbage after byte 8192
    db_path = vault.bron_dir / "memory" / "index.db"
    original = db_path.read_bytes()
    corrupted = original[:8192] + b"garbage data corruption" * 100
    db_path.write_bytes(corrupted)
    # Search should still work, having detected and rebuilt
    hits = index.search(vault, cfg, as_agent="Bron", query="funding")
    assert hits


def test_old_schema_database_is_rebuilt(vault, cfg):
    import sqlite3
    # Create an old-schema database (files table with mtime instead of mtime_ns)
    db_path = vault.bron_dir / "memory" / "index.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE files (path TEXT PRIMARY KEY, mtime REAL, size INTEGER)")
    con.execute(
        "CREATE VIRTUAL TABLE entries USING fts5("
        "path UNINDEXED, kind UNINDEXED, agent UNINDEXED, title, date UNINDEXED, body, "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    con.execute("INSERT INTO files VALUES ('dummy.md', 1234567890.0, 100)")
    con.commit()
    con.close()
    # Now try to search; the old schema should be detected and rebuilt
    commands.remember(vault, cfg, as_agent="Bron", text="Schema migration test")
    hits = index.search(vault, cfg, as_agent="Bron", query="Schema")
    assert hits


def test_irrecoverable_corruption_raises_memory_error(vault, cfg, monkeypatch):
    # Build a valid index first
    commands.remember(vault, cfg, as_agent="Bron", text="Important fact")
    index.search(vault, cfg, as_agent="Bron", query="fact")

    # Corrupt it
    db_path = vault.bron_dir / "memory" / "index.db"
    db_path.write_bytes(b"garbage")

    # Monkeypatch the rebuild to keep failing
    original_connect = __import__('sqlite3').connect
    def failing_connect(*args, **kwargs):
        raise __import__('sqlite3').DatabaseError("Simulated persistent failure")
    monkeypatch.setattr(__import__('sqlite3'), 'connect', failing_connect)

    # Search should raise MemoryError, not infinite loop
    with pytest.raises(commands.MemoryError) as exc_info:
        index.search(vault, cfg, as_agent="Bron", query="fact")
    assert "couldn't be rebuilt" in str(exc_info.value)


def test_sidecar_files_are_deleted(vault, cfg):
    import os
    # Build an index
    for i in range(10):
        note(vault, "Bron", f"2026-10-03 09.{i:02d} Item {i}", f"## Asked\n- Item {i}", session=f"s{i}")
    index.search(vault, cfg, as_agent="Bron", query="Item")

    # Create sidecar files manually to verify they get deleted
    db_path = vault.bron_dir / "memory" / "index.db"
    wal_file = db_path.with_suffix(".db-wal")
    journal_file = db_path.with_suffix(".db-journal")
    shm_file = db_path.with_suffix(".db-shm")

    # Write marker files
    wal_file.write_bytes(b"wal marker")
    journal_file.write_bytes(b"journal marker")
    shm_file.write_bytes(b"shm marker")

    # Verify they exist
    assert wal_file.exists()
    assert journal_file.exists()
    assert shm_file.exists()

    # Corrupt main db to trigger rebuild
    db_path.write_bytes(b"corrupted")

    # Search triggers rebuild and cleanup
    index.search(vault, cfg, as_agent="Bron", query="Item")

    # All sidecars should be gone
    assert not wal_file.exists(), "db-wal should be deleted"
    assert not journal_file.exists(), "db-journal should be deleted"
    assert not shm_file.exists(), "db-shm should be deleted"


def test_wrong_schema_version_triggers_rebuild(vault, cfg):
    import sqlite3
    # Create a valid-shape index with user_version = 1
    db_path = vault.bron_dir / "memory" / "index.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA user_version = 1")
    con.execute("CREATE TABLE files (path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER)")
    con.execute(
        "CREATE VIRTUAL TABLE entries USING fts5("
        "path UNINDEXED, kind UNINDEXED, agent UNINDEXED, title, date UNINDEXED, body, "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    # Insert an entry that should be gone after rebuild
    con.execute(
        "INSERT INTO entries (path, kind, agent, title, date, body) VALUES (?, ?, ?, ?, ?, ?)",
        ("oldentry.md", "conversation", "Bron", "Old Entry", "2026-10-01", "This will be deleted on rebuild")
    )
    con.commit()
    con.close()

    # Now save a fact (which will be indexed on search)
    commands.remember(vault, cfg, as_agent="Bron", text="New fact after version mismatch")

    # Search should detect version mismatch and rebuild
    hits = index.search(vault, cfg, as_agent="Bron", query="fact")
    assert hits
    assert hits[0].excerpt == "New fact after version mismatch."

    # Verify version is now 2
    con = sqlite3.connect(db_path)
    version = con.execute("PRAGMA user_version").fetchone()[0]
    assert version == 2, f"Schema version should be 2 after rebuild, got {version}"

    # Verify old entry is gone
    count = con.execute("SELECT COUNT(*) FROM entries WHERE path='oldentry.md'").fetchone()[0]
    assert count == 0, "Old entry should be gone after rebuild"
    con.close()


def test_future_schema_version_triggers_rebuild(vault, cfg):
    import sqlite3
    # Create a valid-shape index with user_version = 3 (future version)
    db_path = vault.bron_dir / "memory" / "index.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA user_version = 3")
    con.execute("CREATE TABLE files (path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER)")
    con.execute(
        "CREATE VIRTUAL TABLE entries USING fts5("
        "path UNINDEXED, kind UNINDEXED, agent UNINDEXED, title, date UNINDEXED, body, "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    con.commit()
    con.close()

    # Now save a fact and search
    commands.remember(vault, cfg, as_agent="Bron", text="Fact with future schema")

    # Search should detect future version and rebuild
    hits = index.search(vault, cfg, as_agent="Bron", query="schema")
    assert hits
    assert hits[0].excerpt == "Fact with future schema."

    # Verify version is now 2 (rebuilt to current)
    con = sqlite3.connect(db_path)
    version = con.execute("PRAGMA user_version").fetchone()[0]
    assert version == 2, f"Schema version should be 2 after rebuild, got {version}"
    con.close()

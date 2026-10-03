"""Search over facts and conversation summaries: a SQLite FTS5 index that follows the notes."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .. import frontmatter as fm
from ..loader import Config
from ..vault import Vault
from . import commands, facts
from .commands import agent_of, conversations_dir, facts_file

_WORD = re.compile(r"\w+", re.UNICODE)
_TITLE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}\.\d{2} (.+)$")
_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class Hit:
    kind: str
    agent: str
    title: str
    date: str
    excerpt: str
    path: Path


def _create_schema(con: sqlite3.Connection) -> None:
    """Create the database schema with current version."""
    con.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
    con.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, mtime_ns INTEGER, size INTEGER)")
    con.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS entries USING fts5("
        "path UNINDEXED, kind UNINDEXED, agent UNINDEXED, title, date UNINDEXED, body, "
        "tokenize='unicode61 remove_diacritics 2')"
    )


def _db(vault: Vault, *, rebuild: bool = False) -> sqlite3.Connection:
    """Open or create the index database, optionally rebuilding from scratch."""
    folder = vault.bron_dir / "memory"
    folder.mkdir(parents=True, exist_ok=True)
    db_path = folder / "index.db"

    if rebuild:
        for f in [db_path, db_path.with_suffix(".db-wal"), db_path.with_suffix(".db-journal"), db_path.with_suffix(".db-shm")]:
            try:
                f.unlink()
            except OSError:
                pass

    con = sqlite3.connect(db_path)
    try:
        # Check schema version FIRST, before creating schema
        version = con.execute("PRAGMA user_version").fetchone()[0]
        # If database has tables and version is wrong, it's old schema - will be deleted and rebuilt
        has_tables = con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0] > 0
        if has_tables and version != _SCHEMA_VERSION:
            con.close()
            raise sqlite3.DatabaseError(f"Schema version mismatch: got {version}, expected {_SCHEMA_VERSION}")
        # Create or update schema if needed
        _create_schema(con)
        return con
    except sqlite3.DatabaseError:
        con.close()
        raise


def _delete_index_files(vault: Vault) -> None:
    """Delete the index database and all its sidecar files."""
    db_path = vault.bron_dir / "memory" / "index.db"
    for f in [db_path, db_path.with_suffix(".db-wal"), db_path.with_suffix(".db-journal"), db_path.with_suffix(".db-shm")]:
        try:
            f.unlink()
        except OSError:
            pass


def _with_recovery(vault: Vault, fn) -> None:
    """Execute a function with automatic recovery on database corruption."""
    try:
        return fn()
    except sqlite3.DatabaseError as exc:
        # Index is corrupt; delete it, rebuild, and retry once
        _delete_index_files(vault)
        try:
            con = _db(vault, rebuild=True)
            con.close()
            return fn()
        except sqlite3.DatabaseError as retry_exc:
            raise commands.MemoryError("Bron's memory search index couldn't be rebuilt; your notes are safe. Try again in a moment.") from retry_exc


def _sources(vault: Vault, cfg: Config) -> dict[Path, tuple[str, str]]:
    """Every note the index covers: path -> (kind, agent name)."""
    found: dict[Path, tuple[str, str]] = {vault.memory_dir / "Facts.md": ("shared", "")}
    for key, agent in cfg.agents.items():
        found[facts_file(vault, cfg, "mine", key)] = ("own", agent.name)
        folder = conversations_dir(cfg, key)
        if folder.is_dir():
            for path in folder.rglob("*.md"):
                found[path] = ("conversation", agent.name)
    return found


def _rows(path: Path, kind: str, agent: str) -> list[tuple]:
    if kind in ("shared", "own"):
        lines = path.read_text(encoding="utf-8").splitlines()
        return [(str(path), kind, agent, f.text, f.date, f.text) for f in facts.parse(lines)]
    try:
        doc = fm.read(path)
        meta, body = doc.meta, doc.body
    except Exception:  # noqa: BLE001 - a note the user broke is still searchable as text
        meta, body = {}, path.read_text(encoding="utf-8", errors="replace")
    match = _TITLE.match(path.stem)
    title = match.group(1) if match else path.stem
    return [(str(path), kind, agent, title, str(meta.get("date", "")), body)]


def _refresh_impl(vault: Vault, cfg: Config) -> None:
    """Internal refresh implementation without recovery wrapper."""
    con = _db(vault)
    with con:
        sources = _sources(vault, cfg)
        known = {row[0]: (row[1], row[2]) for row in con.execute("SELECT path, mtime_ns, size FROM files")}
        live = {}
        for path, (kind, agent) in sources.items():
            try:
                stat = path.stat()
            except OSError:
                continue
            live[str(path)] = (stat.st_mtime_ns, stat.st_size)
            if known.get(str(path)) == (stat.st_mtime_ns, stat.st_size):
                continue
            con.execute("DELETE FROM entries WHERE path = ?", (str(path),))
            try:
                rows = _rows(path, kind, agent)
            except (OSError, UnicodeDecodeError):
                rows = []
            con.executemany("INSERT INTO entries (path, kind, agent, title, date, body) VALUES (?, ?, ?, ?, ?, ?)", rows)
            con.execute("INSERT OR REPLACE INTO files (path, mtime_ns, size) VALUES (?, ?, ?)", (str(path), stat.st_mtime_ns, stat.st_size))
        for gone in set(known) - set(live):
            con.execute("DELETE FROM entries WHERE path = ?", (gone,))
            con.execute("DELETE FROM files WHERE path = ?", (gone,))
    con.close()


def refresh(vault: Vault, cfg: Config) -> None:
    """Refresh the index with automatic recovery on corruption."""
    _with_recovery(vault, lambda: _refresh_impl(vault, cfg))


def _query(text: str, joiner: str) -> str:
    words = [w for w in _WORD.findall(facts.fold(text)) if w]
    return f" {joiner} ".join(f'"{w}"*' for w in words)


def _search_impl(vault: Vault, cfg: Config, *, as_agent: str, query: str, all_agents: bool = False, limit: int = 8) -> list[Hit]:
    """Internal search implementation without recovery wrapper."""
    agent = agent_of(cfg, as_agent)
    refresh(vault, cfg)
    con = _db(vault)
    try:
        hits: list[Hit] = []
        for joiner in ("AND", "OR"):
            match = _query(query, joiner)
            if not match:
                return []
            rows = con.execute(
                "SELECT path, kind, agent, title, date, snippet(entries, 5, '', '', '…', 16) FROM entries "
                "WHERE entries MATCH :match "
                "AND (kind='shared' OR (kind='own' AND agent=:me) OR (kind='conversation' AND (agent=:me OR :all))) "
                "ORDER BY bm25(entries) LIMIT :limit",
                {"match": match, "me": agent.name, "all": all_agents, "limit": limit},
            ).fetchall()
            for path, kind, owner, title, when, excerpt in rows:
                hits.append(Hit(kind, owner, title, when, " ".join(excerpt.split()), Path(path)))
            if hits:
                break
        return hits[:limit]
    finally:
        con.close()


def search(vault: Vault, cfg: Config, *, as_agent: str, query: str, all_agents: bool = False, limit: int = 8) -> list[Hit]:
    """Search with automatic recovery on corruption."""
    return _with_recovery(vault, lambda: _search_impl(vault, cfg, as_agent=as_agent, query=query, all_agents=all_agents, limit=limit))


def render(hits: list[Hit], root: Path) -> str:
    out = []
    for hit in hits:
        where = {"shared": "shared fact", "own": "own note"}.get(hit.kind, f"conversation: {hit.title}")
        if hit.kind == "conversation" and hit.agent:
            where += f" ({hit.agent})"
        try:
            rel = hit.path.relative_to(root)
        except ValueError:
            rel = hit.path
        date = f"{hit.date} · " if hit.date else ""
        out.append(f"- {date}{where}: {hit.excerpt}\n  {rel}")
    return "\n".join(out)

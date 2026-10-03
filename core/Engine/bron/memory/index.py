"""Search over facts and conversation summaries: a SQLite FTS5 index that follows the notes."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .. import frontmatter as fm
from ..loader import Config
from ..vault import Vault
from . import facts
from .commands import agent_of, conversations_dir, facts_file

_WORD = re.compile(r"\w+", re.UNICODE)
_TITLE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}\.\d{2} (.+)$")


@dataclass(frozen=True)
class Hit:
    kind: str
    agent: str
    title: str
    date: str
    excerpt: str
    path: Path


def _db(vault: Vault) -> sqlite3.Connection:
    folder = vault.bron_dir / "memory"
    folder.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(folder / "index.db")
    con.execute("CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, mtime REAL, size INTEGER)")
    con.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS entries USING fts5("
        "path UNINDEXED, kind UNINDEXED, agent UNINDEXED, title, date UNINDEXED, body, "
        "tokenize='unicode61 remove_diacritics 2')"
    )
    return con


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


def refresh(vault: Vault, cfg: Config) -> None:
    con = _db(vault)
    with con:
        sources = _sources(vault, cfg)
        known = {row[0]: (row[1], row[2]) for row in con.execute("SELECT path, mtime, size FROM files")}
        live = {}
        for path, (kind, agent) in sources.items():
            try:
                stat = path.stat()
            except OSError:
                continue
            live[str(path)] = (stat.st_mtime, stat.st_size)
            if known.get(str(path)) == (stat.st_mtime, stat.st_size):
                continue
            con.execute("DELETE FROM entries WHERE path = ?", (str(path),))
            try:
                rows = _rows(path, kind, agent)
            except (OSError, UnicodeDecodeError):
                rows = []
            con.executemany("INSERT INTO entries (path, kind, agent, title, date, body) VALUES (?, ?, ?, ?, ?, ?)", rows)
            con.execute("INSERT OR REPLACE INTO files (path, mtime, size) VALUES (?, ?, ?)", (str(path), stat.st_mtime, stat.st_size))
        for gone in set(known) - set(live):
            con.execute("DELETE FROM entries WHERE path = ?", (gone,))
            con.execute("DELETE FROM files WHERE path = ?", (gone,))
    con.close()


def _query(text: str, joiner: str) -> str:
    words = [w for w in _WORD.findall(facts.fold(text)) if w]
    return f" {joiner} ".join(f'"{w}"*' for w in words)


def search(vault: Vault, cfg: Config, *, as_agent: str, query: str, all_agents: bool = False, limit: int = 8) -> list[Hit]:
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
                "WHERE entries MATCH ? ORDER BY bm25(entries) LIMIT ?",
                (match, limit * 4),
            ).fetchall()
            for path, kind, owner, title, when, excerpt in rows:
                if kind == "own" and owner != agent.name:
                    continue
                if kind == "conversation" and owner != agent.name and not all_agents:
                    continue
                hits.append(Hit(kind, owner, title, when, " ".join(excerpt.split()), Path(path)))
            if hits:
                break
        return hits[:limit]
    finally:
        con.close()


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

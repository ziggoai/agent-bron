"""remember / forget: the commands agents run to keep lasting facts. Notes are the truth."""
from __future__ import annotations

import os
import tempfile
from datetime import date as _date
from pathlib import Path

from ..loader import Config
from ..model import Agent, slug
from ..statefile import locked
from ..vault import Vault
from . import facts
from .secrets import looks_secret

SECRET = "That looks like a password or key, so I didn't save it."
TICKET_SHARED = "Only a conversation with you can change shared memory, so I saved this to my own notes."
TIDY_HINT = " Memory is getting long; I can tidy it."
WRITE_LOCK = "memory.json"


class MemoryError(ValueError):
    """A memory command that can't be done, with the reason in plain words."""


def agent_of(cfg: Config, name: str) -> Agent:
    agent = cfg.agents.get(slug(name))
    if agent is None:
        raise MemoryError(f"There's no agent called {name}.")
    return agent


def facts_file(vault: Vault, cfg: Config, scope: str, agent_key: str) -> Path:
    if scope == "shared":
        return vault.memory_dir / "Facts.md"
    return cfg.agents[agent_key].path.parent / "Memory" / "Facts.md"


def conversations_dir(cfg: Config, agent_key: str) -> Path:
    return cfg.agents[agent_key].path.parent / "Memory" / "Conversations"


def read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as exc:
        raise MemoryError(f"Bron couldn't read {path.name} ({exc.__class__.__name__}); nothing was changed.") from exc


def write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines).rstrip("\n") + "\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _near_limit(lines: list[str], scope: str) -> bool:
    return facts.size(lines) >= 0.9 * facts.LIMITS[scope]


def remember(vault: Vault, cfg: Config, *, as_agent: str, text: str, scope: str = "shared",
             section: str = "decisions", replaces: str = "", today: str | None = None) -> str:
    agent = agent_of(cfg, as_agent)
    if looks_secret(text) or looks_secret(replaces):
        raise MemoryError(SECRET)
    try:
        fact = facts.clean(text)
    except ValueError as exc:
        raise MemoryError(str(exc)) from exc
    prefix = ""
    if scope == "shared" and os.environ.get("BRON_TICKET"):
        scope, prefix = "mine", TICKET_SHARED + " "
    when = today or _date.today().isoformat()
    path = facts_file(vault, cfg, scope, agent.key)
    with locked(vault.state_dir / WRITE_LOCK):
        lines = read_lines(path)
        old = facts.matches(lines, replaces) if replaces else []
        if len(old) == 1:
            lines, verb = facts.replace(lines, old[0], fact, when, agent.name), "Updated"
        else:
            lines, verb = facts.add(lines, fact, section, when, agent.name), "Noted"
        write_lines(path, lines)
    hint = TIDY_HINT if _near_limit(lines, scope) else ""
    return f"{prefix}{verb}: {fact}{hint}"


def forget(vault: Vault, cfg: Config, *, as_agent: str, text: str) -> str:
    agent = agent_of(cfg, as_agent)
    with locked(vault.state_dir / WRITE_LOCK):
        found = []
        for scope in ("shared", "mine"):
            path = facts_file(vault, cfg, scope, agent.key)
            lines = read_lines(path)
            found += [(path, lines, f) for f in facts.matches(lines, text)]
        if not found:
            raise MemoryError(f"I couldn't find a saved fact matching \"{text}\".")
        if len(found) > 1:
            listed = "\n".join(f"- {f.text}" for _, _, f in found)
            raise MemoryError(f"That matches more than one fact; nothing was changed. Say which one:\n{listed}")
        path, lines, fact = found[0]
        write_lines(path, facts.remove(lines, fact))
    return f"Forgotten: {fact.text}"


def forget_conversation(vault: Vault, cfg: Config, *, as_agent: str, query: str) -> str:
    agent = agent_of(cfg, as_agent)
    folder = conversations_dir(cfg, agent.key)
    needle = facts.fold(query)
    notes = sorted(p for p in folder.rglob("*.md") if needle in facts.fold(p.stem)) if folder.is_dir() else []
    if not notes:
        raise MemoryError(f"I couldn't find a conversation matching \"{query}\".")
    if len(notes) > 1:
        listed = "\n".join(f"- {p.stem}" for p in notes)
        raise MemoryError(f"That matches more than one conversation; nothing was changed. Say which one:\n{listed}")
    notes[0].unlink()
    return f"Forgotten: the conversation \"{notes[0].stem}\"."

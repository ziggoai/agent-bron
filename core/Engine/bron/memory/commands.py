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
        # Preserve existing file permissions, or use 0o644 for new files
        if path.exists():
            mode = path.stat().st_mode & 0o777
        else:
            mode = 0o644
        os.chmod(tmp, mode)
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
        if len(old) > 1:
            listed = "\n".join(f"- {f.text}" for f in old)
            raise MemoryError(f"'{replaces}' matches more than one saved fact; nothing was changed. Say which one:\n{listed}")
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
        is_ticket_run = os.environ.get("BRON_TICKET")
        # In ticket runs, only search own notes
        scopes = ("mine",) if is_ticket_run else ("shared", "mine")
        for scope in scopes:
            path = facts_file(vault, cfg, scope, agent.key)
            lines = read_lines(path)
            found += [(path, lines, f, scope) for f in facts.matches(lines, text)]
        # If in ticket run and found nothing in own notes, check if it exists in shared
        if is_ticket_run and not found:
            shared_path = facts_file(vault, cfg, "shared", agent.key)
            shared_lines = read_lines(shared_path)
            shared_matches = facts.matches(shared_lines, text)
            if shared_matches:
                raise MemoryError(f"{TICKET_SHARED}.")
        if not found:
            raise MemoryError(f"I couldn't find a saved fact matching \"{text}\".")
        if len(found) > 1:
            listed = "\n".join(f"- {f.text}" for _, _, f, _ in found)
            raise MemoryError(f"That matches more than one fact; nothing was changed. Say which one:\n{listed}")
        path, lines, fact, _ = found[0]
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
    with locked(vault.state_dir / WRITE_LOCK):
        # File may have vanished between check and delete; treat as already forgotten
        notes[0].unlink(missing_ok=True)
    return f"Forgotten: the conversation \"{notes[0].stem}\"."


def _other_text(lines: list[str]) -> set[str]:
    """The user's own lines that aren't facts or the four standard headings (free text, notes, other headings)."""
    standard = {facts.fold(title) for _, title in facts.SECTIONS}
    out = set()
    for line in lines:
        s = line.strip()
        if not s or facts._FACT.match(line):
            continue
        heading = facts._HEADING.match(s)
        if heading and facts.fold(heading.group(1)) in standard:
            continue
        out.add(s)
    return out


def tidy_change(vault: Vault, cfg: Config, *, as_agent: str, scope: str, draft: str):
    from ..setup import Change, SetupError

    agent = agent_of(cfg, as_agent)
    if scope == "shared" and os.environ.get("BRON_TICKET"):
        raise SetupError("Only a conversation with you can change shared memory.")
    if not draft.strip():
        raise SetupError("The draft is empty; nothing was changed.")
    if looks_secret(draft):
        raise SetupError(SECRET)
    path = facts_file(vault, cfg, scope, agent.key)
    old = facts.parse(read_lines(path))
    new = facts.parse(draft.splitlines())
    kept = {facts.fold(f.text) for f in new}
    dropped = [f.text for f in old if facts.fold(f.text) not in kept]
    lost = _other_text(read_lines(path)) - _other_text(draft.splitlines())
    rel = path.relative_to(vault.root).as_posix()
    summary = [f"Tidy {rel}: {len(old)} facts → {len(new)}."]
    if dropped:
        summary += ["No longer kept as written:", *[f"- {t}" for t in dropped]]
    if lost:
        shown = sorted(lost)
        summary += ["Other text that will be removed:"]
        summary += [f"- {t}" for t in shown[:10]] if len(shown) <= 10 else [f"- {len(shown)} other lines of your own text"]
    return Change(summary=summary, writes={rel: draft.rstrip("\n") + "\n"}, done=f"Tidied {rel}.")

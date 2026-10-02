"""Saved approvals: "don't ask again" choices Claude Code wrote into the vault, moved into always_allow.

In a vault that isn't a git repository Claude Code saves them in .claude/settings.json, which sync
regenerates; inside a git repository it uses .claude/settings.local.json, which sync never writes.
"""
from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter as fm
from .access import claude_server
from .statefile import locked, read_json, update_json
from .vault import Vault

LAST = "claude-settings.last.json"  # exactly what sync last wrote to .claude/settings.json
NOTICE = "approvals-notice.json"
_BASH = re.compile(r"^Bash\(\s*([^*():\"']+?)\s*(?::\*|\s\*)?\s*\)$")
_PLAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]*$")


@dataclass
class Imported:
    entries: list[str] = field(default_factory=list)  # added to the default agent's always_allow
    agent: str = ""
    kept: list[str] = field(default_factory=list)  # Claude-only rules moved to settings.local.json
    problem: str = ""
    keep_settings: bytes | None = None  # on failure: keep .claude/settings.json exactly as it is
    only_allow_changed: bool = False  # .claude/settings.json differs from Bron's copy only in permissions.allow


def to_entry(rule: str, cfg) -> str | None:
    """A Claude permission rule as an always_allow entry, or None when Codex has no equivalent."""
    if not isinstance(rule, str):
        return None
    match = _BASH.match(rule.strip())
    if match:
        words = " ".join(match.group(1).split())
        return f"shell:{words}" if words else None
    for conn in sorted(cfg.connections.values(), key=lambda c: -len(claude_server(c) or "")):
        server = claude_server(conn)
        prefix = f"mcp__{server}__"
        if server and rule.startswith(prefix) and len(rule) > len(prefix):
            return f"mcp:{conn.name}:{rule[len(prefix):]}"
    return None


def _norm(entry: str) -> str:
    return re.sub(r"\s+", " ", entry.strip().lower())


def _flow(value: str) -> str:
    return value if _PLAIN.match(value) else json.dumps(value, ensure_ascii=False)


def append_always_allow(path: Path, entries: list[str]) -> list[str]:
    """Add entries to always_allow in Agent.md, changing only that one setting. Returns what was added."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path.name} has no settings block at the top")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError(f"{path.name}'s settings block has no closing '---' line")
    current = fm.parse(text).meta.get("always_allow") or []
    if isinstance(current, str):
        current = [v.strip() for v in current.split(",") if v.strip()]
    if not isinstance(current, list):
        raise ValueError(f"'always_allow' in {path.name} isn't a list")
    have = {_norm(str(v)) for v in current}
    added: list[str] = []
    for entry in entries:
        if _norm(entry) not in have:
            added.append(entry)
            have.add(_norm(entry))
    if not added:
        return []
    values = [str(v) for v in current] + added
    new_line = "always_allow: [" + ", ".join(_flow(v) for v in values) + "]\n"
    index = next((i for i in range(1, end) if re.match(r"^always_allow\s*:", lines[i])), None)
    if index is None:
        lines.insert(end, new_line)
    else:
        stop = index + 1
        while stop < end and lines[stop].strip() and (lines[stop][0] in " \t" or lines[stop].lstrip().startswith("- ")):
            stop += 1
        lines[index:stop] = [new_line]
    new_text = "".join(lines)
    if fm.parse(new_text).meta.get("always_allow") != values:
        raise ValueError(f"Bron couldn't update 'always_allow' in {path.name} safely")
    tmp = path.with_name(f"{path.name}.{os.getpid()}.bron-tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(path)
    return added


def _load(path: Path, *, strict: bool = False) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if strict:
            raise ValueError(str(exc)) from exc
        return None
    if not isinstance(data, dict):
        if strict:
            raise ValueError("it isn't a settings object")
        return None
    return data


def _allow(data: dict | None) -> list[str]:
    permissions = (data or {}).get("permissions")
    rules = permissions.get("allow") if isinstance(permissions, dict) else None
    return [r for r in rules if isinstance(r, str)] if isinstance(rules, list) else []


def _without_allow(data: dict) -> dict:
    copied = copy.deepcopy(data)
    permissions = dict(copied.get("permissions") or {})
    permissions.pop("allow", None)
    copied["permissions"] = permissions
    return copied


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.bron-tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def import_approvals(vault: Vault, cfg) -> Imported:
    from .gen_claude import project_allow

    out = Imported()
    agent = cfg.default_agent
    claude_dir = vault.root / ".claude"
    if agent is None or not claude_dir.is_dir():
        return out
    out.agent = agent.name
    settings_path, local_path = claude_dir / "settings.json", claude_dir / "settings.local.json"
    disk = _load(settings_path)
    last = _load(vault.state_dir / LAST)
    known = set(_allow(last)) if last is not None else set(project_allow(cfg))
    if disk is not None and last is not None:
        out.only_allow_changed = _without_allow(disk) == _without_allow(last)
    try:
        local = _load(local_path, strict=True)
    except ValueError:
        out.problem = "Claude Code's .claude/settings.local.json can't be read, so Bron left your saved approvals where they are"
        out.keep_settings = settings_path.read_bytes() if settings_path.is_file() else None
        out.only_allow_changed = False
        return out
    project_rules = [r for r in _allow(disk) if r not in known]
    local_rules = _allow(local)
    candidates = project_rules + [r for r in local_rules if r not in project_rules]
    if not candidates:
        return out
    entries: list[str] = []
    claude_only: list[str] = []
    for rule in candidates:
        entry = to_entry(rule, cfg)
        if entry is None:
            claude_only.append(rule)
        elif entry not in entries:
            entries.append(entry)
    try:
        added = append_always_allow(agent.path, entries) if entries else []
    except (OSError, ValueError) as exc:
        out.problem = f'Bron couldn\'t save your "always allow" choices to {agent.name}\'s Agent.md ({exc}); they stay in Claude Code\'s settings until this is fixed'
        out.keep_settings = settings_path.read_bytes() if settings_path.is_file() else None
        out.only_allow_changed = False
        return out
    keep = [r for r in local_rules if r in claude_only] + [r for r in claude_only if r not in local_rules]
    if keep != local_rules:
        data = dict(local or {})
        permissions = dict(data.get("permissions") or {})
        if keep:
            permissions["allow"] = keep
        else:
            permissions.pop("allow", None)
        if permissions:
            data["permissions"] = permissions
        else:
            data.pop("permissions", None)
        _write_json(local_path, data)
    out.kept = [r for r in claude_only if r not in local_rules]
    out.entries = added
    if added:
        record_notice(vault, agent.name, added)
    return out


def remember_generated(vault: Vault, data: bytes) -> None:
    path = vault.state_dir / LAST
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def record_notice(vault: Vault, agent: str, entries: list[str]) -> None:
    def add(data: dict) -> None:
        listed = data.setdefault(agent, [])
        listed += [e for e in entries if e not in listed]

    update_json(vault.state_dir / NOTICE, {}, add)


def describe_entry(entry: str) -> str:
    if entry.startswith("shell:"):
        return "shell " + entry[len("shell:"):]
    if entry.startswith("mcp:"):
        parts = entry.split(":", 2)
        if len(parts) == 3:
            return f"{parts[1]} {parts[2]}"
    return entry


def take_notice(vault: Vault) -> str:
    """The one-time 'Saved your always allow choices' line ('' when there is none)."""
    path = vault.state_dir / NOTICE
    if not path.is_file():
        return ""
    with locked(path):
        data = read_json(path, {})
        path.unlink(missing_ok=True)
    lines = [
        f'Saved your "always allow" choices for {agent}: ' + "; ".join(describe_entry(e) for e in entries) + "."
        for agent, entries in sorted(data.items())
        if isinstance(entries, list) and entries
    ]
    return "\n".join(lines)

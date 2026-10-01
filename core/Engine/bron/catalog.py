"""Built-in lookups kept in Core/Manual as readable pages: model aliases and permission action groups."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter as fm
from .model import DEFAULT_MODEL, Agent, Issue, Settings, conn_key
from .vault import Vault


def norm(value: str) -> str:
    return re.sub(r"\s+", "-", value.strip().lower())


@dataclass
class ActionGroup:
    mcp: dict[str, list[str]] = field(default_factory=dict)  # connection key -> tool names
    shell: list[tuple[str, ...]] = field(default_factory=list)  # command prefixes


@dataclass
class Actions:
    mcp: dict[str, set[str]] = field(default_factory=dict)
    shell: list[tuple[str, ...]] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    def add_shell(self, words: tuple[str, ...]) -> None:
        if words and words not in self.shell:
            self.shell.append(words)


@dataclass
class Catalog:
    model_aliases: dict[str, dict[str, str]] = field(default_factory=dict)
    action_groups: dict[str, ActionGroup] = field(default_factory=dict)

    def resolve_model(self, cli: str, value: str | None) -> str | None:
        """The model string to pass to the CLI, or None to use the CLI's own default."""
        if value is None or not str(value).strip():
            return None
        key = norm(str(value))
        if key == DEFAULT_MODEL:
            return None
        return self.model_aliases.get(cli, {}).get(key, str(value).strip())

    def resolve_actions(self, entries: list[str]) -> Actions:
        out = Actions()
        for entry in entries:
            text = entry.strip()
            if text.startswith("mcp:"):
                parts = text.split(":")
                if len(parts) == 3 and parts[1].strip() and parts[2].strip():
                    out.mcp.setdefault(conn_key(parts[1]), set()).add(parts[2].strip())
                else:
                    out.unknown.append(entry)
            elif text.startswith("shell:"):
                words = tuple(text[len("shell:") :].split())
                if words:
                    out.add_shell(words)
                else:
                    out.unknown.append(entry)
            elif (group := self.action_groups.get(norm(text))) is not None:
                for conn, tools in group.mcp.items():
                    out.mcp.setdefault(conn, set()).update(tools)
                for words in group.shell:
                    out.add_shell(words)
            else:
                out.unknown.append(entry)
        return out

    def permissions_for(self, agent: Agent) -> tuple[Actions, Actions]:
        """(ask, allow) for an agent. 'Always allow' wins over 'ask before'."""
        allow = self.resolve_actions(agent.always_allow)
        ask = self.resolve_actions(agent.ask_before)
        for conn, tools in allow.mcp.items():
            if conn in ask.mcp:
                ask.mcp[conn] -= tools
                if not ask.mcp[conn]:
                    del ask.mcp[conn]
        ask.shell = [words for words in ask.shell if words not in allow.shell]
        return ask, allow


def load_catalog(vault: Vault, settings: Settings, issues: list[Issue]) -> Catalog:
    catalog = Catalog()
    models = _meta(vault.core_manual / "models.md", issues)
    for cli, table in (models.get("aliases") or {}).items():
        if isinstance(table, dict):
            catalog.model_aliases[str(cli)] = {norm(str(k)): str(v) for k, v in table.items()}
    permissions_page = vault.core_manual / "permissions.md"
    groups = dict(_meta(permissions_page, issues).get("action_groups") or {})
    groups.update(settings.action_groups)
    for name, spec in groups.items():
        group = _group(spec)
        if group is None:
            where = settings.path if name in settings.action_groups else permissions_page
            issues.append(Issue("error", "permissions.bad-group", f"The action group '{name}' isn't written correctly", where))
            continue
        catalog.action_groups[norm(str(name))] = group
    return catalog


def _meta(path: Path, issues: list[Issue]) -> dict:
    try:
        return fm.read(path).meta
    except FileNotFoundError:
        issues.append(Issue("error", "core.file-missing", "A framework file is missing; update or reinstall Bron", path))
    except (fm.FrontmatterError, OSError, UnicodeDecodeError) as exc:
        issues.append(Issue("error", "core.file-unreadable", f"A framework file can't be read: {exc}", path))
    return {}


def _group(spec) -> ActionGroup | None:
    if not isinstance(spec, dict):
        return None
    mcp = spec.get("mcp") or {}
    shell = spec.get("shell") or []
    if not isinstance(mcp, dict) or not isinstance(shell, list):
        return None
    group = ActionGroup()
    for conn, tools in mcp.items():
        if not isinstance(tools, list):
            return None
        group.mcp[conn_key(str(conn))] = [str(t) for t in tools]
    for prefix in shell:
        if not isinstance(prefix, list) or not prefix:
            return None
        group.shell.append(tuple(str(w) for w in prefix))
    return group

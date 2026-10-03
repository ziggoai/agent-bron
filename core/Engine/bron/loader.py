"""Reads System/ and Core/ into one Config. Problems are collected as Issues, never raised."""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter as fm
from .catalog import Catalog, load_catalog
from .model import (
    CLIS,
    CONNECTION_TYPES,
    RUNS_IN,
    SKILL_NAME,
    Agent,
    Connection,
    Helper,
    Issue,
    Settings,
    Skill,
    slug,
)
from .vault import Vault


@dataclass
class Config:
    vault: Vault
    settings: Settings
    catalog: Catalog
    agents: dict[str, Agent] = field(default_factory=dict)
    helpers: dict[str, Helper] = field(default_factory=dict)
    skills: dict[str, Skill] = field(default_factory=dict)
    connections: dict[str, Connection] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def default_agent(self) -> Agent | None:
        return self.agents.get(slug(self.settings.default_agent))


def load(vault: Vault) -> Config:
    issues: list[Issue] = []
    settings = _settings(vault, issues)
    cfg = Config(vault, settings, load_catalog(vault, settings, issues), issues=issues)
    _agents(cfg)
    _helpers(cfg)
    _skills(cfg)
    _connections(cfg)
    return cfg


class _Fields:
    """Typed access to one file's frontmatter, recording friendly problems."""

    def __init__(self, meta: dict, path: Path, issues: list[Issue]):
        self.meta, self.path, self.issues = meta, path, issues

    def problem(self, code: str, message: str, level: str = "error") -> None:
        self.issues.append(Issue(level, code, message, self.path))

    def text(self, key: str, *, required: bool = False, default: str = "") -> str:
        value = self.meta.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                self.problem("field.missing", f"'{key}' is missing")
            return default
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            self.problem("field.type", f"'{key}' should be plain text")
            return default
        return str(value).strip()

    def names(self, key: str) -> list[str]:
        value = self.meta.get(key)
        if value is None:
            return []
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        if isinstance(value, list) and all(isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in value):
            return [str(v).strip() for v in value if str(v).strip()]
        self.problem("field.type", f"'{key}' should be a list, like [a, b]")
        return []

    def arguments(self, key: str) -> list[str]:
        value = self.meta.get(key)
        if value is None:
            return []
        if isinstance(value, str):
            try:
                return shlex.split(value)
            except ValueError:
                self.problem("field.type", f"'{key}' has an unclosed quote")
                return []
        if isinstance(value, list):
            return [str(v) for v in value]
        self.problem("field.type", f"'{key}' should be a list of command arguments")
        return []

    def number(self, key: str, default: int, *, minimum: int = 1) -> int:
        value = self.meta.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            self.problem("field.type", f"'{key}' should be a whole number of at least {minimum}")
            return default
        return value

    def flag(self, key: str, default: bool = False) -> bool:
        value = self.meta.get(key, default)
        if not isinstance(value, bool):
            self.problem("field.type", f"'{key}' should be true or false")
            return default
        return value

    def models(self) -> dict[str, str]:
        value = self.meta.get("models")
        if value is None:
            return {}
        if not isinstance(value, dict):
            self.problem("field.type", "'models' should name one model per CLI, like {claude: opus, codex: default}")
            return {}
        out: dict[str, str] = {}
        for cli, model in value.items():
            if cli not in CLIS:
                self.problem("field.value", f"'models' only takes 'claude' and 'codex', not '{cli}'")
                continue
            if model is None or isinstance(model, bool) or not isinstance(model, (str, int, float)) or not str(model).strip():
                self.problem("field.type", f"the {cli} model should be a model name or 'default'")
                continue
            out[cli] = str(model).strip()
        return out


def _open(path: Path, issues: list[Issue]) -> fm.Document | None:
    try:
        return fm.read(path)
    except fm.FrontmatterError as exc:
        issues.append(Issue("error", "file.unreadable", f"Bron can't read this file: {exc}", path))
    except (OSError, UnicodeDecodeError) as exc:
        issues.append(Issue("error", "file.unreadable", f"Bron can't open this file ({exc.__class__.__name__})", path))
    return None


def _subfolders(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith("."))


def _settings(vault: Vault, issues: list[Issue]) -> Settings:
    path = vault.settings_file
    settings = Settings(path=path)
    if not path.is_file():
        issues.append(Issue("error", "settings.missing", "System/Settings.md is missing", path))
        return settings
    doc = _open(path, issues)
    if doc is None:
        return settings
    f = _Fields(doc.meta, path, issues)
    settings.user_name = f.text("user_name")
    settings.company = f.text("company")
    settings.user_role = f.text("user_role")
    settings.tone = f.text("tone")
    settings.preferences = f.text("preferences")
    settings.default_cli = f.text("default_cli", default="claude").lower()
    if settings.default_cli not in CLIS:
        f.problem("field.value", "'default_cli' should be 'claude' or 'codex'")
        settings.default_cli = "claude"
    settings.default_agent = f.text("default_agent", default="Bron")
    runner = doc.meta.get("runner") or {}
    if not isinstance(runner, dict):
        f.problem("field.type", "'runner' should hold max_parallel and max_minutes")
        runner = {}
    rf = _Fields(runner, path, issues)
    settings.max_parallel = rf.number("max_parallel", 3)
    settings.max_minutes = rf.number("max_minutes", 30)
    check = doc.meta.get("update_check", True)
    if isinstance(check, bool):
        settings.update_check = check
    else:
        f.problem("field.type", "'update_check' should be true or false", level="warning")
    groups = doc.meta.get("action_groups") or {}
    if isinstance(groups, dict):
        settings.action_groups = groups
    else:
        f.problem("field.type", "'action_groups' should be a list of named groups")
    return settings


def _agents(cfg: Config) -> None:
    folder = cfg.vault.agents_dir
    if not folder.is_dir():
        cfg.issues.append(Issue("error", "agents.missing", "System/Agents/ is missing", folder))
        return
    for sub in _subfolders(folder):
        path = sub / "Agent.md"
        if not path.is_file():
            cfg.issues.append(Issue("error", "agent.file-missing", f"The agent folder '{sub.name}' has no Agent.md", sub))
            continue
        doc = _open(path, cfg.issues)
        if doc is None:
            continue
        f = _Fields(doc.meta, path, cfg.issues)
        name = f.text("name", required=True)
        if not name:
            continue
        if name != sub.name:
            f.problem("agent.name-mismatch", f"The name '{name}' must match the folder name '{sub.name}'")
        runs_in = f.text("runs_in", default="any").lower()
        if runs_in not in RUNS_IN:
            f.problem("field.value", "'runs_in' should be any, claude or codex")
            runs_in = "any"
        agent = Agent(
            name=name,
            role=f.text("role", required=True),
            reports_to=f.text("reports_to", required=True),
            runs_in=runs_in,
            path=path,
            models=f.models(),
            helpers=f.names("helpers"),
            connections=f.names("connections"),
            can_assign_to=f.names("can_assign_to"),
            ask_before=f.names("ask_before"),
            always_allow=f.names("always_allow"),
            instructions=doc.body.strip(),
        )
        if not agent.key:
            f.problem("agent.bad-name", f"The name '{name}' needs at least one letter or number")
            continue
        if agent.key in cfg.agents:
            f.problem("agent.duplicate", f"Two agents share the name '{name}' (both become '{agent.key}')")
            continue
        cfg.agents[agent.key] = agent


def _helpers(cfg: Config) -> None:
    for source, folder in (("core", cfg.vault.core_helpers), ("user", cfg.vault.helpers_dir)):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            doc = _open(path, cfg.issues)
            if doc is None:
                continue
            f = _Fields(doc.meta, path, cfg.issues)
            name = f.text("name", required=True)
            description = f.text("description", required=True)
            if not name or not description or not slug(name):
                continue
            helper = Helper(
                name=name,
                description=description,
                path=path,
                source=source,
                models=f.models(),
                connections=f.names("connections"),
                read_only=f.flag("read_only"),
                instructions=doc.body.strip(),
            )
            cfg.helpers[helper.key] = helper  # a user file replaces the core one of the same name


def _skills(cfg: Config) -> None:
    sources: list[tuple[str, Path, str]] = [("core", cfg.vault.core_skills, ""), ("user", cfg.vault.skills_dir, "")]
    for key, agent in sorted(cfg.agents.items()):
        sources.append((f"agent:{key}", agent.path.parent / "Skills", key))
    for source, folder, owner_key in sources:
        if not folder.is_dir():
            continue
        for sub in _subfolders(folder):
            path = sub / "SKILL.md"
            if not path.is_file():
                cfg.issues.append(Issue("warning", "skill.file-missing", f"The skill folder '{sub.name}' has no SKILL.md, so it is skipped", sub))
                continue
            doc = _open(path, cfg.issues)
            if doc is None:
                continue
            f = _Fields(doc.meta, path, cfg.issues)
            name = f.text("name", required=True)
            description = f.text("description", required=True)
            if not name or not description:
                continue
            if not SKILL_NAME.match(name) or len(name) > 64:
                f.problem("skill.bad-name", f"The skill name '{name}' may only use lower-case letters, numbers and hyphens (64 at most)")
                continue
            if name != sub.name:
                f.problem("skill.name-mismatch", f"The skill name '{name}' should match its folder name '{sub.name}'", level="warning")
            if owner_key:
                owner = cfg.agents[owner_key].name
                skill = Skill(f"{owner_key}-{name}", f"(For {owner} only) {description}", sub, source, rewrite=True)
            else:
                skill = Skill(name, description, sub, source)
            cfg.skills[skill.name] = skill


def _connections(cfg: Config) -> None:
    folder = cfg.vault.connections_dir
    if not folder.is_dir():
        return
    for path in sorted(folder.glob("*.md")):
        doc = _open(path, cfg.issues)
        if doc is None:
            continue
        f = _Fields(doc.meta, path, cfg.issues)
        name = f.text("name", required=True)
        kind = f.text("type", required=True).lower()
        if not name or not kind:
            continue
        if kind not in CONNECTION_TYPES:
            f.problem("field.value", "'type' should be mcp-stdio, mcp-http or native")
            continue
        env = doc.meta.get("env") or {}
        if not isinstance(env, dict) or not all(isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in env.values()):
            f.problem("field.type", "'env' should be 'NAME: value' lines")
            env = {}
        conn = Connection(
            name=name,
            type=kind,
            path=path,
            command=f.text("command"),
            args=f.arguments("args"),
            env={str(k): str(v) for k, v in env.items()},
            url=f.text("url"),
            description=f.text("description"),
            claude=f.text("claude"),
            codex=f.text("codex"),
            status=f.text("status"),
        )
        if kind == "native" and not (conn.claude or conn.codex):
            f.problem("field.missing", "A native connection needs 'claude' or 'codex' (the name each CLI uses for it)")
            continue
        if kind == "mcp-stdio" and not conn.command:
            f.problem("field.missing", "'command' is missing (needed for mcp-stdio)")
            continue
        if kind == "mcp-http" and not conn.url:
            f.problem("field.missing", "'url' is missing (needed for mcp-http)")
            continue
        if not conn.key:
            f.problem("connection.bad-name", f"The name '{name}' needs at least one letter or number")
            continue
        if conn.key in cfg.connections:
            f.problem("connection.duplicate", f"Another connection already uses the name '{name}'")
            continue
        cfg.connections[conn.key] = conn

"""What a Bron vault defines: agents, helpers, skills, connections and settings."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

CLIS = ("claude", "codex")
CLI_NAMES = {"claude": "Claude Code", "codex": "Codex"}
RUNS_IN = ("any", "claude", "codex")
CONNECTION_TYPES = ("mcp-stdio", "mcp-http", "native")
ALL = "all"  # in an agent's or helper's connections: every registered connection
DEFAULT_MODEL = "default"  # use whatever model the CLI itself is set to
SKILL_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def slug(name: str) -> str:
    """Agent/helper key for file names and @tags: 'Chief Finance' -> 'chief-finance'."""
    return re.sub(r"[^a-z0-9]+", "-", _ascii(name).strip().lower()).strip("-")


def conn_key(name: str) -> str:
    """Connection key used as the MCP server name: 'Google Drive' -> 'google_drive'."""
    return re.sub(r"[^a-z0-9]+", "_", _ascii(name).strip().lower()).strip("_")


@dataclass(frozen=True)
class Issue:
    level: str  # "error" | "warning"
    code: str
    message: str
    path: Path | None = None

    def render(self, root: Path | None = None) -> str:
        where = ""
        if self.path is not None:
            shown = self.path
            if root is not None:
                try:
                    shown = self.path.relative_to(root)
                except ValueError:
                    pass
            where = f" ({shown})"
        icon = "✗" if self.level == "error" else "!"
        return f"{icon} {self.message}{where}"


@dataclass
class Agent:
    name: str
    role: str
    reports_to: str
    runs_in: str
    path: Path
    models: dict[str, str] = field(default_factory=dict)
    helpers: list[str] = field(default_factory=list)
    connections: list[str] = field(default_factory=list)
    can_assign_to: list[str] = field(default_factory=list)
    ask_before: list[str] = field(default_factory=list)
    always_allow: list[str] = field(default_factory=list)
    instructions: str = ""

    @property
    def key(self) -> str:
        return slug(self.name)


@dataclass
class Helper:
    name: str
    description: str
    path: Path
    source: str  # "core" | "user"
    models: dict[str, str] = field(default_factory=dict)
    connections: list[str] = field(default_factory=list)
    read_only: bool = False
    instructions: str = ""

    @property
    def key(self) -> str:
        return slug(self.name)


@dataclass
class Skill:
    name: str  # published name
    description: str  # published description
    folder: Path
    source: str  # "core" | "user" | "agent:<key>"
    rewrite: bool = False  # True when name/description differ from the source SKILL.md


@dataclass
class Connection:
    name: str
    type: str
    path: Path
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    description: str = ""
    claude: str = ""  # native: the server id in Claude Code tool names (mcp__<claude>__<tool>)
    codex: str = ""  # native: the server name in the user's Codex config
    status: str = ""  # native: what the last scan saw (connected / needs sign-in / available / not found)

    @property
    def key(self) -> str:
        return conn_key(self.name)


@dataclass
class Settings:
    path: Path
    user_name: str = ""
    company: str = ""
    default_cli: str = "claude"
    default_agent: str = "Bron"
    max_parallel: int = 3
    max_minutes: int = 30
    action_groups: dict = field(default_factory=dict)

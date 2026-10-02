"""Finding the connectors already set up in Claude Code and Codex, and keeping System/Connections in step.

One file per connector (type: native) records the name each CLI uses for it. Re-scanning only
changes the claude, codex, url and status lines, so the user's own description and notes stay.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter as fm
from .loader import load
from .model import ALL, conn_key
from .vault import Vault

_LINE = re.compile(r"^(?P<name>.+?): (?P<target>.+) - (?P<status>.+)$")
_UNSAFE_ID = re.compile(r"[^A-Za-z0-9_-]")
_UNSAFE_FILE = re.compile(r'[\\/:*?"<>|]')
MANAGED = ("claude", "codex", "url", "status")
BODY = (
    "Found automatically by Bron on {date}.\n"
    "You can edit the description or add notes below. Bron only updates the claude, codex, url and status lines.\n"
)


@dataclass
class Found:
    name: str
    url: str = ""
    claude: str = ""
    codex: str = ""
    status: str = ""


@dataclass
class ScanReport:
    found_claude: int = 0
    found_codex: int = 0
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    needs_sign_in: list[str] = field(default_factory=list)
    opened_for: str = ""
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [f"Connectors found: {self.found_claude} in Claude Code, {self.found_codex} in Codex."]
        if self.created:
            lines.append("Added: " + ", ".join(self.created))
        if self.updated:
            lines.append("Updated: " + ", ".join(self.updated))
        if not self.created and not self.updated:
            lines.append("No changes to System/Connections.")
        if self.needs_sign_in:
            lines.append("Needs you to sign in again: " + ", ".join(self.needs_sign_in))
        if self.missing:
            lines.append("No longer found (kept, marked 'not found'): " + ", ".join(self.missing))
        if self.opened_for:
            lines.append(f"{self.opened_for} can now use all of them.")
        lines += self.notes
        return "\n".join(lines)


def _status(text: str) -> str:
    low = text.lower()
    if "auth" in low:
        return "needs sign-in"
    if "connected" in low and "fail" not in low:
        return "connected"
    return "error"


def parse_claude_list(text: str) -> list[Found]:
    out: list[Found] = []
    for raw_line in text.splitlines():
        match = _LINE.match(raw_line.strip())
        if not match:
            continue
        raw, target, status = match["name"].strip(), match["target"].strip(), match["status"].strip()
        if raw.startswith("claude.ai "):
            name = raw[len("claude.ai "):].strip()
            server = "claude_ai_" + _UNSAFE_ID.sub("_", name)
        elif raw.startswith("plugin:"):
            name = raw.split(":")[-1]
            server = _UNSAFE_ID.sub("_", raw)
        else:
            name = raw
            server = raw
        url = target.split()[0] if target.startswith("http") else ""
        out.append(Found(name=name, url=url, claude=server, status=_status(status)))
    return out


def parse_codex_list(text: str) -> list[Found]:
    start = text.find("[")
    if start < 0:
        return []
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return []
    out: list[Found] = []
    for server in data if isinstance(data, list) else []:
        if not isinstance(server, dict) or not server.get("enabled", True):
            continue
        name = str(server.get("name") or "").strip()
        if not name:
            continue
        transport = server.get("transport")
        url = str(transport.get("url") or "") if isinstance(transport, dict) else ""
        out.append(Found(name=name, url=url, codex=name))
    return out


def _same_url(a: str, b: str) -> bool:
    return bool(a and b) and a.strip().lower().rstrip("/") == b.strip().lower().rstrip("/")


def merge(claude: list[Found], codex: list[Found], skip: set[str]) -> list[Found]:
    merged = [f for f in claude if conn_key(f.name) not in skip]
    for c in codex:
        if conn_key(c.name) in skip:
            continue
        match = next((m for m in merged if not m.codex and _same_url(m.url, c.url)), None)
        if match is None:
            match = next((m for m in merged if not m.codex and conn_key(m.name) == conn_key(c.name)), None)
        if match is None:
            merged.append(c)
        else:
            match.codex = c.codex
            match.url = match.url or c.url
    return merged


def _new_path(vault: Vault, name: str) -> Path:
    base = _UNSAFE_FILE.sub("-", name).strip(" .") or conn_key(name) or "connector"
    path = vault.connections_dir / f"{base}.md"
    n = 2
    while path.exists():
        path = vault.connections_dir / f"{base} {n}.md"
        n += 1
    return path


def apply_found(vault: Vault, found: list[Found], *, scanned_claude: bool, scanned_codex: bool) -> ScanReport:
    cfg = load(vault)
    report = ScanReport()
    natives = {key: conn for key, conn in cfg.connections.items() if conn.type == "native"}
    seen: set[str] = set()
    for item in found:
        key = conn_key(item.name)
        if not key or (key in cfg.connections and cfg.connections[key].type != "native"):
            continue
        existing = next(
            (
                c
                for c in natives.values()
                if c is not None and ((item.claude and c.claude == item.claude) or (item.codex and c.codex == item.codex))
            ),
            None,
        )
        if existing is None and key in natives:
            existing = natives[key]
            if existing is None:  # a connector of the same name was already added in this scan
                continue
        values = {
            "claude": item.claude,
            "codex": item.codex,
            "url": item.url,
            "status": item.status or ("available" if item.codex else ""),
        }
        if existing is not None:
            seen.add(existing.key)
            doc = fm.read(existing.path)
            changed = False
            for field_name, value in values.items():
                if value and doc.meta.get(field_name) != value:
                    doc.meta[field_name] = value
                    changed = True
            if changed:
                fm.write(existing.path, doc)
                report.updated.append(existing.name)
        else:
            meta = {"name": item.name, "type": "native", **{k: v for k, v in values.items() if v}}
            fm.write(_new_path(vault, item.name), fm.Document(meta, BODY.format(date=time.strftime("%Y-%m-%d"))))
            report.created.append(item.name)
            seen.add(key)
            natives[key] = None  # reserve the key so a later duplicate updates instead of re-creating
        if item.status == "needs sign-in":
            report.needs_sign_in.append(item.name)
    for key, conn in natives.items():
        if conn is None or key in seen or conn.status == "not found":
            continue
        could_check = (conn.claude and scanned_claude) or (conn.codex and scanned_codex)
        if could_check:
            doc = fm.read(conn.path)
            doc.meta["status"] = "not found"
            fm.write(conn.path, doc)
            report.missing.append(conn.name)
    agent = cfg.default_agent
    if agent is not None and not any(name.strip().lower() == ALL for name in agent.connections):
        doc = fm.read(agent.path)
        current = doc.meta.get("connections")
        others = [str(c) for c in current] if isinstance(current, list) else []
        doc.meta["connections"] = [ALL, *[c for c in others if c.strip().lower() != ALL]]
        fm.write(agent.path, doc)
        report.opened_for = agent.name
    return report


def _ask(cli: str, argv: list[str], vault: Vault, run, notes: list[str]) -> str | None:
    if shutil.which(cli) is None and run is subprocess.run:
        notes.append(f"{'Claude Code' if cli == 'claude' else 'Codex'} isn't installed, so its connectors weren't checked.")
        return None
    try:
        done = run(argv, cwd=vault.root, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        notes.append(f"Couldn't ask {cli} for its connectors ({exc.__class__.__name__}).")
        return None
    return done.stdout


def scan(vault: Vault, *, claude_text: str | None = None, codex_text: str | None = None, run=subprocess.run) -> ScanReport:
    notes: list[str] = []
    if claude_text is None:
        claude_text = _ask("claude", ["claude", "mcp", "list"], vault, run, notes)
    if codex_text is None:
        codex_text = _ask("codex", ["codex", "mcp", "list", "--json"], vault, run, notes)
    claude = parse_claude_list(claude_text) if claude_text is not None else []
    codex = parse_codex_list(codex_text) if codex_text is not None else []
    cfg = load(vault)
    skip = {key for key, conn in cfg.connections.items() if conn.type != "native"}
    report = apply_found(
        vault,
        merge(claude, codex, skip),
        scanned_claude=claude_text is not None,
        scanned_codex=codex_text is not None,
    )
    report.found_claude, report.found_codex = len(claude), len(codex)
    report.notes += notes
    return report

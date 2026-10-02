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
    origin: str = ""


@dataclass
class ScanReport:
    found_claude: int = 0
    found_codex: int = 0
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    needs_sign_in: list[str] = field(default_factory=list)
    not_set_up: int = 0  # found, but not usable yet (needs authentication, not configured, failing)
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
        if self.not_set_up:
            lines.append(f"Not set up yet (available to connect in claude.ai or the CLI): {self.not_set_up}")
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
    if "not configured" in low:
        return "not configured"
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
        origin = ""
        if raw.startswith("claude.ai "):
            name = raw[len("claude.ai "):].strip()
            server = "claude_ai_" + _UNSAFE_ID.sub("_", name)
            origin = "claude.ai"
        elif raw.startswith("plugin:"):
            parts = raw.split(":")
            origin = parts[1] if len(parts) > 1 else ""
            name = parts[-1]
            server = _UNSAFE_ID.sub("_", raw)
        else:
            name = raw
            server = raw
        url = target.split()[0] if target.startswith("http") else ""
        out.append(Found(name=name, url=url, claude=server, status=_status(status), origin=origin))
    return out


def parse_codex_list(text: str) -> list[Found]:
    lines = text.splitlines()
    for line_idx, line in enumerate(lines):
        start = line.find("[")
        if start < 0:
            continue
        # Try to decode from this line onwards, including all remaining lines
        remaining_text = "\n".join(lines[line_idx:])[start:]
        try:
            data, _ = json.JSONDecoder().raw_decode(remaining_text)
        except ValueError:
            continue
        out: list[Found] = []
        for server in data if isinstance(data, list) else []:
            if not isinstance(server, dict) or not server.get("enabled", True):
                continue
            name = str(server.get("name") or "").strip()
            if not name:
                continue
            transport = server.get("transport")
            url = str(transport.get("url") or "") if isinstance(transport, dict) else ""
            out.append(Found(name=name, url=url, codex=name, origin="codex"))
        return out
    return []


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


def _safe_filename(name: str) -> str:
    return _UNSAFE_FILE.sub("-", name).strip(" .") or conn_key(name) or "connector"


def apply_found(vault: Vault, found: list[Found], *, scanned_claude: bool, scanned_codex: bool) -> ScanReport:
    cfg = load(vault)
    report = ScanReport()
    natives = {key: conn for key, conn in cfg.connections.items() if conn.type == "native"}
    # Seed with ALL existing connection keys (both natives and vault connections)
    used_keys: set[str] = set(cfg.connections.keys())
    # Track which native keys were found in this scan (fix: restore seen_keys)
    seen_keys: set[str] = set()

    for item in found:
        # Try to match by id (claude or codex id)
        existing = None
        if item.claude:
            existing = next(
                (c for c in natives.values() if c is not None and c.claude == item.claude),
                None,
            )
        if existing is None and item.codex:
            existing = next(
                (c for c in natives.values() if c is not None and c.codex == item.codex),
                None,
            )

        # Fallback to name match only if the existing record has no id on the side(s) the found item has
        if existing is None:
            key = conn_key(item.name)
            if key and key in natives:
                candidate = natives[key]
                if candidate is not None:
                    has_conflict = False
                    if item.claude and candidate.claude and candidate.claude != item.claude:
                        has_conflict = True
                    if item.codex and candidate.codex and candidate.codex != item.codex:
                        has_conflict = True
                    if not has_conflict:
                        existing = candidate

        # Only connectors that work now get a file (connected in Claude Code, or enabled in Codex);
        # the rest are only counted. Registered connectors are always kept up to date.
        if existing is None and item.status != "connected" and not item.codex:
            report.not_set_up += 1
            continue

        # Determine the name and key to use
        use_name = item.name
        use_key = conn_key(use_name)

        if existing is None and use_key and use_key in used_keys:
            # Key is taken, try with origin suffix
            if item.origin:
                use_name = f"{item.name} ({item.origin})"
                use_key = conn_key(use_name)

            if use_key and use_key in used_keys:
                # Still taken, skip with note
                report.notes.append(f"Couldn't add {use_name}: another connector already uses that name.")
                continue

        values = {
            "claude": item.claude,
            "codex": item.codex,
            "url": item.url,
            "status": item.status or ("available" if item.codex else ""),
        }

        if existing is not None:
            # Update existing
            doc = fm.read(existing.path)
            changed = False
            for field_name, value in values.items():
                if value and doc.meta.get(field_name) != value:
                    doc.meta[field_name] = value
                    changed = True
            if changed:
                fm.write(existing.path, doc)
                report.updated.append(existing.name)
            seen_keys.add(existing.key)
            if item.status == "needs sign-in":
                report.needs_sign_in.append(existing.name)
        else:
            # Create new file
            if not use_key:
                report.notes.append(f"Couldn't add {item.name}: the name doesn't contain any letters or numbers.")
                continue

            safe_name = _safe_filename(use_name)
            path = vault.connections_dir / f"{safe_name}.md"

            if path.exists():
                # File already exists (may be hand-broken)
                report.notes.append(f"{path.name} exists but couldn't be read as a connection; fix it and scan again.")
                continue

            meta = {"name": use_name, "type": "native", **{k: v for k, v in values.items() if v}}
            fm.write(path, fm.Document(meta, BODY.format(date=time.strftime("%Y-%m-%d"))))
            report.created.append(use_name)
            used_keys.add(use_key)
            seen_keys.add(use_key)

    # Mark missing connectors (skip seen_keys to avoid marking found connectors as missing)
    for key, conn in natives.items():
        if conn is None or conn.status == "not found" or key in seen_keys:
            continue

        checks = [(conn.claude, scanned_claude), (conn.codex, scanned_codex)]
        could_check = all(scanned for cid, scanned in checks if cid) and any(cid for cid, _ in checks)

        if could_check:
            doc = fm.read(conn.path)
            doc.meta["status"] = "not found"
            fm.write(conn.path, doc)
            report.missing.append(conn.name)

    # Update default agent
    agent = cfg.default_agent
    if agent is not None:
        current = agent.connections
        is_empty = not current or (isinstance(current, list) and all(not str(c).strip() for c in current))

        if is_empty and (scanned_claude or scanned_codex):
            doc = fm.read(agent.path)
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

    if done.returncode != 0:
        notes.append(f"{'Claude Code' if cli == 'claude' else 'Codex'} couldn't list its connectors (exit {done.returncode}).")
        return None

    return done.stdout


def _claude_readable(text: str) -> bool:
    """A valid Claude output, even if empty."""
    return "No MCP servers" in text or _LINE.search(text) is not None


def _codex_readable(text: str) -> bool:
    """A valid Codex JSON output, even if empty array."""
    if not text:
        return False
    start = text.find("[")
    if start < 0:
        return False
    try:
        json.JSONDecoder().raw_decode(text[start:])
        return True
    except ValueError:
        return False


def scan(vault: Vault, *, claude_text: str | None = None, codex_text: str | None = None, run=subprocess.run) -> ScanReport:
    notes: list[str] = []
    if claude_text is None:
        claude_text = _ask("claude", ["claude", "mcp", "list"], vault, run, notes)
    if codex_text is None:
        codex_text = _ask("codex", ["codex", "mcp", "list", "--json"], vault, run, notes)

    # Determine what was actually scanned: valid output that can be read counts as scanned
    scanned_claude = claude_text is not None and _claude_readable(claude_text)
    scanned_codex = codex_text is not None and _codex_readable(codex_text)

    # Parse the text
    claude = parse_claude_list(claude_text) if claude_text is not None else []
    codex = parse_codex_list(codex_text) if codex_text is not None else []

    cfg = load(vault)
    skip = {key for key, conn in cfg.connections.items() if conn.type != "native"}
    report = apply_found(
        vault,
        merge(claude, codex, skip),
        scanned_claude=scanned_claude,
        scanned_codex=scanned_codex,
    )
    report.found_claude, report.found_codex = len(claude), len(codex)
    report.notes += notes
    return report

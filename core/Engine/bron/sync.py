"""Sync: turn System/ into each CLI's own setup, safely and only when something changed."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import bron
from . import gen_claude, gen_codex
from .agents_md import render_agents_md
from .check import has_errors, run_checks
from .loader import Config, load
from .model import Issue
from .vault import MARKER, Vault
from .writer import GeneratedWriter, WriteReport

AGENTS_MD_MAX = 32 * 1024
AGENTS_MD_TARGET = 8 * 1024


def fingerprint(vault: Vault) -> str:
    """Cheap signature of every source file sync reads (size + modification time), excluding memory."""
    digest = hashlib.sha256(f"{bron.__version__}\0{vault.root}".encode("utf-8"))
    paths = [vault.settings_file, vault.root / MARKER]
    for folder in (
        vault.agents_dir,
        vault.helpers_dir,
        vault.skills_dir,
        vault.connections_dir,
        vault.core_manual,
        vault.core_skills,
        vault.core_helpers,
        vault.core_templates,
    ):
        if folder.is_dir():
            paths += [p for p in folder.rglob("*") if p.is_file()]
    for path in sorted(paths):
        rel = path.relative_to(vault.root)
        if rel.parts[:2] == ("System", "Agents") and len(rel.parts) > 3 and rel.parts[3] == "Memory":
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        digest.update(f"{rel.as_posix()}\0{st.st_size}\0{st.st_mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()


def plan_files(cfg: Config) -> dict[str, bytes]:
    files = {"AGENTS.md": render_agents_md(cfg).encode("utf-8")}
    files.update(gen_claude.generate(cfg))
    files.update(gen_codex.generate(cfg))
    return files


def output_issues(files: dict[str, bytes]) -> list[Issue]:
    size = len(files["AGENTS.md"])
    if size > AGENTS_MD_MAX:
        return [Issue("error", "agents-md.too-large", f"AGENTS.md would be {size // 1024} KB, but Codex reads at most 32 KB. Shorten agent roles or move detail into the manual.")]
    if size > AGENTS_MD_TARGET:
        return [Issue("warning", "agents-md.large", f"AGENTS.md is {size // 1024} KB; keeping it under 8 KB keeps every session fast.")]
    return []


def drift_issues(vault: Vault) -> list[Issue]:
    drift = GeneratedWriter(vault).drift()
    if not drift:
        return []
    shown = ", ".join(drift[:5]) + (f" and {len(drift) - 5} more" if len(drift) > 5 else "")
    return [Issue("warning", "generated.drift", f"Generated files were changed or removed by hand: {shown}. The next sync restores them and keeps a backup of any edits.")]


@dataclass
class SyncResult:
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    report: WriteReport | None = None


def run_sync(vault: Vault, *, dry_run: bool = False) -> SyncResult:
    cfg = load(vault)
    issues = run_checks(cfg, include_environment=False)
    if has_errors(issues):
        return SyncResult(False, issues)
    try:
        files = plan_files(cfg)
    except (OSError, KeyError, ValueError) as exc:
        return SyncResult(False, issues + [Issue("error", "sync.failed", f"Bron couldn't build the CLI setup ({exc.__class__.__name__}: {exc})")])
    issues += output_issues(files)
    if has_errors(issues) or dry_run:
        return SyncResult(not has_errors(issues), issues)
    try:
        report = GeneratedWriter(vault).apply(files, fingerprint(vault))
    except (OSError, ValueError) as exc:
        return SyncResult(False, issues + [Issue("error", "sync.failed", f"Bron couldn't write the CLI setup: {exc}")])
    return SyncResult(True, issues, report)


def needs_sync(vault: Vault) -> bool:
    writer = GeneratedWriter(vault)
    return writer.manifest.get("fingerprint") != fingerprint(vault) or bool(writer.drift())

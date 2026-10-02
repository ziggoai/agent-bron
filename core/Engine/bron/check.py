"""The health check: everything Bron can validate without changing anything."""
from __future__ import annotations

import shutil

from .access import allowed_keys, codex_defined_servers, codex_server, codex_switchable, codex_trusts
from .loader import Config
from .model import ALL, CLI_NAMES, Issue, conn_key, slug

SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def run_checks(cfg: Config, *, include_environment: bool = True) -> list[Issue]:
    issues = list(cfg.issues)
    issues += _settings(cfg)
    issues += _agents(cfg)
    issues += _cycles(cfg)
    issues += _helpers(cfg)
    issues += _connections(cfg)
    issues += _locks(cfg)
    if include_environment:
        issues += _environment(cfg)
        issues += _routines(cfg)  # routine problems never stop a sync
    return issues


def _routines(cfg: Config) -> list[Issue]:
    from .routines import load_runbooks

    runbooks, out = load_runbooks(cfg.vault)
    for runbook in runbooks:
        if runbook.owner and slug(runbook.owner) not in cfg.agents:
            out.append(Issue(
                "warning",
                "routine.owner-unknown",
                f"The routine '{runbook.name}' is owned by '{runbook.owner}', which isn't an agent; the default agent looks after it",
                runbook.path,
            ))
    return out


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.level == "error" for issue in issues)


def _settings(cfg: Config) -> list[Issue]:
    if cfg.default_agent is None:
        return [Issue("error", "settings.default-agent-unknown", f"The default agent '{cfg.settings.default_agent}' doesn't exist in System/Agents/", cfg.settings.path)]
    return []


def _agents(cfg: Config) -> list[Issue]:
    out: list[Issue] = []
    for key, agent in cfg.agents.items():
        def bad(code: str, message: str, level: str = "error") -> None:
            out.append(Issue(level, code, message, agent.path))

        boss = slug(agent.reports_to)
        if boss and boss != "you" and boss not in cfg.agents:
            bad("agent.reports-to-unknown", f"{agent.name} reports to '{agent.reports_to}', which isn't an agent (use 'you' or an agent's name)")
        if key in cfg.helpers:
            bad("agent.name-taken", f"{agent.name} has the same name as a helper; rename one of them")
        for helper in agent.helpers:
            if slug(helper) not in cfg.helpers:
                bad("agent.helper-unknown", f"{agent.name} uses the helper '{helper}', which doesn't exist")
        for conn in agent.connections:
            if conn.strip().lower() != ALL and conn_key(conn) not in cfg.connections:
                bad("agent.connection-unknown", f"{agent.name} uses the connection '{conn}', which isn't set up in System/Connections/")
        for other in agent.can_assign_to:
            other_key = slug(other)
            if other_key == key:
                bad("agent.assign-self", f"{agent.name} can't assign tickets to itself")
            elif other_key not in cfg.agents:
                bad("agent.assign-unknown", f"{agent.name} can assign work to '{other}', which isn't an agent")
        for field_name in ("ask_before", "always_allow"):
            for entry in cfg.catalog.resolve_actions(getattr(agent, field_name)).unknown:
                bad("agent.action-unknown", f"{agent.name}'s {field_name} lists '{entry}', which Bron doesn't recognise (see System/Core/Manual/permissions.md)", "warning")
        if agent.runs_in in CLI_NAMES and agent.runs_in not in agent.models:
            bad(
                "agent.model-missing",
                f"{agent.name} only runs in {CLI_NAMES[agent.runs_in]} but has no {agent.runs_in} model set; it will use {CLI_NAMES[agent.runs_in]}'s default model",
                "warning",
            )
    return out


def _cycles(cfg: Config) -> list[Issue]:
    out: list[Issue] = []
    reported: set[frozenset[str]] = set()
    for start in sorted(cfg.agents):
        seen: list[str] = []
        key = start
        while key in cfg.agents and key not in seen:
            seen.append(key)
            key = slug(cfg.agents[key].reports_to)
        if key in seen:
            loop = seen[seen.index(key):]
            if frozenset(loop) not in reported:
                reported.add(frozenset(loop))
                names = " → ".join(cfg.agents[k].name for k in loop) + f" → {cfg.agents[key].name}"
                out.append(Issue("error", "agent.reports-cycle", f"Reporting goes in a circle: {names}", cfg.agents[key].path))
    return out


def _helpers(cfg: Config) -> list[Issue]:
    out: list[Issue] = []
    for helper in cfg.helpers.values():
        for conn in helper.connections:
            if conn.strip().lower() != ALL and conn_key(conn) not in cfg.connections:
                out.append(Issue("error", "helper.connection-unknown", f"The helper '{helper.name}' uses the connection '{conn}', which isn't set up", helper.path))
    return out


def _connections(cfg: Config) -> list[Issue]:
    out: list[Issue] = []
    for conn in cfg.connections.values():
        if conn.type == "mcp-http" and conn.env:
            out.append(Issue("warning", "connection.env-ignored", f"The connection '{conn.name}' is an http connection, so 'env' isn't used; sign in through the CLI instead.", conn.path))
        for name, value in conn.env.items():
            if "${" in value and value != f"${{{name}}}":
                out.append(Issue(
                    "error",
                    "connection.env-reference",
                    f"The connection '{conn.name}' sets {name} to '{value}'. Bron can only pass a variable through under its own name: write it as ${{{name}}} and set {name} in your shell or Keychain.",
                    conn.path,
                ))
                continue
            if any(word in name.upper() for word in SECRET_WORDS) and not value.startswith("${"):
                out.append(Issue(
                    "error",
                    "connection.secret-in-vault",
                    f"The connection '{conn.name}' stores {name} in the vault. Keep secrets out of the vault: write it as ${{{name}}} and set it in your shell or Keychain",
                    conn.path,
                ))
    return out


def _locks(cfg: Config) -> list[Issue]:
    from .locks import stale

    leftovers = stale(cfg.vault, cfg.settings.max_minutes)
    if not leftovers:
        return []
    ids = ", ".join(lock.ticket_id for lock in leftovers)
    return [Issue("warning", "locks.stale", f"Leftover ticket locks from runs that stopped: {ids}. The next session marks a ticket still in-progress as blocked, and the next run of each ticket clears its lock automatically.")]


def _environment(cfg: Config) -> list[Issue]:
    out: list[Issue] = []
    needed = {cfg.settings.default_cli} | {a.runs_in for a in cfg.agents.values() if a.runs_in != "any"}
    for cli in sorted(needed):
        if shutil.which(cli) is None:
            out.append(Issue("warning", "cli.missing", f"{CLI_NAMES[cli]} isn't installed (or isn't on PATH), but your setup uses it"))
    if shutil.which("codex") is not None and not codex_trusts(cfg.vault.root):
        out.append(Issue("warning", "codex.untrusted", "Codex doesn't trust this vault yet, so Codex sessions here ignore Bron's setup. Open Codex in this vault once and accept its trust prompt."))
    if shutil.which("codex") is not None:
        out += _codex_unswitchable(cfg)
    return out


def _codex_unswitchable(cfg: Config) -> list[Issue]:
    """Connectors Codex lists but won't let Bron switch off by flag (for example plugin servers)."""
    defined = codex_defined_servers(cfg.vault)
    out: list[Issue] = []
    for _, agent in sorted(cfg.agents.items()):
        if agent.runs_in not in ("codex", "any"):
            continue
        keep = allowed_keys(cfg, agent.connections)
        for key, conn in sorted(cfg.connections.items()):
            # Vault connections are either switchable (Codex loads the vault setup) or absent (it doesn't).
            if key in keep or conn.type != "native" or conn.status == "not found" or not codex_server(conn):
                continue
            if not codex_switchable(conn, defined):
                out.append(Issue(
                    "warning",
                    "connection.codex-unswitchable",
                    f"{agent.name} can't be kept away from {conn.name} in Codex (Codex doesn't let Bron switch it off); it is still kept away in Claude Code.",
                    agent.path,
                ))
    return out

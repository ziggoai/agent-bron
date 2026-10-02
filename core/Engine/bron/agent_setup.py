"""Agent setup changes: create and change team members (rename, retire and bring back are below)."""
from __future__ import annotations

import re
from pathlib import Path

from . import frontmatter as fm
from .catalog import norm
from .fmedit import EditError, edit_meta, replace_body
from .loader import Config
from .model import ALL, CLI_NAMES, CLIS, RUNS_IN, Agent, conn_key, slug
from .setup import Change, SetupError

DEFAULT_HELPERS = ("reader", "researcher", "reviewer")
ALWAYS_ASK = ("delete-files", "git-push")
_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]\n\r\t]')
_CLAUDE_HINTS = ("claude", "opus", "sonnet", "haiku", "fable")
_CODEX_HINTS = ("gpt", "codex", "o1", "o3", "o4")
ASK_WORDS = {
    "delete-files": "deleting files",
    "git-push": "pushing to git",
    "send-email": "sending email",
    "share-file": "sharing files",
    "external-post": "posting outside the vault (for example on Slack)",
}


def rel(cfg: Config, path: Path) -> str:
    return path.relative_to(cfg.vault.root).as_posix()


def _edit(cfg: Config, path: Path, changes: dict) -> str:
    """edit_meta on a file's text; an unusual hand-edited file becomes a plain SetupError."""
    try:
        return edit_meta(path.read_text(encoding="utf-8"), changes)
    except EditError as exc:
        raise SetupError(f"Bron couldn't update {rel(cfg, path)}: {exc}") from exc


def check_name(cfg: Config, name: str) -> str:
    """A new agent name, tidied; raises SetupError when it can't be used."""
    name = " ".join(name.split())
    if not name or name.startswith(".") or _UNSAFE.search(name) or not slug(name):
        raise SetupError(f"'{name}' can't be used as a name: use letters, numbers and spaces.")
    key = slug(name)
    if key == "you":
        raise SetupError("'you' is reserved: it means you, the user.")
    if key in (ALL, "any"):
        raise SetupError(f"'{name}' is reserved: it has a special meaning in agent settings.")
    if key in cfg.agents:
        raise SetupError(f"There's already an agent called {cfg.agents[key].name}.")
    if key in cfg.helpers:
        raise SetupError(f"'{name}' is already the name of a helper.")
    return name


def find_agent(cfg: Config, name: str) -> Agent:
    agent = cfg.agents.get(slug(name))
    if agent is None:
        raise SetupError(f"There's no agent called '{name}'. Agents: {', '.join(a.name for a in cfg.agents.values())}")
    return agent


def model_cli(cfg: Config, model: str) -> str | None:
    """Which app a model belongs to, from Bron's model list or the model's name (None when it can't tell)."""
    key = norm(model)
    for cli in CLIS:
        if key in cfg.catalog.model_aliases.get(cli, {}):
            return cli
    if key.startswith(_CLAUDE_HINTS):
        return "claude"
    if key.startswith(_CODEX_HINTS):
        return "codex"
    return None


def parse_models(cfg: Config, values: list[str]) -> dict[str, str]:
    """'claude=opus-5.5', 'codex=default' or a bare model name -> {cli: model}."""
    out: dict[str, str] = {}
    for value in values:
        cli, sep, model = value.partition("=")
        if sep and cli.strip() in CLIS:
            out[cli.strip()] = model.strip()
            continue
        found = model_cli(cfg, value)
        if found is None:
            raise SetupError(f"Bron can't tell which app '{value}' runs in; say claude=<model> or codex=<model>.")
        out[found] = value.strip()
    for cli, model in out.items():
        if not model:
            raise SetupError(f"The {CLI_NAMES[cli]} model is empty.")
    return out


def resolve_connections(cfg: Config, names) -> list[str]:
    """Connection names as written in System/Connections/ (matched case-insensitively), or 'all'."""
    out: list[str] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        if name.lower() == ALL:
            if ALL not in out:
                out.append(ALL)
            continue
        conn = cfg.connections.get(conn_key(name))
        if conn is None:
            known = ", ".join(sorted(c.name for c in cfg.connections.values())) or "none yet"
            raise SetupError(f"There's no connection called '{name}'. Connections: {known}")
        if conn.name not in out:
            out.append(conn.name)
    return out


def safety_defaults(cfg: Config, connections: list[str]) -> list[str]:
    """Always ask before deleting and pushing; plus every send/share/post group that touches these connections."""
    keys = set(cfg.connections) if ALL in connections else {conn_key(c) for c in connections}
    groups = [g for g in ALWAYS_ASK if g in cfg.catalog.action_groups]
    for name, group in sorted(cfg.catalog.action_groups.items()):
        if name not in groups and set(group.mcp) & keys:
            groups.append(name)
    return groups


def _merge(base, extra) -> list[str]:
    out = [str(x) for x in base]
    seen = {norm(x) for x in out}
    for item in extra:
        if norm(item) not in seen:
            out.append(item)
            seen.add(norm(item))
    return out


def describe_asks(entries) -> str:
    words = []
    for entry in entries:
        if norm(entry) in ASK_WORDS:
            words.append(ASK_WORDS[norm(entry)])
        elif entry.startswith("shell:"):
            words.append(f"running `{entry[len('shell:'):].strip()}`")
        elif entry.startswith("mcp:") and len(entry.split(":", 2)) == 3:
            _, conn, tool = entry.split(":", 2)
            words.append(f"{conn} {tool}")
        else:
            words.append(entry)
    return ", ".join(words) if words else "nothing"


def _describe_runs(runs_in: str, models: dict[str, str]) -> str:
    def model(cli: str) -> str:
        value = models.get(cli, "default")
        return "its default model" if norm(value) == "default" else value

    if runs_in in CLIS:
        return f"Runs in {CLI_NAMES[runs_in]} on {model(runs_in)}"
    return f"Runs in whichever app hands it work (Claude Code: {model('claude')}; Codex: {model('codex')})"


def _check_asks(cfg: Config, entries: list[str]) -> None:
    unknown = cfg.catalog.resolve_actions(entries).unknown
    if unknown:
        raise SetupError(f"Bron doesn't know these ask-first entries: {', '.join(unknown)}. See System/Core/Manual/permissions.md.")


def default_instructions(name: str, role: str, boss: str) -> str:
    boss_text = "the user" if boss == "you" else boss
    return (
        "# Who you are\n"
        f"You are {name}, {role} on the team. You report to {boss_text}.\n\n"
        "# How you work\n"
        "- Work comes to you through tickets and @-mentions; your final reply is the answer.\n"
        "- Start from what you already know: the briefing, shared memory in `System/Memory/`, and the knowledge base.\n"
        "- Save one-off work in `Projects/<Project>/` and repeating work in `Routines/<Routine>/`.\n"
        "- Say clearly what you did, what you found, and what still needs a decision.\n\n"
        "# Boundaries\n"
        "- Never change anything in `System/` without showing the user the change first and getting a yes.\n"
        "- Never edit `System/Core/` or the hidden `.claude/`, `.codex/` and `.agents/` folders.\n"
        "- Ask before anything on your ask-first list, and before anything that leaves the vault.\n"
    )


def _boss(cfg: Config, reports_to: str, *, default: str) -> tuple[str, str]:
    """(key, display name) of a boss; 'you' for the user."""
    key = slug(reports_to) if reports_to.strip() else default
    if key in ("", "you"):
        return "you", "you"
    if key not in cfg.agents:
        raise SetupError(f"There's no such agent as '{reports_to}' to report to.")
    return key, cfg.agents[key].name


def create_agent(cfg: Config, *, name: str, role: str, reports_to: str = "", models: dict | None = None, runs_in: str = "",
                 connections=(), ask_before=(), helpers=None, instructions: str = "", defaults: bool = True) -> Change:
    name = check_name(cfg, name)
    if (cfg.vault.agents_dir / name).exists():
        raise SetupError(f"The folder System/Agents/{name} already exists; move it away first.")
    role = " ".join(role.split())
    if not role:
        raise SetupError("Give the agent a role, like 'Chief Operating Officer'.")
    boss_key, boss = _boss(cfg, reports_to, default=cfg.default_agent.key if cfg.default_agent else "you")
    models = dict(models or {})
    if runs_in and runs_in not in RUNS_IN:
        raise SetupError("The app should be any, claude or codex.")
    if runs_in in CLIS:
        for cli, model in models.items():
            if cli != runs_in and norm(model) != "default":
                raise SetupError(f"That model is for {CLI_NAMES[cli]}, but you chose {CLI_NAMES[runs_in]}; pick one.")
    if not runs_in:
        chosen = [cli for cli, model in models.items() if norm(model) != "default"]
        runs_in = chosen[0] if len(chosen) == 1 else "any"
    for cli in (CLIS if runs_in == "any" else (runs_in,)):
        models.setdefault(cli, "default")
    conns = resolve_connections(cfg, connections)
    asks = _merge(safety_defaults(cfg, conns) if defaults else [], [a.strip() for a in ask_before if a.strip()])
    _check_asks(cfg, asks)
    helper_names = list(DEFAULT_HELPERS) if helpers is None else [h.strip() for h in helpers if h.strip()]
    missing = [h for h in helper_names if slug(h) not in cfg.helpers]
    if helpers is not None and missing:
        raise SetupError(f"There's no helper called {', '.join(missing)}. Helpers: {', '.join(sorted(cfg.helpers))}")
    helper_names = [h for h in helper_names if slug(h) in cfg.helpers]
    meta = {
        "name": name,
        "role": role,
        "reports_to": boss,
        "models": {cli: models[cli] for cli in CLIS if cli in models},
        "runs_in": runs_in,
        "helpers": helper_names,
        "connections": conns,
        "can_assign_to": [],
        "ask_before": asks,
        "always_allow": [],
    }
    body = instructions.strip() or default_instructions(name, role, boss)
    change = Change(done=f"Created {name}. Say hi with @{slug(name)}.")
    change.writes[f"System/Agents/{name}/Agent.md"] = fm.dump(fm.Document(meta, "\n" + body.rstrip() + "\n"))
    change.folders.append(f"System/Agents/{name}/Memory")
    if boss_key != "you":
        chief = cfg.agents[boss_key]
        change.writes[rel(cfg, chief.path)] = _edit(cfg, chief.path, {"can_assign_to": _merge(chief.can_assign_to, [name])})
    change.summary = [
        f"New agent: {name} ({role}).",
        f"{_describe_runs(runs_in, models)}.",
        f"Reports to {boss}." + (f" {boss} can hand it work." if boss_key != "you" else ""),
        "Can use: " + (", ".join(conns) if conns else "no connectors") + ".",
        "Asks you before: " + describe_asks(asks) + ".",
    ]
    return change


def set_agent(cfg: Config, name: str, *, role=None, reports_to=None, models=None, runs_in=None, add_connections=(),
              remove_connections=(), add_ask=(), remove_ask=(), instructions=None, defaults: bool = True) -> Change:
    agent = find_agent(cfg, name)
    changes: dict = {}
    lines: list[str] = []
    if role is not None and " ".join(role.split()) and " ".join(role.split()) != agent.role:
        changes["role"] = " ".join(role.split())
        lines.append(f"Role: {changes['role']}")
    new_models = dict(agent.models)
    models = {cli: model for cli, model in (models or {}).items() if agent.models.get(cli) != model}
    if models:
        new_models.update(models)
        changes["models"] = {cli: new_models[cli] for cli in CLIS if cli in new_models}
        lines.append("Model: " + ", ".join(f"{CLI_NAMES[cli]} {model}" for cli, model in models.items()))
        if runs_in is None and len(models) == 1:
            cli = next(iter(models))
            if agent.runs_in in CLIS and agent.runs_in != cli:
                runs_in = cli
    if runs_in is not None and runs_in != agent.runs_in:
        if runs_in not in RUNS_IN:
            raise SetupError("The app should be any, claude or codex.")
        changes["runs_in"] = runs_in
        lines.append("Runs in " + (CLI_NAMES[runs_in] if runs_in in CLIS else "whichever app hands it work"))
        if runs_in in CLIS and runs_in not in new_models:
            new_models[runs_in] = "default"
            changes["models"] = {cli: new_models[cli] for cli in CLIS if cli in new_models}
    added = resolve_connections(cfg, add_connections)
    removed = resolve_connections(cfg, remove_connections)
    conns = _merge(agent.connections, added)
    gone = {conn_key(r) for r in removed if r != ALL}
    conns = [c for c in conns if conn_key(c) not in gone and not (c.lower() == ALL and ALL in removed)]
    if conns != list(agent.connections):
        changes["connections"] = conns
        new_ones = [c for c in added if c not in agent.connections]
        if new_ones:
            lines.append("Can now use: " + ", ".join(new_ones))
        had = {conn_key(c) for c in agent.connections if c.lower() != ALL}
        really = [r for r in removed if (r == ALL and ALL in [c.lower() for c in agent.connections]) or (r != ALL and conn_key(r) in had)]
        if really:
            lines.append("No longer uses: " + ", ".join(really))
    extra = safety_defaults(cfg, added) if (defaults and added) else []
    asks = _merge(agent.ask_before, extra + [a.strip() for a in add_ask if a.strip()])
    dropped = {norm(a) for a in remove_ask}
    asks = [a for a in asks if norm(a) not in dropped]
    if asks != list(agent.ask_before):
        _check_asks(cfg, asks)
        changes["ask_before"] = asks
        lines.append("Asks you before: " + describe_asks(asks))
    boss_change = None
    if reports_to is not None:
        new_key, new_boss = _boss(cfg, reports_to, default="you")
        if new_key == agent.key:
            raise SetupError(f"{agent.name} can't report to itself.")
        if new_key != (slug(agent.reports_to) or "you"):
            changes["reports_to"] = new_boss
            lines.append(f"Reports to {new_boss}")
            boss_change = (slug(agent.reports_to), new_key)
    text = agent.path.read_text(encoding="utf-8")
    if changes:
        text = _edit(cfg, agent.path, changes)
    if instructions is not None and instructions.strip():
        try:
            text = replace_body(text, instructions)
        except EditError as exc:
            raise SetupError(f"Bron couldn't update {rel(cfg, agent.path)}: {exc}") from exc
        old_lines = len(fm.read(agent.path).body.strip().splitlines())
        lines.append(f"Replaces all of its instructions (now {len(instructions.strip().splitlines())} lines, was {old_lines} lines)")
    if not lines:
        raise SetupError(f"Nothing to change for {agent.name}.")
    change = Change(summary=[f"Change {agent.name}:"] + [f"- {line}." for line in lines], done=f"Updated {agent.name}.")
    change.writes[rel(cfg, agent.path)] = text
    if boss_change:
        old_key, new_key = boss_change
        if old_key in cfg.agents and old_key != agent.key:
            old = cfg.agents[old_key]
            change.writes[rel(cfg, old.path)] = _edit(cfg, old.path, {"can_assign_to": [x for x in old.can_assign_to if slug(x) != agent.key]})
        if new_key in cfg.agents:
            new = cfg.agents[new_key]
            change.writes[rel(cfg, new.path)] = _edit(cfg, new.path, {"can_assign_to": _merge(new.can_assign_to, [agent.name])})
    return change


# ---- rename, retire, bring back ----

def _open_tickets(cfg: Config):
    from .tickets import OPEN, list_tickets

    tickets, _ = list_tickets(cfg.vault)
    return [t for t in tickets if t.status in OPEN]


def rename_agent(cfg: Config, name: str, new_name: str) -> Change:
    from .routines import load_runbooks
    from .tickets import add_message, render

    agent = find_agent(cfg, name)
    if slug(new_name) == agent.key:
        raise SetupError(f"That's the same name as {agent.name}.")
    new_name = check_name(cfg, new_name)
    busy = [t.id for t in _open_tickets(cfg) if t.assignee == agent.key and t.status == "in-progress"]
    if busy:
        raise SetupError(f"{agent.name} is working on {', '.join(busy)} right now; rename it once that's finished.")
    old_folder, new_folder = f"System/Agents/{agent.path.parent.name}", f"System/Agents/{new_name}"
    if (cfg.vault.root / new_folder).exists():
        raise SetupError(f"The folder {new_folder} already exists.")
    change = Change(done=f"Renamed {agent.name} to {new_name}. Tag it with @{slug(new_name)}.")
    change.moves.append((old_folder, new_folder))
    change.writes[f"{new_folder}/Agent.md"] = _edit(cfg, agent.path, {"name": new_name})
    also: list[str] = []
    for other in cfg.agents.values():
        if other.key == agent.key:
            continue
        edits: dict = {}
        if slug(other.reports_to) == agent.key:
            edits["reports_to"] = new_name
        if any(slug(x) == agent.key for x in other.can_assign_to):
            edits["can_assign_to"] = [new_name if slug(x) == agent.key else x for x in other.can_assign_to]
        if edits:
            change.writes[rel(cfg, other.path)] = _edit(cfg, other.path, edits)
            also.append(other.name)
    if cfg.default_agent is not None and cfg.default_agent.key == agent.key:
        change.writes[rel(cfg, cfg.settings.path)] = _edit(cfg, cfg.settings.path, {"default_agent": new_name})
        also.append("your settings (it's your main agent)")
    runbooks, _ = load_runbooks(cfg.vault)
    owned = [rb for rb in runbooks if rb.owner and slug(rb.owner) == agent.key]
    for rb in owned:
        change.writes[rel(cfg, rb.path)] = _edit(cfg, rb.path, {"owner": new_name})
    moved = 0
    for ticket in _open_tickets(cfg):
        touched = False
        if ticket.assignee == agent.key:
            ticket.assignee, touched = slug(new_name), True
        if slug(ticket.requested_by) == agent.key:
            ticket.requested_by, touched = slug(new_name), True
        if touched:
            add_message(ticket, "bron", f"{agent.name} was renamed {new_name}")
            change.writes[rel(cfg, ticket.path)] = render(ticket)
            moved += 1
    change.summary = [f"Rename {agent.name} to {new_name}."]
    if also:
        change.summary.append("Also updates: " + ", ".join(also) + ".")
    skills = sorted(f.parent.name for f in (agent.path.parent / "Skills").glob("*/SKILL.md"))
    if skills:
        change.summary.append("Its own skills are renamed to " + ", ".join(f"{slug(new_name)}-{x}" for x in skills) + ".")
    if owned:
        change.summary.append(f"Routines it owns: {', '.join(rb.name for rb in owned)}.")
    if moved:
        change.summary.append(f"Open tickets that follow the new name: {moved}. Closed tickets keep the old name.")
    return change


def retire_agent(cfg: Config, name: str, hand_to: str = "") -> Change:
    from .routines import load_runbooks
    from .tickets import add_message, render, set_status

    agent = find_agent(cfg, name)
    if cfg.default_agent is not None and agent.key == cfg.default_agent.key:
        raise SetupError(f"{agent.name} is your main agent and can't be retired; you can rename it instead.")
    boss_key = slug(agent.reports_to)
    boss = cfg.agents.get(boss_key)
    target = find_agent(cfg, hand_to) if hand_to.strip() else (boss or cfg.default_agent)
    if target is None or target.key == agent.key:
        raise SetupError(f"Say who should take over {agent.name}'s work.")
    mine = [t for t in _open_tickets(cfg) if t.assignee == agent.key]
    busy = [t.id for t in mine if t.status == "in-progress"]
    if busy:
        raise SetupError(f"{agent.name} is working on {', '.join(busy)} right now; retire it once that's finished.")
    archive = f"System/Archive/Agents/{agent.path.parent.name}"
    if (cfg.vault.root / archive).exists():
        raise SetupError(f"There's already a retired agent at {archive}; bring it back or move it first.")
    new_boss = boss.name if boss is not None else "you"
    owner = boss.name if boss is not None else (cfg.default_agent.name if cfg.default_agent else "")
    change = Change(done=f"Retired {agent.name}. Its files are in {archive}; say 'bring back {agent.name}' to restore it.")
    handed: list[str] = []
    chats = 0
    followed = 0
    for ticket in _open_tickets(cfg):
        mine_now = ticket.assignee == agent.key
        asked = slug(ticket.requested_by) == agent.key
        if not (mine_now or asked):
            continue
        if mine_now and ticket.kind == "chat":
            set_status(ticket, "done", "bron", f"chat ended ({agent.name} retired)")
            chats += 1
        else:
            if mine_now:
                ticket.assignee = target.key
                add_message(ticket, "bron", f"handed over from {agent.name} to {target.name} ({agent.name} retired)")
                handed.append(ticket.id)
            if asked:
                ticket.requested_by = target.key
                add_message(ticket, "bron", f"requested by {agent.name}, now followed up by {target.name} ({agent.name} retired)")
                followed += 1
        change.writes[rel(cfg, ticket.path)] = render(ticket)
    team_lists: list[str] = []
    reports: list[str] = []
    for other in cfg.agents.values():
        if other.key == agent.key:
            continue
        edits: dict = {}
        if any(slug(x) == agent.key for x in other.can_assign_to):
            edits["can_assign_to"] = [x for x in other.can_assign_to if slug(x) != agent.key]
            team_lists.append(other.name)
        if slug(other.reports_to) == agent.key:
            edits["reports_to"] = new_boss
            reports.append(other.name)
        if edits:
            change.writes[rel(cfg, other.path)] = _edit(cfg, other.path, edits)
    runbooks, _ = load_runbooks(cfg.vault)
    owned = [rb for rb in runbooks if rb.owner and slug(rb.owner) == agent.key]
    for rb in owned:
        change.writes[rel(cfg, rb.path)] = _edit(cfg, rb.path, {"owner": owner})
    change.moves.append((f"System/Agents/{agent.path.parent.name}", archive))
    change.summary = [f"Retire {agent.name}."]
    change.summary.append(f"Open work handed to {target.name}: {', '.join(handed)}." if handed else "It has no open work.")
    if team_lists:
        change.summary.append(f"Removed from the team list of {', '.join(team_lists)}.")
    if reports:
        change.summary.append(f"{', '.join(reports)} will report to {new_boss}.")
    if owned:
        change.summary.append(f"Routines it owned move to {owner}: {', '.join(rb.name for rb in owned)}.")
    if chats:
        change.summary.append(f"Its {chats} open chat{'s' if chats != 1 else ''} will be ended.")
    if followed:
        change.summary.append(f"Tickets it asked others for now report back to {target.name}: {followed}.")
    change.summary.append(f"Its files move to {archive}; you can bring it back later (it rejoins its boss's team; other team lists stay as they are now).")
    return change


def restore_agent(cfg: Config, name: str) -> Change:
    archive = cfg.vault.system / "Archive" / "Agents"
    folders = [p for p in archive.iterdir() if p.is_dir() and slug(p.name) == slug(name)] if archive.is_dir() else []
    if not folders:
        raise SetupError(f"There's no retired agent called '{name}'.")
    folder = folders[0]
    if slug(folder.name) in cfg.agents or (cfg.vault.agents_dir / folder.name).exists():
        raise SetupError(f"There's already an agent called {folder.name}.")
    try:
        text = (folder / "Agent.md").read_text(encoding="utf-8")
        meta = fm.parse(text).meta
    except (OSError, UnicodeDecodeError, fm.FrontmatterError) as exc:
        raise SetupError(f"{folder.name}'s file can't be read ({exc}).") from exc
    target = f"System/Agents/{folder.name}"
    change = Change(done=f"{folder.name} is back.")
    change.moves.append((rel(cfg, folder), target))
    boss_key = slug(str(meta.get("reports_to") or ""))
    change.summary = [f"Bring back {folder.name}."]
    if boss_key not in ("", "you") and boss_key not in cfg.agents and cfg.default_agent is not None:
        change.writes[f"{target}/Agent.md"] = _edit(cfg, folder / "Agent.md", {"reports_to": cfg.default_agent.name})
        boss_key = cfg.default_agent.key
        change.summary.append(f"Its old boss is gone, so it will report to {cfg.default_agent.name}.")
    if boss_key in cfg.agents:
        chief = cfg.agents[boss_key]
        change.writes[rel(cfg, chief.path)] = _edit(cfg, chief.path, {"can_assign_to": _merge(chief.can_assign_to, [folder.name])})
        change.summary.append(f"{chief.name} can hand it work again.")
    change.summary.append("Other team lists it was on aren't restored; ask if you want it added back.")
    change.summary.append("Tickets and routines it had before stay with whoever took them over.")
    return change

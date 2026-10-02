"""Setup changes for work and settings: projects, routines, skills, connections, the user's settings."""
from __future__ import annotations

import re
import shlex
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import frontmatter as fm
from .agent_setup import MAX_NAME, _edit
from .loader import Config
from .model import ALL, CLIS, SKILL_NAME, conn_key, slug
from .setup import Change, SetupError

_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]\n\r\t]')


_LIMITS = {"user_name": 100, "user_role": 100, "company": 100, "tone": 400, "preferences": 400}
_SECRET_MSG = "That looks like a password or key. Keep it in the tool's own sign-in or settings, not in Bron's files."
_FLAG = re.compile(r"^--?([A-Za-z0-9_-]+)(=.*)?$")
_SECRET_WORDS = {"token", "secret", "password", "passwd"}  # anywhere in a flag's name: --auth-token, --clientSecret
_SECRET_LAST = {"key", "apikey", "auth", "credentials", "passphrase", "pat", "bearer", "pw"}  # the last part of a flag's name: --api-key, --apiKey, --key (not --key-file)
_HARMLESS_LAST = {"file", "path", "name", "scheme", "type", "id", "limit", "endpoint", "url", "env", "count"}  # --token-file, --secret-name, --auth-scheme, --key-id
_KEY_FILES = {"public", "ssh", "private"}  # --ssh-key ~/.ssh/id_ed25519 is a file, not a key
_NOT_SECRET_KEYS = {"sort", "order", "group", "primary", "partition"}  # --sort-key name
_SECRET_ASSIGN = re.compile(r"^(--?[A-Za-z0-9_-]+=)?[A-Za-z0-9_]*(key|token|secret|password)[A-Za-z0-9_]*=.+", re.I)
_SECRET_HEADER = re.compile(r"^([\w=. -]*(?:api[-_ ]?key|token|secret|authorization)[\w=. -]*):\s*\S", re.I)
_URL_PASSWORD = re.compile(r"^\w[\w+.-]*://[^/\s]*:[^/\s@]*@")
_URL_QUERY_SECRET = re.compile(r"://[^\s]*[?&](?:api[_-]?key|token|secret|password|key)=([^&#\s]+)", re.I)
_PLACEHOLDER = re.compile(r"^\$\{?[\w:]+\}?$")  # ${API_KEY}, $API_KEY, ${env:API_KEY}
_SECRET_VALUE = re.compile(r"(^|=)(sk-|ghp_|xox)", re.I)
_BEARER = re.compile(r"^bearer(\s|$)", re.I)


def _flag_words(name: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", name)  # accessToken -> access-Token
    return [part.lower() for part in re.split(r"[-_]", spaced) if part]


def _secret_flag(token: str, following: str | None) -> bool:
    """A flag that would carry a secret, with a value (after '=' or as the next word)."""
    flag = _FLAG.match(token)
    if not flag:
        return False
    parts = _flag_words(flag.group(1))
    value = flag.group(2)[1:] if flag.group(2) else following
    if not parts or value is None or value == "" or _PLACEHOLDER.match(value):
        return False
    if parts[-1] == "user":
        return ":" in value  # a plain user name is fine; user:password is not
    if parts[-1] in _HARMLESS_LAST:
        return False
    if parts[-1] == "key":
        if set(parts[:-1]) & _NOT_SECRET_KEYS:
            return False
        if set(parts[:-1]) & _KEY_FILES and value.startswith(("/", "~", ".")):
            return False
    return bool(set(parts) & _SECRET_WORDS or parts[-1] in _SECRET_LAST)


def _secret_header(token: str) -> bool:
    match = _SECRET_HEADER.match(token)
    if not match:
        return False
    words = _flag_words(re.sub(r"[ .]+", "-", match.group(1).split("=")[-1]))
    return not (words and words[-1] in _HARMLESS_LAST)  # 'X-Token-Type: foo' is not a credential


def _secret_url(token: str) -> bool:
    """A web address that carries a password or a key, as a bare argument or after '--flag='."""
    if _URL_PASSWORD.search(token) or _URL_PASSWORD.search(token.split("=", 1)[-1]):
        return True
    return any(not _PLACEHOLDER.match(v) for v in _URL_QUERY_SECRET.findall(token))


def _looks_secret(tokens: list[str]) -> bool:
    for i, tok in enumerate(tokens):
        has_next = i + 1 < len(tokens)
        if _secret_flag(tok, tokens[i + 1] if has_next else None):
            return True
        if _SECRET_VALUE.search(tok) or _secret_header(tok) or _secret_url(tok):
            return True
        if _SECRET_ASSIGN.match(tok) and not _PLACEHOLDER.match(tok.rsplit("=", 1)[1]):
            return True
        if _BEARER.match(tok) and (tok.strip().lower() != "bearer" or has_next):
            return True
    return False


def _folder_name(name: str, what: str) -> str:
    name = " ".join(name.split())
    if len(name) > MAX_NAME:
        raise SetupError(f"Keep the name under {MAX_NAME} characters.")
    if not name or name.startswith(".") or _UNSAFE.search(name):
        raise SetupError(f"'{name}' can't be used as a {what} name: use letters, numbers and spaces.")
    return name


def _taken(folder, name: str) -> bool:
    return folder.is_dir() and any(p.name.lower() == name.lower() for p in folder.iterdir())


def new_project(cfg: Config, name: str, goal: str = "") -> Change:
    name = _folder_name(name, "project")
    if _taken(cfg.vault.projects_dir, name):
        raise SetupError(f"There's already a project called {name}.")
    goal = " ".join(goal.split())
    today = time.strftime("%Y-%m-%d")
    body = f"\n# {name}\n\n## Goal\n{goal or '(to be written)'}\n\n## Status\nActive since {today}.\n\n## Key decisions\n"
    change = Change(done=f"Started the project {name} in Projects/{name}/.")
    change.writes[f"Projects/{name}/README.md"] = fm.dump(fm.Document({"status": "active", "created": today}, body))
    change.summary = [f"New project: {name}."] + ([f"Goal: {goal}"] if goal else ["No goal written yet."])
    return change


def create_routine(cfg: Config, name: str, draft: str) -> Change:
    from .routines import ONCE, check_runbook

    name = _folder_name(name, "routine")
    if _taken(cfg.vault.routines_dir, name):
        raise SetupError(f"There's already a routine called {name}.")
    try:
        meta = fm.parse(draft).meta
    except fm.FrontmatterError as exc:
        raise SetupError(f"The drafted runbook can't be read ({exc}).") from exc
    runbook, issues = check_runbook(name, meta)
    errors = [i.message for i in issues if i.level == "error"]
    if runbook is None or errors:
        raise SetupError("The routine has problems:\n" + "\n".join(f"- {e}" for e in errors))
    main = cfg.default_agent.name if cfg.default_agent else "the main agent"
    owner_agent = cfg.agents.get(slug(runbook.owner)) if runbook.owner else cfg.default_agent
    # 'you' or an unknown owner: the main agent looks after it (as the health check says)
    keeper = owner_agent.name if owner_agent else (f"{main} (the main agent)" if cfg.default_agent else main)
    change = Change(done=f"Created the routine {name}. Say 'start <period>' when it's time.")
    change.writes[f"Routines/{name}/Runbook.md"] = draft if draft.endswith("\n") else draft + "\n"
    change.summary = [
        f"New routine: {name} ({runbook.cadence}), looked after by {keeper}.",
        f"Due: {runbook.due or 'no due date rule'}.",
    ]
    for key, value in runbook.lists.items():
        change.summary.append(f"List '{key}': {len(value)} fixed items." if isinstance(value, list) else f"List '{key}': from {value}.")
    for number, step in enumerate(runbook.steps, 1):
        text = f"Step {number}: {step.name}, " + ("once" if step.for_ == ONCE else f"for each of '{step.for_}'")
        if step.after:
            text += f", after {', '.join(step.after)}"
        change.summary.append(text + ".")
    return change


def new_skill(cfg: Config, name: str, description: str, body: str, agent: str = "") -> Change:
    from .agent_setup import find_agent

    if not SKILL_NAME.match(name) or len(name) > 64:
        raise SetupError("Skill names use lower-case letters, numbers and hyphens, like 'lp-report' (64 characters at most).")
    description = " ".join(description.split())
    if not description:
        raise SetupError("Say when the skill should be used.")
    owner = find_agent(cfg, agent) if agent.strip() else None
    folder = (owner.path.parent / "Skills" / name) if owner else (cfg.vault.skills_dir / name)
    if folder.exists():
        raise SetupError(f"There's already a skill called {name}.")
    text = fm.dump(fm.Document({"name": name, "description": description}, "\n" + body.strip() + "\n"))
    change = Change(done=f"Saved the skill {name}.")
    change.writes[folder.relative_to(cfg.vault.root).as_posix() + "/SKILL.md"] = text
    change.summary = [f"New skill: {name} (" + (f"for {owner.name} only" if owner else "for every agent") + ").", f"Used when: {description}"]
    existing = cfg.skills.get(name)
    if owner is None and existing is not None and existing.source == "core":
        change.summary.append(f"It replaces Bron's built-in '{name}' skill.")
    return change


def add_connection(cfg: Config, *, name: str, command: str = "", args: str = "", url: str = "", description: str = "") -> Change:
    name = " ".join(name.split())
    if len(name) > MAX_NAME:
        raise SetupError(f"Keep the name under {MAX_NAME} characters.")
    if not name or name.startswith(".") or _UNSAFE.search(name) or not conn_key(name):
        raise SetupError(f"'{name}' can't be used as a connection name: use letters, numbers and spaces.")
    if conn_key(name) in cfg.connections or (cfg.vault.connections_dir / f"{name}.md").exists():
        raise SetupError(f"There's already a connection called {name}.")
    if bool(command.strip()) == bool(url.strip()):
        raise SetupError("Give either a command (a tool that runs on this Mac) or a web address, not both.")
    try:
        arg_tokens = shlex.split(args) if args.strip() else []
        # a command that is itself an existing file (a path with spaces) is kept whole
        if command.strip() and Path(command.strip()).expanduser().is_file():
            cmd_tokens = [command.strip()]
        else:
            cmd_tokens = shlex.split(command) if command.strip() else []
    except ValueError as exc:
        raise SetupError(f"The command's arguments have an unclosed quote ({exc}).") from exc
    if _looks_secret(cmd_tokens + arg_tokens):
        raise SetupError(_SECRET_MSG)
    if url.strip():
        try:
            parts = urlsplit(url.strip())
        except ValueError:
            raise SetupError("The web address should start with https:// or http://.") from None
        if parts.username is not None or parts.password is not None or "@" in parts.netloc or parts.query:
            raise SetupError(_SECRET_MSG)
    meta: dict = {"name": name, "type": "mcp-stdio" if command.strip() else "mcp-http"}
    if command.strip():
        # 'npx -y foo': the first word is the command, the rest go before --args.
        meta["command"] = cmd_tokens[0]
        if cmd_tokens[1:] + arg_tokens:
            meta["args"] = cmd_tokens[1:] + arg_tokens
        where = f"Runs on this Mac. Command: {meta['command']}." + (f" Arguments: {' '.join(meta['args'])}." if meta.get("args") else "")
    else:
        if not re.match(r"^https?://\S+$", url.strip()):
            raise SetupError("The web address should start with https:// or http://.")
        meta["url"] = url.strip()
        where = f"Web address: {url.strip()}."
    if description.strip():
        meta["description"] = " ".join(description.split())
    everyone = [a.name for a in cfg.agents.values() if any(c.strip().lower() == ALL for c in a.connections)]
    change = Change(done=f"Added {name}. Tell me which agents may use it.")
    change.writes[f"System/Connections/{name}.md"] = fm.dump(fm.Document(meta, ""))
    change.summary = [
        f"New connection: {name}.",
        where,
        (f"{', '.join(everyone)} can use it straight away (they use every connection); " if everyone else "") + "other agents only once you add it to them.",
    ]
    return change


_LABELS = {"user_name": "Your name", "user_role": "Your role", "company": "Company", "default_cli": "Main app", "tone": "Tone", "preferences": "Preferences"}


def set_settings(cfg: Config, **fields) -> Change:
    current = {
        "user_name": cfg.settings.user_name,
        "user_role": cfg.settings.user_role,
        "company": cfg.settings.company,
        "default_cli": cfg.settings.default_cli,
        "tone": cfg.settings.tone,
        "preferences": cfg.settings.preferences,
    }
    changes: dict = {}
    for key, value in fields.items():
        if key not in _LABELS:
            raise SetupError(f"'{key}' isn't a setting Bron knows.")
        if value is None:
            continue
        value = " ".join(str(value).split())
        if key in _LIMITS and len(value) > _LIMITS[key]:
            raise SetupError(f"Keep {_LABELS[key]} under {_LIMITS[key]} characters; longer notes belong in System/Memory/.")
        if key == "default_cli" and value not in CLIS:
            raise SetupError("The main app should be claude or codex.")
        if value != current[key]:
            changes[key] = value
    if not changes:
        raise SetupError("Nothing to change in your settings.")
    change = Change(done="Saved your settings.")
    change.writes[cfg.settings.path.relative_to(cfg.vault.root).as_posix()] = _edit(cfg, cfg.settings.path, changes)
    change.summary = ["Update your settings:"] + [f"- {_LABELS[key]}: {value}" for key, value in changes.items()]
    return change

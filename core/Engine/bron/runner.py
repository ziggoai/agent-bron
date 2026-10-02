"""Running a ticket: start the assignee in its CLI, keep the ticket consistent, remember the session."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass

from .launch import LaunchSpec, choose_cli, run_spec
from .loader import load
from .locks import acquire, active, release
from .model import CLI_NAMES, slug
from .notifications import record
from .statefile import read_json, update_json
from .sync import needs_sync, run_sync
from .tickets import TicketError, add_message, editing, find_ticket, load_ticket, normalize_id, set_result, set_status
from .vault import Vault

NEEDS_OK = "Needs your OK:"
APPROVAL_SIGNAL = "approval required by policy"

TASK_PROMPT = """You are {agent}, working ticket {id} in this Bron vault: "{title}".
Read the ticket first: {path}

Do the work it asks for. Save any files you produce in the project or routine folder the ticket links to (or in Projects/Unsorted/ if it links none) and mention them in your result.

Report only through the ticket, with these commands, run from the vault folder:
- To ask a question you need answered: .bron/bin/bron ticket status {id} blocked --as {key} --note "<your question>"   (then stop and wait)
- When you're finished: .bron/bin/bron ticket result {id} --as {key} --text "<a short summary, plus links to any files you made>"

If an action is refused or needs approval (sending, sharing, deleting, pushing, or anything on your ask-before list), don't look for a way around it. Run
.bron/bin/bron ticket status {id} blocked --as {key} --note "{needs_ok} <the exact action, with every detail needed to do it>"
and stop."""

RESUME_PROMPT = """New messages on ticket {id} since your last turn:
{messages}

Continue working the ticket with the same rules as before: report through `.bron/bin/bron ticket` commands, and mark it blocked with "{needs_ok} …" for anything that needs approval."""


@dataclass
class Execution:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class RunOutcome:
    ticket_id: str
    status: str
    cli: str
    message: str


def _text(value) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def execute(argv: list[str], *, env: dict[str, str], cwd, timeout: int) -> Execution:
    try:
        done = subprocess.run(
            argv,
            cwd=cwd,
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        return Execution(-1, _text(exc.stdout), _text(exc.stderr), timed_out=True)
    except OSError as exc:
        return Execution(-1, "", str(exc))
    return Execution(done.returncode, done.stdout, done.stderr)


def parse_claude(stdout: str) -> tuple[str, str, list[str]]:
    data = None
    for line in reversed(stdout.strip().splitlines()):
        try:
            data = json.loads(line)
            break
        except ValueError:
            continue
    if not isinstance(data, dict):
        return "", "", []
    denials: list[str] = []
    for denial in data.get("permission_denials") or []:
        if not isinstance(denial, dict):
            continue
        tool = str(denial.get("tool_name") or "a tool")
        detail = denial.get("tool_input")
        if isinstance(detail, dict):
            detail = detail.get("command") or json.dumps(detail, ensure_ascii=False)
        denials.append(f"{tool}: {str(detail)[:300]}" if detail else tool)
    return str(data.get("session_id") or ""), str(data.get("result") or ""), denials


def parse_codex(stdout: str, stderr: str) -> tuple[str, str, list[str]]:
    thread, text = "", ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "thread.started":
            thread = str(event.get("thread_id") or thread)
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            text = str(item.get("text") or text)
    denials = ["a command that needs approval (Codex: approval required by policy)"] if APPROVAL_SIGNAL in stderr else []
    return thread, text, denials


def _block(vault: Vault, ticket, cli: str, note: str) -> RunOutcome:
    with editing(vault, ticket.id) as current:
        set_status(current, "blocked", "runner", note)
    record(vault, current)
    return RunOutcome(current.id, "blocked", cli, f"{current.id} is blocked: {note}")


def _wait_for_slot(vault: Vault, settings, sleep, now) -> bool:
    deadline = now() + settings.max_minutes * 60
    while len(active(vault, settings.max_minutes)) >= settings.max_parallel:
        if now() > deadline:
            return False
        sleep(5)
    return True


def _write_log(vault: Vault, run_id: str, spec: LaunchSpec, result: Execution) -> str:
    path = vault.bron_dir / "runs" / f"{run_id}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    note = " (timed out)" if result.timed_out else ""
    path.write_text(
        f"$ {' '.join(spec.argv[:3])} …\nexit: {result.returncode}{note}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n",
        encoding="utf-8",
    )
    return str(path.relative_to(vault.root))


def _settle(ticket, agent, result: Execution, text: str, denials: list[str], log: str) -> None:
    """Make sure the ticket never stays in-progress after a run."""
    if ticket.status != "in-progress":
        if denials and ticket.status != "blocked":
            add_message(ticket, "runner", "Some actions were refused while working: " + "; ".join(denials))
        return
    if result.timed_out:
        set_status(ticket, "blocked", "runner", f"{agent.name} took longer than the time limit and was stopped; see {log}")
    elif denials:
        set_status(ticket, "blocked", "runner", f"{NEEDS_OK} " + "; ".join(denials))
    elif text.strip():
        add_message(ticket, "runner", f"{agent.name} didn't report through the ticket; its final answer was saved as the result.")
        set_result(ticket, text, "runner")
    else:
        set_status(ticket, "blocked", "runner", f"The run ended without an answer (exit code {result.returncode}); see {log}")


def run_ticket(
    vault: Vault,
    ticket_id: str,
    *,
    caller_cli: str | None = None,
    resume: bool = False,
    run=execute,
    which=shutil.which,
    sleep=time.sleep,
    now=time.time,
) -> RunOutcome:
    cfg = load(vault)
    try:
        ticket = load_ticket(find_ticket(vault, ticket_id))
    except TicketError as exc:
        return RunOutcome(ticket_id, "error", "", str(exc))
    tid = ticket.id
    if ticket.status in ("done", "cancelled"):
        return RunOutcome(tid, ticket.status, "", f"{tid} is {ticket.status}; nothing to run.")
    agent = cfg.agents.get(slug(ticket.assignee))
    if agent is None:
        return _block(vault, ticket, "", f"The assignee '{ticket.assignee}' isn't an agent in System/Agents/.")
    runs_path = vault.state_dir / "runs.json"
    previous = read_json(runs_path, {}).get(tid, {}) if resume else {}
    cli = previous.get("cli") or choose_cli(cfg, agent, caller_cli)
    if which(cli) is None:
        return _block(vault, ticket, cli, f"{CLI_NAMES[cli]} isn't installed on this Mac, so {agent.name} can't work this ticket.")
    if not _wait_for_slot(vault, cfg.settings, sleep, now):
        return RunOutcome(tid, ticket.status, cli, "Too many tickets are running right now; try again shortly.")
    run_id = uuid.uuid4().hex[:12]
    if not acquire(vault, tid, run_id, max_minutes=cfg.settings.max_minutes):
        return RunOutcome(tid, ticket.status, cli, f"{tid} is already being worked on.")
    try:
        session = previous.get("session") or None
        if session:
            new = ticket.thread[int(previous.get("thread_len", 0)):]
            prompt = RESUME_PROMPT.format(id=tid, messages="\n".join(new) or "(no new messages; carry on)", needs_ok=NEEDS_OK)
        else:
            prompt = TASK_PROMPT.format(
                agent=agent.name,
                id=tid,
                key=agent.key,
                title=ticket.title,
                path=ticket.path.relative_to(vault.root),
                needs_ok=NEEDS_OK,
            )
        if needs_sync(vault) and not run_sync(vault).ok:
            return _block(vault, ticket, cli, f"Bron's setup has problems, so {agent.name} can't start; run `.bron/bin/bron check`.")
        with editing(vault, tid) as current:
            set_status(current, "in-progress", "runner", f"{agent.name} started in {CLI_NAMES[cli]}" + (" (continuing)" if session else ""))
        spec = run_spec(cfg, agent, cli, prompt, session=session, ticket_id=tid)
        result = run(spec.argv, env=spec.env, cwd=vault.root, timeout=cfg.settings.max_minutes * 60)
        log = _write_log(vault, run_id, spec, result)
        if cli == "claude":
            found_session, text, denials = parse_claude(result.stdout)
        else:
            found_session, text, denials = parse_codex(result.stdout, result.stderr)
        with editing(vault, tid) as ticket:
            _settle(ticket, agent, result, text, denials, log)
        entry = {
            "cli": cli,
            "session": found_session or session or "",
            "agent": agent.key,
            "thread_len": len(ticket.thread),
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        update_json(runs_path, {}, lambda data: data.update({tid: entry}))
        record(vault, ticket)
        note = f": {ticket.thread[-1].split(': ', 1)[-1]}" if ticket.status == "blocked" else ""
        return RunOutcome(tid, ticket.status, cli, f"{tid} is now {ticket.status} ({agent.name}){note}")
    finally:
        release(vault, tid, run_id)


def start_background(vault: Vault, ticket_id: str, *, caller_cli: str | None = None, resume: bool = False, popen=subprocess.Popen) -> int:
    tid = normalize_id(ticket_id)
    log = vault.bron_dir / "runs" / f"background-{tid}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = [str(vault.bron_command), "run", tid]
    if caller_cli:
        argv += ["--caller-cli", caller_cli]
    if resume:
        argv.append("--resume")
    with open(log, "a", encoding="utf-8") as out:
        process = popen(argv, cwd=vault.root, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    return process.pid

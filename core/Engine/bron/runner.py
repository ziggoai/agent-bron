"""Running a ticket: start the assignee in its CLI, keep the ticket consistent, remember the session."""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass

from .launch import LaunchSpec, choose_cli, run_spec
from .loader import load
from .locks import acquire, active, release
from .model import CLI_NAMES, CLIS, slug
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


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def execute(argv: list[str], *, env: dict[str, str], cwd, timeout: int) -> Execution:
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env={**os.environ, **env},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
    except OSError as exc:
        return Execution(-1, "", str(exc))
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_group(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout, stderr = _text(exc.stdout), _text(exc.stderr)
        return Execution(-1, stdout or "", stderr or "", timed_out=True)
    except BaseException:
        _kill_group(proc)
        raise
    return Execution(proc.returncode, stdout, stderr)


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
    raw = data.get("permission_denials")
    for denial in raw if isinstance(raw, list) else []:
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
    denials: list[str] = []
    if APPROVAL_SIGNAL in stderr:
        line = next((ln.strip() for ln in stderr.splitlines() if APPROVAL_SIGNAL in ln), "")
        denials = [f"a command that needs approval (Codex: {line[:300]})" if line else "a command that needs approval (Codex: approval required by policy)"]
    return thread, text, denials


def _block(vault: Vault, ticket, cli: str, note: str) -> RunOutcome:
    with editing(vault, ticket.id) as current:
        set_status(current, "blocked", "runner", note)
    record(vault, current)
    return RunOutcome(current.id, "blocked", cli, f"{current.id} is blocked: {note}")


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
    """Make sure the ticket never stays in-progress after a run, and that refused actions are surfaced."""
    needs_ok = f"{NEEDS_OK} " + "; ".join(denials)
    if ticket.status == "in-progress":
        if result.timed_out:
            set_status(ticket, "blocked", "runner", f"{agent.name} took longer than the time limit and was stopped; see {log}")
        elif denials:
            set_status(ticket, "blocked", "runner", needs_ok)
        elif text.strip():
            add_message(ticket, "runner", f"{agent.name} didn't report through the ticket; its final answer was saved as the result.")
            set_result(ticket, text, "runner")
        else:
            set_status(ticket, "blocked", "runner", f"The run ended without an answer (exit code {result.returncode}); see {log}")
        return
    if not denials:
        return
    if ticket.status in ("in-review", "blocked"):
        if ticket.status == "blocked" and ticket.thread and NEEDS_OK in ticket.thread[-1]:
            return
        set_status(ticket, "blocked", "runner", needs_ok)
    else:
        add_message(ticket, "runner", "Some actions were refused while working: " + "; ".join(denials))


def refusal(ticket, resume: bool) -> str | None:
    """Why a ticket shouldn't be started now (None when it can be)."""
    if ticket.status in ("done", "cancelled"):
        return f"{ticket.id} is {ticket.status}; nothing to run."
    if ticket.status == "in-review" and not resume:
        return f"{ticket.id} is waiting for review; use --resume to continue it."
    return None


def _valid_previous(entry, agent, which) -> dict:
    if not isinstance(entry, dict):
        return {}
    cli, session, length = entry.get("cli"), entry.get("session"), entry.get("thread_len")
    if cli not in CLIS or not isinstance(session, str) or not session:
        return {}
    if not isinstance(length, int) or isinstance(length, bool) or length < 0:
        return {}
    if entry.get("agent") != agent.key:
        return {}
    if agent.runs_in in CLIS and agent.runs_in != cli:
        return {}
    if which(cli) is None:
        return {}
    return entry


def _rescue(vault: Vault, tid: str, exc: BaseException, log: str) -> None:
    """Best effort: a run that blew up must not leave its ticket in-progress."""
    try:
        with editing(vault, tid) as ticket:
            if ticket.status == "in-progress":
                set_status(ticket, "blocked", "runner", f"The run stopped unexpectedly ({exc.__class__.__name__}: {exc}); see {log}")
        record(vault, ticket)
    except BaseException:
        pass


def _remember(vault: Vault, tid: str, entry: dict) -> None:
    try:
        update_json(vault.state_dir / "runs.json", {}, lambda data: data.update({tid: entry}))
    except (OSError, ValueError):
        pass


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
        tid = load_ticket(find_ticket(vault, ticket_id)).id
    except TicketError as exc:
        return RunOutcome(ticket_id, "error", "", str(exc))
    settings = cfg.settings
    run_id = uuid.uuid4().hex[:12]
    deadline = now() + settings.max_minutes * 60
    # Take the ticket's run lock first, then wait for a free slot without holding anything else up.
    while True:
        if not acquire(vault, tid, run_id, max_minutes=settings.max_minutes):
            return RunOutcome(tid, "", "", f"{tid} is already being worked on.")
        if len([lock for lock in active(vault, settings.max_minutes) if lock.ticket_id != tid]) < settings.max_parallel:
            break
        release(vault, tid, run_id)
        if now() > deadline:
            return RunOutcome(tid, "", "", "Too many tickets are running right now; try again shortly.")
        sleep(5)
    cli, log = "", ".bron/runs"
    try:
        try:
            ticket = load_ticket(find_ticket(vault, tid))
        except TicketError as exc:
            return RunOutcome(tid, "error", "", str(exc))
        why = refusal(ticket, resume)
        if why:
            return RunOutcome(tid, ticket.status, "", why)
        agent = cfg.agents.get(slug(ticket.assignee))
        if agent is None:
            return _block(vault, ticket, "", f"The assignee '{ticket.assignee}' isn't an agent in System/Agents/.")
        previous = _valid_previous(read_json(vault.state_dir / "runs.json", {}).get(tid) if resume else None, agent, which)
        cli = previous.get("cli") or choose_cli(cfg, agent, caller_cli)
        if which(cli) is None:
            return _block(vault, ticket, cli, f"{CLI_NAMES[cli]} isn't installed on this Mac, so {agent.name} can't work this ticket.")
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
        result = run(spec.argv, env=spec.env, cwd=vault.root, timeout=settings.max_minutes * 60)
        log = _write_log(vault, run_id, spec, result)
        if cli == "claude":
            found_session, text, denials = parse_claude(result.stdout)
        else:
            found_session, text, denials = parse_codex(result.stdout, result.stderr)
        entry = {"cli": cli, "session": found_session or session or "", "agent": agent.key, "thread_len": 0, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
        try:
            with editing(vault, tid) as ticket:
                _settle(ticket, agent, result, text, denials, log)
        except TicketError as exc:
            _remember(vault, tid, entry)
            return RunOutcome(tid, "error", cli, f"{tid} couldn't be read after the run: {exc}")
        entry["thread_len"] = len(ticket.thread)
        _remember(vault, tid, entry)
        record(vault, ticket)
        note = f": {ticket.thread[-1].split(': ', 1)[-1]}" if ticket.status == "blocked" else ""
        return RunOutcome(tid, ticket.status, cli, f"{tid} is now {ticket.status} ({agent.name}){note}")
    except BaseException as exc:
        _rescue(vault, tid, exc, log)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return RunOutcome(tid, "blocked", cli, f"{tid} is blocked: the run stopped unexpectedly ({exc.__class__.__name__}: {exc}); see {log}")
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

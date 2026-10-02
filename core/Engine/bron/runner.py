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
from .locks import acquire, is_stale, read_lock, release, take_slot
from .model import CLI_NAMES, CLIS, slug
from .notifications import acknowledge, record
from .statefile import read_json, update_json
from .sync import needs_sync, run_sync
from .tickets import TicketError, add_message, editing, find_ticket, list_tickets, load_ticket, normalize_id, set_result, set_status
from .vault import Vault

NEEDS_OK = "Needs your OK:"
APPROVAL_SIGNAL = "approval required by policy"

TASK_PROMPT = """You are {agent}, working ticket {id} in this Bron vault: "{title}" (file: {path}).

## Request
{request}

## Context
{context}

Do the work it asks for. Everything you need should be above: don't look around the vault or read files unless the request needs them. Save any files you produce in the project or routine folder the ticket links to (or in Projects/Unsorted/ if it links none) and mention them in your answer.

Your final reply becomes the ticket's Result: when you're finished, just reply with the answer (short, plus links to any files you made). Use a ticket command only to stop and ask, run from the vault folder:
- To ask a question you need answered: .bron/bin/bron ticket status {id} blocked --as {key} --note '<your question>'   (then stop and wait)
- If an action is refused or needs approval (sending, sharing, deleting, pushing, or anything on your ask-before list), don't look for a way around it. Run
  .bron/bin/bron ticket status {id} blocked --as {key} --note '{needs_ok} <the exact action, with every detail needed to do it>'
  and stop.
Put the text in single quotes; if the text contains a single quote, write it to a file and use `--file` (result) or `--note-file` (status)."""

RESUME_PROMPT = """New messages on ticket {id} since your last turn:
{messages}

Continue working the ticket with the same rules as before: your final reply becomes the Result; to ask a question, mark it blocked with `.bron/bin/bron ticket status` (text in single quotes, or `--note-file` when it contains one), and mark it blocked with '{needs_ok} …' for anything that needs approval."""


CHAT_PROMPT = """You are {agent}. The user is talking to you directly from a chat in this Bron vault (chat ticket {id}).

## Earlier in the chat
{context}

## The user's message
{request}{later}

Reply to the user directly, in your own voice: your final reply is shown to them word for word, so make it the answer itself, with nothing about tickets. Don't look around the vault unless the message needs it.
If something needs the user's OK (sending, sharing, deleting, pushing, or anything on your ask-before list), don't do it and don't look for a way around it. Run
.bron/bin/bron ticket status {id} blocked --as {key} --note '{needs_ok} <the exact action, with every detail needed to do it>'
and stop. Put the text in single quotes; if the text contains a single quote, write it to a file and use `--file` (result) or `--note-file` (status)."""

CHAT_RESUME_PROMPT = """The user replied in the chat (ticket {id}):
{messages}

Reply to them directly, the same way as before: your final reply is shown to them word for word. For anything that needs their OK, mark the ticket blocked with '{needs_ok} …' and stop."""


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


def ask_line(cfg, agent) -> str:
    """The agent's own ask-before actions, spelled out for a background run ('' when there are none)."""
    ask, _ = cfg.catalog.permissions_for(agent)
    parts = []
    if ask.shell:
        parts.append("shell " + ", ".join(f"`{' '.join(words)}`" for words in ask.shell))
    tools = [f"{conn}/{tool}" for conn, names in sorted(ask.mcp.items()) if conn in cfg.connections for tool in sorted(names)]
    if tools:
        parts.append("tool " + ", ".join(tools))
    if not parts:
        return ""
    return f"These actions need the user's OK — never do them yourself, mark the ticket blocked with '{NEEDS_OK} …' instead: " + "; ".join(parts)


def parse_claude(stdout: str) -> tuple[str, str, list[str], bool]:
    """(session id, final text, refused actions, whether Claude reported an error)."""
    data = None
    for line in reversed(stdout.strip().splitlines()):
        try:
            data = json.loads(line)
            break
        except ValueError:
            continue
    if not isinstance(data, dict):
        return "", "", [], False
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
    return str(data.get("session_id") or ""), str(data.get("result") or ""), denials, data.get("is_error") is True


def _codex_error(event: dict) -> str:
    error = event.get("error")
    if isinstance(error, dict):
        error = error.get("message")
    message = error or event.get("message")
    return str(message).strip() if message else "Codex reported an error"


def parse_codex(stdout: str, stderr: str) -> tuple[str, str, list[str], str]:
    """(thread id, final text, refused actions, failure message or '').

    A `turn.failed` or `error` event is a failure unless a later turn completes (Codex reports
    transient errors such as reconnects as `error` events and then carries on).
    """
    thread, text, failure = "", "", ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind == "thread.started":
            thread = str(event.get("thread_id") or thread)
        elif kind in ("turn.failed", "error"):
            failure = _codex_error(event)
        elif kind == "turn.completed":
            failure = ""
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            text = str(item.get("text") or text)
    denials: list[str] = []
    if APPROVAL_SIGNAL in stderr:
        line = next((ln.strip() for ln in stderr.splitlines() if APPROVAL_SIGNAL in ln), "")
        denials = [f"a command that needs approval (Codex: {line[:300]})" if line else "a command that needs approval (Codex: approval required by policy)"]
    return thread, text, denials, failure


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


def _first_line(*texts: str) -> str:
    for text in texts:
        for line in (text or "").splitlines():
            if line.strip():
                return line.strip()[:300]
    return ""


def _settle(ticket, agent, result: Execution, text: str, denials: list[str], log: str, failure: str = "") -> None:
    """Make sure the ticket never stays in-progress after a run, and that refused actions are surfaced.

    `failure` is the CLI's own error text when it reported one (Claude `is_error`, a failed Codex turn).
    """
    needs_ok = f"{NEEDS_OK} " + "; ".join(denials)
    if ticket.status == "in-progress":
        if result.timed_out:
            set_status(ticket, "blocked", "runner", f"{agent.name} took longer than the time limit and was stopped; see {log}")
        elif denials:
            set_status(ticket, "blocked", "runner", needs_ok)
        elif failure or result.returncode != 0:
            why = _first_line(failure, text, result.stderr) or f"exit code {result.returncode}"
            set_status(ticket, "blocked", "runner", f"The run failed: {why}; see {log}")
        elif text.strip():
            if ticket.kind == "chat":
                # The chat ticket is the conversation's record: every reply goes in the Thread.
                add_message(ticket, agent.key, text)
                ticket.result = text.strip()
                ticket.status = "in-review"
                ticket.invalid.pop("status", None)
            else:
                set_result(ticket, text, agent.key)
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
    shown: bool = False,
) -> RunOutcome:
    """Have the assignee work the ticket. `shown`: the caller is waiting and will show the outcome itself,
    so the requester isn't told about it again in a later message."""
    cfg = load(vault)
    try:
        tid = load_ticket(find_ticket(vault, ticket_id)).id
    except TicketError as exc:
        return RunOutcome(ticket_id, "error", "", str(exc))
    settings = cfg.settings
    run_id = uuid.uuid4().hex[:12]
    deadline = now() + settings.max_minutes * 60
    # Take the ticket's run lock first, marked waiting, then wait for a free slot. The lock stays held while the
    # run is queued, so `ticket wait` keeps waiting for it; a waiting lock doesn't count as a running slot.
    if not acquire(vault, tid, run_id, max_minutes=settings.max_minutes, waiting=True):
        return RunOutcome(tid, "", "", f"{tid} is already being worked on.")
    try:
        while (slot := take_slot(vault, tid, run_id, max_parallel=settings.max_parallel, max_minutes=settings.max_minutes)) == "full":
            if now() > deadline:
                release(vault, tid, run_id)
                return RunOutcome(tid, "", "", "Too many tickets are running right now; try again shortly.")
            sleep(5)
    except BaseException:
        release(vault, tid, run_id)
        raise
    if slot == "lost":
        return RunOutcome(tid, "", "", f"{tid} is already being worked on.")
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
            template = CHAT_RESUME_PROMPT if ticket.kind == "chat" else RESUME_PROMPT
            prompt = template.format(id=tid, messages="\n".join(new) or "(no new messages; carry on)", needs_ok=NEEDS_OK, key=agent.key)
        elif ticket.kind == "chat":
            later = [entry for entry in ticket.thread if " · you: " in entry]
            prompt = CHAT_PROMPT.format(
                agent=agent.name,
                id=tid,
                key=agent.key,
                request=ticket.request or "(none)",
                context=ticket.context or "(none)",
                later=("\n\nLater messages:\n" + "\n".join(later)) if later else "",
                needs_ok=NEEDS_OK,
            )
        else:
            prompt = TASK_PROMPT.format(
                agent=agent.name,
                id=tid,
                key=agent.key,
                title=ticket.title,
                path=ticket.path.relative_to(vault.root),
                request=ticket.request or "(none)",
                context=ticket.context or "(none)",
                needs_ok=NEEDS_OK,
            )
        asks = ask_line(cfg, agent)
        if asks:
            prompt += "\n\n" + asks
        if needs_sync(vault) and not run_sync(vault).ok:
            return _block(vault, ticket, cli, f"Bron's setup has problems, so {agent.name} can't start; run `.bron/bin/bron check`.")
        with editing(vault, tid) as current:
            set_status(current, "in-progress", "runner", f"{agent.name} started in {CLI_NAMES[cli]}" + (" (continuing)" if session else ""))
        spec = run_spec(cfg, agent, cli, prompt, session=session, ticket_id=tid)
        result = run(spec.argv, env=spec.env, cwd=vault.root, timeout=settings.max_minutes * 60)
        log = _write_log(vault, run_id, spec, result)
        if cli == "claude":
            found_session, text, denials, is_error = parse_claude(result.stdout)
            failure = (text.strip() or "Claude Code reported an error") if is_error else ""
        else:
            found_session, text, denials, failure = parse_codex(result.stdout, result.stderr)
        entry = {"cli": cli, "session": found_session or session or "", "agent": agent.key, "thread_len": 0, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
        try:
            with editing(vault, tid) as ticket:
                _settle(ticket, agent, result, text, denials, log, failure)
        except TicketError as exc:
            _remember(vault, tid, entry)
            return RunOutcome(tid, "error", cli, f"{tid} couldn't be read after the run: {exc}")
        entry["thread_len"] = len(ticket.thread)
        _remember(vault, tid, entry)
        record(vault, ticket, shown=shown)
        note = f": {ticket.thread[-1].split(': ', 1)[-1]}" if ticket.status == "blocked" else ""
        answer = f"\nResult:\n{ticket.result}" if ticket.status == "in-review" and ticket.result else ""
        return RunOutcome(tid, ticket.status, cli, f"{tid} is now {ticket.status} ({agent.name}){note}{answer}")
    except BaseException as exc:
        _rescue(vault, tid, exc, log)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return RunOutcome(tid, "blocked", cli, f"{tid} is blocked: the run stopped unexpectedly ({exc.__class__.__name__}: {exc}); see {log}")
    finally:
        release(vault, tid, run_id)


ORPHANED = "The run stopped before it finished (Bron or the Mac was closed); see .bron/runs/"


def recover_orphans(vault: Vault) -> list[str]:
    """Block in-progress tickets whose run is gone (no lock, or a stale one). Returns their ids."""
    max_minutes = load(vault).settings.max_minutes

    def orphaned(tid: str) -> bool:
        lock = read_lock(vault, tid)
        return lock is None or is_stale(lock, max_minutes)

    class _Busy(Exception):
        pass

    tickets, _ = list_tickets(vault)
    blocked: list[str] = []
    for ticket in tickets:
        try:
            if ticket.status != "in-progress" or not orphaned(ticket.id):
                continue
            with editing(vault, ticket.id) as current:
                # Check again under the ticket's lock: a run may have just started it (leave the file untouched).
                if current.status != "in-progress" or not orphaned(current.id):
                    raise _Busy
                set_status(current, "blocked", "runner", ORPHANED)
            record(vault, current)
            blocked.append(current.id)
        except (_Busy, TicketError, OSError, ValueError):
            continue
    return blocked


def start_background(
    vault: Vault,
    ticket_id: str,
    *,
    caller_cli: str | None = None,
    resume: bool = False,
    popen=subprocess.Popen,
) -> int:
    """Start `bron run` detached (its own session, so it outlives the caller). Its update is recorded as usual;
    a `ticket wait` that prints the outcome acknowledges it, so the requester isn't told twice."""
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


def describe_outcome(cfg, ticket) -> str:
    """What the requester shows: the agent's reply, or why it stopped."""
    agent = cfg.agents.get(slug(ticket.assignee))
    name = agent.name if agent else ticket.assignee
    if ticket.status == "in-review":
        return f"{name}: {ticket.result}" if ticket.result else f"{ticket.id} is in-review ({name}) without an answer."
    if ticket.status == "blocked":
        last = ticket.thread[-1] if ticket.thread else ""
        marker = "status → blocked: "
        note = last.split(marker, 1)[1] if marker in last else last.split(": ", 1)[-1]
        return f"{ticket.id} is blocked ({name}): {note}"
    return f"{ticket.id} is {ticket.status} ({name})."


def wait_for(
    vault: Vault, ticket_ids: list[str], *, grace: float = 15.0, poll: float = 0.5, sleep=time.sleep, now=time.time, show=None
) -> list[str]:
    """Wait until each ticket's run has finished, then describe it. A run that hasn't taken its lock gets `grace` seconds
    (a run queued for a free slot already holds its lock). `show` is called with each line as soon as it's ready; once
    a ticket's outcome has been shown, its update is acknowledged so the requester isn't told about it again. An outcome
    that was never shown (the wait gave up or was cut off) is announced in the requester's next message."""
    cfg = load(vault)
    limit = cfg.settings.max_minutes * 60 + 60
    start = now()
    out: list[str] = []

    def emit(line: str, outcome_of: str = "") -> None:
        out.append(line)
        if show is not None:
            show(line)
        if outcome_of:
            try:
                acknowledge(vault, outcome_of)
            except OSError:
                pass  # worst case the update is announced once more

    for raw in ticket_ids:
        try:
            tid = normalize_id(raw)
        except TicketError as exc:
            emit(str(exc))
            continue
        began = now()
        while True:
            # Read the lock first: a run saves its ticket before it releases the lock, so no lock means the ticket is settled.
            running = read_lock(vault, tid) is not None
            try:
                ticket = load_ticket(find_ticket(vault, tid))
            except TicketError as exc:
                emit(str(exc))
                break
            if not running and ticket.status not in ("todo", "in-progress"):
                emit(describe_outcome(cfg, ticket), tid)
                break
            current = now()
            if not running and current - began > grace:
                if ticket.status == "todo":
                    emit(f"{tid} hasn't started; see .bron/runs/background-{tid}.log")
                else:
                    emit(f"{tid} stopped before it finished; see .bron/runs/")
                break
            if current - start > limit:
                emit(f"{tid} is still running after {cfg.settings.max_minutes} minutes; check it later with `.bron/bin/bron ticket show {tid}`.")
                break
            sleep(poll)
    return out

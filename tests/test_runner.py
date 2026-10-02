import json

import pytest

from bron.locks import acquire, read_lock
from bron.runner import APPROVAL_SIGNAL, Execution, parse_claude, parse_codex, run_ticket, start_background
from bron.statefile import read_json
from bron.tickets import add_message, load_ticket, new_ticket, save_ticket, set_result, set_status
from vaultkit import add_agent, set_meta

DEAD_PID = 999_999


@pytest.fixture
def team(vault):
    add_agent(vault, "CFO")
    add_agent(vault, "Pinned", runs_in="codex")
    set_meta(vault.agents_dir / "Bron" / "Agent.md", can_assign_to=["CFO", "Pinned"])
    return vault


def ticket_for(vault, assignee="cfo"):
    return new_ticket(vault, title="Q3 report", assignee=assignee, request="Draft it.", requested_by="bron")


def claude_json(session="s1", result="Done.", denials=()):
    return json.dumps({"session_id": session, "result": result, "permission_denials": list(denials)})


def codex_jsonl(thread="th-1", text="Done."):
    events = [
        {"type": "thread.started", "thread_id": thread},
        {"type": "item.completed", "item": {"id": "a", "type": "agent_message", "text": text}},
        {"type": "turn.completed"},
    ]
    return "\n".join(json.dumps(e) for e in events) + "\n"


class FakeCLI:
    """Stands in for `claude`/`codex`; `act` may edit the ticket like the agent would."""

    def __init__(self, vault, result, act=None):
        self.vault, self.result, self.act, self.calls = vault, result, act, []

    def __call__(self, argv, *, env, cwd, timeout):
        self.calls.append({"argv": argv, "env": env, "cwd": cwd, "timeout": timeout})
        if self.act:
            ticket = load_ticket(next(self.vault.tickets_dir.glob(f"{env['BRON_TICKET']} *.md")))
            self.act(ticket)
            save_ticket(ticket)
        return self.result


def found(_cli):
    return f"/usr/bin/{_cli}"


def test_parsers():
    assert parse_claude(claude_json("s9", "Hi", [{"tool_name": "Bash", "tool_input": {"command": "rm a.txt"}}])) == ("s9", "Hi", ["Bash: rm a.txt"])
    assert parse_claude("garbage") == ("", "", [])
    assert parse_codex(codex_jsonl("th-9", "Hi"), "") == ("th-9", "Hi", [])
    assert parse_codex("", f"exec_command failed: {APPROVAL_SIGNAL}")[2]


def test_claude_run_where_the_agent_reports_through_the_ticket(team):
    ticket = ticket_for(team)
    fake = FakeCLI(team, Execution(0, claude_json(), ""), act=lambda t: set_result(t, "Draft in Projects/Q3.md", "cfo"))
    outcome = run_ticket(team, ticket.id, caller_cli="claude", run=fake, which=found)
    assert outcome.status == "in-review" and outcome.cli == "claude"
    call = fake.calls[0]
    assert call["argv"][0] == "claude" and call["argv"][call["argv"].index("--agent") + 1] == "cfo"
    assert call["env"] == {"BRON_AGENT": "CFO", "BRON_TICKET": "T-0001"}
    assert "Read the ticket first: Tickets/T-0001 Q3 report.md" in call["argv"][2]
    assert call["timeout"] == 30 * 60
    loaded = load_ticket(ticket.path)
    assert loaded.result == "Draft in Projects/Q3.md"
    assert any("CFO started in Claude Code" in e for e in loaded.thread)
    runs = read_json(team.state_dir / "runs.json", {})
    assert runs["T-0001"]["cli"] == "claude" and runs["T-0001"]["session"] == "s1"
    assert read_lock(team, "T-0001") is None
    assert (team.state_dir / "notifications.jsonl").read_text().count("T-0001") == 1


def test_pinned_agent_runs_in_its_own_cli_and_a_silent_agent_still_gets_a_result(team):
    ticket = ticket_for(team, "pinned")
    fake = FakeCLI(team, Execution(0, codex_jsonl(text="The answer is 42."), ""))
    outcome = run_ticket(team, ticket.id, caller_cli="claude", run=fake, which=found)
    assert outcome.cli == "codex" and fake.calls[0]["argv"][:2] == ["codex", "exec"]
    loaded = load_ticket(ticket.path)
    assert loaded.status == "in-review" and loaded.result == "The answer is 42."
    assert any("didn't report through the ticket" in e for e in loaded.thread)
    assert read_json(team.state_dir / "runs.json", {})["T-0001"]["session"] == "th-1"


def test_refused_action_blocks_with_needs_your_ok(team):
    ticket = ticket_for(team)
    denials = [{"tool_name": "Bash", "tool_input": {"command": "rm Projects/keep.txt"}}]
    run_ticket(team, ticket.id, caller_cli="claude", run=FakeCLI(team, Execution(0, claude_json(denials=denials), "")), which=found)
    loaded = load_ticket(ticket.path)
    assert loaded.status == "blocked"
    assert "status → blocked: Needs your OK: Bash: rm Projects/keep.txt" in loaded.thread[-1]


def test_codex_approval_signal_blocks(team):
    ticket = ticket_for(team, "pinned")
    run_ticket(team, ticket.id, run=FakeCLI(team, Execution(0, codex_jsonl(text=""), f"... {APPROVAL_SIGNAL} ...")), which=found)
    assert load_ticket(ticket.path).status == "blocked"
    assert "Needs your OK:" in load_ticket(ticket.path).thread[-1]


def test_timeout_and_silent_failure_never_leave_the_ticket_in_progress(team):
    first = ticket_for(team)
    run_ticket(team, first.id, run=FakeCLI(team, Execution(-1, "", "", timed_out=True)), which=found)
    assert load_ticket(first.path).status == "blocked"
    assert "took longer than the time limit" in load_ticket(first.path).thread[-1]
    second = new_ticket(team, title="Other", assignee="cfo", request="x", requested_by="bron")
    run_ticket(team, second.id, run=FakeCLI(team, Execution(1, "", "boom")), which=found)
    last = load_ticket(second.path).thread[-1]
    assert load_ticket(second.path).status == "blocked" and ".bron/runs/" in last
    assert any("boom" in log.read_text() for log in (team.bron_dir / "runs").glob("*.log"))


def test_agent_question_then_resume_in_the_same_session(team):
    ticket = ticket_for(team)
    ask = FakeCLI(team, Execution(0, claude_json(session="s1"), ""), act=lambda t: set_status(t, "blocked", "cfo", "NAV as of 30 Sep or 15 Oct?"))
    run_ticket(team, ticket.id, caller_cli="claude", run=ask, which=found)
    loaded = load_ticket(ticket.path)
    add_message(loaded, "bron", "Use 30 Sep.")
    save_ticket(loaded)
    answer = FakeCLI(team, Execution(0, claude_json(session="s1"), ""), act=lambda t: set_result(t, "Done with 30 Sep.", "cfo"))
    outcome = run_ticket(team, ticket.id, resume=True, run=answer, which=found)
    argv = answer.calls[0]["argv"]
    assert argv[argv.index("--resume") + 1] == "s1"
    assert "Use 30 Sep." in argv[2] and "created for cfo" not in argv[2]
    assert outcome.status == "in-review"


def test_resume_without_a_saved_session_starts_fresh(team):
    ticket = ticket_for(team)
    fake = FakeCLI(team, Execution(0, claude_json(), ""), act=lambda t: set_result(t, "ok", "cfo"))
    run_ticket(team, ticket.id, resume=True, run=fake, which=found)
    assert "--resume" not in fake.calls[0]["argv"]


def test_missing_cli_blocks_with_a_reason(team):
    ticket = ticket_for(team, "pinned")
    fake = FakeCLI(team, Execution(0, "", ""))
    run_ticket(team, ticket.id, run=fake, which=lambda name: None)
    assert fake.calls == []
    assert "Codex isn't installed" in load_ticket(ticket.path).thread[-1]


def test_a_locked_or_finished_ticket_is_not_run(team):
    ticket = ticket_for(team)
    acquire(team, ticket.id, "other-run")
    fake = FakeCLI(team, Execution(0, claude_json(), ""))
    assert "already being worked on" in run_ticket(team, ticket.id, run=fake, which=found).message
    assert fake.calls == []
    done = new_ticket(team, title="Old", assignee="cfo", request="x", requested_by="bron", status="done")
    assert "nothing to run" in run_ticket(team, done.id, run=fake, which=found).message


def test_unknown_assignee_blocks(team):
    ticket = new_ticket(team, title="Ghost", assignee="ghost", request="x", requested_by="bron")
    run_ticket(team, ticket.id, run=FakeCLI(team, Execution(0, "", "")), which=found)
    assert "isn't an agent" in load_ticket(ticket.path).thread[-1]


def test_waits_for_a_free_slot(team):
    set_meta(team.settings_file, runner={"max_parallel": 1, "max_minutes": 30})
    acquire(team, "T-0099", "busy")
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        (team.bron_dir / "locks" / "T-0099.lock").unlink()

    ticket = ticket_for(team)
    fake = FakeCLI(team, Execution(0, claude_json(), ""), act=lambda t: set_result(t, "ok", "cfo"))
    assert run_ticket(team, ticket.id, run=fake, which=found, sleep=sleep).status == "in-review"
    assert slept == [5]


def test_background_start_detaches_and_passes_options(team):
    seen = {}

    class Proc:
        pid = 4242

    def popen(argv, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs
        return Proc()

    assert start_background(team, "T-0001", caller_cli="codex", resume=True, popen=popen) == 4242
    assert seen["argv"] == [str(team.bron_command), "run", "T-0001", "--caller-cli", "codex", "--resume"]
    assert seen["kwargs"]["start_new_session"] is True and seen["kwargs"]["cwd"] == team.root


def test_a_sync_is_run_before_the_agent_starts_when_needed(team):
    settings = team.root / ".claude" / "bron" / "agents" / "cfo.settings.json"
    settings.unlink(missing_ok=True)
    ticket = ticket_for(team)
    fake = FakeCLI(team, Execution(0, claude_json(), ""), act=lambda t: set_result(t, "ok", "cfo"))
    run_ticket(team, ticket.id, caller_cli="claude", run=fake, which=found)
    assert settings.exists()
    assert fake.calls


def test_a_failing_sync_blocks_the_ticket(team, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr("bron.runner.needs_sync", lambda vault: True)
    monkeypatch.setattr("bron.runner.run_sync", lambda vault: SimpleNamespace(ok=False))
    ticket = ticket_for(team)
    fake = FakeCLI(team, Execution(0, claude_json(), ""))
    run_ticket(team, ticket.id, caller_cli="claude", run=fake, which=found)
    assert fake.calls == []
    loaded = load_ticket(ticket.path)
    assert loaded.status == "blocked"
    assert "Bron's setup has problems, so CFO can't start; run `.bron/bin/bron check`." in loaded.thread[-1]
    assert read_lock(team, "T-0001") is None

import json

import pytest

from bron.locks import acquire, read_lock
from bron.runner import APPROVAL_SIGNAL, Execution, parse_claude, parse_codex, run_ticket, start_background
from bron.statefile import read_json
from bron.tickets import add_message, editing, load_ticket, new_ticket, save_ticket, set_result, set_status
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
    assert parse_claude(claude_json("s9", "Hi", [{"tool_name": "Bash", "tool_input": {"command": "rm a.txt"}}])) == ("s9", "Hi", ["Bash: rm a.txt"], False)
    assert parse_claude("garbage") == ("", "", [], False)
    assert parse_codex(codex_jsonl("th-9", "Hi"), "") == ("th-9", "Hi", [], "")
    assert parse_codex("", f"exec_command failed: {APPROVAL_SIGNAL}")[2]


def test_claude_run_where_the_agent_reports_through_the_ticket(team):
    ticket = ticket_for(team)
    fake = FakeCLI(team, Execution(0, claude_json(), ""), act=lambda t: set_result(t, "Draft in Projects/Q3.md", "cfo"))
    outcome = run_ticket(team, ticket.id, caller_cli="claude", run=fake, which=found)
    assert outcome.status == "in-review" and outcome.cli == "claude"
    call = fake.calls[0]
    assert call["argv"][0] == "claude" and call["argv"][call["argv"].index("--agent") + 1] == "cfo"
    assert call["env"] == {"BRON_AGENT": "CFO", "BRON_TICKET": "T-0001"}
    assert "Draft it." in call["argv"][2]
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
    assert any("pinned: status → in-review: result added" in e for e in loaded.thread)
    assert read_json(team.state_dir / "runs.json", {})["T-0001"]["session"] == "th-1"


def test_refused_action_blocks_with_needs_your_ok(team):
    ticket = ticket_for(team)
    denials = [{"tool_name": "Bash", "tool_input": {"command": "rm Projects/keep.txt"}}]
    run_ticket(team, ticket.id, caller_cli="claude", run=FakeCLI(team, Execution(0, claude_json(denials=denials), "")), which=found)
    loaded = load_ticket(ticket.path)
    assert loaded.status == "blocked"
    assert "status → blocked: Needs your OK: Bash: rm Projects/keep.txt" in loaded.thread[-1]


def test_a_refused_read_in_a_finished_run_keeps_the_answer(team):
    ticket = ticket_for(team)
    denials = [{"tool_name": "Read", "tool_input": {"file_path": "/tmp/notes.txt"}}]
    run_ticket(team, ticket.id, caller_cli="claude", run=FakeCLI(team, Execution(0, claude_json(denials=denials), "")), which=found)
    loaded = load_ticket(ticket.path)
    assert loaded.status == "in-review" and loaded.result == "Done."
    assert any('Some reads were refused while working: Read: {"file_path": "/tmp/notes.txt"}' in e for e in loaded.thread)
    mixed = ticket_for(team)
    denials.append({"tool_name": "Bash", "tool_input": {"command": "rm Projects/keep.txt"}})
    run_ticket(team, mixed.id, caller_cli="claude", run=FakeCLI(team, Execution(0, claude_json(denials=denials), "")), which=found)
    assert load_ticket(mixed.path).status == "blocked"  # anything more than a read still needs the user's OK


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


# ---- fix round 1: robustness, locking, background, resume validation, denials ----

import sys

from bron import runner
from bron.cli import main
from bron.notifications import record, take


def raising(exc):
    def run(argv, **kwargs):
        raise exc

    return run


def test_invalid_utf8_from_a_real_child_never_crashes(team):
    child = [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'\\xff\\xfe')"]
    done = runner.execute(child, env={}, cwd=team.root, timeout=30)
    assert done.returncode == 0 and "�" in done.stdout

    ticket = ticket_for(team)
    run_ticket(team, ticket.id, run=lambda argv, *, env, cwd, timeout: runner.execute(child, env=env, cwd=cwd, timeout=timeout), which=found)
    assert load_ticket(ticket.path).status == "blocked"
    assert read_lock(team, ticket.id) is None


def test_timeout_kills_the_whole_process_group(team):
    child = [sys.executable, "-c", "import time; time.sleep(60)"]
    done = runner.execute(child, env={}, cwd=team.root, timeout=1)
    assert done.timed_out


def test_a_run_that_raises_is_blocked_not_crashed(team):
    ticket = ticket_for(team)
    outcome = run_ticket(team, ticket.id, run=raising(RuntimeError("boom")), which=found)
    assert outcome.status == "blocked"
    loaded = load_ticket(ticket.path)
    assert loaded.status == "blocked" and "RuntimeError: boom" in loaded.thread[-1]
    assert read_lock(team, ticket.id) is None
    assert (team.state_dir / "notifications.jsonl").read_text().count("T-0001") == 1


def test_a_failing_run_log_blocks(team):
    ticket = ticket_for(team)
    team.bron_dir.mkdir(exist_ok=True)
    (team.bron_dir / "runs").write_text("not a dir")
    run_ticket(team, ticket.id, run=FakeCLI(team, Execution(0, claude_json(), "")), which=found)
    assert load_ticket(ticket.path).status == "blocked"


def test_denials_that_are_not_a_list_do_not_crash(team):
    stdout = json.dumps({"session_id": "s", "result": "", "permission_denials": 5})
    assert parse_claude(stdout) == ("s", "", [], False)
    ticket = ticket_for(team)
    run_ticket(team, ticket.id, run=FakeCLI(team, Execution(0, stdout, "")), which=found)
    assert load_ticket(ticket.path).status == "blocked"


def test_agent_deleting_the_ticket_gives_an_error_and_frees_the_lock(team):
    ticket = ticket_for(team)

    def run(argv, **kwargs):
        ticket.path.unlink()
        return Execution(0, claude_json(), "")

    outcome = run_ticket(team, ticket.id, run=run, which=found)
    assert outcome.status == "error" and "couldn't be read after the run" in outcome.message
    assert read_lock(team, "T-0001") is None
    assert read_json(team.state_dir / "runs.json", {})["T-0001"]["session"] == "s1"


def test_keyboard_interrupt_blocks_the_ticket_and_propagates(team):
    ticket = ticket_for(team)
    with pytest.raises(KeyboardInterrupt):
        run_ticket(team, ticket.id, run=raising(KeyboardInterrupt()), which=found)
    assert load_ticket(ticket.path).status == "blocked"
    assert read_lock(team, ticket.id) is None


def test_a_second_run_waiting_for_a_slot_does_not_rerun_a_finished_ticket(team):
    set_meta(team.settings_file, runner={"max_parallel": 1, "max_minutes": 30})
    ticket = ticket_for(team)
    acquire(team, "T-0099", "busy")

    def sleep(seconds):
        loaded = load_ticket(ticket.path)
        set_result(loaded, "done by the first run", "cfo")
        save_ticket(loaded)
        (team.bron_dir / "locks" / "T-0099.lock").unlink()

    fake = FakeCLI(team, Execution(0, claude_json(), ""))
    outcome = run_ticket(team, ticket.id, run=fake, which=found, sleep=sleep)
    assert fake.calls == [] and "waiting for review" in outcome.message
    assert read_lock(team, ticket.id) is None


def test_checks_run_under_the_lock_so_a_busy_ticket_is_left_alone(team):
    ticket = ticket_for(team)
    acquire(team, ticket.id, "other")
    before = ticket.path.read_text()
    run_ticket(team, ticket.id, run=FakeCLI(team, Execution(0, "", "")), which=lambda name: None)
    assert ticket.path.read_text() == before
    assert read_lock(team, ticket.id).run_id == "other"


def test_in_review_needs_resume(team):
    ticket = new_ticket(team, title="R", assignee="cfo", request="x", requested_by="bron", status="in-review")
    fake = FakeCLI(team, Execution(0, claude_json(), ""))
    assert "waiting for review; use --resume" in run_ticket(team, ticket.id, run=fake, which=found).message
    assert fake.calls == []


def test_resume_starts_fresh_when_the_saved_run_does_not_fit(team):
    ticket = ticket_for(team)
    path = team.state_dir / "runs.json"
    entries = [
        "oops",
        {"cli": "gemini", "session": "s", "thread_len": 1, "agent": "cfo"},
        {"cli": "claude", "session": "s", "thread_len": "x", "agent": "cfo"},
        {"cli": "claude", "session": "s", "thread_len": 1, "agent": "someone-else"},
    ]
    for entry in entries:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({ticket.id: entry}))
        fake = FakeCLI(team, Execution(0, claude_json(), ""), act=lambda t: set_result(t, "ok", "cfo"))
        run_ticket(team, ticket.id, resume=True, run=fake, which=found)
        assert "--resume" not in fake.calls[0]["argv"], entry
        loaded = load_ticket(ticket.path)
        loaded.status = "open"
        save_ticket(loaded)


def test_reassigned_ticket_starts_fresh_in_the_new_agents_cli(team):
    ticket = ticket_for(team, "cfo")
    ask = FakeCLI(team, Execution(0, claude_json(session="s1"), ""), act=lambda t: set_status(t, "blocked", "cfo", "q?"))
    run_ticket(team, ticket.id, caller_cli="claude", run=ask, which=found)
    loaded = load_ticket(ticket.path)
    loaded.assignee = "pinned"
    save_ticket(loaded)
    fake = FakeCLI(team, Execution(0, codex_jsonl(), ""))
    outcome = run_ticket(team, ticket.id, resume=True, run=fake, which=found)
    assert outcome.cli == "codex" and fake.calls[0]["argv"][:2] == ["codex", "exec"]
    assert "resume" not in fake.calls[0]["argv"][:3]


def test_a_refusal_wins_over_an_in_review_ticket_but_keeps_the_result(team):
    ticket = ticket_for(team)
    denials = [{"tool_name": "Bash", "tool_input": {"command": "git push"}}]
    fake = FakeCLI(team, Execution(0, claude_json(denials=denials), ""), act=lambda t: set_result(t, "Partial work", "cfo"))
    run_ticket(team, ticket.id, run=fake, which=found)
    loaded = load_ticket(ticket.path)
    assert loaded.status == "blocked" and loaded.result == "Partial work"
    assert "Needs your OK: Bash: git push" in loaded.thread[-1]


def test_codex_refusal_quotes_the_command_line():
    stderr = "noise\nexec_command failed: rm -rf x: " + APPROVAL_SIGNAL + "\nmore"
    assert "rm -rf x" in parse_codex("", stderr)[2][0]


def test_notifications_match_the_requester_by_key(team):
    ticket = new_ticket(team, title="Q", assignee="cfo", request="x", requested_by="Bron")
    record(team, ticket)
    assert [u["id"] for u in take(team, "bron", "bron")] == ["T-0001"]


def test_background_cli_refuses_finished_tickets_and_reports_failures(team, monkeypatch, capsys):
    monkeypatch.chdir(team.root)
    done = new_ticket(team, title="Old", assignee="cfo", request="x", requested_by="bron", status="done")
    started = []
    monkeypatch.setattr("bron.runner.start_background", lambda *a, **k: started.append(a) or 1)
    assert main(["run", done.id, "--background"]) == 0
    assert "nothing to run" in capsys.readouterr().out and started == []

    review = new_ticket(team, title="Rev", assignee="cfo", request="x", requested_by="bron", status="in-review")
    main(["run", review.id, "--background"])
    assert "waiting for review" in capsys.readouterr().out and started == []

    live = ticket_for(team)

    def fail(*a, **k):
        raise OSError("no such file")

    monkeypatch.setattr("bron.runner.start_background", fail)
    assert main(["run", live.id, "--background"]) == 1
    out = capsys.readouterr().out
    assert "Started" not in out and ".bron/bin/bron check" in out

    monkeypatch.setattr("bron.runner.start_background", lambda *a, **k: 7)
    assert main(["run", live.id, "--background"]) == 0
    assert "Started T-" in capsys.readouterr().out
    assert main(["run", "T-9999", "--background"]) == 1


# ---- final fix wave ----

from vaultkit import write_md


def asking_team(vault):
    write_md(vault.connections_dir / "Gmail.md", {"name": "Gmail", "type": "native", "claude": "claude_ai_Gmail", "codex": "gmail"})
    add_agent(vault, "CFO", runs_in="codex", connections=["Gmail"], ask_before=["send-email", "shell:curl"], always_allow=["mcp:gmail:forward_message"])
    set_meta(vault.agents_dir / "Bron" / "Agent.md", can_assign_to=["CFO"])
    return vault


def test_the_prompt_lists_the_agents_own_ask_before_actions(vault):
    team = asking_team(vault)
    ticket = ticket_for(team)
    fake = FakeCLI(team, Execution(0, codex_jsonl(), ""), act=lambda t: set_status(t, "blocked", "cfo", "Q?"))
    run_ticket(team, ticket.id, run=fake, which=found)
    prompt = fake.calls[0]["argv"][-1]
    line = next(ln for ln in prompt.splitlines() if ln.startswith("These actions need the user's OK"))
    assert "never do them yourself, mark the ticket blocked with 'Needs your OK: …' instead:" in line
    assert "shell `curl`" in line and "gmail/send_message" in line and "gmail/reply_to_message" in line
    assert "forward_message" not in line  # always allowed
    resume = FakeCLI(team, Execution(0, codex_jsonl(), ""), act=lambda t: set_result(t, "ok", "cfo"))
    run_ticket(team, ticket.id, resume=True, run=resume, which=found)
    assert "shell `curl`" in resume.calls[0]["argv"][-1]


def test_no_ask_before_line_without_ask_before_actions(team):
    ticket = ticket_for(team)
    fake = FakeCLI(team, Execution(0, claude_json(), ""), act=lambda t: set_result(t, "ok", "cfo"))
    run_ticket(team, ticket.id, run=fake, which=found)
    assert "These actions need the user's OK" not in fake.calls[0]["argv"][2]


def test_a_logged_out_claude_run_is_blocked_with_the_error(team):
    stdout = json.dumps({"is_error": True, "result": "Not logged in · Please run /login", "session_id": "s1"})
    ticket = ticket_for(team)
    run_ticket(team, ticket.id, run=FakeCLI(team, Execution(1, stdout, "")), which=found)
    loaded = load_ticket(ticket.path)
    assert loaded.status == "blocked" and loaded.result == ""
    assert "The run failed: Not logged in · Please run /login; see .bron/runs/" in loaded.thread[-1]


def test_an_erroring_claude_run_with_exit_zero_is_blocked(team):
    stdout = json.dumps({"is_error": True, "result": "API Error: overloaded\nmore detail", "session_id": "s1"})
    ticket = ticket_for(team)
    run_ticket(team, ticket.id, run=FakeCLI(team, Execution(0, stdout, "")), which=found)
    loaded = load_ticket(ticket.path)
    assert loaded.status == "blocked" and loaded.result == ""
    assert "The run failed: API Error: overloaded; see" in loaded.thread[-1]


def test_a_failed_codex_turn_is_blocked_even_after_a_partial_answer(team):
    events = [
        {"type": "thread.started", "thread_id": "th-1"},
        {"type": "item.completed", "item": {"id": "a", "type": "agent_message", "text": "Working on it"}},
        {"type": "turn.failed", "error": {"message": "rate limit"}},
    ]
    stdout = "\n".join(json.dumps(e) for e in events) + "\n"
    assert parse_codex(stdout, "")[3] == "rate limit"
    ticket = ticket_for(team, "pinned")
    run_ticket(team, ticket.id, run=FakeCLI(team, Execution(0, stdout, "")), which=found)
    loaded = load_ticket(ticket.path)
    assert loaded.status == "blocked" and loaded.result == ""
    assert "The run failed: rate limit; see .bron/runs/" in loaded.thread[-1]


def test_a_codex_error_followed_by_a_completed_turn_is_not_a_failure():
    events = [
        {"type": "thread.started", "thread_id": "th-1"},
        {"type": "error", "message": "Reconnecting... 1/5"},
        {"type": "item.completed", "item": {"id": "a", "type": "agent_message", "text": "42"}},
        {"type": "turn.completed"},
    ]
    assert parse_codex("\n".join(json.dumps(e) for e in events), "") == ("th-1", "42", [], "")
    assert parse_codex(json.dumps({"type": "error", "message": "stream closed"}), "")[3] == "stream closed"


# ---- faster handoffs ----

def test_the_prompt_carries_the_request_and_context_so_the_agent_needs_no_lookup(team):
    ticket = new_ticket(team, title="Q3 report", assignee="cfo", request="Draft it.", context="Fund III closed in May.", requested_by="bron")
    fake = FakeCLI(team, Execution(0, claude_json(), ""))
    run_ticket(team, ticket.id, caller_cli="claude", run=fake, which=found)
    prompt = fake.calls[0]["argv"][2]
    assert "Draft it." in prompt and "Fund III closed in May." in prompt
    assert "Read the ticket first" not in prompt
    assert "Your final reply becomes the ticket's Result" in prompt
    assert "don't look around the vault" in prompt


def test_a_final_reply_becomes_the_result_in_the_agents_own_name(team):
    ticket = ticket_for(team, "pinned")
    run_ticket(team, ticket.id, caller_cli="claude", run=FakeCLI(team, Execution(0, codex_jsonl(text="The answer is 42."), "")), which=found)
    loaded = load_ticket(ticket.path)
    assert loaded.status == "in-review" and loaded.result == "The answer is 42."
    assert any(e.endswith("pinned: status → in-review: result added") for e in loaded.thread)
    assert not any("didn't report" in e for e in loaded.thread)


def test_the_outcome_includes_the_result_for_whoever_is_waiting(team):
    ticket = ticket_for(team)
    outcome = run_ticket(team, ticket.id, caller_cli="claude", run=FakeCLI(team, Execution(0, claude_json(result="Q3 is drafted."), "")), which=found)
    assert outcome.message.startswith("T-0001 is now in-review (CFO)")
    assert "Result:\nQ3 is drafted." in outcome.message


def test_a_run_someone_waited_for_is_not_announced_again(team):
    shown = ticket_for(team)
    run_ticket(team, shown.id, caller_cli="claude", run=FakeCLI(team, Execution(0, claude_json(), "")), which=found, shown=True)
    assert take(team, "bron", "bron") == []
    unseen = ticket_for(team)
    run_ticket(team, unseen.id, caller_cli="claude", run=FakeCLI(team, Execution(0, claude_json(), "")), which=found)
    assert [u["id"] for u in take(team, "bron", "bron")] == [unseen.id]


def test_run_wait_and_ticket_new_run_wait_for_the_answer(team, monkeypatch, capsys):
    from bron.runner import RunOutcome

    monkeypatch.chdir(team.root)
    calls = []

    def fake_run(vault, tid, **kwargs):
        calls.append((tid, kwargs))
        return RunOutcome(tid, "in-review", "codex", f"{tid} is now in-review (CFO)\nResult:\nHello.")

    monkeypatch.setattr("bron.runner.run_ticket", fake_run)
    live = ticket_for(team)
    assert main(["run", live.id, "--wait", "--caller-cli", "claude"]) == 0
    assert calls[-1] == (live.id, {"caller_cli": "claude", "resume": False, "shown": True})
    assert "Result:\nHello." in capsys.readouterr().out

    code = main(["ticket", "new", "--to", "CFO", "--from", "Bron", "--title", "Hi", "--request", "Say hi.", "--run", "--caller-cli", "codex"])
    out = capsys.readouterr().out
    assert code == 0 and out.startswith("Created T-0002") and "Result:\nHello." in out
    assert calls[-1] == ("T-0002", {"caller_cli": "codex", "resume": False, "shown": True})

    assert main(["run", live.id]) == 0
    assert calls[-1][1]["shown"] is False


# ---- plan 2b: chats, shown runs, waiting ----

def chat_for(vault, assignee="cfo"):
    return new_ticket(
        vault, title="Chat with CFO", assignee=assignee, request="@cfo what's our cash?", context="User: hi",
        requested_by="bron", kind="chat", extra_meta={"chat_session": "claude:s1"},
    )


def test_a_chat_run_uses_the_chat_prompt_and_records_the_reply(team):
    ticket = chat_for(team)
    fake = FakeCLI(team, Execution(0, claude_json(result="Cash is $12M."), ""))
    outcome = run_ticket(team, ticket.id, caller_cli="claude", run=fake, which=found, shown=True)
    prompt = fake.calls[0]["argv"][2]
    assert "The user is talking to you directly" in prompt and "@cfo what's our cash?" in prompt and "User: hi" in prompt
    assert "Your final reply becomes the ticket's Result" not in prompt
    loaded = load_ticket(ticket.path)
    assert loaded.status == "in-review" and loaded.result == "Cash is $12M."
    assert loaded.thread[-1].endswith("cfo: Cash is $12M.")
    assert take(team, "bron", "bron") == []
    assert outcome.message.endswith("Result:\nCash is $12M.")


def test_a_chat_follow_up_resumes_with_the_users_new_message(team):
    ticket = chat_for(team)
    run_ticket(team, ticket.id, caller_cli="claude", run=FakeCLI(team, Execution(0, claude_json(session="s7", result="Cash is $12M."), "")), which=found, shown=True)
    with editing(team, ticket.id) as current:
        add_message(current, "you", "and next quarter?")
        current.status = "todo"
    fake = FakeCLI(team, Execution(0, claude_json(session="s7", result="About $10M."), ""))
    run_ticket(team, ticket.id, caller_cli="claude", resume=True, run=fake, which=found, shown=True)
    argv = fake.calls[0]["argv"]
    assert argv[argv.index("--resume") + 1] == "s7"
    assert "The user replied in the chat" in argv[2] and "you: and next quarter?" in argv[2]
    assert load_ticket(ticket.path).result == "About $10M."


def test_a_chat_without_a_saved_session_repeats_the_later_messages(team):
    ticket = chat_for(team)
    with editing(team, ticket.id) as current:
        add_message(current, "you", "and next quarter?")
    fake = FakeCLI(team, Execution(0, claude_json(), ""))
    run_ticket(team, ticket.id, caller_cli="claude", resume=True, run=fake, which=found)
    prompt = fake.calls[0]["argv"][2]
    assert "The user is talking to you directly" in prompt
    assert "Later messages:" in prompt and "you: and next quarter?" in prompt


def test_background_runs_record_their_update_normally(team):
    seen = {}

    def popen(argv, **kwargs):
        seen["argv"] = argv
        return type("P", (), {"pid": 5})()

    start_background(team, "T-0001", caller_cli="codex", resume=True, popen=popen)
    assert seen["argv"][2:] == ["T-0001", "--caller-cli", "codex", "--resume"]


def test_wait_prints_each_reply_once_the_run_is_done(team):
    from bron.runner import wait_for

    done = ticket_for(team)
    with editing(team, done.id) as current:
        set_result(current, "Q3 drafted.", "cfo")
    stuck = ticket_for(team, "pinned")
    with editing(team, stuck.id) as current:
        set_status(current, "blocked", "pinned", "Needs your OK: send the email to LPs")
    assert wait_for(team, [done.id, stuck.id], sleep=lambda s: None) == [
        "CFO: Q3 drafted.",
        f"{stuck.id} is blocked (Pinned): Needs your OK: send the email to LPs",
    ]


def test_wait_keeps_waiting_while_the_run_holds_its_lock(team):
    from bron.locks import release
    from bron.runner import wait_for

    ticket = ticket_for(team)
    assert acquire(team, ticket.id, "run1", max_minutes=30)
    ticks = []

    def sleep(_):
        ticks.append(1)
        if len(ticks) == 3:
            with editing(team, ticket.id) as current:
                set_result(current, "Done now.", "cfo")
            release(team, ticket.id, "run1")

    assert wait_for(team, [ticket.id], sleep=sleep) == ["CFO: Done now."]
    assert len(ticks) == 3


def clock(step=5):
    values = iter(range(0, 100_000, step))
    return lambda: next(values)


def test_wait_gives_up_on_a_run_that_never_started_or_stopped_midway(team):
    from bron.runner import wait_for

    never = ticket_for(team)
    assert wait_for(team, [never.id], sleep=lambda s: None, now=clock()) == [f"{never.id} hasn't started; see .bron/runs/background-{never.id}.log"]
    midway = ticket_for(team)
    with editing(team, midway.id) as current:
        current.status = "in-progress"
    assert wait_for(team, [midway.id], sleep=lambda s: None, now=clock()) == [f"{midway.id} stopped before it finished; see .bron/runs/"]


def test_wait_stops_waiting_after_the_time_limit(team):
    from bron.runner import wait_for

    ticket = ticket_for(team)
    assert acquire(team, ticket.id, "run1", max_minutes=30)
    assert wait_for(team, [ticket.id], sleep=lambda s: None, now=clock(step=10_000)) == [
        f"{ticket.id} is still running after 30 minutes; check it later with `.bron/bin/bron ticket show {ticket.id}`."
    ]


def test_ticket_wait_command(team, monkeypatch, capsys):
    monkeypatch.chdir(team.root)
    ticket = ticket_for(team)
    with editing(team, ticket.id) as current:
        set_result(current, "Q3 drafted.", "cfo")
    assert main(["ticket", "wait", ticket.id]) == 0
    assert capsys.readouterr().out == "CFO: Q3 drafted.\n"
    assert main(["ticket", "wait", "T-9999"]) == 0
    assert "There's no ticket T-9999" in capsys.readouterr().out


def test_wait_sees_a_run_that_finishes_between_the_two_reads(team, monkeypatch):
    from bron import runner
    from bron.locks import release

    ticket = ticket_for(team)
    with editing(team, ticket.id) as current:
        current.status = "in-progress"
    assert acquire(team, ticket.id, "run1", max_minutes=30)
    real = runner.read_lock
    calls = []

    def read_lock(vault, tid):
        calls.append(1)
        if len(calls) > 1:
            return real(vault, tid)
        with editing(team, tid) as current:
            set_result(current, "Done fine.", "cfo")
        release(team, tid, "run1")
        return None

    monkeypatch.setattr("bron.runner.read_lock", read_lock)
    assert runner.wait_for(team, [ticket.id], sleep=lambda s: None, now=clock()) == ["CFO: Done fine."]


def test_wait_measures_the_grace_period_for_each_ticket(team):
    from bron.locks import release
    from bron.runner import wait_for

    first, second = ticket_for(team), ticket_for(team)
    assert acquire(team, first.id, "run1", max_minutes=30)
    time_now = [0]
    state = {"second_waits": 0}

    def sleep(_):
        time_now[0] += 10
        if time_now[0] == 30:
            with editing(team, first.id) as current:
                set_result(current, "First done.", "cfo")
            release(team, first.id, "run1")
        elif time_now[0] > 30:
            state["second_waits"] += 1
            if state["second_waits"] == 1:
                assert acquire(team, second.id, "run2", max_minutes=30)
            elif state["second_waits"] == 3:
                with editing(team, second.id) as current:
                    set_result(current, "Second done.", "cfo")
                release(team, second.id, "run2")

    assert wait_for(team, [first.id, second.id], sleep=sleep, now=lambda: time_now[0]) == ["CFO: First done.", "CFO: Second done."]


# ---- final review: queued runs keep their lock, a printed reply is acknowledged ----

def test_a_queued_run_holds_a_waiting_lock_that_takes_no_slot(team):
    from bron.locks import active

    set_meta(team.settings_file, runner={"max_parallel": 1, "max_minutes": 30})
    acquire(team, "T-0099", "busy")
    ticket = ticket_for(team)
    seen = []

    def sleep(_):
        lock = read_lock(team, ticket.id)
        seen.append((lock is not None and lock.waiting, [held.ticket_id for held in active(team, 30)]))
        if len(seen) == 2:
            (team.bron_dir / "locks" / "T-0099.lock").unlink()

    during = []

    def act(current):
        during.append(read_lock(team, current.id).waiting)
        set_result(current, "ok", "cfo")

    assert run_ticket(team, ticket.id, run=FakeCLI(team, Execution(0, claude_json(), ""), act=act), which=found, sleep=sleep).status == "in-review"
    assert seen == [(True, ["T-0099"]), (True, ["T-0099"])]
    assert during == [False]  # running once it has a slot
    assert read_lock(team, ticket.id) is None


def test_a_queued_run_that_never_gets_a_slot_gives_its_lock_back(team):
    set_meta(team.settings_file, runner={"max_parallel": 1, "max_minutes": 30})
    acquire(team, "T-0099", "busy")
    ticket = ticket_for(team)
    outcome = run_ticket(team, ticket.id, run=FakeCLI(team, Execution(0, claude_json(), "")), which=found, sleep=lambda s: None, now=clock(step=600))
    assert "Too many tickets are running" in outcome.message
    assert read_lock(team, ticket.id) is None


def test_wait_keeps_waiting_for_a_run_queued_behind_full_slots(team):
    from bron.locks import release
    from bron.runner import wait_for

    ticket = ticket_for(team)
    assert acquire(team, ticket.id, "queued", max_minutes=30, waiting=True)
    ticks = []

    def sleep(_):
        ticks.append(1)
        if len(ticks) == 10:  # long past the 15-second grace period
            with editing(team, ticket.id) as current:
                set_result(current, "Done after the queue.", "cfo")
            release(team, ticket.id, "queued")

    assert wait_for(team, [ticket.id], sleep=sleep, now=clock()) == ["CFO: Done after the queue."]


def test_a_chat_reply_printed_by_wait_is_not_announced_again(team):
    from bron.runner import wait_for

    ticket = chat_for(team)
    run_ticket(team, ticket.id, caller_cli="claude", run=FakeCLI(team, Execution(0, claude_json(result="Cash is $12M."), "")), which=found)
    printed = []
    assert wait_for(team, [ticket.id], sleep=lambda s: None, show=printed.append) == ["CFO: Cash is $12M."]
    assert printed == ["CFO: Cash is $12M."]
    assert take(team, "bron", "bron") == []


def test_a_chat_reply_the_wait_gave_up_on_is_announced_in_the_next_message(team):
    from bron.locks import release
    from bron.runner import wait_for

    ticket = chat_for(team)
    assert acquire(team, ticket.id, "run1", max_minutes=30)
    assert "is still running" in wait_for(team, [ticket.id], sleep=lambda s: None, now=clock(step=10_000))[0]
    release(team, ticket.id, "run1")
    run_ticket(team, ticket.id, caller_cli="claude", run=FakeCLI(team, Execution(0, claude_json(result="Cash is $12M."), "")), which=found)
    assert [u["id"] for u in take(team, "bron", "bron")] == [ticket.id]


def test_ticket_wait_prints_each_reply_as_soon_as_it_is_ready(team, monkeypatch, capsys):
    monkeypatch.chdir(team.root)
    first, second = ticket_for(team), ticket_for(team)
    for item in (first, second):
        with editing(team, item.id) as current:
            set_result(current, f"{item.id} drafted.", "cfo")
    assert main(["ticket", "wait", first.id, second.id]) == 0
    assert capsys.readouterr().out == f"CFO: {first.id} drafted.\n\nCFO: {second.id} drafted.\n"

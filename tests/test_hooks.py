import io
import json

import pytest

from bron.hooks import main as hook
from vaultkit import add_agent, set_meta


def call(event, cli="claude", payload=None, raw=None):
    out = io.StringIO()
    stdin = io.StringIO(raw if raw is not None else json.dumps(payload or {}))
    code = hook(event, cli, stdin=stdin, stdout=out)
    return code, out.getvalue()


@pytest.fixture
def in_vault(vault, monkeypatch):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    return vault


def test_session_start_syncs_and_briefs(in_vault):
    code, out = call("session-start")
    assert code == 0
    assert out.startswith("# Bron briefing\n")
    assert "You are Bron, working in Claude Code" in out
    assert "First-run setup isn't done yet" in out
    assert "Setup note for you (mention it only if the user asks about setup)" in out
    assert (in_vault.root / ".codex/config.toml").is_file()


def test_second_session_start_is_quiet_about_setup(in_vault):
    call("session-start")
    _, out = call("session-start")
    assert "Setup note for you" not in out


def test_briefing_uses_settings_and_memory_summary(in_vault):
    set_meta(in_vault.settings_file, user_name="Alex", company="Example Capital")
    (in_vault.memory_dir / "Summary.md").write_text("Fund III close is planned for November.\n", encoding="utf-8")
    _, out = call("session-start", "codex")
    assert "working in Codex" in out
    assert "You're working with Alex at Example Capital." in out
    assert "## What you remember" in out and "Fund III close" in out


def test_long_memory_is_clipped(in_vault):
    (in_vault.memory_dir / "Summary.md").write_text("x" * 20000, encoding="utf-8")
    _, out = call("session-start")
    assert len(out) <= 6000


def test_broken_setup_is_reported_without_failing(in_vault):
    call("session-start")
    add_agent(in_vault, "CFO", reports_to="Nobody")
    code, out = call("session-start")
    assert code == 0
    assert "couldn't apply recent setup changes" in out
    assert "Nobody" in out


def test_unexpected_error_still_exits_zero(in_vault, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("kaput")

    monkeypatch.setattr("bron.briefing.build_briefing", boom)
    code, out = call("session-start")
    assert code == 0 and "startup check failed" in out
    assert "RuntimeError: kaput" in (in_vault.state_dir / "hook-errors.log").read_text()


def test_quick_events_append_markers(in_vault, monkeypatch):
    monkeypatch.setenv("BRON_AGENT", "CFO")
    for event in ("pre-compact", "stop", "session-end"):
        assert call(event, "codex", {"session_id": "s1", "transcript_path": "/t.jsonl"}) == (0, "")
    lines = [json.loads(line) for line in (in_vault.state_dir / "markers.jsonl").read_text().splitlines()]
    assert [line["event"] for line in lines] == ["pre-compact", "stop", "session-end"]
    assert lines[0]["agent"] == "CFO" and lines[0]["cli"] == "codex"
    assert lines[0]["session_id"] == "s1" and lines[0]["transcript_path"] == "/t.jsonl"
    assert lines[0]["ticket"] == ""


def test_markers_record_the_ticket(in_vault, monkeypatch):
    monkeypatch.setenv("BRON_TICKET", "T-7")
    call("stop", "claude", {"session_id": "s9", "transcript_path": "/t.jsonl"})
    last = json.loads((in_vault.state_dir / "markers.jsonl").read_text().splitlines()[-1])
    assert last["ticket"] == "T-7"


def test_user_prompt_is_silent_for_now(in_vault):
    assert call("user-prompt", payload={"prompt": "@cfo hello"}) == (0, "")


def test_garbage_input_is_ignored(in_vault):
    assert call("stop", raw="not json") == (0, "")
    assert call("stop", raw="") == (0, "")


def test_outside_a_vault_never_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("BRON_VAULT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert call("stop")[0] == 0
    code, out = call("session-start")
    assert code == 0 and "startup check failed" in out


def test_session_start_does_not_read_stdin(in_vault):
    class AssertingStdin:
        def isatty(self):
            return False

        def read(self):
            raise AssertionError("read called")

    out = io.StringIO()
    code = hook("session-start", "claude", stdin=AssertingStdin(), stdout=out)
    assert code == 0
    output = out.getvalue()
    assert output.startswith("# Bron briefing\n")
    assert "startup check failed" not in output


def test_sync_crash_still_gives_the_briefing(in_vault, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("sync kaput")

    monkeypatch.setattr("bron.sync.run_sync", boom)
    code, out = call("session-start")
    assert code == 0
    assert out.startswith("# Bron briefing\n")
    assert "couldn't check the setup" in out
    assert "RuntimeError: sync kaput" in (in_vault.state_dir / "hook-errors.log").read_text()


def test_session_start_reports_a_backup_of_hand_edits(in_vault):
    call("session-start")
    (in_vault.root / ".claude/settings.json").write_text('{"mine": true}\n', encoding="utf-8")
    _, out = call("session-start")
    assert "# Bron briefing\n" in out
    assert "the edited copy is in .bron/backups/" in out
    backed_up = list(in_vault.backups_dir.glob("*/.claude/settings.json"))
    assert len(backed_up) == 1
    assert backed_up[0].read_text() == '{"mine": true}\n'


def test_user_prompt_drains_large_input(in_vault):
    assert call("user-prompt", payload={"prompt": "x" * 200_000}) == (0, "")


def test_user_prompt_reads_stdin(in_vault):
    class Stdin:
        read_called = False

        def isatty(self):
            return False

        def read(self):
            self.read_called = True
            return "{}"

    stdin = Stdin()
    assert hook("user-prompt", "claude", stdin=stdin, stdout=io.StringIO()) == 0
    assert stdin.read_called


SIGN_OFF = '- Always end your replies with "—Bron".\n'


def edit_bron(vault):
    path = vault.agents_dir / "Bron" / "Agent.md"
    path.write_text(path.read_text(encoding="utf-8") + SIGN_OFF, encoding="utf-8")


@pytest.mark.parametrize("cli", ["claude", "codex"])
def test_instruction_edit_takes_effect_in_the_same_session(in_vault, cli):
    # The CLI loads its instruction files before the startup trigger regenerates them,
    # so the briefing must carry the updated instructions itself.
    call("session-start", cli)
    edit_bron(in_vault)
    _, out = call("session-start", cli)
    assert "## Your updated instructions" in out
    assert "replace the instructions this session started with" in out
    assert "—Bron" in out
    assert "# You are Bron" in out
    _, again = call("session-start", cli)
    assert "## Your updated instructions" not in again


def test_unrelated_change_does_not_resend_instructions_but_flags_shared_rules(in_vault):
    call("session-start", "claude")
    add_agent(in_vault, "CFO")
    _, out = call("session-start", "claude")
    assert "## Your updated instructions" not in out
    assert "The shared rules in AGENTS.md changed" in out


def test_session_start_blocks_tickets_whose_run_stopped(in_vault):
    from bron.locks import acquire
    from bron.tickets import load_ticket, new_ticket

    add_agent(in_vault, "CFO")
    orphan = new_ticket(in_vault, title="No lock", assignee="cfo", request="x", requested_by="bron", status="in-progress")
    dead = new_ticket(in_vault, title="Dead run", assignee="cfo", request="x", requested_by="bron", status="in-progress")
    acquire(in_vault, dead.id, "gone", pid=999_999)
    alive = new_ticket(in_vault, title="Running", assignee="cfo", request="x", requested_by="bron", status="in-progress")
    acquire(in_vault, alive.id, "live")  # this test process: still running
    waiting = new_ticket(in_vault, title="Todo", assignee="cfo", request="x", requested_by="bron")
    code, out = call("session-start")
    assert code == 0 and out.startswith("# Bron briefing\n")
    note = "The run stopped before it finished (Bron or the Mac was closed); see .bron/runs/"
    for ticket in (orphan, dead):
        loaded = load_ticket(ticket.path)
        assert loaded.status == "blocked" and note in loaded.thread[-1]
    assert load_ticket(alive.path).status == "in-progress"
    assert load_ticket(waiting.path).status == "todo"
    updates = (in_vault.state_dir / "notifications.jsonl").read_text()
    assert orphan.id in updates and dead.id in updates and alive.id not in updates


def test_a_failing_orphan_check_never_breaks_the_briefing(in_vault, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk")

    monkeypatch.setattr("bron.runner.list_tickets", boom)
    code, out = call("session-start")
    assert code == 0 and out.startswith("# Bron briefing\n")


def test_first_run_asks_for_name_and_saves_it_without_a_second_yes(in_vault):
    _, out = call("session-start")
    assert "bron settings set --name" in out
    assert "no separate yes" in out

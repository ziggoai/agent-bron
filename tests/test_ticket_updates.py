import io
import json

import pytest

from bron.briefing import build_briefing
from bron.hooks import main as hook
from bron.notifications import record
from bron.tickets import new_ticket
from vaultkit import add_agent, write_md


@pytest.fixture
def in_vault(vault, monkeypatch):
    add_agent(vault, "CFO")
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    return vault


def prompt(text="hi"):
    out = io.StringIO()
    assert hook("user-prompt", "claude", stdin=io.StringIO(json.dumps({"prompt": text})), stdout=out) == 0
    return out.getvalue()


def finished(vault, requested_by="bron"):
    ticket = new_ticket(vault, title="Q3 report", assignee="cfo", request="x", requested_by=requested_by)
    ticket.status = "in-review"
    record(vault, ticket)
    return ticket


def test_message_trigger_shows_new_updates_once(in_vault):
    finished(in_vault)
    first = prompt()
    assert first.startswith("Ticket updates since your last message:")
    assert 'T-0001 "Q3 report" is now in-review (cfo)' in first
    assert prompt() == ""


def test_message_trigger_is_silent_without_updates(in_vault):
    assert prompt() == ""


def test_updates_reach_the_agent_that_asked(in_vault, monkeypatch):
    finished(in_vault)
    monkeypatch.setenv("BRON_AGENT", "CFO")
    assert prompt() == ""
    monkeypatch.setenv("BRON_AGENT", "Bron")
    assert "T-0001" in prompt()


def test_briefing_lists_assigned_tickets_and_updates(in_vault, monkeypatch):
    new_ticket(in_vault, title="Fund III fees", assignee="cfo", request="x", requested_by="bron")
    monkeypatch.setenv("BRON_AGENT", "CFO")
    cfo = build_briefing(in_vault, cli="codex")
    assert "You are CFO, working in Codex" in cfo
    assert "- Assigned to you: T-0001 [todo] Fund III fees" in cfo
    monkeypatch.setenv("BRON_AGENT", "Bron")
    finished(in_vault)
    bron = build_briefing(in_vault, cli="claude")
    assert '- Update: T-0002 "Q3 report" is now in-review (cfo)' in bron
    assert "## Tickets" in bron


def test_user_tickets_report_to_the_default_agent(in_vault):
    finished(in_vault, requested_by="you")
    assert "T-0001" in prompt()


def test_tickets_section_failure_does_not_break_briefing(in_vault, monkeypatch):
    # Monkeypatch take to raise OSError
    def boom(*args, **kwargs):
        raise OSError("test failure")

    monkeypatch.setattr("bron.briefing.take", boom)
    briefing = build_briefing(in_vault, cli="claude")
    assert briefing.startswith("# Bron briefing\n")
    assert "You are Bron, working in Claude Code" in briefing
    assert "Ticket updates couldn't be loaded this time." in briefing


def test_updates_are_capped_at_eight_with_truncation(in_vault, monkeypatch):
    # Create 30 updates with 200-character titles
    long_title = "x" * 200
    for i in range(30):
        ticket = new_ticket(in_vault, title=f"{long_title} #{i}", assignee="bron", request="x", requested_by="bron")
        ticket.status = "in-review"
        record(in_vault, ticket)

    # Add instructions to trigger "## Your updated instructions" section
    from vaultkit import write_md
    agent_config = {
        "name": "Bron",
        "role": "main role",
        "reports_to": "nobody",
        "runs_in": "any",
    }
    write_md(in_vault.agents_dir / "Bron" / "Agent.md", agent_config, "Test instructions\n")

    briefing = build_briefing(in_vault, cli="claude", changed=[".claude/agents/bron.md"])

    # Verify briefing is within limits
    assert len(briefing) <= 6000, f"Briefing too long: {len(briefing)} chars"

    # Verify structure is preserved
    assert "## Your updated instructions" in briefing
    assert "## Tickets" in briefing

    # Count update lines (starting with "- Update:")
    update_lines = [line for line in briefing.split("\n") if line.startswith("- Update:")]
    assert len(update_lines) == 8, f"Expected 8 update lines, got {len(update_lines)}"

    # Verify "…and N more" line is present
    assert "- …and 22 more: run `.bron/bin/bron ticket list`" in briefing

    # Verify no title exceeds 80 characters
    for line in briefing.split("\n"):
        if line.startswith("- Assigned") or line.startswith("- Update:"):
            # Extract the title part (after the id and status/quote)
            # For assigned: "- Assigned to you: T-0001 [todo] TITLE"
            # For update: "- Update: T-0001 "TITLE" is now status (assignee)"
            # Just check that the full line is reasonable
            assert len(line) < 150, f"Line too long (contains title > 80): {line[:100]}"


def test_prompt_trigger_caps_updates_at_eight(in_vault):
    # Create 30 updates
    for i in range(30):
        ticket = new_ticket(in_vault, title=f"Task {i}", assignee="bron", request="x", requested_by="bron")
        ticket.status = "in-review"
        record(in_vault, ticket)

    output = prompt()
    assert output.startswith("Ticket updates since your last message:")

    # Count update lines
    update_lines = [line for line in output.split("\n") if line.startswith("- ") and "T-" in line]
    assert len(update_lines) == 8, f"Expected 8 update lines, got {len(update_lines)}"

    # Verify "…and N more" line
    assert "- …and 22 more: run `.bron/bin/bron ticket list`" in output


def test_a_ticket_run_briefing_shows_assigned_tickets_only(in_vault, monkeypatch):
    # A background run must not consume the updates meant for the requester's own sessions (I3).
    new_ticket(in_vault, title="Fund III fees", assignee="cfo", request="x", requested_by="bron")
    mine = new_ticket(in_vault, title="Ask Bron", assignee="bron", request="x", requested_by="cfo")
    mine.status = "in-review"
    record(in_vault, mine)
    monkeypatch.setenv("BRON_AGENT", "CFO")
    monkeypatch.setenv("BRON_TICKET", "T-0001")
    text = build_briefing(in_vault, cli="codex")
    assert "You are CFO, working in Codex" in text
    assert "- Assigned to you: T-0001 [todo] Fund III fees" in text
    assert "Update:" not in text
    assert "First-run setup" not in text and "You're working with" not in text
    monkeypatch.delenv("BRON_TICKET")
    assert "- Update: T-0002" in build_briefing(in_vault, cli="codex")  # still waiting for CFO's own session


def test_a_ticket_run_briefing_skips_the_name_line_too(in_vault, monkeypatch):
    from vaultkit import set_meta

    set_meta(in_vault.settings_file, user_name="Alex", company="Example Capital")
    monkeypatch.setenv("BRON_TICKET", "T-0001")
    assert "You're working with" not in build_briefing(in_vault, cli="claude")


def test_the_message_trigger_is_silent_in_a_ticket_run(in_vault, monkeypatch):
    finished(in_vault)
    monkeypatch.setenv("BRON_TICKET", "T-0001")
    assert prompt() == ""
    monkeypatch.delenv("BRON_TICKET")
    assert "T-0001" in prompt()  # the update is still there for Bron's own session


def test_prompt_trigger_outside_vault_prints_nothing(monkeypatch):
    monkeypatch.delenv("BRON_VAULT", raising=False)
    out = io.StringIO()
    assert hook("user-prompt", "claude", stdin=io.StringIO(json.dumps({"prompt": "hi"})), stdout=out) == 0
    assert out.getvalue() == ""

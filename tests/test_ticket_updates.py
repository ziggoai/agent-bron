import io
import json

import pytest

from bron.briefing import build_briefing
from bron.hooks import main as hook
from bron.notifications import record
from bron.tickets import new_ticket
from vaultkit import add_agent


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

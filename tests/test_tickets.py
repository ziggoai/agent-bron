import pytest

from bron.cli import main
from bron.tickets import (
    TicketError,
    add_message,
    find_ticket,
    list_tickets,
    load_ticket,
    new_ticket,
    normalize_id,
    save_ticket,
    set_result,
    set_status,
)
from vaultkit import add_agent, set_meta


def make(vault, **overrides):
    data = {"title": "Prepare Q3 LP report", "assignee": "cfo", "request": "Draft the Q3 report.", "requested_by": "bron"}
    data.update(overrides)
    return new_ticket(vault, **data)


def test_normalize_id():
    assert normalize_id("42") == "T-0042"
    assert normalize_id("t-7") == "T-0007"
    assert normalize_id("T-12345") == "T-12345"
    with pytest.raises(TicketError, match="isn't a ticket id"):
        normalize_id("Q3 report")


def test_new_ticket_file_name_sections_and_first_thread_entry(vault):
    ticket = make(vault, context="Use the 30 Sep NAV.")
    assert ticket.id == "T-0001"
    assert ticket.path == vault.tickets_dir / "T-0001 Prepare Q3 LP report.md"
    text = ticket.path.read_text(encoding="utf-8")
    assert text.index("## Request") < text.index("## Context") < text.index("## Thread") < text.index("## Result")
    loaded = load_ticket(ticket.path)
    assert (loaded.status, loaded.kind, loaded.assignee, loaded.requested_by) == ("todo", "task", "cfo", "bron")
    assert loaded.request == "Draft the Q3 report." and loaded.context == "Use the 30 Sep NAV."
    assert loaded.thread[0].endswith("· bron: created for cfo")


def test_ids_are_sequential_and_survive_a_lost_counter(vault):
    assert make(vault).id == "T-0001"
    assert make(vault, title="Second").id == "T-0002"
    (vault.state_dir / "tickets.json").unlink()
    assert make(vault, title="Third").id == "T-0003"


def test_titles_are_made_safe_for_file_names(vault):
    ticket = make(vault, title='Fund I/II: "capital call" #3?')
    assert ticket.path.name == "T-0001 Fund I-II- -capital call- -3-.md"
    assert load_ticket(ticket.path).title == 'Fund I/II: "capital call" #3?'


def test_find_accepts_short_ids_and_explains_missing(vault):
    make(vault)
    assert find_ticket(vault, "1").name.startswith("T-0001 ")
    with pytest.raises(TicketError, match="There's no ticket T-0009"):
        find_ticket(vault, "9")


def test_thread_messages_status_and_result(vault):
    ticket = make(vault)
    add_message(ticket, "cfo", "Question:\nNAV as of 30 Sep or 15 Oct?")
    set_status(ticket, "blocked", "cfo", "waiting for the NAV date")
    save_ticket(ticket)
    loaded = load_ticket(ticket.path)
    assert loaded.status == "blocked"
    assert "cfo: Question:\n  NAV as of 30 Sep or 15 Oct?" in loaded.thread[1]
    assert loaded.thread[2].endswith("cfo: status → blocked: waiting for the NAV date")
    set_result(loaded, "Draft saved to Projects/Q3/draft.md", "cfo")
    save_ticket(loaded)
    again = load_ticket(ticket.path)
    assert again.status == "in-review" and again.result == "Draft saved to Projects/Q3/draft.md"
    with pytest.raises(TicketError, match="isn't a ticket status"):
        set_status(again, "finished", "cfo")


def test_hand_edited_ticket_is_read_tolerantly(vault):
    ticket = make(vault)
    text = ticket.path.read_text(encoding="utf-8")
    text = text.replace("status: todo", "status: waiting").replace("## Context\n", "")
    text = text.replace("## Result", "I typed this without a bullet.\n\n## Result")
    ticket.path.write_text(text, encoding="utf-8")
    loaded = load_ticket(ticket.path)
    assert loaded.status == "todo"
    assert any("waiting" in p for p in loaded.problems)
    assert loaded.context == ""
    assert loaded.thread[-1] == "- I typed this without a bullet."


def test_broken_ticket_file_gives_a_plain_error(vault):
    ticket = make(vault)
    ticket.path.write_text("---\nid: [T-0001\n---\n", encoding="utf-8")
    with pytest.raises(TicketError, match="can't be read"):
        load_ticket(ticket.path)
    tickets, problems = list_tickets(vault)
    assert tickets == [] and any("T-0001" in p for p in problems)


@pytest.fixture
def team(vault, monkeypatch):
    add_agent(vault, "CFO")
    set_meta(vault.agents_dir / "Bron" / "Agent.md", can_assign_to=["CFO"])
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    return vault


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_new_say_status_result_list(team, capsys):
    code, out, _ = run(capsys, "ticket", "new", "--to", "CFO", "--from", "bron", "--title", "Q3 report", "--request", "Draft it.")
    assert code == 0 and out.startswith("Created T-0001: Tickets/T-0001 Q3 report.md")
    assert run(capsys, "ticket", "say", "T-0001", "Use 30 Sep.", "--as", "bron")[0] == 0
    assert run(capsys, "ticket", "status", "1", "blocked", "--as", "cfo", "--note", "Needs your OK: send email to LPs")[0] == 0
    code, out, _ = run(capsys, "ticket", "result", "1", "--as", "cfo", "--text", "Done.")
    assert code == 0 and "T-0001 is now in-review" in out
    code, out, _ = run(capsys, "ticket", "list", "--for", "cfo", "--open")
    assert "T-0001 [in-review] cfo — Q3 report" in out
    code, out, _ = run(capsys, "ticket", "show", "1")
    assert "Needs your OK: send email to LPs" in out


def test_cli_refuses_assignment_outside_can_assign_to(team, capsys):
    add_agent(team, "COO")
    code, _, err = run(capsys, "ticket", "new", "--to", "COO", "--from", "bron", "--title", "x", "--request", "y")
    assert code == 1 and "can't hand work to COO" in err


def test_cli_explains_unknown_agent(team, capsys):
    code, _, err = run(capsys, "ticket", "new", "--to", "Nobody", "--title", "x", "--request", "y")
    assert code == 1 and "There's no agent called 'Nobody'" in err

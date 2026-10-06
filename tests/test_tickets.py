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


def test_cli_status_note_from_a_file_or_stdin(team, capsys, tmp_path, monkeypatch):
    import io

    run(capsys, "ticket", "new", "--to", "CFO", "--from", "bron", "--title", "Q3", "--request", "x")
    note = tmp_path / "note.txt"
    note.write_text("Is it Fund III's or the LP's fee?\n", encoding="utf-8")
    assert run(capsys, "ticket", "status", "1", "blocked", "--as", "cfo", "--note-file", str(note))[0] == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("Needs your OK: send 'Q3' to LPs\n"))
    assert run(capsys, "ticket", "status", "1", "blocked", "--as", "cfo", "--note-file", "-")[0] == 0
    out = run(capsys, "ticket", "show", "1")[1]
    assert "status → blocked: Is it Fund III's or the LP's fee?" in out
    assert "status → blocked: Needs your OK: send 'Q3' to LPs" in out
    with pytest.raises(SystemExit):
        main(["ticket", "status", "1", "blocked", "--note", "a", "--note-file", str(note)])


def test_cli_refuses_assignment_outside_can_assign_to(team, capsys):
    add_agent(team, "COO")
    code, _, err = run(capsys, "ticket", "new", "--to", "COO", "--from", "bron", "--title", "x", "--request", "y")
    assert code == 1 and "can't hand work to COO" in err


def test_cli_explains_unknown_agent(team, capsys):
    code, _, err = run(capsys, "ticket", "new", "--to", "Nobody", "--title", "x", "--request", "y")
    assert code == 1 and "There's no agent called 'Nobody'" in err


def test_hand_edited_with_extra_meta_preamble_invalid_repeated_sections_raw_threads(vault):
    """Test that load→save preserves hand-edited content."""
    import textwrap
    ticket = make(vault)

    # Hand-edit the file with extra metadata, preamble, invalid status/priority, repeated sections, raw thread lines
    content = textwrap.dedent("""\
        ---
        id: T-0001
        title: Prepare Q3 LP report
        kind: task
        status: waiting
        priority: Important
        assignee: cfo
        requested_by: bron
        created: 2026-10-01T00:00
        tags: [lp, q3]
        cssclasses: wide
        ---

        This is a preamble line before the first section.

        ## Request
        Draft the Q3 report.

        ## Context
        Use the 30 Sep NAV.

        ## Context
        Also check Sep balance sheet.

        ## Thread
        - 2026-10-01 12:00 · bron: created for cfo
        ## Notes
        This is a custom section
        - 2026-10-01 13:00 · cfo: Looks good
        	This is a tab-indented continuation

        ## Result

    """)

    ticket.path.write_text(content, encoding="utf-8")
    loaded = load_ticket(ticket.path)

    # Verify extra_meta preserved
    assert loaded.extra_meta.get("tags") == ["lp", "q3"]
    assert loaded.extra_meta.get("cssclasses") == "wide"

    # Verify preamble preserved
    assert "preamble" in loaded.preamble or "This is a preamble" in loaded.preamble

    # Verify invalid status/priority preserved (defaults to todo/normal, but stored)
    assert loaded.status == "todo"  # Default due to invalid
    assert loaded.priority == "normal"  # Default due to invalid
    assert "waiting" in loaded.invalid.get("status", "")
    assert "Important" in loaded.invalid.get("priority", "")
    assert any("waiting" in p for p in loaded.problems)
    assert any("Important" in p for p in loaded.problems)

    # Verify repeated Context sections joined
    assert "Use the 30 Sep NAV" in loaded.context
    assert "Also check Sep balance sheet" in loaded.context

    # Verify raw thread lines preserved (## Notes without - prefix)
    assert any("## Notes" in entry for entry in loaded.thread)

    # Verify tab continuation preserved
    assert any("tab-indented" in entry for entry in loaded.thread)

    # Add a message and save
    add_message(loaded, "cfo", "Adding new message")
    save_ticket(loaded)

    # Load again and verify everything is still there
    again = load_ticket(ticket.path)
    assert again.extra_meta.get("tags") == ["lp", "q3"]
    assert again.extra_meta.get("cssclasses") == "wide"
    assert "preamble" in again.preamble or "This is a preamble" in again.preamble
    assert "Use the 30 Sep NAV" in again.context
    assert "Also check Sep balance sheet" in again.context
    assert any("## Notes" in entry for entry in again.thread)
    assert any("Adding new message" in entry for entry in again.thread)
    assert again.invalid.get("status") == "waiting"
    assert again.invalid.get("priority") == "Important"

    # After set_status, invalid status should be cleared
    set_status(again, "todo", "cfo", "Changed to todo")
    assert "status" not in again.invalid
    assert again.status == "todo"


def test_cli_say_status_result_print_problems_to_stderr(team, capsys):
    """Test that problems from hand-edited tickets are printed to stderr."""
    # Create and hand-edit a ticket with invalid status and priority
    code, out, _ = run(capsys, "ticket", "new", "--to", "CFO", "--from", "bron", "--title", "Q3", "--request", "draft")
    assert code == 0
    ticket_path = team.tickets_dir / "T-0001 Q3.md"

    # Hand-edit to have invalid status and priority
    text = ticket_path.read_text(encoding="utf-8")
    text = text.replace("status: todo", "status: invalid_status")
    text = text.replace("priority: normal", "priority: Critical")
    ticket_path.write_text(text, encoding="utf-8")

    # Run say and check problems printed to stderr
    code, out, err = run(capsys, "ticket", "say", "1", "test message", "--as", "bron")
    assert code == 0
    assert "! " in err and "invalid_status" in err
    assert "Critical" in err

    # Run status which fixes status in memory/file but problems list still shows old issue
    code, out, err = run(capsys, "ticket", "status", "1", "blocked", "--as", "cfo")
    assert code == 0
    # Both problems still appear because file wasn't fully fixed by say
    assert "! " in err and "Critical" in err

    # Run result - problems list still shows old issues
    code, out, err = run(capsys, "ticket", "result", "1", "--as", "cfo", "--text", "done")
    assert code == 0
    assert "! " in err and "Critical" in err


def test_concurrent_updates(vault):
    """Test that concurrent ticket updates don't lose messages."""
    import concurrent.futures

    ticket = make(vault)

    def update_ticket(i):
        from bron.tickets import editing
        with editing(vault, "1") as t:
            add_message(t, f"w{i}", "hi")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(update_ticket, i) for i in range(10)]
        for future in futures:
            future.result()

    # Load and verify all 10 messages are present
    loaded = load_ticket(ticket.path)
    # Original message + 10 new ones = 11 total
    assert len(loaded.thread) == 11
    for i in range(10):
        assert any(f"w{i}: hi" in entry for entry in loaded.thread)


def test_editing_leaves_no_lock_file_next_to_the_ticket(vault):
    from bron.tickets import editing

    ticket = make(vault)
    with editing(vault, "1") as t:
        add_message(t, "cfo", "on it")
    assert [p.name for p in ticket.path.parent.iterdir() if p.name.endswith(".lock")] == []


def test_clear_old_locks_removes_only_empty_ticket_locks(vault):
    from bron.tickets import clear_old_locks

    ticket = make(vault)
    old = ticket.path.with_name(ticket.path.name + ".lock")
    old.write_text("")
    kept = ticket.path.with_name("notes.md.lock")
    kept.write_text("the user's own text")
    assert clear_old_locks(vault) == 1
    assert not old.exists() and kept.exists()

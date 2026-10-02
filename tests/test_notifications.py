from bron.notifications import describe, record, take
from bron.tickets import new_ticket


def test_updates_go_to_the_requester_once(vault):
    ticket = new_ticket(vault, title="Q3", assignee="cfo", request="x", requested_by="bron")
    ticket.status = "in-review"
    record(vault, ticket)
    assert take(vault, "cfo", "bron") == []
    updates = take(vault, "bron", "bron")
    assert [u["id"] for u in updates] == ["T-0001"]
    assert describe(updates[0]) == 'T-0001 "Q3" is now in-review (cfo)'
    assert take(vault, "bron", "bron") == []


def test_tickets_the_user_created_are_reported_to_the_default_agent(vault):
    ticket = new_ticket(vault, title="Mine", assignee="cfo", request="x")
    record(vault, ticket)
    assert [u["id"] for u in take(vault, "bron", "bron")] == ["T-0001"]


def test_a_garbled_line_is_skipped(vault):
    vault.state_dir.mkdir(parents=True, exist_ok=True)
    (vault.state_dir / "notifications.jsonl").write_text("not json\n", encoding="utf-8")
    assert take(vault, "bron", "bron") == []

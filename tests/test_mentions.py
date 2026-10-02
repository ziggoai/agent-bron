import os
import time

import pytest

from bron.loader import load
from bron.mentions import chat_title, close_session_chats, close_stale_chats, start_chat, tagged_agents
from bron.tickets import editing, load_ticket, new_ticket
from vaultkit import add_agent


@pytest.fixture
def team(vault):
    add_agent(vault, "CFO")
    add_agent(vault, "COO")
    return vault


def names(text, vault, self_key="bron"):
    return [a.name for a in tagged_agents(text, load(vault).agents, self_key)]


def chat(vault, message="@cfo what's our cash?", session="claude:s1", agent="cfo"):
    return start_chat(vault, agent=load(vault).agents[agent], requester="bron", session=session, message=message, context="User: hi")


def set_state(vault, ticket_id, status):
    with editing(vault, ticket_id) as current:
        current.status = status


def test_tags_are_found_case_insensitively_once_each(team):
    assert names("@CFO and @coo, then @cfo again", team) == ["CFO", "COO"]
    assert names("(@cfo) please", team) == ["CFO"]


def test_emails_urls_unknown_names_and_self_tags_are_not_tags(team):
    assert names("mail someone@example.com or see x.com/@cfo", team) == []
    assert names("@nobody @bron hi", team) == []
    assert names("@cfo hi", team, self_key="cfo") == []


def test_a_first_message_creates_a_chat_ticket(team):
    ticket, follow_up = chat(team)
    assert follow_up is False
    loaded = load_ticket(ticket.path)
    assert loaded.kind == "chat" and loaded.assignee == "cfo" and loaded.requested_by == "bron" and loaded.status == "todo"
    assert loaded.request == "@cfo what's our cash?" and loaded.context == "User: hi"
    assert loaded.extra_meta["chat_session"] == "claude:s1"
    assert loaded.title == "Chat with CFO: @cfo what's our cash?"


def test_a_follow_up_in_the_same_session_continues_the_chat(team):
    first, _ = chat(team)
    set_state(team, first.id, "in-review")
    again, follow_up = chat(team, message="and next quarter?")
    assert follow_up is True and again.id == first.id
    loaded = load_ticket(first.path)
    assert loaded.status == "todo"
    assert loaded.thread[-1].endswith("you: and next quarter?")


def test_a_chat_closed_by_a_session_end_continues_when_the_same_session_returns(team):
    first, _ = chat(team)
    set_state(team, first.id, "in-review")
    close_session_chats(team, "claude:s1")
    again, follow_up = chat(team, message="and next quarter?")
    assert follow_up is True and again.id == first.id
    loaded = load_ticket(first.path)
    assert loaded.status == "todo" and loaded.thread[-1].endswith("you: and next quarter?")


def test_a_running_chat_or_another_sessions_chat_is_not_continued(team):
    first, _ = chat(team)
    set_state(team, first.id, "in-progress")
    busy, follow_up = chat(team, message="and next quarter?")
    assert follow_up is False and busy.id != first.id
    set_state(team, busy.id, "in-review")
    other, follow_up = chat(team, session="claude:s2")
    assert follow_up is False and other.id not in (first.id, busy.id)
    nameless, follow_up = chat(team, session="")
    assert follow_up is False and "chat_session" not in load_ticket(nameless.path).extra_meta


def test_long_titles_are_cut(team):
    title = chat_title(load(team).agents["cfo"], "word " * 40)
    assert len(title) <= 60 and title.endswith("…")


def test_session_end_closes_only_that_sessions_answered_chats(team):
    answered, _ = chat(team)
    set_state(team, answered.id, "in-review")
    waiting, _ = chat(team, agent="coo")  # todo: its run is about to start
    elsewhere, _ = chat(team, session="claude:s2")
    set_state(team, elsewhere.id, "in-review")
    assert close_session_chats(team, "claude:s1") == [answered.id]
    assert load_ticket(answered.path).status == "done"
    assert load_ticket(waiting.path).status == "todo"
    assert load_ticket(elsewhere.path).status == "in-review"
    assert close_session_chats(team, "") == []


def test_chats_untouched_for_12_hours_are_closed(team):
    old, _ = chat(team)
    set_state(team, old.id, "in-review")
    fresh, _ = chat(team, session="claude:s2")
    set_state(team, fresh.id, "in-review")
    task = new_ticket(team, title="Q3", assignee="cfo", request="x", requested_by="bron", status="in-review")
    long_ago = time.time() - 13 * 3600
    for path in (old.path, task.path):
        os.utime(path, (long_ago, long_ago))
    assert close_stale_chats(team) == [old.id]
    assert load_ticket(old.path).status == "done"
    assert load_ticket(fresh.path).status == "in-review" and load_ticket(task.path).status == "in-review"


def test_follow_up_with_chat_started_between_find_and_edit(team, monkeypatch):
    first, _ = chat(team)
    set_state(team, first.id, "in-review")
    # Snapshot: the chat is in-review
    stale_snapshot = load_ticket(first.path)
    # Now move the file's status to in-progress (simulating a run starting)
    set_state(team, first.id, "in-progress")
    # Save the running file's bytes
    running_bytes = first.path.read_bytes()
    # Monkeypatch open_chat to return the stale snapshot
    monkeypatch.setattr("bron.mentions.open_chat", lambda vault, session, agent_key: stale_snapshot)
    # Try to follow up: should create a new ticket, not continue the running one
    follow_up_ticket, follow_up = chat(team, message="and next quarter?")
    assert follow_up is False
    assert follow_up_ticket.id != first.id
    # The running ticket's file should be completely unchanged
    assert first.path.read_bytes() == running_bytes
    assert load_ticket(first.path).status == "in-progress"


def test_follow_up_with_deleted_ticket_file(team):
    first, _ = chat(team)
    set_state(team, first.id, "in-review")
    # Delete the ticket file
    first.path.unlink()
    # Try to follow up: should create a new ticket, not raise an exception
    follow_up_ticket, follow_up = chat(team, message="and next quarter?")
    assert follow_up is False
    assert follow_up_ticket.id not in ("", None)  # A new ticket was created
    # Verify the new ticket can be loaded
    loaded = load_ticket(follow_up_ticket.path)
    assert loaded.kind == "chat" and loaded.status == "todo"

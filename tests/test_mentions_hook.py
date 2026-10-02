import io
import json
import os
import time

import pytest

from bron.hooks import main as hook
from bron.notifications import record
from bron.tickets import editing, find_ticket, load_ticket, new_ticket
from vaultkit import add_agent


@pytest.fixture
def team(vault, monkeypatch):
    add_agent(vault, "CFO", runs_in="codex")
    add_agent(vault, "COO")
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    started = []
    monkeypatch.setattr("bron.runner.start_background", lambda vault, tid, **kw: started.append((tid, kw)) or 1)
    return vault, started


def send(payload, cli="claude"):
    out = io.StringIO()
    assert hook("user-prompt", cli, stdin=io.StringIO(json.dumps(payload)), stdout=out) == 0
    return out.getvalue()


def end(session_id, cli="claude"):
    assert hook("session-end", cli, stdin=io.StringIO(json.dumps({"session_id": session_id})), stdout=io.StringIO()) == 0


def ticket(vault, tid):
    return load_ticket(find_ticket(vault, tid))


def transcript(tmp_path):
    path = tmp_path / "t.jsonl"
    entries = [
        {"type": "user", "message": {"role": "user", "content": "How is Fund I doing?"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Fund I is up 3%."}]}},
    ]
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


def test_a_tag_starts_the_agent_at_once_and_tells_the_session_to_wait(team, tmp_path):
    vault, started = team
    out = send({"prompt": "@cfo what's our cash?", "session_id": "s1", "transcript_path": str(transcript(tmp_path))})
    assert started == [("T-0001", {"caller_cli": "claude", "resume": False})]
    assert out.startswith("@CFO is answering this message (chat ticket T-0001). Don't answer it yourself.")
    assert "`.bron/bin/bron ticket wait T-0001`" in out and "**CFO:**" in out
    chat = ticket(vault, "T-0001")
    assert chat.kind == "chat" and chat.extra_meta["chat_session"] == "claude:s1"
    assert chat.context == "User: How is Fund I doing?\n\nBron: Fund I is up 3%."


def test_a_follow_up_resumes_the_same_chat(team):
    vault, started = team
    send({"prompt": "@cfo what's our cash?", "session_id": "s1"})
    with editing(vault, "T-0001") as current:
        current.status = "in-review"
    send({"prompt": "@cfo and next quarter?", "session_id": "s1"})
    assert started[-1] == ("T-0001", {"caller_cli": "claude", "resume": True})


def test_several_tags_start_one_chat_each(team):
    vault, started = team
    out = send({"prompt": "@cfo @coo thoughts?", "session_id": "s1"}, cli="codex")
    assert [tid for tid, _ in started] == ["T-0001", "T-0002"]
    assert all(kw["caller_cli"] == "codex" for _, kw in started)
    assert out.startswith("@CFO, @COO are answering this message (chat tickets T-0001 T-0002).")
    assert "ticket wait T-0001 T-0002" in out
    assert ticket(vault, "T-0001").extra_meta["chat_session"] == "codex:s1"


def test_no_routing_for_emails_yourself_or_inside_ticket_runs(team, monkeypatch):
    vault, started = team
    assert send({"prompt": "email someone@example.com please"}) == ""
    monkeypatch.setenv("BRON_AGENT", "CFO")
    assert send({"prompt": "@cfo hi"}) == ""
    monkeypatch.delenv("BRON_AGENT")
    monkeypatch.setenv("BRON_TICKET", "T-0009")
    assert send({"prompt": "@cfo hi"}) == ""
    assert started == []


def test_a_failed_start_is_reported_and_never_blocks_the_message(team, monkeypatch):
    vault, _ = team

    def boom(*args, **kwargs):
        raise OSError("bron is missing")

    monkeypatch.setattr("bron.runner.start_background", boom)
    out = send({"prompt": "@cfo hi", "session_id": "s1"})
    assert out == "Couldn't start @CFO (bron is missing); tell the user.\n"
    assert ticket(vault, "T-0001").status == "blocked"

    def crash(*args, **kwargs):
        raise RuntimeError("bad")

    monkeypatch.setattr("bron.mentions.route", crash)
    assert "Bron couldn't pass the @-mention on this time" in send({"prompt": "@cfo hi"})


def test_ticket_updates_still_show_after_routing(team):
    vault, _ = team
    done = new_ticket(vault, title="Q3 report", assignee="coo", request="x", requested_by="bron")
    done.status = "in-review"
    record(vault, done)
    out = send({"prompt": "@cfo hi", "session_id": "s1"})
    assert "@CFO is answering this message" in out and "Ticket updates since your last message:" in out


def test_session_end_closes_that_sessions_chats(team):
    vault, _ = team
    send({"prompt": "@cfo hi", "session_id": "s1"})
    with editing(vault, "T-0001") as current:
        current.status = "in-review"
    end("s1", cli="codex")
    assert ticket(vault, "T-0001").status == "in-review"
    end("s1")
    assert ticket(vault, "T-0001").status == "done"


def test_session_start_closes_stale_chats(team):
    vault, _ = team
    send({"prompt": "@cfo hi", "session_id": "s1"})
    path = find_ticket(vault, "T-0001")
    long_ago = time.time() - 13 * 3600
    os.utime(path, (long_ago, long_ago))
    assert hook("session-start", "claude", stdin=io.StringIO(""), stdout=io.StringIO()) == 0
    assert ticket(vault, "T-0001").status == "done"


# ---- final review: routing never breaks on odd input ----

def test_an_odd_codex_transcript_line_still_routes_without_history(team, tmp_path):
    vault, started = team
    path = tmp_path / "rollout.jsonl"
    path.write_text(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": 5}}) + "\n", encoding="utf-8")
    out = send({"prompt": "@coo hi", "session_id": "s1", "transcript_path": str(path)}, cli="codex")
    assert out.startswith("@COO is answering this message")
    assert ticket(vault, "T-0001").context == "(no earlier chat available)"


def test_a_transcript_that_blows_up_still_routes_without_history(team, monkeypatch):
    vault, started = team

    def boom(*args, **kwargs):
        raise RuntimeError("bad transcript")

    monkeypatch.setattr("bron.transcript.recent_exchanges", boom)
    out = send({"prompt": "@cfo hi", "session_id": "s1", "transcript_path": "/x"})
    assert out.startswith("@CFO is answering this message")
    assert ticket(vault, "T-0001").context == "(no earlier chat available)"


def test_one_agent_failing_never_drops_the_others(team, monkeypatch):
    vault, started = team
    from bron import mentions

    real = mentions.start_chat

    def flaky(vault, *, agent, **kwargs):
        if agent.key == "cfo":
            raise RuntimeError("odd ticket")
        return real(vault, agent=agent, **kwargs)

    monkeypatch.setattr("bron.mentions.start_chat", flaky)
    out = send({"prompt": "@cfo @coo thoughts?", "session_id": "s1"})
    assert "@COO is answering this message" in out
    assert "Couldn't pass the message to @CFO (odd ticket); tell the user." in out
    assert [tid for tid, _ in started] == ["T-0001"]

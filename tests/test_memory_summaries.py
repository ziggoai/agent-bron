import json
import os
import time
from pathlib import Path

import pytest

from bron.loader import load
from bron.memory import summaries
from bron.memory.summaries import SummaryError
from vaultkit import set_meta

REPLY = """TITLE: Q3 report fields
ASKED:
- Which fields go in the Q3 one-pager
DECIDED:
- Exclude written-off companies
OPEN:
- Nothing
"""


def claude_transcript(path: Path, exchanges: int = 2) -> Path:
    rows = []
    for i in range(exchanges):
        rows.append({"type": "user", "message": {"role": "user", "content": f"question {i}"}})
        rows.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": f"answer {i}"}]}})
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def mark(vault, event, session, transcript, *, cli="claude", agent="", ticket="", when="2026-10-03T09:15:00-0300"):
    vault.state_dir.mkdir(parents=True, exist_ok=True)
    with open(vault.state_dir / "markers.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"time": when, "event": event, "cli": cli, "agent": agent, "ticket": ticket,
                             "session_id": session, "transcript_path": str(transcript)}) + "\n")


class FakeModel:
    def __init__(self, reply=REPLY, fail=False):
        self.reply, self.fail, self.calls = reply, fail, []

    def __call__(self, cli, model, prompt, timeout=180):
        self.calls.append((cli, model, prompt))
        if self.fail:
            raise SummaryError("offline")
        return self.reply


def notes(vault, agent="Bron"):
    folder = vault.agents_dir / agent / "Memory" / "Conversations"
    return sorted(folder.rglob("*.md")) if folder.is_dir() else []


def test_session_end_writes_a_note(vault, tmp_path):
    t = claude_transcript(tmp_path / "s1.jsonl")
    mark(vault, "session-end", "s1", t)
    model = FakeModel()
    assert summaries.run(vault, session_id="s1", call=model) == 1
    [note] = notes(vault)
    assert note.parent.name == "2026-10" and note.name == "2026-10-03 09.15 Q3 report fields.md"
    text = note.read_text()
    assert "session_id: s1" in text and "cli: claude" in text and "## Decided\n- Exclude written-off companies" in text
    assert model.calls[0][1] == "haiku" and "question 0" in model.calls[0][2] and "answer 1" in model.calls[0][2]


def test_codex_uses_its_own_model(vault, tmp_path):
    t = tmp_path / "rollout.jsonl"
    rows = [
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hi"}]}},
    ]
    t.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    mark(vault, "session-end", "c1", t, cli="codex")
    model = FakeModel()
    summaries.run(vault, session_id="c1", call=model)
    assert model.calls[0][:2] == ("codex", "gpt-6-luna")


def test_note_goes_to_the_sessions_agent(vault, tmp_path):
    from vaultkit import add_agent

    add_agent(vault, "CFO")
    mark(vault, "session-end", "s2", claude_transcript(tmp_path / "s2.jsonl"), agent="cfo")
    summaries.run(vault, session_id="s2", call=FakeModel())
    assert notes(vault, "CFO") and not notes(vault, "Bron")


def test_skips_ticket_runs_and_empty_conversations(vault, tmp_path):
    mark(vault, "session-end", "t1", claude_transcript(tmp_path / "t1.jsonl"), ticket="T-7")
    empty = tmp_path / "e.jsonl"
    empty.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n")
    mark(vault, "session-end", "e1", empty)
    model = FakeModel()
    assert summaries.run(vault, pending=True, call=model) == 0
    assert model.calls == [] and notes(vault) == []


def test_resumed_conversation_updates_its_note(vault, tmp_path):
    t = claude_transcript(tmp_path / "s1.jsonl")
    mark(vault, "session-end", "s1", t)
    summaries.run(vault, session_id="s1", call=FakeModel())
    claude_transcript(t, exchanges=4)
    mark(vault, "session-end", "s1", t, when="2026-10-03T11:00:00-0300")
    summaries.run(vault, session_id="s1", call=FakeModel(REPLY.replace("Q3 report fields", "Q3 report and memo")))
    [note] = notes(vault)
    assert note.name == "2026-10-03 09.15 Q3 report and memo.md"


def test_unchanged_conversation_is_not_summarised_again(vault, tmp_path):
    t = claude_transcript(tmp_path / "s1.jsonl")
    mark(vault, "session-end", "s1", t)
    summaries.run(vault, session_id="s1", call=FakeModel())
    model = FakeModel()
    assert summaries.run(vault, pending=True, call=model) == 0 and model.calls == []


def test_catch_up_waits_for_quiet_conversations(vault, tmp_path):
    t = claude_transcript(tmp_path / "s3.jsonl")
    mark(vault, "stop", "s3", t)
    model = FakeModel()
    assert summaries.run(vault, pending=True, call=model, now=time.time()) == 0
    assert summaries.run(vault, pending=True, call=model, now=time.time() + 3600) == 1


def test_catch_up_is_capped_newest_first(vault, tmp_path):
    for i in range(8):
        mark(vault, "session-end", f"s{i}", claude_transcript(tmp_path / f"s{i}.jsonl"), when=f"2026-10-0{1 + i % 3}T09:1{i}:00-0300")
    assert summaries.run(vault, pending=True, call=FakeModel()) == summaries.CATCH_UP


def test_failures_retry_then_give_up(vault, tmp_path):
    mark(vault, "session-end", "s1", claude_transcript(tmp_path / "s1.jsonl"))
    for _ in range(summaries.MAX_ATTEMPTS):
        assert summaries.run(vault, pending=True, call=FakeModel(fail=True)) == 0
    model = FakeModel()
    assert summaries.run(vault, pending=True, call=model) == 0 and model.calls == []
    state = json.loads((vault.bron_dir / "memory" / "summaries.json").read_text())
    assert state["s1"]["status"] == "failed" and state["s1"]["attempts"] == summaries.MAX_ATTEMPTS


def test_bad_model_reply_is_a_failure(vault, tmp_path):
    mark(vault, "session-end", "s1", claude_transcript(tmp_path / "s1.jsonl"))
    assert summaries.run(vault, session_id="s1", call=FakeModel("I can't help with that")) == 0
    assert notes(vault) == []


def test_only_one_summarizer_runs(vault, tmp_path):
    from bron.statefile import locked

    mark(vault, "session-end", "s1", claude_transcript(tmp_path / "s1.jsonl"))
    model = FakeModel()
    with summaries._hold_lock(vault) as got:
        assert got
        assert summaries.run(vault, pending=True, call=model) == 0
    assert model.calls == []


def test_summaries_can_be_turned_off(vault, tmp_path):
    set_meta(vault.settings_file, memory={"summaries": False})
    mark(vault, "session-end", "s1", claude_transcript(tmp_path / "s1.jsonl"))
    model = FakeModel()
    assert summaries.run(vault, session_id="s1", call=model) == 0 and model.calls == []


def test_long_conversations_keep_the_start_and_the_end(vault, tmp_path):
    t = tmp_path / "long.jsonl"
    rows = [{"type": "user", "message": {"role": "user", "content": "FIRST " + "a" * 30000}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "b" * 90000 + " LAST"}]}}]
    t.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    mark(vault, "session-end", "s1", t)
    model = FakeModel()
    summaries.run(vault, session_id="s1", call=model)
    prompt = model.calls[0][2]
    assert "FIRST" in prompt and "LAST" in prompt and len(prompt) < 85000


@pytest.mark.parametrize("reply", ["", "TITLE:\nASKED:\n", "no structure at all"])
def test_parse_reply_rejects_unusable_answers(reply):
    with pytest.raises(SummaryError):
        summaries.parse_reply(reply)


def test_parse_reply_cleans_the_title():
    title, asked, decided, still_open = summaries.parse_reply(REPLY.replace("Q3 report fields", 'A/very: long "title" with far too many words in it'))
    assert "/" not in title and ":" not in title and '"' not in title and len(title.split()) <= 6


def test_call_model_builds_the_headless_commands(monkeypatch):
    seen = {}

    class Done:
        returncode, stdout, stderr = 0, REPLY, ""

    def fake_run(argv, **kw):
        seen["argv"], seen["cwd"], seen["env"], seen["input"] = argv, kw["cwd"], kw["env"], kw["input"]
        return Done()

    monkeypatch.setattr(summaries.subprocess, "run", fake_run)
    assert summaries.call_model("claude", "haiku", "PROMPT") == REPLY
    assert seen["argv"][:4] == ["claude", "-p", "--model", "haiku"] and "--no-session-persistence" in seen["argv"]
    assert seen["env"]["BRON_MEMORY_JOB"] == "1" and seen["input"] == "PROMPT"
    assert "BRON_VAULT" not in seen["env"]
    summaries.call_model("codex", "gpt-6-luna", "PROMPT")
    assert seen["argv"][:2] == ["codex", "exec"] and "--ephemeral" in seen["argv"] and seen["argv"][-1] == "-"


def test_call_model_failures_become_summary_errors(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(summaries.subprocess, "run", boom)
    with pytest.raises(SummaryError):
        summaries.call_model("claude", "haiku", "x")


def test_spawn_is_a_no_op_without_the_vault_command(vault):
    calls = []
    assert summaries.spawn(vault, pending=True, popen=lambda *a, **k: calls.append(a)) is False and calls == []


def test_spawn_starts_a_detached_summarizer(vault, monkeypatch):
    shim = vault.bron_command
    shim.parent.mkdir(parents=True, exist_ok=True)
    shim.write_text("#!/bin/sh\n")
    shim.chmod(0o755)
    calls = []
    assert summaries.spawn(vault, session_id="s1", popen=lambda argv, **kw: calls.append((argv, kw))) is True
    argv, kw = calls[0]
    assert argv[1:] == ["memory", "summarize", "--session", "s1"] and kw["start_new_session"] is True
    monkeypatch.setenv("BRON_TICKET", "T-1")
    assert summaries.spawn(vault, pending=True, popen=lambda *a, **k: calls.append(a)) is False

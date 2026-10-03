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


@pytest.fixture(autouse=True)
def _no_age_cutoff(monkeypatch):
    monkeypatch.setattr(summaries, "MAX_AGE_DAYS", 100000)  # fixed 2026 marker dates must not age out


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
    model = FakeModel()
    assert summaries.run(vault, pending=True, call=model) == summaries.CATCH_UP
    # sessions s0..s7 have times 2026-10-0{1+i%3}T09:1{i}; the 5 newest by marker time are chosen, newest first
    newest = [s.session_id for s in summaries.sessions(vault)][: summaries.CATCH_UP]
    state = json.loads((vault.bron_dir / "memory" / "summaries.json").read_text())
    assert set(state) == set(newest) and len(model.calls) == summaries.CATCH_UP


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
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")

    class Done:
        returncode, stdout, stderr = 0, REPLY, ""

    def fake_run(argv, **kw):
        seen["argv"], seen["cwd"], seen["env"], seen["input"] = argv, kw["cwd"], kw["env"], kw["input"]
        return Done()

    monkeypatch.setattr(summaries.subprocess, "run", fake_run)
    assert summaries.call_model("claude", "haiku", "PROMPT") == REPLY
    assert seen["argv"][:4] == ["claude", "-p", "--model", "haiku"] and "--no-session-persistence" in seen["argv"]
    assert "--strict-mcp-config" in seen["argv"] and "--disable-slash-commands" in seen["argv"]
    assert seen["env"]["BRON_MEMORY_JOB"] == "1" and seen["input"] == "PROMPT"
    assert "CLAUDECODE" not in seen["env"] and "CLAUDE_CODE_ENTRYPOINT" not in seen["env"]
    assert "BRON_VAULT" not in seen["env"]
    summaries.call_model("codex", "gpt-6-luna", "PROMPT")
    assert seen["argv"][:2] == ["codex", "exec"] and "--ephemeral" in seen["argv"] and seen["argv"][-1] == "-"
    for flag in ("--ignore-user-config", "shell_tool", "apps"):
        assert flag in seen["argv"]


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


def test_long_titles_are_capped(vault, tmp_path):
    mark(vault, "session-end", "s1", claude_transcript(tmp_path / "s1.jsonl"))
    long = " ".join(["w" * 60] * 6)
    summaries.run(vault, session_id="s1", call=FakeModel(REPLY.replace("Q3 report fields", long)))
    [note] = notes(vault)
    assert len(note.stem.split(" ", 2)[2]) <= 60


def test_a_failed_write_is_recorded_and_not_retried_forever(vault, tmp_path, monkeypatch):
    mark(vault, "session-end", "s1", claude_transcript(tmp_path / "s1.jsonl"))

    def boom(*a, **k):
        raise OSError("name too long")

    monkeypatch.setattr(summaries, "_write_note", boom)
    model = FakeModel()
    for _ in range(summaries.MAX_ATTEMPTS + 2):
        assert summaries.run(vault, pending=True, call=model) == 0
    assert len(model.calls) == summaries.MAX_ATTEMPTS
    state = json.loads((vault.bron_dir / "memory" / "summaries.json").read_text())
    assert state["s1"]["status"] == "failed"


def test_same_minute_same_title_keeps_both_notes(vault, tmp_path):
    mark(vault, "session-end", "a", claude_transcript(tmp_path / "a.jsonl"))
    mark(vault, "session-end", "b", claude_transcript(tmp_path / "b.jsonl"))
    summaries.run(vault, pending=True, call=FakeModel())
    assert [n.name for n in notes(vault)] == ["2026-10-03 09.15 Q3 report fields (2).md", "2026-10-03 09.15 Q3 report fields.md"]
    # a retitle of one never deletes the other
    t = claude_transcript(tmp_path / "a.jsonl", exchanges=4)
    mark(vault, "session-end", "a", t, when="2026-10-03T09:15:00-0300")
    summaries.run(vault, session_id="a", call=FakeModel(REPLY.replace("Q3 report fields", "Renamed")))
    names = [n.name for n in notes(vault)]
    assert len(names) == 2 and any("Renamed" in n for n in names)
    assert sum("Q3 report fields" in n for n in names) == 1


def test_bad_marker_lines_are_skipped(vault, tmp_path):
    vault.state_dir.mkdir(parents=True, exist_ok=True)
    (vault.state_dir / "markers.jsonl").write_bytes(b'\xff\xfe not json\n[1, 2]\n')
    mark(vault, "session-end", "s1", claude_transcript(tmp_path / "s1.jsonl"))
    assert summaries.run(vault, pending=True, call=FakeModel()) == 1


def test_unreadable_markers_never_raise(vault, monkeypatch):
    def boom(v):
        raise RuntimeError("bad")

    monkeypatch.setattr(summaries, "sessions", boom)
    assert summaries.run(vault, pending=True, call=FakeModel()) == 0


def test_sections_are_capped():
    many = "\n".join(f"- item {i}" for i in range(9))
    reply = f"TITLE: T\nASKED:\n{many}\nDECIDED:\n- {'x' * 300}\nOPEN:\n- Nothing\n"
    _, asked, decided, _ = summaries.parse_reply(reply)
    assert len(asked) == summaries.MAX_BULLETS
    assert len(decided[0]) == summaries.MAX_BULLET and decided[0].endswith("…")


def test_a_resumed_conversation_waits_for_quiet_again(vault, tmp_path):
    t = claude_transcript(tmp_path / "s1.jsonl")
    mark(vault, "session-end", "s1", t)
    mark(vault, "stop", "s1", t, when="2026-10-03T11:00:00-0300")
    [s] = summaries.sessions(vault)
    assert s.ended is False
    assert summaries.run(vault, pending=True, call=FakeModel(), now=time.time()) == 0


def test_old_sessions_are_not_caught_up(vault, tmp_path, monkeypatch):
    monkeypatch.setattr(summaries, "MAX_AGE_DAYS", 14)
    mark(vault, "session-end", "old", claude_transcript(tmp_path / "o.jsonl"), when="2026-10-03T09:15:00-0300")
    now = time.mktime((2026, 11, 1, 12, 0, 0, 0, 0, -1))
    model = FakeModel()
    assert summaries.run(vault, pending=True, call=model, now=now) == 0 and model.calls == []
    assert summaries.run(vault, pending=True, call=model, now=now - 25 * 86400) == 1


# ---- final review fixes ----

def runs(vault, entries):
    vault.state_dir.mkdir(parents=True, exist_ok=True)
    (vault.state_dir / "runs.json").write_text(json.dumps(entries))


def state_of(vault):
    return json.loads((vault.bron_dir / "memory" / "summaries.json").read_text())


def test_old_ticket_run_markers_without_a_ticket_field_are_skipped(vault, tmp_path):
    # 0.5.0 markers had no "ticket" field; the runner's runs.json says which sessions were ticket runs
    vault.state_dir.mkdir(parents=True, exist_ok=True)
    with open(vault.state_dir / "markers.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"time": "2026-10-03T09:15:00-0300", "event": "session-end", "cli": "claude", "agent": "",
                             "session_id": "run1", "transcript_path": str(claude_transcript(tmp_path / "r.jsonl"))}) + "\n")
    mark(vault, "session-end", "chat1", claude_transcript(tmp_path / "c.jsonl"))
    runs(vault, {"T-3": {"cli": "claude", "session": "run1", "agent": "bron", "thread_len": 0}, "bad": "x"})
    assert [s.session_id for s in summaries.sessions(vault)] == ["chat1"]
    model = FakeModel()
    assert summaries.run(vault, pending=True, call=model) == 1 and len(model.calls) == 1


def test_the_prompt_asks_to_leave_out_secrets():
    assert "Leave out passwords, keys, tokens and account numbers." in summaries.PROMPT


def test_secret_bullets_are_dropped_and_secret_titles_refused(vault, tmp_path):
    reply = REPLY.replace("- Exclude written-off companies",
                          "- Exclude written-off companies\n- The api key is sk-abc123def456ghi789")
    mark(vault, "session-end", "s1", claude_transcript(tmp_path / "s1.jsonl"))
    summaries.run(vault, session_id="s1", call=FakeModel(reply))
    [note] = notes(vault)
    text = note.read_text()
    assert "sk-abc123" not in text and "Exclude written-off companies" in text
    only_secret = REPLY.replace("- Nothing", "- password: hunter22")
    assert summaries.parse_reply(only_secret)[3] == ["Nothing"]
    with pytest.raises(SummaryError):
        summaries.parse_reply(REPLY.replace("Q3 report fields", "Key 3f9a8b7c2d1e4f5a6b7c8d9e0f1a2b3c"))


def test_byte_growth_without_new_messages_does_not_call_the_model(vault, tmp_path):
    t = claude_transcript(tmp_path / "s1.jsonl")
    mark(vault, "session-end", "s1", t)
    summaries.run(vault, session_id="s1", call=FakeModel())
    assert state_of(vault)["s1"]["messages"] == 4
    with open(t, "a", encoding="utf-8") as fh:  # tool noise: the file grows, the conversation doesn't
        fh.write(json.dumps({"type": "summary", "summary": "x" * 500}) + "\n")
    model = FakeModel()
    assert summaries.run(vault, session_id="s1", call=model) == 0 and model.calls == []
    entry = state_of(vault)["s1"]
    assert entry["status"] == "done" and entry["size"] == t.stat().st_size and entry["messages"] == 4
    assert summaries.run(vault, pending=True, call=model) == 0 and model.calls == []
    assert len(notes(vault)) == 1


def test_a_forgotten_conversation_is_never_summarised_again(vault, tmp_path):
    from bron.memory import commands

    t = claude_transcript(tmp_path / "s1.jsonl")
    mark(vault, "session-end", "s1", t)
    summaries.run(vault, session_id="s1", call=FakeModel())
    commands.forget_conversation(vault, load(vault), as_agent="Bron", query="Q3 report")
    assert notes(vault) == [] and state_of(vault)["s1"]["forgotten"] is True
    claude_transcript(t, exchanges=5)  # the conversation was resumed and grew
    mark(vault, "session-end", "s1", t, when="2026-10-03T11:00:00-0300")
    model = FakeModel()
    assert summaries.run(vault, session_id="s1", call=model) == 0
    assert summaries.run(vault, pending=True, call=model) == 0
    assert model.calls == [] and notes(vault) == []


def test_forgetting_during_the_model_call_wins(vault, tmp_path):
    from bron.memory import commands

    t = claude_transcript(tmp_path / "s1.jsonl")
    mark(vault, "session-end", "s1", t)
    summaries.run(vault, session_id="s1", call=FakeModel())
    claude_transcript(t, exchanges=4)
    mark(vault, "session-end", "s1", t, when="2026-10-03T11:00:00-0300")

    def forget_meanwhile(cli, model, prompt, timeout=180):
        commands.forget_conversation(vault, load(vault), as_agent="Bron", query="Q3 report")
        return REPLY

    assert summaries.run(vault, session_id="s1", call=forget_meanwhile) == 0
    assert notes(vault) == [] and state_of(vault)["s1"]["forgotten"] is True


def test_a_vanished_old_note_is_not_a_failure(vault, tmp_path):
    t = claude_transcript(tmp_path / "s1.jsonl")
    mark(vault, "session-end", "s1", t)
    summaries.run(vault, session_id="s1", call=FakeModel())
    [old] = notes(vault)
    old.unlink()
    claude_transcript(t, exchanges=4)
    mark(vault, "session-end", "s1", t, when="2026-10-03T11:00:00-0300")
    assert summaries.run(vault, session_id="s1", call=FakeModel(REPLY.replace("Q3 report fields", "Renamed"))) == 1
    assert state_of(vault)["s1"]["status"] == "done" and [n.name for n in notes(vault)] == ["2026-10-03 09.15 Renamed.md"]


def test_the_note_is_written_under_the_memory_write_lock(vault, tmp_path, monkeypatch):
    from bron.statefile import held_elsewhere

    seen = []
    real = summaries.fm.write

    def spy(path, doc):
        seen.append(held_elsewhere(vault.state_dir / "memory.json"))
        return real(path, doc)

    monkeypatch.setattr(summaries.fm, "write", spy)
    mark(vault, "session-end", "s1", claude_transcript(tmp_path / "s1.jsonl"))
    assert summaries.run(vault, session_id="s1", call=FakeModel()) == 1
    assert seen == [True]


def test_any_model_exception_is_a_failed_attempt(vault, tmp_path):
    mark(vault, "session-end", "s1", claude_transcript(tmp_path / "s1.jsonl"))

    def boom(*a, **k):
        raise ValueError("odd output")

    for _ in range(summaries.MAX_ATTEMPTS + 1):
        assert summaries.run(vault, pending=True, call=boom) == 0
    entry = state_of(vault)["s1"]
    assert entry["status"] == "failed" and entry["attempts"] == summaries.MAX_ATTEMPTS
    assert "ValueError" in entry["error"] and isinstance(entry["when"], (int, float))


def test_call_model_keeps_the_login_variables(monkeypatch):
    seen = {}
    for name in ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "ANTHROPIC_API_KEY",
                 "CLAUDE_CODE_ENTRYPOINT", "CLAUDECODE", "BRON_AGENT"):
        monkeypatch.setenv(name, "1")

    class Done:
        returncode, stdout, stderr = 0, REPLY, ""

    def fake_run(argv, **kw):
        seen["env"] = kw["env"]
        return Done()

    monkeypatch.setattr(summaries.subprocess, "run", fake_run)
    summaries.call_model("claude", "haiku", "PROMPT")
    env = seen["env"]
    for kept in ("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "ANTHROPIC_API_KEY"):
        assert env[kept] == "1"
    for gone in ("CLAUDE_CODE_ENTRYPOINT", "CLAUDECODE", "BRON_AGENT"):
        assert gone not in env

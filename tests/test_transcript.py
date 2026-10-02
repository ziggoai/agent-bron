import json
from pathlib import Path

from bron.transcript import NO_HISTORY, messages, recent_exchanges

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"


def write_jsonl(path, entries):
    path.write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")
    return path


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def reply(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def claude_entries():
    return [
        user("What did Fund II return in Q2?"),
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "hmm"}]}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}},
        reply("Fund II returned 4.2% in Q2."),
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "<command-name>/clear</command-name>"}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "Base directory for this skill: /x"}]}},
        {"type": "attachment", "attachment": {"type": "hook_additional_context"}},
        user("@cfo what do you think about this?"),
    ]


def test_claude_transcript_keeps_only_user_and_assistant_text(tmp_path):
    path = write_jsonl(tmp_path / "c.jsonl", claude_entries())
    assert messages("claude", path) == [
        ("user", "What did Fund II return in Q2?"),
        ("assistant", "Fund II returned 4.2% in Q2."),
        ("user", "@cfo what do you think about this?"),
    ]


def test_recent_exchanges_drop_the_current_message_and_label_speakers(tmp_path):
    path = write_jsonl(tmp_path / "c.jsonl", claude_entries())
    text = recent_exchanges("claude", path, "@cfo what do you think about this?", assistant="Bron")
    assert text == "User: What did Fund II return in Q2?\n\nBron: Fund II returned 4.2% in Q2."


def codex_entries():
    def item(role, *texts, kind="input_text"):
        return {"type": "response_item", "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": t} for t in texts]}}

    return [
        {"type": "session_meta", "payload": {}},
        item("developer", "rules"),
        item("user", "# AGENTS.md instructions for /v", "<environment_context>x</environment_context>"),
        item("user", "How much cash does Fund I have?"),
        {"type": "response_item", "payload": {"type": "function_call", "name": "shell"}},
        item("assistant", "About $12M.", kind="output_text"),
        {"type": "event_msg", "payload": {"type": "agent_message", "message": "About $12M."}},
    ]


def test_codex_transcript_skips_injected_instructions(tmp_path):
    path = write_jsonl(tmp_path / "x.jsonl", codex_entries())
    assert messages("codex", path) == [("user", "How much cash does Fund I have?"), ("assistant", "About $12M.")]


def test_only_the_last_three_exchanges_count_and_long_messages_are_cut(tmp_path):
    entries = []
    for i in range(5):
        entries += [user(f"question {i}"), reply(("x" * 2000) if i == 4 else f"answer {i}")]
    text = recent_exchanges("claude", write_jsonl(tmp_path / "c.jsonl", entries), "")
    assert "question 1" not in text and "question 2" in text
    assert "x" * 1499 + "…" in text and "x" * 1500 not in text


def test_the_total_is_capped_keeping_the_newest(tmp_path):
    entries = []
    for letter_user, letter_reply in (("a", "b"), ("c", "d"), ("e", "f")):
        entries += [user(letter_user * 1400), reply(letter_reply * 1400)]
    text = recent_exchanges("claude", write_jsonl(tmp_path / "c.jsonl", entries), "")
    assert "f" * 1400 in text and "c" * 1400 in text
    assert "b" * 1400 not in text and "a" * 1400 not in text


def test_unreadable_missing_or_garbage_transcripts_fall_back(tmp_path):
    assert recent_exchanges("claude", tmp_path / "missing.jsonl", "hi") == NO_HISTORY
    assert recent_exchanges("codex", "", "hi") == NO_HISTORY
    assert recent_exchanges("claude", None, "hi") == NO_HISTORY
    garbage = tmp_path / "g.jsonl"
    garbage.write_text('not json\n[1, 2]\n{"type": "user", "message": {"role": "user", "content": "half', encoding="utf-8")
    assert recent_exchanges("claude", garbage, "hi") == NO_HISTORY


def test_only_the_tail_of_a_huge_transcript_is_read(tmp_path):
    entries = [user(f"old {i} " + "p" * 500) for i in range(5000)] + [reply("ignored"), user("latest question"), reply("latest answer")]
    path = write_jsonl(tmp_path / "big.jsonl", entries)
    assert path.stat().st_size > 2_000_000
    found = messages("claude", path)
    assert found[-2:] == [("user", "latest question"), ("assistant", "latest answer")]
    assert "old 0 " not in "".join(text for _, text in found)


def test_real_transcripts_from_both_clis():
    for cli in ("claude", "codex"):
        found = messages(cli, FIXTURES / f"{cli}.jsonl")
        roles = [role for role, _ in found]
        assert "user" in roles and "assistant" in roles, cli
        assert not any(text.lstrip().startswith(("<", "# AGENTS.md")) for role, text in found if role == "user"), cli
        assert any("fixture-ok" in text for role, text in found if role == "assistant"), cli


def test_fixtures_are_small_and_contain_nothing_personal():
    import re

    for cli in ("claude", "codex"):
        path = FIXTURES / f"{cli}.jsonl"
        raw = path.read_text(encoding="utf-8")
        assert path.stat().st_size < 50_000, cli
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", raw), cli
        assert not [p for p in re.findall(r"/Users/[^/\"\\\s]*", raw) if p != "/Users/tester"], cli
        assert "/private/var/folders" not in raw, cli
        lowered = raw.lower()
        for word in ("atl-", "carta", "affinity", "notion"):
            assert word not in lowered, (cli, word)

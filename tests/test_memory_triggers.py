import io
import json

import pytest

from bron.hooks import main as hook
from bron.memory import summaries


@pytest.fixture
def spawned(vault, monkeypatch):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    calls = []
    monkeypatch.setattr(summaries, "spawn", lambda v, **kw: calls.append(kw) or True)
    return calls


def call(event, payload=None):
    return hook(event, "claude", stdin=io.StringIO(json.dumps(payload or {})), stdout=io.StringIO())


def test_session_end_starts_a_summary_for_that_session(spawned):
    call("session-end", {"session_id": "s1", "transcript_path": "/tmp/x.jsonl"})
    assert spawned == [{"session_id": "s1"}]


def test_pre_compact_starts_one_too(spawned):
    call("pre-compact", {"session_id": "s1", "transcript_path": "/tmp/x.jsonl"})
    assert spawned == [{"session_id": "s1"}]


def test_stop_does_not(spawned):
    call("stop", {"session_id": "s1", "transcript_path": "/tmp/x.jsonl"})
    assert spawned == []


def test_session_start_catches_up(spawned):
    call("session-start")
    assert spawned == [{"pending": True}]


def test_a_failing_spawn_never_breaks_the_trigger(vault, monkeypatch):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))

    def boom(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(summaries, "spawn", boom)
    assert call("session-end", {"session_id": "s1", "transcript_path": "/tmp/x.jsonl"}) == 0
    out = io.StringIO()
    assert hook("session-start", "claude", stdin=io.StringIO("{}"), stdout=out) == 0
    assert out.getvalue().startswith("# Bron briefing")


# ---- final review fixes ----

def test_an_empty_session_id_starts_nothing(spawned):
    call("session-end", {"session_id": "", "transcript_path": "/tmp/x.jsonl"})
    call("pre-compact", {})
    assert spawned == []


def test_a_failing_chat_close_still_starts_the_summary(spawned, monkeypatch):
    from bron import hooks

    def boom(cli, payload):
        raise RuntimeError("chats")

    monkeypatch.setattr(hooks, "_close_chats", boom)
    assert call("session-end", {"session_id": "s1", "transcript_path": "/tmp/x.jsonl"}) == 0
    assert spawned == [{"session_id": "s1"}]


def test_summary_errors_are_logged_with_the_hooks_cli(vault, monkeypatch):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    monkeypatch.setenv("BRON_CLI", "wrong")

    def boom(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(summaries, "spawn", boom)
    hook("pre-compact", "codex", stdin=io.StringIO(json.dumps({"session_id": "s1"})), stdout=io.StringIO())
    log = (vault.state_dir / "hook-errors.log").read_text()
    assert " codex memory RuntimeError: no" in log and "wrong" not in log

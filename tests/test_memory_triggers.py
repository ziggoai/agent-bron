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

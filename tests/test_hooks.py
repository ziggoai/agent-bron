import io
import json

import pytest

from bron.hooks import main as hook
from vaultkit import add_agent, set_meta


def call(event, cli="claude", payload=None, raw=None):
    out = io.StringIO()
    stdin = io.StringIO(raw if raw is not None else json.dumps(payload or {}))
    code = hook(event, cli, stdin=stdin, stdout=out)
    return code, out.getvalue()


@pytest.fixture
def in_vault(vault, monkeypatch):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    return vault


def test_session_start_syncs_and_briefs(in_vault):
    code, out = call("session-start")
    assert code == 0
    assert out.startswith("# Bron briefing\n")
    assert "You are Bron, working in Claude Code" in out
    assert "First-run setup isn't done yet" in out
    assert "Bron applied recent setup changes" in out
    assert (in_vault.root / ".codex/config.toml").is_file()


def test_second_session_start_is_quiet_about_setup(in_vault):
    call("session-start")
    _, out = call("session-start")
    assert "applied recent setup changes" not in out


def test_briefing_uses_settings_and_memory_summary(in_vault):
    set_meta(in_vault.settings_file, user_name="Alex", company="Example Capital")
    (in_vault.memory_dir / "Summary.md").write_text("Fund III close is planned for November.\n", encoding="utf-8")
    _, out = call("session-start", "codex")
    assert "working in Codex" in out
    assert "You're working with Alex at Example Capital." in out
    assert "## What you remember" in out and "Fund III close" in out


def test_long_memory_is_clipped(in_vault):
    (in_vault.memory_dir / "Summary.md").write_text("x" * 20000, encoding="utf-8")
    _, out = call("session-start")
    assert len(out) <= 6000


def test_broken_setup_is_reported_without_failing(in_vault):
    call("session-start")
    add_agent(in_vault, "CFO", reports_to="Nobody")
    code, out = call("session-start")
    assert code == 0
    assert "couldn't apply recent setup changes" in out
    assert "Nobody" in out


def test_unexpected_error_still_exits_zero(in_vault, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("kaput")

    monkeypatch.setattr("bron.briefing.build_briefing", boom)
    code, out = call("session-start")
    assert code == 0 and "startup check failed" in out
    assert "RuntimeError: kaput" in (in_vault.state_dir / "hook-errors.log").read_text()


def test_quick_events_append_markers(in_vault, monkeypatch):
    monkeypatch.setenv("BRON_AGENT", "CFO")
    for event in ("pre-compact", "stop", "session-end"):
        assert call(event, "codex", {"session_id": "s1", "transcript_path": "/t.jsonl"}) == (0, "")
    lines = [json.loads(line) for line in (in_vault.state_dir / "markers.jsonl").read_text().splitlines()]
    assert [line["event"] for line in lines] == ["pre-compact", "stop", "session-end"]
    assert lines[0]["agent"] == "CFO" and lines[0]["cli"] == "codex"
    assert lines[0]["session_id"] == "s1" and lines[0]["transcript_path"] == "/t.jsonl"


def test_user_prompt_is_silent_for_now(in_vault):
    assert call("user-prompt", payload={"prompt": "@cfo hello"}) == (0, "")


def test_garbage_input_is_ignored(in_vault):
    assert call("stop", raw="not json") == (0, "")
    assert call("stop", raw="") == (0, "")


def test_outside_a_vault_never_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("BRON_VAULT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert call("stop")[0] == 0
    code, out = call("session-start")
    assert code == 0 and "startup check failed" in out

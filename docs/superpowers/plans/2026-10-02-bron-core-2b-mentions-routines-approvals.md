# Bron Core Plan 2b: @-mentions, routines, saved approvals — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user talk to any team member with `@name` from any session (the tagged agent starts at once and its reply is shown word for word), track repeating routines per period with checklists and due dates in the briefing, and keep Claude Code's "don't ask again" choices by moving them into the agent's `always_allow`.

**Architecture:** Three new engine modules (`transcript.py`, `mentions.py`, `routines.py`, `approvals.py`) plus small changes to the runner (chat prompts, `shown` background runs, `ticket wait`), the message/session triggers, the briefing, the health check, sync (approvals import before regenerating) and the safe writer (no backup for a file whose only change was an approval). New commands: `bron ticket wait`, `bron routine list|start|refresh`. New content: `routines` skill, `routines.md` manual page, `Routines/Board.base`, chat and approvals sections in existing manual pages.

**Tech Stack:** Python 3.12 (uv, `core/Engine`), PyYAML, pytest. Claude Code and Codex CLIs for the live tests.

**Spec:** `docs/superpowers/specs/2026-10-02-bron-core-2b-design.md` (refines `docs/superpowers/specs/2026-10-01-bron-core-design.md`; builds on Plan 2a as built, framework 0.2.3).

## Global Constraints

- Python 3.12; runtime dependencies stay PyYAML and tomli-w only (no new packages).
- Run tests from the repo root: `uv run --project core/Engine pytest tests -q`. Live tests only where a task says so: `BRON_LIVE=1 uv run --project core/Engine pytest tests/live -q`.
- Every commit ends with exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (use `git commit -m "<subject>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`).
- A trigger (`bron hook …`) must never fail or block the user's message: every error degrades to no routing plus at most a one-line note, exit code 0.
- The trigger configuration (`hookconfig.py`, `.claude/settings.json` hooks, `.codex/hooks.json`) must not change: Codex would ask the user to re-approve it.
- Never use `--bare`, `--strict-mcp-config` or `--dangerously-bypass-hook-trust`.
- Free text in documented commands is single-quoted, with the file fallback sentence: "if the text contains a single quote, write it to a file and use `--file` (result) or `--note-file` (status)".
- `AGENTS.md` stays under 8 KB (`tests/test_handoff_content.py` checks it).
- User-facing text (messages, notes, docs) is plain English for a non-technical user; no jargon such as "hook", "JSON", "flag" in messages shown to the user.
- Routine problems never stop a sync: runbook checks run only in `bron check`, never in sync.
- The tagged agent's reply is shown word for word; the session agent never rewrites it.

## Review Focus

1. A message with an email address, a URL path (`x.com/@cfo`) or an unknown `@name` must not route anything; the session's own agent and headless ticket runs never route (Task 2, Task 4 tests).
2. A follow-up sent while the previous reply is still being written must start a new chat ticket, never corrupt the running one (Task 2 test).
3. A huge transcript, or one whose last line is half-written or garbage, must still give context quickly or fall back to "(no earlier chat available)" (Task 1 tests).
4. A Tracking note the user edited by hand (notes after items, `* [X]`, extra `###` groups) must be counted correctly and its body never rewritten (Task 5 test).
5. An `Agent.md` with comments, a block-style `always_allow` list, or no `always_allow` key must keep every other line intact when an approval is imported (Task 7 test).

## File map

| File | Task | Responsibility |
|---|---|---|
| `core/Engine/bron/transcript.py` (new) | 1 | Last few user/assistant exchanges from a CLI transcript file |
| `tests/fixtures/transcripts/{claude,codex}.jsonl` (new) | 1 | Real transcript samples captured from both CLIs |
| `core/Engine/bron/tickets.py` | 2 | `new_ticket(..., extra_meta=)` |
| `core/Engine/bron/mentions.py` (new) | 2, 4 | Tag detection, chat tickets (create, follow-up, close), routing for the trigger |
| `core/Engine/bron/runner.py` | 3 | Chat prompts, chat replies in the Thread, `shown` background runs, `wait_for` |
| `core/Engine/bron/cli.py`, `tickets_cli.py` | 3, 6 | `bron run --shown`, `bron ticket wait`, `bron routine …` |
| `core/Engine/bron/hooks.py` | 4 | Message trigger routes tags; session end/start close chats |
| `core/Engine/bron/routines.py` (new) | 5, 6 | Runbooks, periods, due dates, Tracking notes, progress, status/briefing lines |
| `core/Engine/bron/routines_cli.py` (new) | 6 | `bron routine list|start|refresh` |
| `core/Engine/bron/briefing.py` | 6, 7 | Routines block; approvals notice |
| `core/Engine/bron/check.py` | 6 | Runbook problems in `bron check` |
| `core/Engine/bron/approvals.py` (new) | 7 | Import Claude "don't ask again" rules into `always_allow` |
| `core/Engine/bron/writer.py`, `sync.py`, `gen_claude.py` | 7 | `accept` (no backup), import before regenerating, `project_allow` |
| `core/Skills/routines/SKILL.md`, `core/Manual/routines.md`, `template/Routines/Board.base` (new) | 6 | Bron's routine instructions, formats, board |
| `core/Manual/{tickets,permissions,index}.md`, `core/Templates/AGENTS.md.tmpl` | 4, 6, 7 | Chat, routines and saved-approvals docs |
| `tests/live/test_mentions.py` (new), version files | 8 | Live @-mentions both ways; framework 0.3.0 |

---

### Task 1: Transcript reader

**Files:**
- Create: `tests/fixtures/transcripts/claude.jsonl`, `tests/fixtures/transcripts/codex.jsonl` (captured from the real CLIs)
- Create: `docs/superpowers/specs/2026-10-02-bron-plan2b-cli-verification.md`
- Create: `core/Engine/bron/transcript.py`
- Test: `tests/test_transcript.py`

**Interfaces:**
- Produces: `transcript.NO_HISTORY: str`; `transcript.messages(cli: str, path: str | Path) -> list[tuple[str, str]]` (role `"user"`/`"assistant"`, text, consecutive same-role merged); `transcript.recent_exchanges(cli: str, path: str | Path | None, current_prompt: str = "", *, assistant: str = "Assistant") -> str`.

- [ ] **Step 1: Capture real transcripts from both CLIs**

Run from a scratch folder outside the repo (a Codex trust entry for it may be added to `~/.codex/config.toml`; that is expected):

```bash
D="$(mktemp -d)/probe"; mkdir -p "$D"; cd "$D"
claude -p "Run the shell command: echo fixture-ok   Then tell me in one short sentence what it printed." --output-format json --allowedTools Bash > claude.json
SID=$(python3 -c 'import json;print(json.load(open("claude.json"))["session_id"])')
ls ~/.claude/projects/*/"$SID".jsonl
codex exec --json --skip-git-repo-check "Run the shell command: echo fixture-ok   Then tell me in one short sentence what it printed." > codex.jsonl
TID=$(head -1 codex.jsonl | python3 -c 'import json,sys;print(json.load(sys.stdin)["thread_id"])')
ls ~/.codex/sessions/*/*/*/rollout-*"$TID".jsonl
```

Then copy them into the repo with this sanitiser (run from the repo root; pass the two paths printed above):

```bash
uv run --project core/Engine python - "<claude transcript path>" "<codex rollout path>" <<'EOF'
import json, os, sys
from pathlib import Path
home = os.path.expanduser("~")
out = Path("tests/fixtures/transcripts"); out.mkdir(parents=True, exist_ok=True)
def clean(line):
    return line.replace(home, "/Users/tester")
claude_lines = [clean(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
(out / "claude.jsonl").write_text("".join(claude_lines), encoding="utf-8")
codex_lines = []
for l in open(sys.argv[2], encoding="utf-8"):
    try:
        e = json.loads(l)
    except ValueError:
        continue
    if e.get("type") not in ("response_item", "event_msg"):
        continue
    p = e.get("payload") or {}
    if p.get("type") == "message" and p.get("role") == "developer":
        for c in p.get("content") or []:
            if isinstance(c, dict) and "text" in c:
                c["text"] = c["text"][:200]
    codex_lines.append(clean(json.dumps(e, ensure_ascii=False)) + "\n")
(out / "codex.jsonl").write_text("".join(codex_lines), encoding="utf-8")
print(len(claude_lines), len(codex_lines))
EOF
```

Open both fixture files and confirm: the Claude file has `"type":"user"` entries with string content (the prompt) and `tool_result` lists, and `"type":"assistant"` entries with `text`/`tool_use`/`thinking` blocks; the Codex file has `response_item` entries with `payload.type == "message"` and `role` user/assistant whose `content` items are `input_text`/`output_text`, plus injected user messages starting with `# AGENTS.md instructions` or `<environment_context>` (only if the scratch folder had an AGENTS.md; otherwise just `<environment_context>`). If a format differs from this, write down exactly how in the verification doc (Step 2) and adapt `_claude_text` / `_codex_text` in Step 5 to the real format, keeping the tests in Step 3 passing.

- [ ] **Step 2: Write the verification doc**

Create `docs/superpowers/specs/2026-10-02-bron-plan2b-cli-verification.md`:

```markdown
# Plan 2b CLI verification

| # | Question | What was run | Finding | Consequence |
|---|---|---|---|---|
| T1 | Claude Code transcript format (`transcript_path`) | `claude -p … --allowedTools Bash` in a scratch folder; transcript copied to tests/fixtures/transcripts/claude.jsonl | <fill in: entry types seen, where user/assistant text lives> | transcript.py `_claude_text` |
| T2 | Codex transcript format (`transcript_path`) | `codex exec --json …`; rollout copied to tests/fixtures/transcripts/codex.jsonl | <fill in: entry types seen, injected user messages> | transcript.py `_codex_text` |
| T3 | Message-trigger output reaches the model in Codex | Plan 2a ticket updates use the same path | Assumed yes (Plan 2a); confirmed in the user's hands-on test | — |
| T4 | A process started by the message trigger survives the trigger's exit | `start_background` uses `start_new_session=True` | Checked by tests/live/test_mentions.py (Task 8) | — |
| T5 | Claude "don't ask again" location and format in a non-git vault | Plan 2 verification D1 (docs): `permissions.allow` in `.claude/settings.json`; rules like `Bash(npm run test:*)` / `Bash(npm run test *)`, `mcp__server__tool` | Both Bash forms are handled | approvals.py `to_entry` |
| T6 | Time from Enter to the shown reply | tests/live/test_mentions.py (Task 8) | <filled in by Task 8> | — |
```

Fill in the two `<fill in>` cells with what you saw in Step 1.

- [ ] **Step 3: Write the failing tests**

Create `tests/test_transcript.py`:

```python
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
```

- [ ] **Step 4: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_transcript.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'bron.transcript'`.

- [ ] **Step 5: Write the module**

Create `core/Engine/bron/transcript.py`:

```python
"""The last few exchanges of a chat, read from the CLI's own transcript file (context for @-mentions)."""
from __future__ import annotations

import json
from pathlib import Path

MAX_EXCHANGES = 3
MAX_MESSAGE = 1500
MAX_TOTAL = 6000
TAIL_BYTES = 1_000_000
NO_HISTORY = "(no earlier chat available)"
# User-side text the CLIs or Bron inject, which the user didn't type.
_INJECTED = ("<", "# AGENTS.md instructions", "Base directory for this skill")


def _claude_text(entry: dict) -> tuple[str, str] | None:
    if entry.get("type") not in ("user", "assistant") or entry.get("isMeta") or entry.get("isSidechain"):
        return None
    message = entry.get("message")
    if not isinstance(message, dict):
        return None
    role, content = message.get("role"), message.get("content")
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list):
        texts = [str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    else:
        return None
    text = "\n".join(t for t in texts if t.strip()).strip()
    if role not in ("user", "assistant") or not text:
        return None
    return role, text


def _codex_text(entry: dict) -> tuple[str, str] | None:
    payload = entry.get("payload")
    if entry.get("type") != "response_item" or not isinstance(payload, dict) or payload.get("type") != "message":
        return None
    role = payload.get("role")
    if role not in ("user", "assistant"):
        return None
    parts = [
        str(c.get("text") or "")
        for c in payload.get("content") or []
        if isinstance(c, dict) and c.get("type") in ("input_text", "output_text")
    ]
    kept = [p for p in parts if p.strip() and not (role == "user" and p.lstrip().startswith(_INJECTED))]
    text = "\n".join(kept).strip()
    return (role, text) if text else None


def _tail_lines(path: str | Path) -> list[str]:
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - TAIL_BYTES))
        data = fh.read()
    if size > TAIL_BYTES:
        data = data.split(b"\n", 1)[-1]  # the first line is probably cut
    return data.decode("utf-8", "replace").splitlines()


def messages(cli: str, path: str | Path) -> list[tuple[str, str]]:
    """(role, text) pairs in order: what the user typed and what the assistant said. [] if unreadable."""
    pick = _claude_text if cli == "claude" else _codex_text
    try:
        lines = _tail_lines(path)
    except (OSError, ValueError):
        return []
    out: list[tuple[str, str]] = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        found = pick(entry)
        if found is None:
            continue
        role, text = found
        if role == "user" and text.lstrip().startswith(_INJECTED):
            continue
        if out and out[-1][0] == role:
            out[-1] = (role, out[-1][1] + "\n" + text)
        else:
            out.append((role, text))
    return out


def recent_exchanges(cli: str, path: str | Path | None, current_prompt: str = "", *, assistant: str = "Assistant") -> str:
    """Up to the last 3 exchanges before the current message, newest kept when cutting."""
    if not path:
        return NO_HISTORY
    items = messages(cli, path)
    if items and items[-1][0] == "user" and items[-1][1].strip() == current_prompt.strip():
        items = items[:-1]
    items = items[-2 * MAX_EXCHANGES:]
    labels = {"user": "User", "assistant": assistant}
    blocks: list[str] = []
    total = 0
    for role, text in reversed(items):
        if len(text) > MAX_MESSAGE:
            text = text[: MAX_MESSAGE - 1] + "…"
        block = f"{labels[role]}: {text}"
        if total + len(block) > MAX_TOTAL:
            break
        blocks.append(block)
        total += len(block)
    return "\n\n".join(reversed(blocks)) if blocks else NO_HISTORY
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests/test_transcript.py -q`
Expected: all pass. Then the full suite: `uv run --project core/Engine pytest tests -q` — all pass.

- [ ] **Step 7: Commit**

```bash
git add core/Engine/bron/transcript.py tests/test_transcript.py tests/fixtures/transcripts docs/superpowers/specs/2026-10-02-bron-plan2b-cli-verification.md
git commit -m "feat: read the last chat exchanges from Claude Code and Codex transcripts" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Tags and chat tickets

**Files:**
- Modify: `core/Engine/bron/tickets.py` (`new_ticket`)
- Create: `core/Engine/bron/mentions.py`
- Test: `tests/test_mentions.py`

**Interfaces:**
- Consumes: `tickets.new_ticket`, `tickets.editing`, `tickets.list_tickets`, `tickets.add_message`, `tickets.set_status`, `model.slug`, `model.Agent`.
- Produces:
  - `tickets.new_ticket(..., extra_meta: dict | None = None)` (extra frontmatter keys, e.g. `chat_session`).
  - `mentions.tagged_agents(text: str, agents: dict[str, Agent], self_key: str) -> list[Agent]`
  - `mentions.open_chat(vault, session: str, agent_key: str) -> Ticket | None` (only `blocked`/`in-review` chats of that session)
  - `mentions.chat_title(agent: Agent, message: str) -> str`
  - `mentions.start_chat(vault, *, agent: Agent, requester: str, session: str, message: str, context: str) -> tuple[Ticket, bool]` (ticket, is_follow_up)
  - `mentions.close_session_chats(vault, session: str) -> list[str]`
  - `mentions.close_stale_chats(vault, *, now: float | None = None) -> list[str]`
  - constants `CONTINUABLE = ("blocked", "in-review")`, `STALE_HOURS = 12`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mentions.py`:

```python
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
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_mentions.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'bron.mentions'`.

- [ ] **Step 3: Let `new_ticket` take extra frontmatter**

In `core/Engine/bron/tickets.py`, change the `new_ticket` signature and the `Ticket(...)` it builds:

```python
def new_ticket(
    vault: Vault,
    *,
    title: str,
    assignee: str,
    request: str,
    requested_by: str = "you",
    context: str = "",
    kind: str = "task",
    project: str = "",
    parent: str = "",
    priority: str = "normal",
    due: str = "",
    status: str = "todo",
    extra_meta: dict | None = None,
) -> Ticket:
```

and add `extra_meta=dict(extra_meta or {}),` as the last argument of the `Ticket(...)` call inside it (after `context=context.strip(),`).

- [ ] **Step 4: Write the module**

Create `core/Engine/bron/mentions.py`:

```python
"""@-mentions: which agents a message tags, and the chat tickets that carry those conversations."""
from __future__ import annotations

import re
import time

from .model import Agent, slug
from .tickets import Ticket, TicketError, add_message, editing, list_tickets, new_ticket, set_status
from .vault import Vault

# '@' not preceded by a letter, digit, '.', '@' or '/', so emails and URL paths aren't tags.
_TAG = re.compile(r"(?<![\w.@/])@([A-Za-z][\w-]*)")
CONTINUABLE = ("blocked", "in-review")  # a chat whose agent has answered (or is waiting for an OK)
STALE_HOURS = 12
TITLE_MAX = 60


def tagged_agents(text: str, agents: dict[str, Agent], self_key: str) -> list[Agent]:
    """Agents tagged in the message, in order, each once; never the session's own agent."""
    found: list[Agent] = []
    for match in _TAG.finditer(text):
        agent = agents.get(slug(match.group(1)))
        if agent is not None and agent.key != self_key and all(a.key != agent.key for a in found):
            found.append(agent)
    return found


def _session_of(ticket: Ticket) -> str:
    return str(ticket.extra_meta.get("chat_session") or "")


def open_chat(vault: Vault, session: str, agent_key: str) -> Ticket | None:
    if not session:
        return None
    tickets, _ = list_tickets(vault)
    for ticket in reversed(tickets):
        if ticket.kind == "chat" and ticket.assignee == agent_key and ticket.status in CONTINUABLE and _session_of(ticket) == session:
            return ticket
    return None


def chat_title(agent: Agent, message: str) -> str:
    title = f"Chat with {agent.name}: {' '.join(message.split())}"
    return title if len(title) <= TITLE_MAX else title[: TITLE_MAX - 1].rstrip() + "…"


def start_chat(vault: Vault, *, agent: Agent, requester: str, session: str, message: str, context: str) -> tuple[Ticket, bool]:
    """Continue this session's open chat with the agent, or start a new one. Returns (ticket, is_follow_up)."""
    existing = open_chat(vault, session, agent.key)
    if existing is not None:
        with editing(vault, existing.id) as ticket:
            add_message(ticket, "you", message)
            # Back to todo without a Thread line: `ticket wait` then waits for the new run.
            ticket.status = "todo"
            ticket.invalid.pop("status", None)
        return ticket, True
    ticket = new_ticket(
        vault,
        title=chat_title(agent, message),
        assignee=agent.key,
        request=message,
        requested_by=requester,
        context=context,
        kind="chat",
        extra_meta={"chat_session": session} if session else None,
    )
    return ticket, False


def close_session_chats(vault: Vault, session: str) -> list[str]:
    """When a session ends: its answered chats are done. Chats still running or about to run are left."""
    if not session:
        return []
    closed: list[str] = []
    tickets, _ = list_tickets(vault)
    for ticket in tickets:
        if ticket.kind != "chat" or ticket.status not in CONTINUABLE or _session_of(ticket) != session:
            continue
        try:
            with editing(vault, ticket.id) as current:
                if current.status in CONTINUABLE:
                    set_status(current, "done", "bron", "chat ended")
            closed.append(ticket.id)
        except (TicketError, OSError):
            continue
    return closed


def close_stale_chats(vault: Vault, *, now: float | None = None) -> list[str]:
    """Fallback when a session end was missed: chats untouched for 12 hours are done."""
    cutoff = (time.time() if now is None else now) - STALE_HOURS * 3600
    closed: list[str] = []
    tickets, _ = list_tickets(vault)
    for ticket in tickets:
        if ticket.kind != "chat" or ticket.status not in ("todo", *CONTINUABLE):
            continue
        try:
            if ticket.path.stat().st_mtime >= cutoff:
                continue
            with editing(vault, ticket.id) as current:
                if current.status in ("todo", *CONTINUABLE):
                    set_status(current, "done", "bron", f"chat ended (no activity for {STALE_HOURS} hours)")
            closed.append(ticket.id)
        except (TicketError, OSError):
            continue
    return closed
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests/test_mentions.py tests/test_tickets.py -q`
Expected: all pass. Then `uv run --project core/Engine pytest tests -q` — all pass.

- [ ] **Step 6: Commit**

```bash
git add core/Engine/bron/tickets.py core/Engine/bron/mentions.py tests/test_mentions.py
git commit -m "feat: @-tags and chat tickets (create, follow up, close)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Chat runs, shown background runs, `ticket wait`

**Files:**
- Modify: `core/Engine/bron/runner.py` (prompts, `run_ticket`, `_settle`, `start_background`, new `wait_for`/`describe_outcome`)
- Modify: `core/Engine/bron/cli.py` (`bron run --shown`)
- Modify: `core/Engine/bron/tickets_cli.py` (`bron ticket wait`)
- Test: `tests/test_runner.py` (append)

**Interfaces:**
- Consumes: Task 2's `new_ticket(..., kind="chat", extra_meta=…)`; Plan 2a's `run_ticket(..., shown=)`, `locks.read_lock/acquire/release`, `notifications.take`.
- Produces:
  - `runner.CHAT_PROMPT`, `runner.CHAT_RESUME_PROMPT` (str templates)
  - `runner.start_background(vault, ticket_id, *, caller_cli=None, resume=False, shown=False, popen=subprocess.Popen) -> int` (adds `--shown`)
  - `runner.describe_outcome(cfg, ticket) -> str`
  - `runner.wait_for(vault, ticket_ids: list[str], *, grace: float = 15.0, poll: float = 0.5, sleep=time.sleep, now=time.time) -> list[str]`
  - CLI: `bron run <id> --shown` (hidden), `bron ticket wait <id> [<id> …]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_runner.py`:

```python
# ---- plan 2b: chats, shown runs, waiting ----

def chat_for(vault, assignee="cfo"):
    return new_ticket(
        vault, title="Chat with CFO", assignee=assignee, request="@cfo what's our cash?", context="User: hi",
        requested_by="bron", kind="chat", extra_meta={"chat_session": "claude:s1"},
    )


def test_a_chat_run_uses_the_chat_prompt_and_records_the_reply(team):
    ticket = chat_for(team)
    fake = FakeCLI(team, Execution(0, claude_json(result="Cash is $12M."), ""))
    outcome = run_ticket(team, ticket.id, caller_cli="claude", run=fake, which=found, shown=True)
    prompt = fake.calls[0]["argv"][2]
    assert "The user is talking to you directly" in prompt and "@cfo what's our cash?" in prompt and "User: hi" in prompt
    assert "Your final reply becomes the ticket's Result" not in prompt
    loaded = load_ticket(ticket.path)
    assert loaded.status == "in-review" and loaded.result == "Cash is $12M."
    assert loaded.thread[-1].endswith("cfo: Cash is $12M.")
    assert take(team, "bron", "bron") == []
    assert outcome.message.endswith("Result:\nCash is $12M.")


def test_a_chat_follow_up_resumes_with_the_users_new_message(team):
    ticket = chat_for(team)
    run_ticket(team, ticket.id, caller_cli="claude", run=FakeCLI(team, Execution(0, claude_json(session="s7", result="Cash is $12M."), "")), which=found, shown=True)
    with editing(team, ticket.id) as current:
        add_message(current, "you", "and next quarter?")
        current.status = "todo"
    fake = FakeCLI(team, Execution(0, claude_json(session="s7", result="About $10M."), ""))
    run_ticket(team, ticket.id, caller_cli="claude", resume=True, run=fake, which=found, shown=True)
    argv = fake.calls[0]["argv"]
    assert argv[argv.index("--resume") + 1] == "s7"
    assert "The user replied in the chat" in argv[2] and "you: and next quarter?" in argv[2]
    assert load_ticket(ticket.path).result == "About $10M."


def test_a_chat_without_a_saved_session_repeats_the_later_messages(team):
    ticket = chat_for(team)
    with editing(team, ticket.id) as current:
        add_message(current, "you", "and next quarter?")
    fake = FakeCLI(team, Execution(0, claude_json(), ""))
    run_ticket(team, ticket.id, caller_cli="claude", resume=True, run=fake, which=found)
    prompt = fake.calls[0]["argv"][2]
    assert "The user is talking to you directly" in prompt
    assert "Later messages:" in prompt and "you: and next quarter?" in prompt


def test_background_runs_can_be_marked_shown(team, monkeypatch, capsys):
    seen = {}

    def popen(argv, **kwargs):
        seen["argv"] = argv
        return type("P", (), {"pid": 5})()

    start_background(team, "T-0001", caller_cli="codex", resume=True, shown=True, popen=popen)
    assert seen["argv"][2:] == ["T-0001", "--caller-cli", "codex", "--resume", "--shown"]

    from bron.runner import RunOutcome

    calls = []
    monkeypatch.chdir(team.root)
    monkeypatch.setattr("bron.runner.run_ticket", lambda vault, tid, **kw: calls.append(kw) or RunOutcome(tid, "in-review", "claude", "ok"))
    live = ticket_for(team)
    assert main(["run", live.id, "--shown"]) == 0
    assert calls[-1]["shown"] is True


def test_wait_prints_each_reply_once_the_run_is_done(team):
    from bron.runner import wait_for

    done = ticket_for(team)
    with editing(team, done.id) as current:
        set_result(current, "Q3 drafted.", "cfo")
    stuck = ticket_for(team, "pinned")
    with editing(team, stuck.id) as current:
        set_status(current, "blocked", "pinned", "Needs your OK: send the email to LPs")
    assert wait_for(team, [done.id, stuck.id], sleep=lambda s: None) == [
        "CFO: Q3 drafted.",
        f"{stuck.id} is blocked (Pinned): Needs your OK: send the email to LPs",
    ]


def test_wait_keeps_waiting_while_the_run_holds_its_lock(team):
    from bron.locks import release
    from bron.runner import wait_for

    ticket = ticket_for(team)
    assert acquire(team, ticket.id, "run1", max_minutes=30)
    ticks = []

    def sleep(_):
        ticks.append(1)
        if len(ticks) == 3:
            with editing(team, ticket.id) as current:
                set_result(current, "Done now.", "cfo")
            release(team, ticket.id, "run1")

    assert wait_for(team, [ticket.id], sleep=sleep) == ["CFO: Done now."]
    assert len(ticks) == 3


def clock(step=5):
    values = iter(range(0, 100_000, step))
    return lambda: next(values)


def test_wait_gives_up_on_a_run_that_never_started_or_stopped_midway(team):
    from bron.runner import wait_for

    never = ticket_for(team)
    assert wait_for(team, [never.id], sleep=lambda s: None, now=clock()) == [f"{never.id} hasn't started; see .bron/runs/background-{never.id}.log"]
    midway = ticket_for(team)
    with editing(team, midway.id) as current:
        current.status = "in-progress"
    assert wait_for(team, [midway.id], sleep=lambda s: None, now=clock()) == [f"{midway.id} stopped before it finished; see .bron/runs/"]


def test_wait_stops_waiting_after_the_time_limit(team):
    from bron.runner import wait_for

    ticket = ticket_for(team)
    assert acquire(team, ticket.id, "run1", max_minutes=30)
    assert wait_for(team, [ticket.id], sleep=lambda s: None, now=clock(step=10_000)) == [
        f"{ticket.id} is still running after 30 minutes; check it later with `.bron/bin/bron ticket show {ticket.id}`."
    ]


def test_ticket_wait_command(team, monkeypatch, capsys):
    monkeypatch.chdir(team.root)
    ticket = ticket_for(team)
    with editing(team, ticket.id) as current:
        set_result(current, "Q3 drafted.", "cfo")
    assert main(["ticket", "wait", ticket.id]) == 0
    assert capsys.readouterr().out == "CFO: Q3 drafted.\n"
    assert main(["ticket", "wait", "T-9999"]) == 0
    assert "There's no ticket T-9999" in capsys.readouterr().out
```

Also add `editing` and `set_status` to the existing `from bron.tickets import …` line at the top of `tests/test_runner.py` if they aren't there (the file already imports `add_message, load_ticket, new_ticket, save_ticket, set_result, set_status`; add `editing`).

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_runner.py -q`
Expected: the new tests FAIL (unknown `shown` argument for `start_background`, missing chat prompt, missing `wait_for`, unknown `wait` command); the older tests still pass.

- [ ] **Step 3: Add the chat prompts**

In `core/Engine/bron/runner.py`, after `RESUME_PROMPT`, add:

```python
CHAT_PROMPT = """You are {agent}. The user is talking to you directly from a chat in this Bron vault (chat ticket {id}).

## Earlier in the chat
{context}

## The user's message
{request}{later}

Reply to the user directly, in your own voice: your final reply is shown to them word for word, so make it the answer itself, with nothing about tickets. Don't look around the vault unless the message needs it.
If something needs the user's OK (sending, sharing, deleting, pushing, or anything on your ask-before list), don't do it and don't look for a way around it. Run
.bron/bin/bron ticket status {id} blocked --as {key} --note '{needs_ok} <the exact action, with every detail needed to do it>'
and stop. Put the text in single quotes; if the text contains a single quote, write it to a file and use `--file` (result) or `--note-file` (status)."""

CHAT_RESUME_PROMPT = """The user replied in the chat (ticket {id}):
{messages}

Reply to them directly, the same way as before: your final reply is shown to them word for word. For anything that needs their OK, mark the ticket blocked with '{needs_ok} …' and stop."""
```

- [ ] **Step 4: Choose the prompt by ticket kind**

In `run_ticket`, replace the block that builds `prompt` (from `if session:` through the closing `)` of `TASK_PROMPT.format(...)`) with:

```python
        if session:
            new = ticket.thread[int(previous.get("thread_len", 0)):]
            template = CHAT_RESUME_PROMPT if ticket.kind == "chat" else RESUME_PROMPT
            prompt = template.format(id=tid, messages="\n".join(new) or "(no new messages; carry on)", needs_ok=NEEDS_OK, key=agent.key)
        elif ticket.kind == "chat":
            later = [entry for entry in ticket.thread if " · you: " in entry]
            prompt = CHAT_PROMPT.format(
                agent=agent.name,
                id=tid,
                key=agent.key,
                request=ticket.request or "(none)",
                context=ticket.context or "(none)",
                later=("\n\nLater messages:\n" + "\n".join(later)) if later else "",
                needs_ok=NEEDS_OK,
            )
        else:
            prompt = TASK_PROMPT.format(
                agent=agent.name,
                id=tid,
                key=agent.key,
                title=ticket.title,
                path=ticket.path.relative_to(vault.root),
                request=ticket.request or "(none)",
                context=ticket.context or "(none)",
                needs_ok=NEEDS_OK,
            )
```

- [ ] **Step 5: Keep chat replies in the Thread**

In `_settle`, replace

```python
        elif text.strip():
            set_result(ticket, text, agent.key)
```

with

```python
        elif text.strip():
            if ticket.kind == "chat":
                # The chat ticket is the conversation's record: every reply goes in the Thread.
                add_message(ticket, agent.key, text)
                ticket.result = text.strip()
                ticket.status = "in-review"
                ticket.invalid.pop("status", None)
            else:
                set_result(ticket, text, agent.key)
```

- [ ] **Step 6: `shown` background runs**

Replace `start_background` with:

```python
def start_background(
    vault: Vault,
    ticket_id: str,
    *,
    caller_cli: str | None = None,
    resume: bool = False,
    shown: bool = False,
    popen=subprocess.Popen,
) -> int:
    """Start `bron run` detached (its own session, so it outlives the caller). `shown`: the caller shows the outcome itself."""
    tid = normalize_id(ticket_id)
    log = vault.bron_dir / "runs" / f"background-{tid}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = [str(vault.bron_command), "run", tid]
    if caller_cli:
        argv += ["--caller-cli", caller_cli]
    if resume:
        argv.append("--resume")
    if shown:
        argv.append("--shown")
    with open(log, "a", encoding="utf-8") as out:
        process = popen(argv, cwd=vault.root, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    return process.pid
```

In `core/Engine/bron/cli.py`, after the `when.add_argument("--wait", …)` line, add:

```python
    p_run.add_argument("--shown", action="store_true", help=argparse.SUPPRESS)
```

(add `import argparse` at the top of `cli.py` if it isn't imported), and in `_run` change the `run_ticket(...)` call to:

```python
    outcome = run_ticket(vault, args.id, caller_cli=args.caller_cli, resume=args.resume, shown=args.wait or args.shown)
```

- [ ] **Step 7: Waiting for runs**

Add to `core/Engine/bron/runner.py` (after `start_background`), and add `read_lock` to the existing `from .locks import …` line if it isn't imported:

```python
def describe_outcome(cfg, ticket) -> str:
    """What the requester shows: the agent's reply, or why it stopped."""
    agent = cfg.agents.get(slug(ticket.assignee))
    name = agent.name if agent else ticket.assignee
    if ticket.status == "in-review":
        return f"{name}: {ticket.result}" if ticket.result else f"{ticket.id} is in-review ({name}) without an answer."
    if ticket.status == "blocked":
        last = ticket.thread[-1] if ticket.thread else ""
        marker = "status → blocked: "
        note = last.split(marker, 1)[1] if marker in last else last.split(": ", 1)[-1]
        return f"{ticket.id} is blocked ({name}): {note}"
    return f"{ticket.id} is {ticket.status} ({name})."


def wait_for(vault: Vault, ticket_ids: list[str], *, grace: float = 15.0, poll: float = 0.5, sleep=time.sleep, now=time.time) -> list[str]:
    """Wait until each ticket's run has finished, then describe it. A run that hasn't taken its lock gets `grace` seconds."""
    cfg = load(vault)
    limit = cfg.settings.max_minutes * 60 + 60
    start = now()
    out: list[str] = []
    for raw in ticket_ids:
        try:
            tid = normalize_id(raw)
        except TicketError as exc:
            out.append(str(exc))
            continue
        while True:
            try:
                ticket = load_ticket(find_ticket(vault, tid))
            except TicketError as exc:
                out.append(str(exc))
                break
            running = read_lock(vault, tid) is not None
            if not running and ticket.status not in ("todo", "in-progress"):
                out.append(describe_outcome(cfg, ticket))
                break
            waited = now() - start
            if not running and waited > grace:
                if ticket.status == "todo":
                    out.append(f"{tid} hasn't started; see .bron/runs/background-{tid}.log")
                else:
                    out.append(f"{tid} stopped before it finished; see .bron/runs/")
                break
            if waited > limit:
                out.append(f"{tid} is still running after {cfg.settings.max_minutes} minutes; check it later with `.bron/bin/bron ticket show {tid}`.")
                break
            sleep(poll)
    return out
```

In `core/Engine/bron/tickets_cli.py`, in `add_parser` after the `listing` parser, add:

```python
    wait = commands.add_parser("wait", help="wait for tickets' runs to finish and print each answer")
    wait.add_argument("ids", nargs="+")
```

and in `handle`, before `if command == "list":`, add:

```python
        if command == "wait":
            from . import runner

            print("\n\n".join(runner.wait_for(vault, args.ids)))
            return 0
```

- [ ] **Step 8: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests/test_runner.py -q`, then `uv run --project core/Engine pytest tests -q`.
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add core/Engine/bron/runner.py core/Engine/bron/cli.py core/Engine/bron/tickets_cli.py tests/test_runner.py
git commit -m "feat: chat runs, shown background runs and 'bron ticket wait'" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The message trigger routes @-mentions

**Files:**
- Modify: `core/Engine/bron/mentions.py` (add `route`, `routing_note`)
- Modify: `core/Engine/bron/hooks.py` (user-prompt, session-end, session-start)
- Modify: `core/Templates/AGENTS.md.tmpl`, `core/Manual/tickets.md`
- Test: `tests/test_mentions_hook.py`, `tests/test_handoff_content.py` (append)

**Interfaces:**
- Consumes: Task 1 `transcript.recent_exchanges`; Task 2 `tagged_agents`, `open_chat`, `start_chat`, `close_session_chats`, `close_stale_chats`; Task 3 `runner.start_background(..., shown=True)`.
- Produces: `mentions.route(vault, *, cli: str, prompt: str, session_id: str, transcript_path: str) -> str`; `mentions.routing_note(started: list[tuple[Agent, Ticket]], failed: list[str]) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mentions_hook.py`:

```python
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
    assert started == [("T-0001", {"caller_cli": "claude", "resume": False, "shown": True})]
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
    assert started[-1] == ("T-0001", {"caller_cli": "claude", "resume": True, "shown": True})


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
```

Append to `tests/test_handoff_content.py`:

```python
def test_the_rules_and_manual_explain_tagged_chats(vault):
    rules = render_agents_md(load(vault))
    assert "don't answer for them: wait with `.bron/bin/bron ticket wait <id>`" in rules
    manual = (vault.core_manual / "tickets.md").read_text(encoding="utf-8")
    assert "## Chats with @-mentions" in manual and "`.bron/bin/bron ticket wait <id>`" in manual
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_mentions_hook.py tests/test_handoff_content.py -q`
Expected: FAIL (no routing yet; `route` missing; rules/manual text missing).

- [ ] **Step 3: Routing**

Append to `core/Engine/bron/mentions.py` (add `import os` to its imports):

```python
def route(vault: Vault, *, cli: str, prompt: str, session_id: str, transcript_path: str) -> str:
    """Start every agent the message tags and tell the session's agent what to do ('' when nothing is tagged)."""
    from . import runner
    from .loader import load
    from .transcript import recent_exchanges

    cfg = load(vault)
    self_key = slug(os.environ.get("BRON_AGENT") or cfg.settings.default_agent)
    agents = tagged_agents(prompt, cfg.agents, self_key)
    if not agents:
        return ""
    session = f"{cli}:{session_id}" if session_id else ""
    requester = self_key if self_key in cfg.agents else "you"
    speaker = cfg.agents[self_key].name if self_key in cfg.agents else "Assistant"
    context: str | None = None
    started: list[tuple[Agent, Ticket]] = []
    failed: list[str] = []
    for agent in agents:
        try:
            if context is None and open_chat(vault, session, agent.key) is None:
                context = recent_exchanges(cli, transcript_path, prompt, assistant=speaker)
            ticket, follow_up = start_chat(vault, agent=agent, requester=requester, session=session, message=prompt, context=context or "")
        except (TicketError, OSError) as exc:
            failed.append(f"Couldn't pass the message to @{agent.name} ({exc}); tell the user.")
            continue
        try:
            runner.start_background(vault, ticket.id, caller_cli=cli, resume=follow_up, shown=True)
        except OSError as exc:
            try:
                with editing(vault, ticket.id) as current:
                    set_status(current, "blocked", "runner", f"Bron couldn't start {agent.name} ({exc})")
            except (TicketError, OSError):
                pass
            failed.append(f"Couldn't start @{agent.name} ({exc}); tell the user.")
            continue
        started.append((agent, ticket))
    return routing_note(started, failed)


def routing_note(started: list[tuple[Agent, Ticket]], failed: list[str]) -> str:
    lines: list[str] = []
    if started:
        names = ", ".join(f"@{agent.name}" for agent, _ in started)
        ids = " ".join(ticket.id for _, ticket in started)
        one = len(started) == 1
        lines += [
            f"{names} {'is' if one else 'are'} answering this message (chat {'ticket' if one else 'tickets'} {ids}). Don't answer it yourself.",
            f"Run `.bron/bin/bron ticket wait {ids}` as an ordinary command and wait for it (give it a 10-minute timeout if your command tool takes one). "
            f"Then show each reply word for word, starting with the agent's name in bold, like **{started[0][0].name}:**. "
            "You may add one short note of your own after the replies if it helps.",
            "If a reply says a ticket is blocked with 'Needs your OK', follow the delegate skill. If an agent couldn't run, tell the user plainly what the note says.",
        ]
    lines += failed
    return "\n".join(lines) + "\n" if lines else ""
```

- [ ] **Step 4: Wire the triggers**

In `core/Engine/bron/hooks.py`:

1. Replace the QUICK branch of `main`:

```python
        if event in QUICK:
            payload = _payload(stdin)
            _marker(event, cli, payload)
            if event == "session-end":
                _close_chats(cli, payload)
```

2. Replace the `user-prompt` branch:

```python
        elif event == "user-prompt":
            payload = _payload(stdin)
            text = _route(cli, payload) + _ticket_updates()
            if text:
                try:
                    stdout.write(text)
                except Exception:  # noqa: BLE001
                    pass
```

3. In `_session_start`, after the `recover_orphans` try/except block, add:

```python
    try:
        from .mentions import close_stale_chats

        close_stale_chats(vault)
    except Exception as exc:  # noqa: BLE001 - best effort, never fails the briefing
        _log_error("session-start", cli, exc)
```

4. Add these functions after `_ticket_updates`:

```python
def _route(cli: str, payload: dict) -> str:
    """@-mentions: start the tagged agents now and tell the session's agent to wait for them."""
    if os.environ.get("BRON_TICKET"):
        return ""  # a headless ticket run never routes
    prompt = str(payload.get("prompt") or "")
    if "@" not in prompt:
        return ""
    from . import mentions
    from .vault import Vault, VaultNotFound

    try:
        vault = Vault.find()
    except VaultNotFound:
        return ""
    try:
        return mentions.route(
            vault,
            cli=cli,
            prompt=prompt,
            session_id=str(payload.get("session_id") or ""),
            transcript_path=str(payload.get("transcript_path") or ""),
        )
    except Exception as exc:  # noqa: BLE001 - a trigger must never fail the message
        _log_error("user-prompt", cli, exc)
        return f"Bron couldn't pass the @-mention on this time ({exc.__class__.__name__}); answer the message yourself and say so.\n"


def _close_chats(cli: str, payload: dict) -> None:
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        return
    try:
        from .mentions import close_session_chats
        from .vault import Vault

        close_session_chats(Vault.find(), f"{cli}:{session_id}")
    except Exception as exc:  # noqa: BLE001
        _log_error("session-end", cli, exc)
```

- [ ] **Step 5: Tell agents and document it**

In `core/Templates/AGENTS.md.tmpl`, in the `## Tickets` section, after the line starting `- Quick question or short task for a team member:`, add:

```markdown
- When the message trigger says a tagged agent (`@name`) is answering, don't answer for them: wait with `.bron/bin/bron ticket wait <id>` and show their reply word for word.
```

In `core/Manual/tickets.md`, add after the `## Commands (from the vault folder)` list's last bullet:

```markdown
- `.bron/bin/bron ticket wait <id> [<id> …]`: wait for those tickets' runs to finish and print each answer
```

and add a section before `` `Tickets/Board.base` shows…``:

```markdown
## Chats with @-mentions
Write `@cfo` (any agent's name) in a message in any session and that agent answers it. The message trigger starts the agent straight away, with your message and the last few exchanges of the chat, on its own model and CLI. The session's agent waits with `.bron/bin/bron ticket wait <id>` and shows the reply word for word. Follow-ups to the same agent in the same session continue the same conversation. Tag several agents and each answers separately. Each conversation is a chat ticket (`kind: chat`), hidden from the board's main views, closed when the session ends (or after 12 hours without activity). A message without a tag goes to the session's own agent.
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests/test_mentions_hook.py tests/test_hooks.py tests/test_handoff_content.py -q`, then `uv run --project core/Engine pytest tests -q`.
Expected: all pass (`test_user_prompt_is_silent_for_now` still passes: its vault has no CFO, so `@cfo` isn't a tag).

- [ ] **Step 7: Commit**

```bash
git add core/Engine/bron/mentions.py core/Engine/bron/hooks.py core/Templates/AGENTS.md.tmpl core/Manual/tickets.md tests/test_mentions_hook.py tests/test_handoff_content.py
git commit -m "feat: @-mentions start the tagged agent from the message trigger" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Routines core

**Files:**
- Create: `core/Engine/bron/routines.py`
- Test: `tests/test_routines.py`

**Interfaces:**
- Produces (all in `bron.routines`):
  - `CADENCES`, `ONCE = "once"`, `TRACKING = "Tracking.md"`, `class RoutineError(ValueError)`
  - `@dataclass Step(name: str, for_: str = ONCE, after: list[str], items: list[str])`
  - `@dataclass Runbook(name, path, cadence, owner="", due="", lists: dict[str, list[str] | str], steps: list[Step])` with property `folder`
  - `@dataclass TrackingState(meta: dict, status: str, progress: str)`
  - `load_runbooks(vault) -> tuple[list[Runbook], list[Issue]]`
  - `period_of(cadence, day: date) -> str`, `period_bounds(cadence, name) -> tuple[date, date]` (ValueError on a bad name), `last_ended(cadence, today: date) -> str`, `due_date(rule: str, period_end: date) -> date | None`
  - `parse_list_items(text: str) -> list[tuple[str, str]]` (group, item)
  - `start_period(vault, runbook, period: str, lists: dict[str, list[tuple[str, str]]]) -> Path`
  - `read_steps(path) -> tuple[dict, list[StepCount]]`, `refresh_tracking(path, runbook) -> TrackingState`, `tracking_notes(runbook) -> list[Path]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_routines.py`:

```python
import copy
import os
from datetime import date

import pytest

from bron import frontmatter as fm
from bron.routines import (
    RoutineError,
    due_date,
    last_ended,
    load_runbooks,
    parse_list_items,
    period_bounds,
    period_of,
    refresh_tracking,
    start_period,
)
from vaultkit import write_md

RUNBOOK = {
    "cadence": "quarterly",
    "owner": "bron",
    "due": "45 days after period end",
    "lists": {
        "companies": "active portfolio companies of each fund in Carta (FMV > 0), grouped by fund",
        "funds": ["Fund I", "Fund II", "Fund III"],
    },
    "steps": [
        {"name": "Collect financials and KPIs", "for": "companies"},
        {"name": "Stacked ranking", "for": "once", "items": ["Sent to the investment team", "Back from the investment team"]},
        {"name": "One-pager", "for": "funds", "after": ["Collect financials and KPIs", "Stacked ranking"]},
    ],
}
COMPANIES = [("Fund I", "Company A"), ("Fund I", "Company B"), ("Fund II", "Company C")]


def add_routine(vault, name="Portco Monitoring", **changes):
    meta = {**copy.deepcopy(RUNBOOK), **changes}
    meta = {k: v for k, v in meta.items() if v is not None}
    return write_md(vault.routines_dir / name / "Runbook.md", meta, "## How to do each step\n")


def runbook(vault):
    runbooks, _ = load_runbooks(vault)
    return runbooks[0]


def test_a_runbook_loads(vault):
    add_routine(vault)
    runbooks, issues = load_runbooks(vault)
    rb = runbooks[0]
    assert issues == []
    assert rb.name == "Portco Monitoring" and rb.cadence == "quarterly" and rb.owner == "bron"
    assert [s.name for s in rb.steps] == ["Collect financials and KPIs", "Stacked ranking", "One-pager"]
    assert rb.steps[2].after == ["Collect financials and KPIs", "Stacked ranking"] and rb.steps[0].for_ == "companies"
    assert rb.lists["funds"] == ["Fund I", "Fund II", "Fund III"] and isinstance(rb.lists["companies"], str)


def test_runbook_problems_are_reported(vault):
    add_routine(vault, "Weekly", cadence="weekly")
    add_routine(vault, "Broken", owner=None, steps=[
        {"name": "A", "for": "missing"},
        {"name": "B", "after": ["C"]},
        {"name": "C"},
        {"name": "c"},
        {"for": "funds"},
    ])
    runbooks, issues = load_runbooks(vault)
    assert [rb.name for rb in runbooks] == ["Broken"]
    codes = {issue.code for issue in issues}
    assert {"routine.cadence", "routine.step-list", "routine.step-after", "routine.step-duplicate", "routine.step", "routine.owner"} <= codes
    assert next(i for i in issues if i.code == "routine.owner").level == "warning"


def test_periods():
    assert period_of("monthly", date(2026, 9, 30)) == "2026-09"
    assert period_of("quarterly", date(2026, 10, 1)) == "2026-Q4"
    assert period_of("annual", date(2026, 3, 1)) == "2026"
    assert period_bounds("quarterly", "2026-Q3") == (date(2026, 7, 1), date(2026, 9, 30))
    assert period_bounds("monthly", "2026-12") == (date(2026, 12, 1), date(2026, 12, 31))
    assert period_bounds("monthly", "2026-02") == (date(2026, 2, 1), date(2026, 2, 28))
    assert period_bounds("annual", "2025") == (date(2025, 1, 1), date(2025, 12, 31))
    assert last_ended("quarterly", date(2026, 10, 1)) == "2026-Q3"
    assert last_ended("monthly", date(2026, 1, 15)) == "2025-12"
    assert last_ended("annual", date(2026, 3, 1)) == "2025"
    for cadence, name in (("quarterly", "2026-Q5"), ("monthly", "2026-13"), ("annual", "26"), ("quarterly", "2026-09")):
        with pytest.raises(ValueError):
            period_bounds(cadence, name)


def test_due_dates():
    assert due_date("45 days after period end", date(2026, 9, 30)) == date(2026, 11, 14)
    assert due_date("1 day after the period end", date(2026, 9, 30)) == date(2026, 10, 1)
    assert due_date("before the quarterly meeting", date(2026, 9, 30)) is None
    assert due_date("", date(2026, 9, 30)) is None


def test_list_files():
    text = "Fund I: Company A\n- Fund I: Company B\n\n# a note\nCompany C\n"
    assert parse_list_items(text) == [("Fund I", "Company A"), ("Fund I", "Company B"), ("", "Company C")]


def test_starting_a_period_writes_the_tracking_note(vault):
    add_routine(vault)
    path = start_period(vault, runbook(vault), "2026-Q3", {"companies": COMPANIES})
    assert path == vault.routines_dir / "Portco Monitoring" / "2026-Q3" / "Tracking.md"
    doc = fm.read(path)
    assert doc.meta["routine"] == "Portco Monitoring" and doc.meta["period"] == "2026-Q3"
    assert str(doc.meta["due"]) == "2026-11-14" and doc.meta["status"] == "todo"
    assert doc.meta["progress"] == "Collect financials and KPIs 0/3 · Stacked ranking 0/2 · One-pager waiting"
    assert doc.body == (
        "## Collect financials and KPIs\n### Fund I\n- [ ] Company A\n- [ ] Company B\n### Fund II\n- [ ] Company C\n\n"
        "## Stacked ranking\n- [ ] Sent to the investment team\n- [ ] Back from the investment team\n\n"
        "## One-pager\n- [ ] Fund I\n- [ ] Fund II\n- [ ] Fund III\n"
    )


def test_starting_needs_source_lists_a_valid_period_and_happens_once(vault):
    add_routine(vault)
    rb = runbook(vault)
    with pytest.raises(RoutineError, match="comes from a source"):
        start_period(vault, rb, "2026-Q3", {})
    with pytest.raises(RoutineError, match="isn't a quarterly period"):
        start_period(vault, rb, "2026-Q5", {"companies": COMPANIES})
    with pytest.raises(RoutineError, match="is empty"):
        start_period(vault, rb, "2026-Q3", {"companies": []})
    start_period(vault, rb, "2026-Q3", {"companies": COMPANIES})
    with pytest.raises(RoutineError, match="has already started"):
        start_period(vault, rb, "2026-Q3", {"companies": COMPANIES})


def tick(path, *items):
    text = path.read_text(encoding="utf-8")
    for item in items:
        text = text.replace(f"- [ ] {item}\n", f"- [x] {item}\n", 1)
    path.write_text(text, encoding="utf-8")


def test_progress_counts_ticks_groups_and_waiting_steps(vault):
    add_routine(vault)
    rb = runbook(vault)
    path = start_period(vault, rb, "2026-Q3", {"companies": COMPANIES})
    text = path.read_text(encoding="utf-8")
    text = text.replace("- [ ] Company A\n", "- [x] Company A: received 12 Oct\n").replace("- [ ] Company C\n", "* [X] Company C\n")
    path.write_text(text, encoding="utf-8")
    tick(path, "Sent to the investment team", "Back from the investment team")
    body = fm.read(path).body
    state = refresh_tracking(path, rb)
    assert state.status == "in-progress"
    assert state.progress == "Collect financials and KPIs 2/3 · Stacked ranking 2/2 · One-pager waiting"
    assert fm.read(path).meta["progress"] == state.progress and fm.read(path).body == body
    tick(path, "Company B")
    assert refresh_tracking(path, rb).progress == "Collect financials and KPIs 3/3 · Stacked ranking 2/2 · One-pager 0/3"
    tick(path, "Fund I", "Fund II", "Fund III")
    assert refresh_tracking(path, rb).status == "done"


def test_refresh_only_writes_when_something_changed(vault):
    add_routine(vault)
    rb = runbook(vault)
    path = start_period(vault, rb, "2026-Q3", {"companies": COMPANIES})
    refresh_tracking(path, rb)
    before = os.stat(path).st_mtime_ns
    refresh_tracking(path, rb)
    assert os.stat(path).st_mtime_ns == before


def test_a_runbook_without_steps_is_one_checklist(vault):
    write_md(vault.routines_dir / "Board Pack" / "Runbook.md", {"cadence": "monthly", "owner": "bron", "lists": {"items": ["Deck", "Minutes"]}})
    rb = runbook(vault)
    path = start_period(vault, rb, "2026-09", {})
    assert fm.read(path).body == "## Board Pack\n- [ ] Deck\n- [ ] Minutes\n"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_routines.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'bron.routines'`.

- [ ] **Step 3: Write the module**

Create `core/Engine/bron/routines.py`:

```python
"""Routines: repeating work tracked per period (Routines/<Routine>/Runbook.md and <Period>/Tracking.md)."""
from __future__ import annotations

import calendar
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import frontmatter as fm
from .model import Issue
from .vault import Vault

CADENCES = ("monthly", "quarterly", "annual")
ONCE = "once"
TRACKING = "Tracking.md"
_DUE = re.compile(r"^\s*(\d+)\s+days?\s+after\s+(?:the\s+)?period\s+end\s*$", re.I)
_BOX = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+")


class RoutineError(ValueError):
    """A routine problem to show the user as it is."""


@dataclass
class Step:
    name: str
    for_: str = ONCE
    after: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)


@dataclass
class Runbook:
    name: str
    path: Path
    cadence: str
    owner: str = ""
    due: str = ""
    lists: dict[str, list[str] | str] = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)

    @property
    def folder(self) -> Path:
        return self.path.parent


@dataclass
class StepCount:
    name: str
    done: int = 0
    total: int = 0


@dataclass
class TrackingState:
    meta: dict
    status: str
    progress: str


# ---- runbooks ----

def load_runbooks(vault: Vault) -> tuple[list[Runbook], list[Issue]]:
    runbooks: list[Runbook] = []
    issues: list[Issue] = []
    folder = vault.routines_dir
    if not folder.is_dir():
        return runbooks, issues
    for sub in sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")):
        path = sub / "Runbook.md"
        if not path.is_file():
            continue
        try:
            meta = fm.read(path).meta
        except (fm.FrontmatterError, OSError, UnicodeDecodeError) as exc:
            issues.append(Issue("error", "routine.unreadable", f"Bron can't read this runbook: {exc}", path))
            continue
        runbook = _runbook(sub.name, path, meta, issues)
        if runbook is not None:
            runbooks.append(runbook)
    return runbooks, issues


def _names(value) -> list[str] | None:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list) and all(isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in value):
        return [str(v).strip() for v in value if str(v).strip()]
    return None


def _runbook(name: str, path: Path, meta: dict, issues: list[Issue]) -> Runbook | None:
    def bad(code: str, message: str, level: str = "error") -> None:
        issues.append(Issue(level, code, message, path))

    cadence = str(meta.get("cadence") or "").strip().lower()
    if cadence not in CADENCES:
        bad("routine.cadence", f"'cadence' should be monthly, quarterly or annual (it is '{meta.get('cadence') or ''}')")
        return None
    lists: dict[str, list[str] | str] = {}
    raw_lists = meta.get("lists") or {}
    if not isinstance(raw_lists, dict):
        bad("routine.lists", "'lists' should name each list, like 'funds: [Fund I, Fund II]'")
        raw_lists = {}
    for key, value in raw_lists.items():
        if isinstance(value, str) and value.strip():
            lists[str(key)] = value.strip()
        elif (items := _names(value)) is not None and isinstance(value, list):
            lists[str(key)] = items
        else:
            bad("routine.lists", f"The list '{key}' should be a list of items or a sentence saying where its items come from")
    steps: list[Step] = []
    raw_steps = meta.get("steps")
    if raw_steps is None:
        steps = [Step(name=name, for_=next(iter(lists), ONCE))]
    elif not isinstance(raw_steps, list):
        bad("routine.step", "'steps' should be a list of steps, each with a name")
    else:
        seen: list[str] = []
        for index, raw in enumerate(raw_steps, 1):
            if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
                bad("routine.step", f"Step {index} needs a name")
                continue
            step_name = str(raw["name"]).strip()
            if step_name.lower() in (s.lower() for s in seen):
                bad("routine.step-duplicate", f"Two steps are called '{step_name}'")
                continue
            for_ = str(raw.get("for") or ONCE).strip()
            if for_ != ONCE and for_ not in lists:
                bad("routine.step-list", f"The step '{step_name}' is done for '{for_}', which isn't one of the lists")
            after = _names(raw.get("after"))
            if after is None:
                bad("routine.step-after", f"'after' in the step '{step_name}' should be a list of earlier steps")
                after = []
            for other in after:
                if other.lower() not in (s.lower() for s in seen):
                    bad("routine.step-after", f"The step '{step_name}' waits for '{other}', which isn't an earlier step")
            items = _names(raw.get("items")) or []
            steps.append(Step(step_name, for_, after, items))
            seen.append(step_name)
    owner = str(meta.get("owner") or "").strip()
    if not owner:
        bad("routine.owner", f"The routine '{name}' has no 'owner'; the default agent looks after it", "warning")
    return Runbook(name, path, cadence, owner, str(meta.get("due") or "").strip(), lists, steps)


# ---- periods ----

def period_of(cadence: str, day: date) -> str:
    if cadence == "monthly":
        return f"{day.year}-{day.month:02d}"
    if cadence == "quarterly":
        return f"{day.year}-Q{(day.month - 1) // 3 + 1}"
    return f"{day.year}"


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def period_bounds(cadence: str, name: str) -> tuple[date, date]:
    """First and last day of a period ('2026-09', '2026-Q3', '2026'). ValueError for a name that doesn't fit."""
    patterns = {"monthly": r"(\d{4})-(\d{2})", "quarterly": r"(\d{4})-Q([1-4])", "annual": r"(\d{4})"}
    match = re.fullmatch(patterns.get(cadence, "$^"), name.strip())
    if not match:
        raise ValueError(f"'{name}' isn't a {cadence} period")
    year = int(match.group(1))
    if cadence == "annual":
        return date(year, 1, 1), date(year, 12, 31)
    number = int(match.group(2))
    if cadence == "monthly":
        if not 1 <= number <= 12:
            raise ValueError(f"'{name}' isn't a {cadence} period")
        return date(year, number, 1), _month_end(year, number)
    first = 3 * (number - 1) + 1
    return date(year, first, 1), _month_end(year, first + 2)


def last_ended(cadence: str, today: date) -> str:
    """The latest period that has ended: the one to run now (Q3's run starts on 1 October)."""
    start, _ = period_bounds(cadence, period_of(cadence, today))
    return period_of(cadence, start - timedelta(days=1))


def due_date(rule: str, period_end: date) -> date | None:
    match = _DUE.match(rule or "")
    return period_end + timedelta(days=int(match.group(1))) if match else None


# ---- tracking notes ----

def parse_list_items(text: str) -> list[tuple[str, str]]:
    """One item per line, optionally 'Group: item'. Blank lines and '# notes' are skipped."""
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if not line or line.startswith("#"):
            continue
        group, sep, item = line.partition(": ")
        out.append((group.strip(), item.strip()) if sep and group.strip() and item.strip() else ("", line))
    return out


def _step_lines(step: Step, items: list[tuple[str, str]]) -> list[str]:
    lines = [f"## {step.name}"]
    group = ""
    for item_group, item in items:
        if item_group != group:
            if item_group:
                lines.append(f"### {item_group}")
            group = item_group
        lines.append(f"- [ ] {item}")
    return lines


def start_period(vault: Vault, runbook: Runbook, period: str, lists: dict[str, list[tuple[str, str]]]) -> Path:
    """Create <Routine>/<period>/Tracking.md with one checklist per step."""
    try:
        _, end = period_bounds(runbook.cadence, period)
    except ValueError as exc:
        raise RoutineError(str(exc)) from exc
    path = runbook.folder / period / TRACKING
    if path.exists():
        raise RoutineError(f"{runbook.name} {period} has already started ({path.relative_to(vault.root)})")
    sections: list[str] = []
    for step in runbook.steps:
        if step.for_ == ONCE:
            items = [("", item) for item in (step.items or [step.name])]
        elif step.for_ in lists:
            items = lists[step.for_]
        elif isinstance(runbook.lists.get(step.for_), list):
            items = [("", item) for item in runbook.lists[step.for_]]
        else:
            source = runbook.lists.get(step.for_, "")
            raise RoutineError(f"The list '{step.for_}' comes from a source ({source}); give it with --list {step.for_}=<file>")
        if not items:
            raise RoutineError(f"The list '{step.for_}' is empty")
        sections.append("\n".join(_step_lines(step, items)))
    meta: dict = {"routine": runbook.name, "period": period, "status": "todo"}
    due = due_date(runbook.due, end)
    if due:
        meta["due"] = due.isoformat()
    meta["progress"] = ""
    fm.write(path, fm.Document(meta, "\n\n".join(sections) + "\n"))
    refresh_tracking(path, runbook)
    return path


def read_steps(path: Path) -> tuple[dict, list[StepCount]]:
    doc = fm.read(path)
    steps: list[StepCount] = []
    for line in doc.body.splitlines():
        if line.startswith("## "):
            steps.append(StepCount(line[3:].strip()))
        elif steps and (match := _BOX.match(line)):
            steps[-1].total += 1
            if match.group(1) in "xX":
                steps[-1].done += 1
    return doc.meta, steps


def refresh_tracking(path: Path, runbook: Runbook) -> TrackingState:
    """Recount the checklists and update status and progress (never the checkboxes). Writes only on change."""
    doc = fm.read(path)
    _, steps = read_steps(path)
    complete = {s.name.lower() for s in steps if s.total and s.done == s.total}
    by_name = {s.name.lower(): s for s in runbook.steps}
    parts: list[str] = []
    for count in steps:
        rule = by_name.get(count.name.lower())
        waiting = rule is not None and count.done == 0 and any(a.lower() not in complete for a in rule.after)
        parts.append(f"{count.name} waiting" if waiting else f"{count.name} {count.done}/{count.total}")
    progress = " · ".join(parts)
    if steps and all(s.total and s.done == s.total for s in steps):
        status = "done"
    elif any(s.done for s in steps):
        status = "in-progress"
    else:
        status = "todo"
    if doc.meta.get("status") != status or doc.meta.get("progress") != progress:
        doc.meta["status"], doc.meta["progress"] = status, progress
        tmp = path.with_name(f"{path.name}.{os.getpid()}.bron-tmp")
        tmp.write_text(fm.dump(doc), encoding="utf-8")
        tmp.replace(path)
    return TrackingState(doc.meta, status, progress)


def tracking_notes(runbook: Runbook) -> list[Path]:
    return sorted(runbook.folder.glob(f"*/{TRACKING}"))
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests/test_routines.py -q`, then `uv run --project core/Engine pytest tests -q`.
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/routines.py tests/test_routines.py
git commit -m "feat: routines core (runbooks, periods, due dates, Tracking notes)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Routines in Bron (commands, briefing, health check, board, skill, manual)

**Files:**
- Modify: `core/Engine/bron/routines.py` (append status/briefing lines)
- Create: `core/Engine/bron/routines_cli.py`
- Modify: `core/Engine/bron/cli.py` (register and dispatch `routine`)
- Modify: `core/Engine/bron/briefing.py` (Routines block; `today` parameter)
- Modify: `core/Engine/bron/check.py` (`_routines`, health check only)
- Create: `template/Routines/Board.base`, `core/Skills/routines/SKILL.md`, `core/Manual/routines.md`
- Modify: `core/Manual/index.md`
- Test: `tests/test_routines_cli.py`; `tests/test_handoff_content.py` (extend the command-parse test)

**Interfaces:**
- Consumes: Task 5's `bron.routines` API.
- Produces:
  - `routines.today() -> date`, `routines.format_day(day: date) -> str` ("14 Nov 2026"), `routines.due_text(value, today) -> str`
  - `routines.find_runbook(runbooks, name) -> Runbook` (RoutineError when missing)
  - `routines.status_lines(runbooks, today) -> list[str]` (for `bron routine list`)
  - `routines.briefing_lines(vault, cfg, agent_key: str, today: date) -> list[str]`
  - `briefing.build_briefing(vault, *, cli, notes=None, changed=(), today: date | None = None)`
  - CLI: `bron routine list`, `bron routine start <name> [--period P] [--list NAME=FILE]…`, `bron routine refresh [<name>]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_routines_cli.py`:

```python
from datetime import date

import yaml

from bron import frontmatter as fm
from bron.briefing import build_briefing
from bron.check import run_checks
from bron.cli import main
from bron.loader import load
from bron.routines import briefing_lines, load_runbooks, start_period
from test_routines import COMPANIES, add_routine, tick
from vaultkit import add_agent


def lines(vault, agent="bron", today=date(2026, 10, 1)):
    return briefing_lines(vault, load(vault), agent, today)


def started(vault):
    rb = load_runbooks(vault)[0][0]
    return rb, start_period(vault, rb, "2026-Q3", {"companies": COMPANIES})


def test_the_briefing_offers_to_start_then_shows_progress_and_due_dates(vault):
    add_routine(vault)
    assert lines(vault) == ["Portco Monitoring 2026-Q3: can start (due 14 Nov 2026). Offer to set it up (routines skill)."]
    _, path = started(vault)
    tick(path, "Company A", "Company C", "Sent to the investment team", "Back from the investment team")
    progress = "Collect financials and KPIs 2/3 · Stacked ranking 2/2 · One-pager waiting"
    assert lines(vault, today=date(2026, 11, 2)) == [f"Portco Monitoring 2026-Q3: {progress}; due in 12 days"]
    assert lines(vault, today=date(2026, 11, 13)) == [f"Portco Monitoring 2026-Q3: {progress}; due tomorrow"]
    assert lines(vault, today=date(2026, 11, 14)) == [f"Portco Monitoring 2026-Q3: {progress}; due today"]
    assert lines(vault, today=date(2026, 11, 17)) == [f"Portco Monitoring 2026-Q3: {progress}; overdue by 3 days"]
    tick(path, "Company B", "Fund I", "Fund II", "Fund III")
    assert lines(vault, today=date(2026, 11, 2)) == []


def test_routines_follow_their_owner(vault):
    add_agent(vault, "CFO")
    add_routine(vault, owner="CFO")
    assert lines(vault, "bron") == [] and len(lines(vault, "cfo")) == 1
    add_routine(vault, "Orphan", owner="Ghost")
    assert [line.split(":")[0] for line in lines(vault, "bron")] == ["Orphan 2026-Q3"]


def test_the_session_briefing_has_a_routines_block_capped_at_eight(vault):
    for index in range(10):
        add_routine(vault, f"Routine {index:02d}")
    text = build_briefing(vault, cli="claude", today=date(2026, 10, 1))
    block = text.split("## Routines\n", 1)[1]
    assert block.startswith("- Routine 00 2026-Q3: can start (due 14 Nov 2026).")
    assert block.count("\n- Routine") == 7 and "- …and 2 more: run `.bron/bin/bron routine list`" in block


def test_routine_commands(vault, monkeypatch, capsys):
    monkeypatch.chdir(vault.root)
    monkeypatch.setattr("bron.routines.today", lambda: date(2026, 10, 1))
    add_routine(vault)
    (vault.root / "companies.txt").write_text("Fund I: Company A\nFund I: Company B\nFund II: Company C\n", encoding="utf-8")
    assert main(["routine", "list"]) == 0
    assert capsys.readouterr().out == "Portco Monitoring 2026-Q3: not started (due 14 Nov 2026)\n"
    assert main(["routine", "start", "portco monitoring", "--list", "companies=companies.txt"]) == 0
    assert capsys.readouterr().out == "Started Portco Monitoring 2026-Q3: Routines/Portco Monitoring/2026-Q3/Tracking.md\n"
    assert main(["routine", "start", "Portco Monitoring", "--period", "2026-Q3", "--list", "companies=companies.txt"]) == 1
    assert "has already started" in capsys.readouterr().out
    assert main(["routine", "list"]) == 0
    assert capsys.readouterr().out == "Portco Monitoring 2026-Q3 [todo] Collect financials and KPIs 0/3 · Stacked ranking 0/2 · One-pager waiting; due in 44 days\n"
    assert main(["routine", "refresh", "Portco Monitoring"]) == 0
    assert "Portco Monitoring 2026-Q3 [todo]" in capsys.readouterr().out
    assert main(["routine", "start", "Nope"]) == 1
    assert capsys.readouterr().out == "There's no routine called 'Nope'. Routines: Portco Monitoring\n"
    assert main(["routine", "start", "Portco Monitoring", "--period", "2026-Q2", "--list", "companies"]) == 1
    assert "--list needs NAME=FILE" in capsys.readouterr().out
    assert main(["routine", "start", "Portco Monitoring", "--period", "2026-Q2", "--list", "companies=missing.txt"]) == 1
    assert "Couldn't read a list file" in capsys.readouterr().out


def test_runbook_problems_show_in_the_health_check_but_never_stop_a_sync(vault):
    add_routine(vault, cadence="weekly")
    add_routine(vault, "Orphan", owner="Ghost")
    cfg = load(vault)
    codes = {issue.code for issue in run_checks(cfg)}
    assert {"routine.cadence", "routine.owner-unknown"} <= codes
    assert not {"routine.cadence", "routine.owner-unknown"} & {i.code for i in run_checks(cfg, include_environment=False)}


def test_the_routines_board_lists_tracking_notes(vault):
    board = yaml.safe_load((vault.routines_dir / "Board.base").read_text(encoding="utf-8"))
    assert 'file.basename == "Tracking"' in str(board["filters"])
    assert board["views"][0]["groupBy"]["property"] == "status"
    assert board["views"][0]["order"] == ["routine", "period", "status", "progress", "due"]


def test_the_routines_skill_and_manual_are_published(vault):
    cfg = load(vault)
    assert "routines" in cfg.skills
    index = (vault.core_manual / "index.md").read_text(encoding="utf-8")
    assert "](routines.md)" in index and (vault.core_manual / "routines.md").is_file()
```

In `tests/test_handoff_content.py`, in `test_quoted_commands_parse`:
- extend the collected text with the routines skill and manual:

```python
    routines_text = (vault.core_skills / "routines" / "SKILL.md").read_text(encoding="utf-8") + "\n" + (vault.core_manual / "routines.md").read_text(encoding="utf-8")
    commands = re.findall(pattern, skill_text + "\n" + manual_text + "\n" + agents_text + "\n" + routines_text)
```

  (replace the existing `commands = re.findall(...)` line with these two lines);
- add to `placeholders`: `"<Routine>": "x", "<period>": "2026-Q3",`.

`tests/test_routines_cli.py` imports helpers from `tests/test_routines.py`; pytest's rootdir import mode already lets tests import `vaultkit`, so `from test_routines import …` works the same way.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_routines_cli.py tests/test_handoff_content.py -q`
Expected: FAIL (`briefing_lines` missing, no `routine` command, no board/skill/manual).

- [ ] **Step 3: Status and briefing lines**

Append to `core/Engine/bron/routines.py` (add `from .model import slug` to its imports):

```python
# ---- what's due ----

def today() -> date:
    return date.today()


def format_day(day: date) -> str:
    return f"{day.day} {day.strftime('%b %Y')}"


def _as_date(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def due_text(value, today_: date) -> str:
    due = _as_date(value)
    if due is None:
        return ""
    days = (due - today_).days
    if days > 1:
        return f"; due in {days} days"
    if days == 1:
        return "; due tomorrow"
    if days == 0:
        return "; due today"
    return f"; overdue by {-days} day{'s' if days < -1 else ''}"


def find_runbook(runbooks: list[Runbook], name: str) -> Runbook:
    for runbook in runbooks:
        if runbook.name.lower() == name.strip().lower():
            return runbook
    known = ", ".join(r.name for r in runbooks) or "none yet"
    raise RoutineError(f"There's no routine called '{name}'. Routines: {known}")


def _period_lines(runbook: Runbook, today_: date, *, briefing: bool) -> list[str]:
    out: list[str] = []
    for path in tracking_notes(runbook):
        period = path.parent.name
        try:
            state = refresh_tracking(path, runbook)
        except (fm.FrontmatterError, OSError, UnicodeDecodeError):
            out.append(f"{runbook.name} {period}: its Tracking note can't be read (Routines/{runbook.folder.name}/{period}/{TRACKING})")
            continue
        due = due_text(state.meta.get("due"), today_) if state.status != "done" else ""
        if briefing:
            if state.status != "done":
                out.append(f"{runbook.name} {period}: {state.progress}{due}")
        else:
            out.append(f"{runbook.name} {period} [{state.status}] {state.progress}{due}")
    period = last_ended(runbook.cadence, today_)
    if not (runbook.folder / period / TRACKING).exists():
        due = due_date(runbook.due, period_bounds(runbook.cadence, period)[1])
        when = f" (due {format_day(due)})" if due else ""
        if briefing:
            out.append(f"{runbook.name} {period}: can start{when}. Offer to set it up (routines skill).")
        else:
            out.append(f"{runbook.name} {period}: not started{when}")
    return out


def status_lines(runbooks: list[Runbook], today_: date) -> list[str]:
    return [line for runbook in runbooks for line in _period_lines(runbook, today_, briefing=False)]


def briefing_lines(vault: Vault, cfg, agent_key: str, today_: date) -> list[str]:
    """Due and in-progress periods of the routines this agent owns (the default agent also gets ownerless ones)."""
    runbooks, _ = load_runbooks(vault)
    default_key = cfg.default_agent.key if cfg.default_agent else ""
    out: list[str] = []
    for runbook in runbooks:
        owner = slug(runbook.owner) if runbook.owner else ""
        if owner == agent_key or (agent_key == default_key and owner not in cfg.agents):
            out += _period_lines(runbook, today_, briefing=True)
    return out
```

- [ ] **Step 4: The `routine` command**

Create `core/Engine/bron/routines_cli.py`:

```python
"""`bron routine …`: look after repeating work."""
from __future__ import annotations

from pathlib import Path


def add_parser(sub) -> None:
    parser = sub.add_parser("routine", help="routines: repeating work tracked per period")
    commands = parser.add_subparsers(dest="routine_command", required=True)
    commands.add_parser("list", help="each routine's periods, progress and due dates")
    start = commands.add_parser("start", help="start a period: create its folder and Tracking note")
    start.add_argument("name")
    start.add_argument("--period", default="")
    start.add_argument("--list", dest="lists", action="append", default=[], metavar="NAME=FILE")
    refresh = commands.add_parser("refresh", help="recount progress in the Tracking notes")
    refresh.add_argument("name", nargs="?", default="")


def handle(args, vault) -> int:
    from . import routines

    runbooks, issues = routines.load_runbooks(vault)
    try:
        if args.routine_command == "list":
            if not runbooks and not issues:
                print("No routines yet. Each routine is a folder in Routines/ with a Runbook.md.")
            for line in routines.status_lines(runbooks, routines.today()):
                print(line)
            for issue in issues:
                print("  " + issue.render(vault.root))
            return 0
        if args.routine_command == "refresh":
            chosen = [routines.find_runbook(runbooks, args.name)] if args.name else runbooks
            for runbook in chosen:
                for path in routines.tracking_notes(runbook):
                    state = routines.refresh_tracking(path, runbook)
                    print(f"{runbook.name} {path.parent.name} [{state.status}] {state.progress}")
            return 0
        runbook = routines.find_runbook(runbooks, args.name)
        period = args.period.strip() or routines.last_ended(runbook.cadence, routines.today())
        lists = {}
        for spec in args.lists:
            name, sep, file = spec.partition("=")
            if not sep or not name.strip() or not file.strip():
                raise routines.RoutineError(f"--list needs NAME=FILE, like companies=companies.txt (got '{spec}')")
            lists[name.strip()] = routines.parse_list_items(Path(file.strip()).read_text(encoding="utf-8"))
        path = routines.start_period(vault, runbook, period, lists)
    except routines.RoutineError as exc:
        print(exc)
        return 1
    except OSError as exc:
        print(f"Couldn't read a list file ({exc})")
        return 1
    print(f"Started {runbook.name} {period}: {path.relative_to(vault.root)}")
    return 0
```

In `core/Engine/bron/cli.py`, in `build_parser`, next to `tickets_cli.add_parser(sub)`:

```python
    from . import routines_cli, tickets_cli

    tickets_cli.add_parser(sub)
    routines_cli.add_parser(sub)
```

(replace the existing `from . import tickets_cli` + `tickets_cli.add_parser(sub)` lines), and in `main`, next to the `ticket` dispatch:

```python
    if args.command == "routine":
        from . import routines_cli

        return routines_cli.handle(args, vault)
```

- [ ] **Step 5: Briefing block**

In `core/Engine/bron/briefing.py`:
- add `from datetime import date` to the imports;
- change the signature to `def build_briefing(vault: Vault, *, cli: str, notes: list[str] | None = None, changed: list[str] | tuple = (), today: date | None = None) -> str:`;
- after the Tickets `try/except` block and before `summary = vault.memory_dir / "Summary.md"`, add:

```python
    if not ticket_run:
        try:
            from .routines import briefing_lines, today as routines_today

            due = briefing_lines(vault, cfg, key, today or routines_today())
            if due:
                lines += ["", "## Routines", *[f"- {line}" for line in due[:8]]]
                if len(due) > 8:
                    lines.append(f"- …and {len(due) - 8} more: run `.bron/bin/bron routine list`")
        except Exception:  # noqa: BLE001
            lines.append("Routines couldn't be checked this time.")
```

- [ ] **Step 6: Health check**

In `core/Engine/bron/check.py`, inside `run_checks`, change the environment block to:

```python
    if include_environment:
        issues += _environment(cfg)
        issues += _routines(cfg)  # routine problems never stop a sync
```

and add:

```python
def _routines(cfg: Config) -> list[Issue]:
    from .routines import load_runbooks

    runbooks, out = load_runbooks(cfg.vault)
    for runbook in runbooks:
        if runbook.owner and slug(runbook.owner) not in cfg.agents:
            out.append(Issue(
                "warning",
                "routine.owner-unknown",
                f"The routine '{runbook.name}' is owned by '{runbook.owner}', which isn't an agent; the default agent looks after it",
                runbook.path,
            ))
    return out
```

- [ ] **Step 7: Board, skill, manual**

Create `template/Routines/Board.base`:

```yaml
filters:
  and:
    - file.inFolder("Routines")
    - 'file.basename == "Tracking"'
views:
  - type: table
    name: "By status"
    groupBy:
      property: status
      direction: ASC
    order:
      - routine
      - period
      - status
      - progress
      - due
  - type: table
    name: "By routine"
    groupBy:
      property: routine
      direction: ASC
    order:
      - period
      - status
      - progress
      - due
```

Create `core/Skills/routines/SKILL.md`:

```markdown
---
name: routines
description: Look after repeating work (monthly, quarterly or annual routines): start a period, track who has sent what, say what's due, hand steps to team members, and write a new routine's runbook. Use when the briefing says a routine can start or is due, or the user asks about a routine.
---

# Routines

A routine is a folder in `Routines/` with a `Runbook.md`: how often it runs, who owns it, when it's due, its lists and its steps. Each period has its own folder (`2026-09`, `2026-Q3`, `2026`) with a `Tracking.md` checklist and that period's outputs. Formats: `System/Core/Manual/routines.md`.

Put free text in single quotes; if the text contains a single quote, write it to a file and use `--file` (result) or `--note-file` (status).

## Start a period (when the briefing says "can start", and only after the user says yes)
1. Read the runbook. For each list that is a sentence (a source), get the items from that source (for example Carta), grouped the way the runbook says, and show the user the full lists. Wait for their yes or corrections.
2. Write each confirmed list to `.bron/tmp/<name>.txt`, one item per line, as `Group: item` when grouped (for example `Fund I: Company A`).
3. Run `.bron/bin/bron routine start '<Routine>' --list <name>=.bron/tmp/<name>.txt` with one `--list` per list from a source (add `--period <period>` for a period other than the latest one that ended).
4. Tell the user in one line what was set up and when it's due.

## During the period
- Tick items in the Tracking note (`- [ ]` → `- [x]`) when they're done; you may add a short note after the item (`- [x] Company A: received 12 Oct`). Never untick or remove items without the user's say-so.
- "Who's still missing?": read the Tracking note and list the unticked items of the step asked about.
- Progress and due dates: `.bron/bin/bron routine list`.
- A step for a team member: hand it off with a ticket linked to the routine (`--project '<Routine>'`), as in the delegate skill. Outputs go in the period folder.

## A new routine
Write `Routines/<Routine>/Runbook.md` in the manual's format, show the user the whole file first, and write it only after their yes.
```

Create `core/Manual/routines.md`:

````markdown
# Routines

A routine is repeating work: monthly, quarterly or annual, often once per fund or per company. Nothing runs on its own: the briefing says what can start and what's due, and Bron does the work when you ask.

## Runbook: `Routines/<Routine>/Runbook.md`
```markdown
---
cadence: quarterly                 # monthly | quarterly | annual
owner: bron                        # the agent that looks after it
due: 45 days after period end      # "N days after period end" becomes a date; any other rule, Bron asks
lists:
  companies: active portfolio companies of each fund in Carta (FMV > 0), grouped by fund
  funds: [Fund I, Fund II, Fund III]
steps:
  - name: Collect financials and KPIs
    for: companies
  - name: Stacked ranking
    for: once
    items: [Sent to the investment team, Back from the investment team]
  - name: One-pager
    for: funds
    after: [Collect financials and KPIs, Stacked ranking]
---

## How to do each step
Plain instructions per step: where the template is, what to update, who to send to.
```
- A list is either fixed items or a sentence saying where the items come from; Bron gets those items when a period starts and shows them to you first. They stay fixed for that period.
- `for` is a list or `once`. `after` names earlier steps that must be finished first. A runbook without `steps` is one checklist of its first list.

## Periods and the Tracking note
- Period folders sit in the routine folder: `2026-09`, `2026-Q3`, `2026`. The period to run is the latest one that has ended.
- `<Period>/Tracking.md` has one `##` section per step and a checkbox per item, grouped under `###` headings when the list is grouped. Tick items in Obsidian or ask Bron. Notes may follow an item on the same line.
- Bron keeps `status` (todo, in-progress, done) and `progress` at the top up to date; it never changes the checkboxes.
- Outputs for the period go next to the Tracking note. `Routines/Board.base` shows every period by status.

## Commands (from the vault folder)
- `.bron/bin/bron routine list`
- `.bron/bin/bron routine start '<Routine>' [--period <period>] [--list <name>=<path>]`
- `.bron/bin/bron routine refresh ['<Routine>']`
````

In `core/Manual/index.md`, add a row after the `tickets.md` row:

```markdown
| [routines.md](routines.md) | Routines: repeating work per period, checklists and due dates |
```

- [ ] **Step 8: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests/test_routines_cli.py tests/test_routines.py tests/test_handoff_content.py tests/test_hooks.py -q`, then `uv run --project core/Engine pytest tests -q`.
Expected: all pass. If `test_quoted_commands_parse` rejects `<path>` inside `--list <name>=<path>`, check the placeholder mapping (`<name>` → `bron`, `<path>` → `x` gives `--list bron=x`, which parses).

- [ ] **Step 9: Commit**

```bash
git add core/Engine/bron/routines.py core/Engine/bron/routines_cli.py core/Engine/bron/cli.py core/Engine/bron/briefing.py core/Engine/bron/check.py template/Routines/Board.base core/Skills/routines core/Manual/routines.md core/Manual/index.md tests/test_routines_cli.py tests/test_handoff_content.py
git commit -m "feat: routines in Bron (routine commands, briefing, health check, board, skill, manual)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Saved approvals

**Files:**
- Create: `core/Engine/bron/approvals.py`
- Modify: `core/Engine/bron/gen_claude.py` (`project_allow`)
- Modify: `core/Engine/bron/writer.py` (`apply(..., accept=)`)
- Modify: `core/Engine/bron/sync.py` (`_sync`)
- Modify: `core/Engine/bron/briefing.py` (notice)
- Modify: `core/Manual/permissions.md`
- Test: `tests/test_approvals.py`

**Interfaces:**
- Consumes: `gen_claude.rules`, `access.claude_server`, `catalog.permissions_for`, `statefile.update_json/read_json/locked`.
- Produces:
  - `gen_claude.project_allow(cfg) -> list[str]`
  - `GeneratedWriter.apply(files, fingerprint="", accept: frozenset[str] | set[str] = frozenset()) -> WriteReport`
  - `approvals.LAST = "claude-settings.last.json"`, `approvals.NOTICE = "approvals-notice.json"`
  - `@dataclass approvals.Imported(entries: list[str], agent: str, kept: list[str], problem: str, keep_settings: bytes | None, only_allow_changed: bool)`
  - `approvals.to_entry(rule: str, cfg) -> str | None`
  - `approvals.append_always_allow(path: Path, entries: list[str]) -> list[str]` (the entries actually added)
  - `approvals.import_approvals(vault, cfg) -> Imported`
  - `approvals.remember_generated(vault, data: bytes) -> None`
  - `approvals.record_notice(vault, agent: str, entries: list[str]) -> None`, `approvals.take_notice(vault) -> str`, `approvals.describe_entry(entry: str) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_approvals.py`:

```python
import json

import pytest

from bron import frontmatter as fm
from bron.approvals import append_always_allow, take_notice, to_entry
from bron.briefing import build_briefing
from bron.loader import load
from bron.sync import run_sync
from vaultkit import add_connection, set_meta


def claude_file(vault, local=False):
    return vault.root / ".claude" / ("settings.local.json" if local else "settings.json")


def click_always_allow(vault, *rules, local=False, extra=None):
    """What Claude Code does when the user picks "Yes, and don't ask again"."""
    path = claude_file(vault, local)
    data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    data.update(extra or {})
    data.setdefault("permissions", {}).setdefault("allow", []).extend(rules)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")


def bron_allows(vault):
    return load(vault).agents["bron"].always_allow


@pytest.fixture
def synced(vault):
    add_connection(vault, "Gmail", type="native", claude="claude_ai_Gmail")
    assert run_sync(vault).ok
    return vault


def test_rules_map_to_always_allow_entries(synced):
    cfg = load(synced)
    assert to_entry("Bash(git push:*)", cfg) == "shell:git push"
    assert to_entry("Bash(npm run test *)", cfg) == "shell:npm run test"
    assert to_entry("Bash(rm)", cfg) == "shell:rm"
    assert to_entry("mcp__claude_ai_Gmail__reply", cfg) == "mcp:Gmail:reply"
    assert to_entry("mcp__claude_ai_Gmail", cfg) is None
    assert to_entry("mcp__claude_ai_Unknown__x", cfg) is None
    assert to_entry("WebFetch(domain:carta.com)", cfg) is None
    assert to_entry('Bash(echo "a:b")', cfg) is None


def test_a_click_survives_sync_and_lands_in_bron_always_allow(synced):
    click_always_allow(synced, "Bash(git push:*)", "mcp__claude_ai_Gmail__reply")
    result = run_sync(synced)
    assert result.ok
    assert bron_allows(synced) == ["shell:git push", "mcp:Gmail:reply"]
    allow = json.loads(claude_file(synced).read_text(encoding="utf-8"))["permissions"]["allow"]
    assert "Bash(git push)" in allow and "mcp__claude_ai_Gmail__reply" in allow
    assert result.report.backup_dir is None  # a click isn't a hand edit: no backup, no note
    assert take_notice(synced) == 'Saved your "always allow" choices for Bron: shell git push; Gmail reply.'
    assert take_notice(synced) == ""
    assert run_sync(synced).ok and bron_allows(synced) == ["shell:git push", "mcp:Gmail:reply"]


def test_claude_only_rules_move_to_the_local_settings_file(synced):
    click_always_allow(synced, "WebFetch(domain:carta.com)")
    assert run_sync(synced).ok
    local = json.loads(claude_file(synced, local=True).read_text(encoding="utf-8"))
    assert local == {"permissions": {"allow": ["WebFetch(domain:carta.com)"]}}
    assert bron_allows(synced) == []
    assert run_sync(synced).ok
    assert json.loads(claude_file(synced, local=True).read_text(encoding="utf-8")) == local


def test_local_settings_rules_are_imported_and_removed(synced):
    click_always_allow(synced, "Bash(git status:*)", "Read(~/secrets/**)", local=True, extra={"env": {"X": "1"}})
    assert run_sync(synced).ok
    assert bron_allows(synced) == ["shell:git status"]
    local = json.loads(claude_file(synced, local=True).read_text(encoding="utf-8"))
    assert local == {"env": {"X": "1"}, "permissions": {"allow": ["Read(~/secrets/**)"]}}


def test_an_allow_bron_generated_and_the_user_removed_is_not_reimported(synced):
    bron = synced.agents_dir / "Bron" / "Agent.md"
    set_meta(bron, always_allow=["shell:git status"])
    assert run_sync(synced).ok
    set_meta(bron, always_allow=[])
    assert run_sync(synced).ok
    assert bron_allows(synced) == []
    assert take_notice(synced) == ""


def test_appending_keeps_the_rest_of_agent_md(tmp_path):
    path = tmp_path / "Agent.md"
    path.write_text(
        "---\nname: Bron\n# my note\nalways_allow:\n  - shell:git status\n  - delete-files\nrole: Chief of Staff\n---\nBody stays.\n",
        encoding="utf-8",
    )
    assert append_always_allow(path, ["shell:git status", "shell:git push"]) == ["shell:git push"]
    text = path.read_text(encoding="utf-8")
    assert "# my note\n" in text and text.endswith("---\nBody stays.\n")
    meta = fm.read(path).meta
    assert meta["always_allow"] == ["shell:git status", "delete-files", "shell:git push"] and meta["role"] == "Chief of Staff"
    bare = tmp_path / "Bare.md"
    bare.write_text("---\nname: Bron\nrole: x\n---\nBody.\n", encoding="utf-8")
    assert append_always_allow(bare, ["mcp:Gmail:reply"]) == ["mcp:Gmail:reply"]
    assert fm.read(bare).meta["always_allow"] == ["mcp:Gmail:reply"] and fm.read(bare).body == "Body.\n"
    assert append_always_allow(bare, ["MCP:gmail:reply"]) == []


def test_a_failed_save_keeps_the_click_where_it_is(synced, monkeypatch):
    from bron import approvals

    click_always_allow(synced, "Bash(git push:*)")

    def fail(*args, **kwargs):
        raise OSError("disk full")

    original = approvals.append_always_allow
    monkeypatch.setattr(approvals, "append_always_allow", fail)
    result = run_sync(synced)
    assert result.ok and "approvals.import" in {i.code for i in result.issues}
    assert "Bash(git push:*)" in claude_file(synced).read_text(encoding="utf-8")
    monkeypatch.setattr(approvals, "append_always_allow", original)
    assert run_sync(synced).ok
    assert bron_allows(synced) == ["shell:git push"]


def test_nothing_to_import_in_a_fresh_vault(vault):
    assert run_sync(vault).ok
    assert take_notice(vault) == ""


def test_the_briefing_shows_the_notice_once_and_never_in_a_ticket_run(synced, monkeypatch):
    click_always_allow(synced, "Bash(git push:*)")
    assert run_sync(synced).ok
    monkeypatch.setenv("BRON_TICKET", "T-0001")
    assert "always allow" not in build_briefing(synced, cli="claude")
    monkeypatch.delenv("BRON_TICKET")
    assert 'Saved your "always allow" choices for Bron: shell git push.' in build_briefing(synced, cli="claude")
    assert "always allow" not in build_briefing(synced, cli="claude")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_approvals.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'bron.approvals'`.

- [ ] **Step 3: `project_allow` and `accept`**

In `core/Engine/bron/gen_claude.py`, add after `_settings`:

```python
def project_allow(cfg: Config) -> list[str]:
    """The permissions.allow list sync writes to .claude/settings.json."""
    if cfg.default_agent is None:
        return []
    return _settings(cfg)["permissions"]["allow"]
```

In `core/Engine/bron/writer.py`, change `apply`'s signature to

```python
    def apply(self, files: dict[str, bytes], fingerprint: str = "", accept: frozenset[str] | set[str] = frozenset()) -> WriteReport:
        """`accept`: generated files whose on-disk change was already taken care of (no backup needed)."""
```

and in its write loop change `if old.get(rel) != sha256(current):` to `if old.get(rel) != sha256(current) and rel not in accept:`.

- [ ] **Step 4: The approvals module**

Create `core/Engine/bron/approvals.py`:

```python
"""Saved approvals: "don't ask again" choices Claude Code wrote into the vault, moved into always_allow.

In a vault that isn't a git repository Claude Code saves them in .claude/settings.json, which sync
regenerates; inside a git repository it uses .claude/settings.local.json, which sync never writes.
"""
from __future__ import annotations

import copy
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter as fm
from .access import claude_server
from .statefile import locked, read_json, update_json
from .vault import Vault

LAST = "claude-settings.last.json"  # exactly what sync last wrote to .claude/settings.json
NOTICE = "approvals-notice.json"
_BASH = re.compile(r"^Bash\(\s*([^*():\"']+?)\s*(?::\*|\s\*)?\s*\)$")
_PLAIN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]*$")


@dataclass
class Imported:
    entries: list[str] = field(default_factory=list)  # added to the default agent's always_allow
    agent: str = ""
    kept: list[str] = field(default_factory=list)  # Claude-only rules moved to settings.local.json
    problem: str = ""
    keep_settings: bytes | None = None  # on failure: keep .claude/settings.json exactly as it is
    only_allow_changed: bool = False  # .claude/settings.json differs from Bron's copy only in permissions.allow


def to_entry(rule: str, cfg) -> str | None:
    """A Claude permission rule as an always_allow entry, or None when Codex has no equivalent."""
    if not isinstance(rule, str):
        return None
    match = _BASH.match(rule.strip())
    if match:
        words = " ".join(match.group(1).split())
        return f"shell:{words}" if words else None
    for conn in sorted(cfg.connections.values(), key=lambda c: -len(claude_server(c) or "")):
        server = claude_server(conn)
        prefix = f"mcp__{server}__"
        if server and rule.startswith(prefix) and len(rule) > len(prefix):
            return f"mcp:{conn.name}:{rule[len(prefix):]}"
    return None


def _norm(entry: str) -> str:
    return re.sub(r"\s+", " ", entry.strip().lower())


def _flow(value: str) -> str:
    return value if _PLAIN.match(value) else json.dumps(value, ensure_ascii=False)


def append_always_allow(path: Path, entries: list[str]) -> list[str]:
    """Add entries to always_allow in Agent.md, changing only that one setting. Returns what was added."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path.name} has no settings block at the top")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError(f"{path.name}'s settings block has no closing '---' line")
    current = fm.parse(text).meta.get("always_allow") or []
    if isinstance(current, str):
        current = [v.strip() for v in current.split(",") if v.strip()]
    if not isinstance(current, list):
        raise ValueError(f"'always_allow' in {path.name} isn't a list")
    have = {_norm(str(v)) for v in current}
    added: list[str] = []
    for entry in entries:
        if _norm(entry) not in have:
            added.append(entry)
            have.add(_norm(entry))
    if not added:
        return []
    values = [str(v) for v in current] + added
    new_line = "always_allow: [" + ", ".join(_flow(v) for v in values) + "]\n"
    index = next((i for i in range(1, end) if re.match(r"^always_allow\s*:", lines[i])), None)
    if index is None:
        lines.insert(end, new_line)
    else:
        stop = index + 1
        while stop < end and lines[stop].strip() and (lines[stop][0] in " \t" or lines[stop].lstrip().startswith("- ")):
            stop += 1
        lines[index:stop] = [new_line]
    new_text = "".join(lines)
    if fm.parse(new_text).meta.get("always_allow") != values:
        raise ValueError(f"Bron couldn't update 'always_allow' in {path.name} safely")
    tmp = path.with_name(f"{path.name}.{os.getpid()}.bron-tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(path)
    return added


def _load(path: Path, *, strict: bool = False) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if strict:
            raise ValueError(str(exc)) from exc
        return None
    if not isinstance(data, dict):
        if strict:
            raise ValueError("it isn't a settings object")
        return None
    return data


def _allow(data: dict | None) -> list[str]:
    permissions = (data or {}).get("permissions")
    rules = permissions.get("allow") if isinstance(permissions, dict) else None
    return [r for r in rules if isinstance(r, str)] if isinstance(rules, list) else []


def _without_allow(data: dict) -> dict:
    copied = copy.deepcopy(data)
    permissions = dict(copied.get("permissions") or {})
    permissions.pop("allow", None)
    copied["permissions"] = permissions
    return copied


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.bron-tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def import_approvals(vault: Vault, cfg) -> Imported:
    from .gen_claude import project_allow

    out = Imported()
    agent = cfg.default_agent
    claude_dir = vault.root / ".claude"
    if agent is None or not claude_dir.is_dir():
        return out
    out.agent = agent.name
    settings_path, local_path = claude_dir / "settings.json", claude_dir / "settings.local.json"
    disk = _load(settings_path)
    last = _load(vault.state_dir / LAST)
    known = set(_allow(last)) if last is not None else set(project_allow(cfg))
    if disk is not None and last is not None:
        out.only_allow_changed = _without_allow(disk) == _without_allow(last)
    try:
        local = _load(local_path, strict=True)
    except ValueError:
        out.problem = "Claude Code's .claude/settings.local.json can't be read, so Bron left your saved approvals where they are"
        out.keep_settings = settings_path.read_bytes() if settings_path.is_file() else None
        out.only_allow_changed = False
        return out
    project_rules = [r for r in _allow(disk) if r not in known]
    local_rules = _allow(local)
    candidates = project_rules + [r for r in local_rules if r not in project_rules]
    if not candidates:
        return out
    entries: list[str] = []
    claude_only: list[str] = []
    for rule in candidates:
        entry = to_entry(rule, cfg)
        if entry is None:
            claude_only.append(rule)
        elif entry not in entries:
            entries.append(entry)
    try:
        added = append_always_allow(agent.path, entries) if entries else []
    except (OSError, ValueError) as exc:
        out.problem = f'Bron couldn\'t save your "always allow" choices to {agent.name}\'s Agent.md ({exc}); they stay in Claude Code\'s settings until this is fixed'
        out.keep_settings = settings_path.read_bytes() if settings_path.is_file() else None
        out.only_allow_changed = False
        return out
    keep = [r for r in local_rules if r in claude_only] + [r for r in claude_only if r not in local_rules]
    if keep != local_rules:
        data = dict(local or {})
        permissions = dict(data.get("permissions") or {})
        if keep:
            permissions["allow"] = keep
        else:
            permissions.pop("allow", None)
        if permissions:
            data["permissions"] = permissions
        else:
            data.pop("permissions", None)
        _write_json(local_path, data)
    out.kept = [r for r in claude_only if r not in local_rules]
    out.entries = added
    if added:
        record_notice(vault, agent.name, added)
    return out


def remember_generated(vault: Vault, data: bytes) -> None:
    path = vault.state_dir / LAST
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def record_notice(vault: Vault, agent: str, entries: list[str]) -> None:
    def add(data: dict) -> None:
        listed = data.setdefault(agent, [])
        listed += [e for e in entries if e not in listed]

    update_json(vault.state_dir / NOTICE, {}, add)


def describe_entry(entry: str) -> str:
    if entry.startswith("shell:"):
        return "shell " + entry[len("shell:"):]
    if entry.startswith("mcp:"):
        parts = entry.split(":", 2)
        if len(parts) == 3:
            return f"{parts[1]} {parts[2]}"
    return entry


def take_notice(vault: Vault) -> str:
    """The one-time 'Saved your always allow choices' line ('' when there is none)."""
    path = vault.state_dir / NOTICE
    if not path.is_file():
        return ""
    with locked(path):
        data = read_json(path, {})
        path.unlink(missing_ok=True)
    lines = [
        f'Saved your "always allow" choices for {agent}: ' + "; ".join(describe_entry(e) for e in entries) + "."
        for agent, entries in sorted(data.items())
        if isinstance(entries, list) and entries
    ]
    return "\n".join(lines)
```

- [ ] **Step 5: Import before regenerating**

In `core/Engine/bron/sync.py`, replace `_sync` with:

```python
def _sync(vault: Vault, *, dry_run: bool) -> SyncResult:
    from .approvals import import_approvals, remember_generated

    cfg = load(vault)
    issues = run_checks(cfg, include_environment=False)
    if has_errors(issues):
        return SyncResult(False, issues)
    approvals = None
    if not dry_run:
        # Claude Code saves "don't ask again" into a file sync regenerates: move those choices first.
        approvals = import_approvals(vault, cfg)
        if approvals.entries:
            cfg = load(vault)
            issues = run_checks(cfg, include_environment=False)
            if has_errors(issues):
                return SyncResult(False, issues)
        if approvals.problem:
            issues = issues + [Issue("warning", "approvals.import", approvals.problem)]
    try:
        files = plan_files(cfg)
    except (OSError, KeyError, ValueError) as exc:
        return SyncResult(False, issues + [Issue("error", "sync.failed", f"Bron couldn't build the CLI setup ({exc.__class__.__name__}: {exc})")])
    issues += output_issues(files)
    if has_errors(issues) or dry_run:
        return SyncResult(not has_errors(issues), issues)
    accept: set[str] = set()
    if approvals is not None and approvals.keep_settings is not None:
        files[".claude/settings.json"] = approvals.keep_settings  # keep the user's click until it can be saved
    elif approvals is not None and approvals.only_allow_changed:
        accept.add(".claude/settings.json")
    try:
        report = GeneratedWriter(vault).apply(files, fingerprint(vault), accept=accept)
    except (OSError, ValueError) as exc:
        return SyncResult(False, issues + [Issue("error", "sync.failed", f"Bron couldn't write the CLI setup: {exc}")])
    if approvals is not None and approvals.keep_settings is None and ".claude/settings.json" in files:
        try:
            remember_generated(vault, files[".claude/settings.json"])
        except OSError:
            pass
    return SyncResult(True, issues, report)
```

- [ ] **Step 6: The notice in the briefing**

In `core/Engine/bron/briefing.py`, inside the `if not ticket_run:` block you added in Task 6 (before the routines lines), or in a new `if not ticket_run:` block right after the Tickets `try/except`, add:

```python
        try:
            from .approvals import take_notice

            notice = take_notice(vault)
        except Exception:  # noqa: BLE001
            notice = ""
        if notice:
            lines += ["", notice + " Tell the user in one line."]
```

(If Task 6's block isn't there yet, wrap this in its own `if not ticket_run:`.)

- [ ] **Step 7: Document it**

In `core/Manual/permissions.md`, add before `## Codex notes`:

```markdown
## Saved approvals
When you choose "Yes, and don't ask again" in Claude Code, Claude Code saves the rule in the vault's `.claude/` settings, which Bron regenerates. At the next sync Bron moves it into the default agent's `always_allow` (shell commands and connector tools) and tells you in one line. Rules Codex has no equivalent for (for example "always allow this website") stay in `.claude/settings.local.json`, which Bron never overwrites. Codex keeps its own approvals in `~/.codex/rules/default.rules`, outside the vault; Bron leaves them alone. To be asked again, delete the entry from `always_allow`.
```

- [ ] **Step 8: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests/test_approvals.py tests/test_sync.py tests/test_writer.py tests/test_hooks.py -q`, then `uv run --project core/Engine pytest tests -q`.
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add core/Engine/bron/approvals.py core/Engine/bron/gen_claude.py core/Engine/bron/writer.py core/Engine/bron/sync.py core/Engine/bron/briefing.py core/Manual/permissions.md tests/test_approvals.py
git commit -m "feat: keep Claude Code's 'don't ask again' choices in always_allow" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Live @-mentions, version 0.3.0

**Files:**
- Create: `tests/live/test_mentions.py`
- Modify: `core/VERSION`, `core/Engine/pyproject.toml`, `core/Engine/bron/__init__.py`, `core/Engine/uv.lock`, `tests/test_vault.py`, `tests/test_prompts.py`, `tests/test_cli.py`, `tests/test_update.py`
- Modify: `docs/superpowers/specs/2026-10-02-bron-plan2b-cli-verification.md` (row T6)

**Interfaces:**
- Consumes: everything above; `scripts/dev-vault.sh`.

- [ ] **Step 1: Write the live tests**

Create `tests/live/test_mentions.py`:

```python
"""Live @-mentions between Claude Code and Codex. Run with: BRON_LIVE=1 uv run --project core/Engine pytest tests/live/test_mentions.py -q -s"""
import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from bron import frontmatter as fm
from bron.tickets import find_ticket, list_tickets, load_ticket
from bron.vault import Vault

pytestmark = pytest.mark.skipif(os.environ.get("BRON_LIVE") != "1", reason="live CLI test: set BRON_LIVE=1")

REPO = Path(__file__).resolve().parents[2]


def bron(vault: Path, *args: str, stdin: str | None = None) -> str:
    done = subprocess.run([str(vault / ".bron" / "bin" / "bron"), *args], cwd=vault, input=stdin, capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@pytest.fixture(scope="module")
def vault(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("mentions") / "Mention Vault"
    subprocess.run([str(REPO / "scripts" / "dev-vault.sh"), str(root)], check=True)
    root = root.resolve()
    for name, runs_in, extra in (("Gpt", "codex", "connections: []\n"), ("Claudia", "claude", "")):
        folder = root / "System" / "Agents" / name
        folder.mkdir(parents=True)
        (folder / "Agent.md").write_text(
            f"---\nname: {name}\nrole: Test member\nreports_to: Bron\nruns_in: {runs_in}\n{extra}---\nYou are {name}, a careful test agent. Keep answers short.\n",
            encoding="utf-8",
        )
    settings = root / "System" / "Settings.md"
    doc = fm.read(settings)
    doc.meta.update(user_name="Tester", company="Test Co")
    fm.write(settings, doc)
    bron(root, "sync")
    return root


def claude(vault: Path, prompt: str, session: str | None = None) -> tuple[dict, float]:
    argv = ["claude", "-p", prompt, "--output-format", "json", "--permission-mode", "acceptEdits", "--allowedTools", "Bash"]
    if session:
        argv += ["--resume", session]
    started = time.time()
    done = subprocess.run(argv, cwd=vault, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout + done.stderr
    return json.loads(done.stdout), time.time() - started


def chats(vault: Path):
    return [t for t in list_tickets(Vault(vault))[0] if t.kind == "chat"]


def test_a_tag_in_claude_code_reaches_a_codex_agent_and_follow_ups_continue(vault):
    first, seconds = claude(vault, "@gpt What is 17 + 25? Reply with only the number.")
    assert "42" in first["result"] and "Gpt" in first["result"], first["result"]
    found = chats(vault)
    assert len(found) == 1 and found[0].assignee == "gpt"
    assert "started in Codex" in "\n".join(found[0].thread)
    second, _ = claude(vault, "@gpt Now double that number. Reply with only the number.", session=first["session_id"])
    assert "84" in second["result"], second["result"]
    found = chats(vault)
    assert len(found) == 1 and any(" · you: @gpt Now double" in entry for entry in found[0].thread)
    print(f"\n@gpt from Claude Code: first answer {seconds:.1f}s end to end")


def test_a_tag_from_a_codex_session_reaches_a_claude_agent(vault):
    # Codex runs Bron's triggers only after the user approves them (/hooks), so call the trigger as Codex would.
    payload = json.dumps({"prompt": "@claudia What is 6 times 7? Reply with only the number.", "session_id": "live-codex-1", "transcript_path": ""})
    started = time.time()
    note = bron(vault, "hook", "user-prompt", "--cli", "codex", stdin=payload)
    assert "@Claudia is answering this message" in note, note
    tid = note.split("chat ticket ")[1].split(")")[0]
    out = bron(vault, "ticket", "wait", tid)
    assert out.startswith("Claudia:") and "42" in out, out
    assert "started in Claude Code" in "\n".join(load_ticket(find_ticket(Vault(vault), tid)).thread)
    print(f"\n@claudia from Codex: answer {time.time() - started:.1f}s from the trigger")
```

- [ ] **Step 2: Run the live tests**

Run: `BRON_LIVE=1 uv run --project core/Engine pytest tests/live/test_mentions.py -q -s`
Expected: 2 passed; the two printed timings. If the Claude test fails because the reply has no "Gpt" label, read the chat ticket and `.bron/runs/` logs: the trigger's instructions (Task 4) are what make Bron label and wait; fix there, not in the test. Record both timings in row T6 of `docs/superpowers/specs/2026-10-02-bron-plan2b-cli-verification.md`, and set row T4 to "PASS: the detached run survived the trigger's exit (live test)".

Then run all live tests once: `BRON_LIVE=1 uv run --project core/Engine pytest tests/live -q` and record the summary line in your report.

- [ ] **Step 3: Version 0.3.0**

- `core/VERSION`: `0.3.0`
- `core/Engine/pyproject.toml`: `version = "0.3.0"`
- `core/Engine/bron/__init__.py`: `__version__ = "0.3.0"`
- `tests/test_vault.py`, `tests/test_prompts.py`, `tests/test_cli.py`: replace `0.2.3` with `0.3.0`
- `tests/test_update.py`: the fake project script writes `0.3.0` today; change it to write `0.4.0`, and change the expectations to `Updated Bron from version 0.3.0 to 0.4.0.` and `already on the latest version (0.3.0)`
- Run `uv lock --project core/Engine` (from the repo root) to refresh `core/Engine/uv.lock`.

Run: `uv run --project core/Engine pytest tests -q`
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/live/test_mentions.py docs/superpowers/specs/2026-10-02-bron-plan2b-cli-verification.md core/VERSION core/Engine/pyproject.toml core/Engine/bron/__init__.py core/Engine/uv.lock tests/test_vault.py tests/test_prompts.py tests/test_cli.py tests/test_update.py
git commit -m "test(live): @-mentions both ways; framework 0.3.0" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage:** §3.1 detection → Task 2 (`tagged_agents`) + Task 4 (`_route` skips ticket runs, self); §3.2 chat tickets, follow-ups, closing → Task 2 + Task 4 triggers; §3.3 context → Task 1; §3.4 starting runs detached and shown → Task 3 + Task 4; §3.5 what the session agent is told, `ticket wait`, Needs-your-OK, unreachable agents → Task 3 + Task 4; §3.6 speed → chat prompt inline (Task 3), run starts in the trigger (Task 4); §4.1–4.3 runbooks, periods, Tracking → Task 5; §4.4 commands, §4.5 briefing and board, §4.6 skill and manual, §4.7 health check → Task 6; §5 saved approvals → Task 7; §7 testing → every task + Task 8 live; §8 verify first → Task 1 + Task 8.
- **Types:** `start_background(..., shown=)` (Task 3) is what Task 4 calls; `start_chat` returns `(Ticket, bool)` everywhere; `refresh_tracking` returns `TrackingState` (Task 5) and Task 6 uses `.meta/.status/.progress`; `build_briefing(..., today=)` (Task 6) is used by Task 6's test only; `GeneratedWriter.apply(..., accept=)` (Task 7) is called only by sync.

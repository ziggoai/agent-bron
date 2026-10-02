# Bron Core, Plan 2a: Handing off work — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A team member (for example a test CFO) can take a ticket from Bron, work it in the background on its own model and CLI (Claude-to-GPT and GPT-to-Claude included), ask a question or ask for your OK by marking the ticket blocked, continue the same conversation after an answer, and report back, while Bron sees the update. Bron also discovers the connectors you already have in both CLIs and controls which agent may use which.

**Architecture:**
- Tickets are markdown notes in `Tickets/`, written through a small ticket API and `bron ticket …` commands that agents run.
- A runner (`bron run`) does the work: it locks a ticket, builds the right command line for the assignee's CLI (verified templates from the Plan 2 checks), runs it headless with the agent's own instructions, model, connections and permissions, parses the result, keeps the ticket consistent whatever the agent did, records the session for resuming, and leaves a notification.
- Notifications reach the requesting agent through the session briefing and the message trigger, the same way in both CLIs.
- Native connectors are discovered from `claude mcp list` and `codex mcp list --json`, written as `type: native` connection files, and enforced per agent with `--disallowedTools` (Claude) and `-c mcp_servers.<id>.enabled=false` (Codex).

**Tech Stack:** Python 3.12 (uv), PyYAML, tomli-w, pytest. macOS. Claude Code ≥ 2.1.287, Codex CLI ≥ 0.159.2.

**Spec:** `docs/superpowers/specs/2026-10-01-bron-core-design.md`. Read §5–§7 before starting. This plan implements:
- §6.1–6.2: tickets (task tickets; chat tickets are Plan 2b) and locks.
- §7.4: connections, per agent.
- §7.5: the runner.
- §7.6: the direct session (`bron chat`); `@`-mentions are Plan 2b.
- §7.7: stale locks and the model check.
- §7.8: the `delegate` skill.
- §7.9: the tickets and connections manual pages.

**Read also:**
- `docs/superpowers/specs/2026-10-01-bron-plan2-cli-verification.md`: the verified command templates for running and resuming agents in each CLI.
- `docs/superpowers/specs/2026-10-01-bron-core-cli-verification.md`: the Plan 1 findings.

### Where this plan sits

| Plan | Delivers | Status |
|---|---|---|
| 1. Foundation | Formats, loader, health check, safe writer, sync for both CLIs, triggers, briefing, `bron update` | done, merged |
| **2a. Handing off work (this plan)** | Native connectors (discovery and per-agent control), tickets and locks, per-agent launch settings, the runner (both CLIs, mixed vendors, resume, blocked, needs-your-OK), notifications, `bron chat`, the delegate skill, the Tickets board, live handoff tests | now |
| 2b. Conversations and routines | `@`-mentions and chat tickets, routines (cadence and `for_each`) with their board and "what's due" briefing, importing "Always allow" approvals | after 2a |
| 3. Self-configuration | Setup skills (onboarding, create, edit and remove agent, create project and routine, create skill) and the full manual | after 2b |
| 4. Distribution | Installer, the Obsidian bundle (theme and plugins, sync on save), GitHub-based `bron update` with backup and undo | after 3 |

### Decisions approved by the human (2026-10-01)

1. **What a background agent may do.**
   - It may read and write files inside the vault and run ordinary commands.
   - Anything on its `ask_before` list is refused while it runs in the background. The ticket becomes `blocked` with a note starting **"Needs your OK:"** that names the exact action.
   - **How approval works:** the requester (normally Bron, in an interactive session where the CLI can ask the user) performs that exact action itself after the user agrees, which triggers the CLI's normal approval prompt. It writes the outcome in the ticket thread, then resumes the assignee. There is no permission-override trickery in background runs.
2. **Connectors are discovered, not hand-written.**
   - Bron lists the connectors already set up in Claude Code (including claude.ai connectors and plugin servers) and in Codex.
   - It matches the same connector across the two CLIs by URL, then by name.
   - It writes one `System/Connections/<Name>.md` per connector with `type: native`, `claude: <id>` and `codex: <id>`.
   - Re-scanning only updates the `claude`, `codex`, `url` and `status` lines, so the user's edits are kept.
3. **Bron uses all connectors that are already set up.** The default agent gets `connections: [all]`; `all` means every registered connection. Team members only get the connections listed in their own file.
4. **The briefing names the agent actually running** (`BRON_AGENT`, set by the runner and launcher), so a Codex CFO doesn't introduce itself as Bron.

5. **Not in this plan:** spec §7.7's "CLI logged in" check. There is no reliable way to detect a signed-out CLI without starting a billed session. A signed-out CLI instead shows up as a failed run, with its log linked from the blocked ticket.

### Design facts from the Plan 2 checks (binding)

- **Run as agent (Claude):** `claude -p "<prompt>" --agent <key> --output-format json …`
  - Read `session_id`, `result` and `permission_denials` from the JSON.
  - `--resume <session_id>` continues the same session and keeps the agent.
  - Typical timing is about 8 s for a run and 6 s for a resume.
- **Don't use `--bare`.** It drops `.claude/agents`, and it refuses subscription login.
- **Don't use `--strict-mcp-config`.** It also hides claude.ai connectors. Block servers with `--disallowedTools mcp__<server-id>`, comma-separated in one argument.
- **Connector tool names (Claude):** a claude.ai connector "Google Drive" has tools `mcp__claude_ai_Google_Drive__…`. A plugin server `plugin:atl-core-skills:affinity-mcp` has tools `mcp__plugin_atl-core-skills_affinity-mcp__…`.
- **`--settings <file>`** merges with the project `.claude/settings.json` permissions rather than replacing them.
- **Denials (Claude):** in `-p` mode, any Bash command not explicitly allowed is denied. `permission_denials` does not distinguish "ask" from "deny".
- **Run as agent (Codex):** `codex exec --json --skip-git-repo-check --dangerously-bypass-hook-trust -c 'developer_instructions="…"' [-m model] [-c 'mcp_servers.<id>.enabled=false'] "<prompt>"`
  - `-c developer_instructions` replaces the project value.
  - `thread_id` arrives in the first JSONL event (`thread.started`). The answer is the last `item.completed` event whose item has `type == "agent_message"`.
- **Resume (Codex):** `codex exec resume --json --skip-git-repo-check --dangerously-bypass-hook-trust <thread_id> "<prompt>"`
  - The instructions are kept in the thread.
  - `-c` and `-m` are accepted on resume.
- **Denials (Codex):** a refused command prints `approval required by policy` on stderr, and the process still exits 0.
- **Notifications:** Codex has no way to tell a running session that a background process finished. Notifications therefore go through the session-start briefing and the message trigger in both CLIs.
- **Listing connectors:**
  - `claude mcp list` prints lines such as `claude.ai Carta: https://mcp.app.carta.com/mcp - ✔ Connected` or `plugin:supabase:supabase: https://… (HTTP) - ! Needs authentication`.
  - `codex mcp list --json` prints a JSON array of `{"name", "enabled", "transport": {"type", "url"|"command", …}, …}`.

## Global Constraints

Everything in Plan 1's Global Constraints still applies:
- macOS; Python `>=3.12`; only PyYAML and tomli-w at runtime.
- Tests run from the repo root: `uv run --project core/Engine pytest tests -q`.
- Generated paths only (`AGENTS.md`, `CLAUDE.md`, `.mcp.json`, `.claude/`, `.codex/`, `.agents/`); machine data only in `.bron/`.
- Plain-language messages that name the file involved.
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

New for 2a:
- **Tickets** live directly in `Tickets/`, named `T-0042 <Title>.md`. IDs are `T-` plus at least 4 digits, sequential, from `.bron/state/tickets.json`.
- **Statuses:** `backlog | todo | in-progress | blocked | in-review | done | cancelled`. Kinds: `task | chat`. Priorities: `low | normal | high | urgent`.
- **A ticket body** has exactly these sections, in this order: `## Request`, `## Context`, `## Thread`, `## Result`.
- **Thread entries** are written as `- YYYY-MM-DD HH:MM · <author>: <text>`; continuation lines are indented by two spaces.
- **Locks:** `.bron/locks/<ticket id>.lock` (JSON with `run_id`, `pid`, `started`), created atomically. A lock is stale when its process is gone or it is older than `max_minutes + 5` minutes.
- **Machine state:**
  - `.bron/state/runs.json`: per ticket, `cli`, `session`, `agent`, `thread_len` and `updated`.
  - `.bron/state/notifications.jsonl` and `.bron/state/notifications-seen.json`.
  - `.bron/runs/<run_id>.log`.
- **The runner never leaves a ticket in `in-progress`** after a run ends. It always ends `in-review`, `blocked` (with a reason) or whatever the agent set.
- **Approval notes** start exactly with `Needs your OK:`.
- **Generated per-agent Claude permissions:** `.claude/bron/agents/<key>.settings.json`.
- **Environment for runs and direct sessions:** `BRON_AGENT` (the agent's name) and, for ticket runs, `BRON_TICKET`.
- **The word `all`** in a `connections` list (any case) means every registered connection.

## Review Focus

These are the inputs a real user will produce that no feature test would naturally hit. Each has a pinned test in the task named.

1. **A ticket note edited by hand in Obsidian.** Typing in the Thread, deleting a section, a broken settings block, an unknown status. Loading must not crash. The runner and CLI report it plainly and keep what can be kept. Tested in Task 4.
2. **The same ticket started twice, or a run that crashed and left its lock.** The second start does not run. A dead or expired lock is recovered automatically. Tested in Tasks 5 and 7.
3. **An agent that ends without using the ticket commands, a CLI that errors or times out, or a CLI that isn't installed.** The ticket never stays `in-progress`. Tested in Task 7.
4. **Agent instructions with quotes, backslashes, triple quotes, accents and newlines** passed to Codex through `-c developer_instructions=…`. They must arrive intact. Tested in Task 6.
5. **Running the connector scan twice, or after the user edited a connection file.** No duplicates; the user's description and notes are kept. A connector found in only one CLI still works there. Tested in Task 3.

---

## File map

```
core/Engine/bron/
  model.py            MODIFY  native connection type, ALL, Connection.claude/codex/status
  loader.py           MODIFY  load native connections
  check.py            MODIFY  'all', native checks, stale locks, pinned-model warning
  access.py           CREATE  allowed connections per agent/helper; per-CLI server ids
  gen_claude.py       MODIFY  natives excluded from .mcp.json; mapped tool names; per-agent settings files
  gen_codex.py        MODIFY  natives left to the user's Codex config
  scan.py             CREATE  discover connectors in both CLIs; write System/Connections
  statefile.py        CREATE  locked JSON/JSONL state files under .bron/state
  tickets.py          CREATE  ticket model, parse/render, create/find/load/save, thread, status, result
  tickets_cli.py      CREATE  `bron ticket new|show|say|status|result|list`
  locks.py            CREATE  atomic ticket locks with stale recovery
  launch.py           CREATE  command lines for runs, resumes and direct sessions in each CLI
  notifications.py    CREATE  record ticket updates; pending/seen per agent
  runner.py           CREATE  run/resume a ticket, parse results, keep the ticket consistent, background start
  briefing.py         MODIFY  tickets section + updates for the running agent
  hooks.py            MODIFY  user-prompt trigger shows new ticket updates
  update.py           MODIFY  re-scan connections after an update
  cli.py              MODIFY  ticket, run, chat, connections subcommands
core/Skills/delegate/SKILL.md      CREATE
core/Skills/connections/SKILL.md   CREATE
core/Manual/tickets.md             CREATE
core/Manual/connections.md         CREATE
core/Manual/index.md               MODIFY
core/Templates/AGENTS.md.tmpl      MODIFY  short ticket protocol
template/System/Agents/Bron/Agent.md   MODIFY  connections: [all]
template/Tickets/Board.base        CREATE
tests/
  test_native.py test_scan.py test_tickets.py test_locks.py test_launch.py
  test_runner.py test_notifications.py test_chat.py
  live/test_handoff.py              (BRON_LIVE=1)
docs/superpowers/specs/2026-10-01-bron-plan2-cli-verification.md   (from the checks; committed in Task 1)
```

---

### Task 1: Close the last open runner questions (spike; findings kept)

The Plan 2 checks left six questions open that this plan depends on. Answer them in a throwaway vault, add them to the existing findings document, and commit it.

**Files:**
- Modify: `docs/superpowers/specs/2026-10-01-bron-plan2-cli-verification.md` (append a "Plan 2a pre-checks" section). The file already exists, uncommitted.
- Throwaway: a vault built with `scripts/dev-vault.sh` under `$TMPDIR` (never committed).

**Interfaces:**
- Consumes: nothing.
- Produces: verdicts V1–V6. Tasks 6 and 7 are written assuming the "Expected" result for each. **If V2 or V5 differs, stop after committing the findings and report.** Those two decide the runner's permission flags and how it reads Codex's answer.

**Rules:**
- Shell state doesn't persist between commands; store paths in a file and re-read them.
- Never modify `~/.claude/` or `~/.codex/`.
- Codex runs need `--skip-git-repo-check --dangerously-bypass-hook-trust`.
- Keep prompts tiny, and delete the throwaway vault at the end.

- [ ] **Step 1: Build the throwaway vault with a test CFO**

```bash
mkdir -p "$TMPDIR/bron-2a-spike" && echo "$TMPDIR/bron-2a-spike/Spike Vault" > "$TMPDIR/bron-2a-spike/path"
V="$(cat "$TMPDIR/bron-2a-spike/path")"; scripts/dev-vault.sh "$V"
V="$(cat "$TMPDIR/bron-2a-spike/path")"; mkdir -p "$V/System/Agents/CFO" && printf -- '---\nname: CFO\nrole: Chief Financial Officer\nreports_to: Bron\nruns_in: any\n---\nYour name is CFO. Always start replies with "CFO here."\n' > "$V/System/Agents/CFO/Agent.md" && "$V/.bron/bin/bron" sync
```

- [ ] **Step 2: V1. Do Codex triggers see a variable set on the `codex exec` process?**

```bash
V="$(cat "$TMPDIR/bron-2a-spike/path")"; cd "$V" && BRON_AGENT=CFO codex exec --skip-git-repo-check --dangerously-bypass-hook-trust "Reply with the first two lines of your Bron briefing, verbatim." 2>/dev/null | tail -4; tail -1 .bron/state/markers.jsonl
```

Expected: the briefing line reads "You are CFO, working in Codex…", and the last marker has `"agent": "CFO"`.

- [ ] **Step 3: V2. Claude background permissions (PLAN-CRITICAL)**

```bash
V="$(cat "$TMPDIR/bron-2a-spike/path")"; cd "$V" && echo keep > Projects/keep.txt && claude -p "Do three things: 1) run the shell command: echo hello; 2) create the file Projects/made.txt containing hi; 3) run the shell command: rm Projects/keep.txt. Then report each result." --agent cfo --output-format json --permission-mode acceptEdits --allowedTools Bash | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['result']);print(d.get('permission_denials'))"; ls Projects
```

Expected:
- `echo` ran.
- `Projects/made.txt` exists.
- `rm` was refused (it's listed in `permission_denials`, because Bron's project rules ask before `rm`).
- `Projects/keep.txt` still exists.

That confirms "ask" rules win over `--allowedTools Bash` and that `acceptEdits` allows edits in `-p`. If `rm` ran, record it and stop.

- [ ] **Step 4: V3. Does `--settings` need to be passed again on resume?**

Write `$V/agent-perm.json` containing `{"permissions": {"ask": ["Bash(touch *)", "Bash(touch)"]}}`.
1. Run `claude -p "Say ok." --agent cfo --settings agent-perm.json --output-format json`, and keep its `session_id`.
2. Then run `claude -p --resume <id> "Run the shell command: touch Projects/t.txt" --output-format json --permission-mode acceptEdits --allowedTools Bash`, **without** `--settings`.

Record whether `touch` was denied (meaning the setting persisted) or ran (meaning it must be passed again).

- [ ] **Step 5: V4. Hiding a plugin server in Claude**

```bash
V="$(cat "$TMPDIR/bron-2a-spike/path")"; cd "$V" && claude -p "List the MCP server names whose tools you can call. Names only." --output-format json --disallowedTools "mcp__plugin_atl-core-skills_affinity-mcp,mcp__claude_ai_Gmail" | python3 -c "import json,sys;print(json.load(sys.stdin)['result'])"
```

Expected: neither the affinity plugin server nor `claude_ai_Gmail` is listed. Record the result, and note whether a comma-separated single argument works.

- [ ] **Step 6: V5. Reading Codex's answer (PLAN-CRITICAL)**

```bash
V="$(cat "$TMPDIR/bron-2a-spike/path")"; cd "$V" && codex exec --json --skip-git-repo-check --dangerously-bypass-hook-trust "Say: forty-two" 2>/dev/null > "$TMPDIR/bron-2a-spike/codex.jsonl"; python3 -c "
import json
for line in open('$TMPDIR/bron-2a-spike/codex.jsonl'):
    try: e=json.loads(line)
    except ValueError: continue
    print(e.get('type'), sorted((e.get('item') or {}).keys()) if isinstance(e.get('item'),dict) else '')
"
```

Expected: a `thread.started` event carrying `thread_id`, and an `item.completed` event whose item has the keys `id`, `type` (`agent_message`) and `text`. Record the exact key holding the answer text.

- [ ] **Step 7: V6. Can Codex run `.bron/bin/bron` and write files inside the vault from `exec`?**

```bash
V="$(cat "$TMPDIR/bron-2a-spike/path")"; cd "$V" && codex exec --skip-git-repo-check --dangerously-bypass-hook-trust "Run the shell command .bron/bin/bron version and write its output into Projects/v.txt" 2>/dev/null | tail -3; cat Projects/v.txt
```

Expected: `Projects/v.txt` contains `0.1.0`.

- [ ] **Step 8: Write the findings and commit**

Append to `docs/superpowers/specs/2026-10-01-bron-plan2-cli-verification.md`:

```markdown
## Plan 2a pre-checks

| Row | Question | Observed (quoted) | Impact |
|---|---|---|---|
| V1 | Codex triggers see BRON_AGENT | … | … |
| V2 | Claude -p: acceptEdits + --allowedTools Bash; project ask still refuses rm | … | … |
| V3 | --settings remembered on --resume | … | … |
| V4 | --disallowedTools hides plugin and claude.ai servers (comma list) | … | … |
| V5 | Codex answer text key in item.completed | … | … |
| V6 | Codex exec can run .bron/bin/bron and write in the vault | … | … |
```

Edit any Task 6 or 7 code block whose assumption differs; the "Impact" column names the line. Then:

```bash
rm -rf "$TMPDIR/bron-2a-spike"
git add docs/superpowers/specs/2026-10-01-bron-plan2-cli-verification.md docs/superpowers/plans/2026-10-01-bron-core-2a-handoffs.md
git commit -m "docs: plan 2 CLI verification (runner pre-checks)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Native connections and `all`

**Files:**
- Modify: `core/Engine/bron/model.py`, `core/Engine/bron/loader.py`, `core/Engine/bron/check.py`, `core/Engine/bron/gen_claude.py`, `core/Engine/bron/gen_codex.py`, `template/System/Agents/Bron/Agent.md`
- Create: `core/Engine/bron/access.py`
- Test: `tests/test_native.py`

**Interfaces:**
- Consumes: Plan 1's `Config`, `Connection`, `conn_key`, `rules`, `_blocked_servers`, `_servers`.
- Produces:
  - `bron.model`:
    - `CONNECTION_TYPES = ("mcp-stdio", "mcp-http", "native")` and `ALL = "all"`.
    - New `Connection` fields: `claude: str = ""`, `codex: str = ""`, `status: str = ""`.
  - `bron.access`:
    - `allowed_keys(cfg, names: list[str]) -> set[str]`
    - `claude_server(conn) -> str`
    - `codex_server(conn) -> str`, where an empty string means "not available in Codex"
    - `blocked_claude_servers(cfg, names) -> list[str]`, returning tool prefixes such as `mcp__claude_ai_Gmail`
  - `bron.gen_claude.rules(actions, cfg) -> list[str]`. The signature now takes `cfg`.

- [ ] **Step 1: Write the failing tests**

`tests/test_native.py`:

```python
import json
import tomllib

from bron import frontmatter as fm
from bron.access import allowed_keys, blocked_claude_servers
from bron.check import run_checks
from bron.gen_claude import generate as gen_claude
from bron.gen_codex import generate as gen_codex
from bron.loader import load
from vaultkit import add_agent, add_connection, set_meta, write_md

BRON = ("System", "Agents", "Bron", "Agent.md")


def add_native(vault, name, **meta):
    data = {"name": name, "type": "native", **meta}
    return write_md(vault.connections_dir / f"{name}.md", data)


def test_native_connection_loads_with_both_names(vault):
    add_native(vault, "Carta", claude="claude_ai_Carta", codex="carta", status="connected")
    conn = load(vault).connections["carta"]
    assert (conn.type, conn.claude, conn.codex, conn.status) == ("native", "claude_ai_Carta", "carta", "connected")


def test_native_connection_needs_at_least_one_name(vault):
    add_native(vault, "Mystery")
    cfg = load(vault)
    assert "mystery" not in cfg.connections
    assert any("needs 'claude' or 'codex'" in i.message for i in cfg.issues)


def test_bron_template_uses_all_connections(vault):
    assert load(vault).default_agent.connections == ["all"]


def test_all_is_not_an_unknown_connection(vault):
    add_agent(vault, "CFO", connections=["All"])
    assert not [i for i in run_checks(load(vault), include_environment=False) if i.code == "agent.connection-unknown"]


def test_allowed_keys_expands_all(vault):
    add_native(vault, "Carta", claude="claude_ai_Carta")
    add_connection(vault, "Time")
    cfg = load(vault)
    assert allowed_keys(cfg, ["all"]) == {"carta", "time"}
    assert allowed_keys(cfg, ["Carta"]) == {"carta"}
    assert allowed_keys(cfg, []) == set()


def test_blocked_claude_servers_use_each_cli_name(vault):
    add_native(vault, "Carta", claude="claude_ai_Carta", codex="carta")
    add_native(vault, "Codex Only", codex="paper")
    add_connection(vault, "Time")
    cfg = load(vault)
    assert blocked_claude_servers(cfg, ["Time"]) == ["mcp__claude_ai_Carta"]
    assert blocked_claude_servers(cfg, ["all"]) == []


def test_claude_output_keeps_natives_out_of_mcp_json_and_blocks_them_per_agent(vault):
    add_native(vault, "Carta", claude="claude_ai_Carta", codex="carta")
    add_connection(vault, "Time")
    add_agent(vault, "CFO", connections=["Time"])
    files = gen_claude(load(vault))
    assert list(json.loads(files[".mcp.json"])["mcpServers"]) == ["time"]
    settings = json.loads(files[".claude/settings.json"])
    assert settings["enabledMcpjsonServers"] == ["time"]
    cfo = fm.parse(files[".claude/agents/cfo.md"].decode())
    assert cfo.meta["disallowedTools"] == "mcp__claude_ai_Carta"
    bron = fm.parse(files[".claude/agents/bron.md"].decode())
    assert "disallowedTools" not in bron.meta


def test_no_mcp_json_when_only_natives(vault):
    add_native(vault, "Carta", claude="claude_ai_Carta")
    assert ".mcp.json" not in gen_claude(load(vault))


def test_ask_rules_use_the_claude_tool_name_of_a_native_connection(vault):
    add_native(vault, "Gmail", claude="claude_ai_Gmail")
    set_meta(vault.root.joinpath(*BRON), ask_before=["send-email"])
    ask = json.loads(gen_claude(load(vault))[".claude/settings.json"])["permissions"]["ask"]
    assert "mcp__claude_ai_Gmail__send_message" in ask
    assert not any(rule.startswith("mcp__gmail__") for rule in ask)


def test_codex_project_config_leaves_natives_to_the_users_codex(vault):
    add_native(vault, "Carta", claude="claude_ai_Carta", codex="carta")
    add_connection(vault, "Time")
    config = tomllib.loads(gen_codex(load(vault))[".codex/config.toml"].decode())
    assert list(config["mcp_servers"]) == ["time"]
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_native.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.access'`.

- [ ] **Step 3: Update the model and loader**

In `core/Engine/bron/model.py`, replace `CONNECTION_TYPES = ("mcp-stdio", "mcp-http")` with:

```python
CONNECTION_TYPES = ("mcp-stdio", "mcp-http", "native")
ALL = "all"  # in an agent's or helper's connections: every registered connection
```

In the `Connection` dataclass, add these fields after `description`:

```python
    claude: str = ""  # native: the server id in Claude Code tool names (mcp__<claude>__<tool>)
    codex: str = ""  # native: the server name in the user's Codex config
    status: str = ""  # native: what the last scan saw (connected / needs sign-in / available / not found)
```

In `core/Engine/bron/loader.py` `_connections`:

1. Replace the type-check message with:

   ```python
           if kind not in CONNECTION_TYPES:
               f.problem("field.value", "'type' should be mcp-stdio, mcp-http or native")
               continue
   ```

2. Add the three new fields to the `Connection(...)` call:

   ```python
               claude=f.text("claude"),
               codex=f.text("codex"),
               status=f.text("status"),
   ```

3. Immediately after the `Connection(...)` construction, before the `mcp-stdio` check, add:

   ```python
           if kind == "native" and not (conn.claude or conn.codex):
               f.problem("field.missing", "A native connection needs 'claude' or 'codex' (the name each CLI uses for it)")
               continue
   ```

- [ ] **Step 4: Create `access.py`**

`core/Engine/bron/access.py`:

```python
"""Which connections an agent or helper may use, and how each CLI names a connection."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .model import ALL, Connection, conn_key

if TYPE_CHECKING:
    from .loader import Config


def allowed_keys(cfg: "Config", names: list[str]) -> set[str]:
    if any(name.strip().lower() == ALL for name in names):
        return set(cfg.connections)
    return {conn_key(name) for name in names} & set(cfg.connections)


def claude_server(conn: Connection) -> str:
    """The server id Claude Code uses in tool names (mcp__<id>__tool); empty if not in Claude Code."""
    if conn.type == "native":
        return conn.claude
    return conn.key


def codex_server(conn: Connection) -> str:
    """The server name Codex uses; empty if not in Codex."""
    if conn.type == "native":
        return conn.codex
    return conn.key


def blocked_claude_servers(cfg: "Config", names: list[str]) -> list[str]:
    keep = allowed_keys(cfg, names)
    return [
        f"mcp__{claude_server(conn)}"
        for key, conn in sorted(cfg.connections.items())
        if key not in keep and claude_server(conn)
    ]
```

- [ ] **Step 5: Update the health check**

In `core/Engine/bron/check.py`:

1. In `_agents`, replace the connection loop with:

   ```python
           for conn in agent.connections:
               if conn.strip().lower() != ALL and conn_key(conn) not in cfg.connections:
                   bad("agent.connection-unknown", f"{agent.name} uses the connection '{conn}', which isn't set up in System/Connections/")
   ```

2. In `_helpers`, replace its connection loop with:

   ```python
           for conn in helper.connections:
               if conn.strip().lower() != ALL and conn_key(conn) not in cfg.connections:
                   out.append(Issue("error", "helper.connection-unknown", f"The helper '{helper.name}' uses the connection '{conn}', which isn't set up", helper.path))
   ```

3. Import `ALL`: change `from .model import CLI_NAMES, Issue, conn_key, slug` to `from .model import ALL, CLI_NAMES, Issue, conn_key, slug`.

- [ ] **Step 6: Update the Claude generator**

In `core/Engine/bron/gen_claude.py`:

1. Change the import line `from .model import Agent, Connection, Helper, conn_key` to:

   ```python
   from .access import blocked_claude_servers, claude_server
   from .model import Agent, Connection, Helper
   ```

2. Replace `generate`, `rules`, `_settings` and `_blocked_servers` (delete `_blocked_servers`) with:

   ```python
   def generate(cfg: Config) -> dict[str, bytes]:
       files = {
           "CLAUDE.md": b"@AGENTS.md\n",
           ".claude/settings.json": _json(_settings(cfg)),
       }
       vault_servers = _vault_connections(cfg)
       if vault_servers:
           files[".mcp.json"] = _json({"mcpServers": {key: _server(c) for key, c in sorted(vault_servers.items())}})
       for key, agent in sorted(cfg.agents.items()):
           files[f".claude/agents/{key}.md"] = _agent_file(cfg, agent)
       for key, helper in sorted(cfg.helpers.items()):
           files[f".claude/agents/{key}.md"] = _helper_file(cfg, helper)
       files.update(skill_files(cfg, ".claude/skills"))
       return files


   def _vault_connections(cfg: Config) -> dict[str, Connection]:
       """Connections Bron defines itself; native ones already live in the user's Claude Code."""
       return {key: conn for key, conn in cfg.connections.items() if conn.type != "native"}


   def rules(actions: Actions, cfg: Config) -> list[str]:
       out = []
       for key, tools in sorted(actions.mcp.items()):
           conn = cfg.connections.get(key)
           server = claude_server(conn) if conn is not None else key
           if server:
               out += [f"mcp__{server}__{tool}" for tool in sorted(tools)]
       for words in actions.shell:
           command = " ".join(words)
           out += [f"Bash({command})", f"Bash({command} *)"]
       return out


   def _settings(cfg: Config) -> dict:
       agent = cfg.default_agent
       ask, allow = cfg.catalog.permissions_for(agent)
       return {
           "agent": agent.key,
           "autoMemoryEnabled": False,
           "permissions": {
               "ask": rules(ask, cfg),
               "allow": rules(allow, cfg),
               # Team members take work through tickets only. A deny rule blocks just these subagents;
               # Agent(x) in an agent's disallowedTools would remove the whole Agent tool (verification R5).
               "deny": [f"Agent({key})" for key in sorted(cfg.agents)],
           },
           "enabledMcpjsonServers": sorted(_vault_connections(cfg)),
           "hooks": hooks_block(cfg.vault, "claude"),
       }
   ```

3. In `_agent_file`, replace `blocked = _blocked_servers(cfg, agent.connections)` with `blocked = blocked_claude_servers(cfg, agent.connections)`.

4. In `_helper_file`, replace `blocked = _blocked_servers(cfg, helper.connections) + ["Agent"]` with `blocked = blocked_claude_servers(cfg, helper.connections) + ["Agent"]`.

- [ ] **Step 7: Update the Codex generator**

In `core/Engine/bron/gen_codex.py` `_servers`, change the loop header to skip native connections:

```python
    for key, conn in sorted(cfg.connections.items()):
        if conn.type == "native":
            continue  # defined in the user's own Codex config; per-agent limits are applied at launch
```

Then replace `keep = {conn_key(c) for c in allowed}` with `keep = allowed_keys(cfg, allowed)`, and add `from .access import allowed_keys` to the imports. Remove `conn_key` from the `.model` import if nothing else uses it.

- [ ] **Step 8: Give Bron all connections in the template**

In `template/System/Agents/Bron/Agent.md`, change `connections: []` to `connections: [all]`.

- [ ] **Step 9: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS.

Earlier tests that call `rules(...)` directly would need `cfg`, but none do. Any `test_gen_claude.py` assertion about Bron having no `disallowedTools` still holds, because Bron now has `all`.

- [ ] **Step 10: Commit**

```bash
git add core/Engine/bron/model.py core/Engine/bron/loader.py core/Engine/bron/check.py core/Engine/bron/access.py core/Engine/bron/gen_claude.py core/Engine/bron/gen_codex.py template/System/Agents/Bron/Agent.md tests/test_native.py
git commit -m "feat(core): native connections and 'all'" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Discover connectors in both CLIs (`bron connections scan`)

**Files:**
- Create: `core/Engine/bron/scan.py`, `core/Skills/connections/SKILL.md`, `core/Manual/connections.md`
- Modify: `core/Engine/bron/cli.py`, `core/Engine/bron/update.py`, `core/Manual/index.md`
- Test: `tests/test_scan.py`

**Interfaces:**
- Consumes: `load`, native `Connection` fields (Task 2), `bron.frontmatter`, `conn_key`, `run_sync`.
- Produces: `bron.scan`:
  - `Found(name, url="", claude="", codex="", status="")`
  - `ScanReport` with `.render() -> str`
  - `parse_claude_list(text) -> list[Found]`
  - `parse_codex_list(text) -> list[Found]`
  - `merge(claude, codex, skip: set[str]) -> list[Found]`
  - `apply_found(vault, found, *, scanned_claude: bool, scanned_codex: bool) -> ScanReport`
  - `scan(vault, *, claude_text=None, codex_text=None, run=subprocess.run) -> ScanReport`
  - CLI: `bron connections scan`.

- [ ] **Step 1: Write the failing tests**

`tests/test_scan.py`:

```python
from bron import frontmatter as fm
from bron.loader import load
from bron.scan import apply_found, merge, parse_claude_list, parse_codex_list, scan
from vaultkit import add_connection, set_meta

CLAUDE_LIST = """Checking MCP server health…

claude.ai Carta: https://mcp.app.carta.com/mcp - ✔ Connected
claude.ai Google Drive: https://drivemcp.googleapis.com/mcp/v1 - ✔ Connected
claude.ai Booking.com: https://demandapi-mcp.booking.com/v1/mcp/8132308 - ✔ Connected
claude.ai HubSpot: https://mcp.hubspot.com/anthropic - ! Needs authentication
plugin:atl-core-skills:affinity-mcp: uvx affinity-mcp - ✔ Connected
plugin:supabase:supabase: https://mcp.supabase.com/mcp (HTTP) - ! Needs authentication
time: uvx mcp-server-time - ✔ Connected
"""

CODEX_LIST = """[
 {"name": "carta", "enabled": true, "transport": {"type": "streamable_http", "url": "https://mcp.app.carta.com/mcp"}},
 {"name": "paper", "enabled": true, "transport": {"type": "stdio", "command": "/x/paper", "args": ["mcp"]}},
 {"name": "computer-use", "enabled": false, "transport": {"type": "stdio", "command": "x"}}
]"""


def names(found):
    return {f.name: f for f in found}


def test_parse_claude_list_names_each_server_like_claude_tool_names():
    found = names(parse_claude_list(CLAUDE_LIST))
    assert found["Carta"].claude == "claude_ai_Carta"
    assert found["Carta"].url == "https://mcp.app.carta.com/mcp"
    assert found["Carta"].status == "connected"
    assert found["Google Drive"].claude == "claude_ai_Google_Drive"
    assert found["Booking.com"].claude == "claude_ai_Booking_com"
    assert found["HubSpot"].status == "needs sign-in"
    assert found["affinity-mcp"].claude == "plugin_atl-core-skills_affinity-mcp"
    assert found["affinity-mcp"].url == ""
    assert found["supabase"].url == "https://mcp.supabase.com/mcp"
    assert found["time"].claude == "time"
    assert "Checking MCP server health…" not in found


def test_parse_codex_list_skips_disabled_and_tolerates_noise():
    found = names(parse_codex_list("warning: something\n" + CODEX_LIST + "\n"))
    assert set(found) == {"carta", "paper"}
    assert found["carta"].codex == "carta" and found["carta"].url == "https://mcp.app.carta.com/mcp"
    assert parse_codex_list("not json") == []


def test_merge_matches_by_url_then_name_and_skips_vault_connections():
    merged = names(merge(parse_claude_list(CLAUDE_LIST), parse_codex_list(CODEX_LIST), skip={"time"}))
    assert merged["Carta"].claude == "claude_ai_Carta" and merged["Carta"].codex == "carta"
    assert merged["paper"].codex == "paper" and merged["paper"].claude == ""
    assert "time" not in merged


def run_scan(vault):
    return scan(vault, claude_text=CLAUDE_LIST, codex_text=CODEX_LIST)


def test_scan_writes_one_file_per_connector_and_reports(vault):
    report = run_scan(vault)
    cfg = load(vault)
    carta = cfg.connections["carta"]
    assert (carta.type, carta.claude, carta.codex, carta.status) == ("native", "claude_ai_Carta", "carta", "connected")
    assert (vault.connections_dir / "Booking.com.md").is_file()
    assert "Carta" in report.created
    assert "HubSpot" in report.needs_sign_in
    text = report.render()
    assert "7 in Claude Code, 2 in Codex" in text
    assert "Needs you to sign in again: HubSpot, supabase" in text


def test_scan_is_idempotent_and_keeps_user_edits(vault):
    run_scan(vault)
    path = vault.connections_dir / "Carta.md"
    doc = fm.read(path)
    doc.meta["description"] = "Fund admin data"
    doc.body += "My note.\n"
    fm.write(path, doc)
    before = sorted(p.name for p in vault.connections_dir.glob("*.md"))
    report = run_scan(vault)
    assert sorted(p.name for p in vault.connections_dir.glob("*.md")) == before
    assert report.created == [] and report.updated == []
    after = fm.read(path)
    assert after.meta["description"] == "Fund admin data" and after.body.endswith("My note.\n")


def test_scan_updates_names_and_marks_missing_connectors(vault):
    run_scan(vault)
    report = scan(vault, claude_text="claude.ai Carta: https://mcp.app.carta.com/mcp - ! Needs authentication\n", codex_text="[]")
    cfg = load(vault)
    assert cfg.connections["carta"].status == "needs sign-in"
    assert cfg.connections["google_drive"].status == "not found"
    assert "Google Drive" in report.missing


def test_scan_does_not_mark_missing_when_a_cli_could_not_be_asked(vault):
    run_scan(vault)
    scan(vault, claude_text=CLAUDE_LIST, codex_text=None, run=lambda *a, **k: (_ for _ in ()).throw(OSError("no codex")))
    assert load(vault).connections["paper"].status != "not found"


def test_scan_never_shadows_a_vault_connection(vault):
    add_connection(vault, "Time")
    run_scan(vault)
    cfg = load(vault)
    assert cfg.connections["time"].type == "mcp-stdio"
    assert not (vault.connections_dir / "time 2.md").exists()


def test_scan_gives_the_default_agent_all_connections(vault):
    set_meta(vault.agents_dir / "Bron" / "Agent.md", connections=[])
    report = run_scan(vault)
    assert load(vault).default_agent.connections == ["all"]
    assert report.opened_for == "Bron"


def test_same_name_twice_in_one_scan_creates_one_file(vault):
    from bron.scan import Found

    apply_found(vault, [Found(name="Notion", claude="claude_ai_Notion"), Found(name="notion", codex="notion")], scanned_claude=True, scanned_codex=True)
    assert [p.name for p in vault.connections_dir.glob("*.md")] == ["Notion.md"]


def test_apply_found_with_nothing_found_changes_nothing(vault):
    report = apply_found(vault, [], scanned_claude=False, scanned_codex=False)
    assert report.created == [] and list(vault.connections_dir.glob("*.md")) == []
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_scan.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.scan'`.

- [ ] **Step 3: Implement `scan.py`**

`core/Engine/bron/scan.py`:

```python
"""Finding the connectors already set up in Claude Code and Codex, and keeping System/Connections in step.

One file per connector (type: native) records the name each CLI uses for it. Re-scanning only
changes the claude, codex, url and status lines, so the user's own description and notes stay.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter as fm
from .loader import load
from .model import ALL, conn_key
from .vault import Vault

_LINE = re.compile(r"^(?P<name>.+?): (?P<target>.+) - (?P<status>.+)$")
_UNSAFE_ID = re.compile(r"[^A-Za-z0-9_-]")
_UNSAFE_FILE = re.compile(r'[\\/:*?"<>|]')
MANAGED = ("claude", "codex", "url", "status")
BODY = (
    "Found automatically by Bron on {date}.\n"
    "You can edit the description or add notes below. Bron only updates the claude, codex, url and status lines.\n"
)


@dataclass
class Found:
    name: str
    url: str = ""
    claude: str = ""
    codex: str = ""
    status: str = ""


@dataclass
class ScanReport:
    found_claude: int = 0
    found_codex: int = 0
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    needs_sign_in: list[str] = field(default_factory=list)
    opened_for: str = ""
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        lines = [f"Connectors found: {self.found_claude} in Claude Code, {self.found_codex} in Codex."]
        if self.created:
            lines.append("Added: " + ", ".join(self.created))
        if self.updated:
            lines.append("Updated: " + ", ".join(self.updated))
        if not self.created and not self.updated:
            lines.append("No changes to System/Connections.")
        if self.needs_sign_in:
            lines.append("Needs you to sign in again: " + ", ".join(self.needs_sign_in))
        if self.missing:
            lines.append("No longer found (kept, marked 'not found'): " + ", ".join(self.missing))
        if self.opened_for:
            lines.append(f"{self.opened_for} can now use all of them.")
        lines += self.notes
        return "\n".join(lines)


def _status(text: str) -> str:
    low = text.lower()
    if "auth" in low:
        return "needs sign-in"
    if "connected" in low and "fail" not in low:
        return "connected"
    return "error"


def parse_claude_list(text: str) -> list[Found]:
    out: list[Found] = []
    for raw_line in text.splitlines():
        match = _LINE.match(raw_line.strip())
        if not match:
            continue
        raw, target, status = match["name"].strip(), match["target"].strip(), match["status"].strip()
        if raw.startswith("claude.ai "):
            name = raw[len("claude.ai "):].strip()
            server = "claude_ai_" + _UNSAFE_ID.sub("_", name)
        elif raw.startswith("plugin:"):
            name = raw.split(":")[-1]
            server = _UNSAFE_ID.sub("_", raw)
        else:
            name = raw
            server = raw
        url = target.split()[0] if target.startswith("http") else ""
        out.append(Found(name=name, url=url, claude=server, status=_status(status)))
    return out


def parse_codex_list(text: str) -> list[Found]:
    start = text.find("[")
    if start < 0:
        return []
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return []
    out: list[Found] = []
    for server in data if isinstance(data, list) else []:
        if not isinstance(server, dict) or not server.get("enabled", True):
            continue
        name = str(server.get("name") or "").strip()
        if not name:
            continue
        transport = server.get("transport")
        url = str(transport.get("url") or "") if isinstance(transport, dict) else ""
        out.append(Found(name=name, url=url, codex=name))
    return out


def _same_url(a: str, b: str) -> bool:
    return bool(a and b) and a.strip().lower().rstrip("/") == b.strip().lower().rstrip("/")


def merge(claude: list[Found], codex: list[Found], skip: set[str]) -> list[Found]:
    merged = [f for f in claude if conn_key(f.name) not in skip]
    for c in codex:
        if conn_key(c.name) in skip:
            continue
        match = next((m for m in merged if not m.codex and _same_url(m.url, c.url)), None)
        if match is None:
            match = next((m for m in merged if not m.codex and conn_key(m.name) == conn_key(c.name)), None)
        if match is None:
            merged.append(c)
        else:
            match.codex = c.codex
            match.url = match.url or c.url
    return merged


def _new_path(vault: Vault, name: str) -> Path:
    base = _UNSAFE_FILE.sub("-", name).strip(" .") or conn_key(name) or "connector"
    path = vault.connections_dir / f"{base}.md"
    n = 2
    while path.exists():
        path = vault.connections_dir / f"{base} {n}.md"
        n += 1
    return path


def apply_found(vault: Vault, found: list[Found], *, scanned_claude: bool, scanned_codex: bool) -> ScanReport:
    cfg = load(vault)
    report = ScanReport()
    natives = {key: conn for key, conn in cfg.connections.items() if conn.type == "native"}
    seen: set[str] = set()
    for item in found:
        key = conn_key(item.name)
        if not key or (key in cfg.connections and cfg.connections[key].type != "native"):
            continue
        existing = next(
            (
                c
                for c in natives.values()
                if c is not None and ((item.claude and c.claude == item.claude) or (item.codex and c.codex == item.codex))
            ),
            None,
        )
        if existing is None and key in natives:
            existing = natives[key]
            if existing is None:  # a connector of the same name was already added in this scan
                continue
        values = {
            "claude": item.claude,
            "codex": item.codex,
            "url": item.url,
            "status": item.status or ("available" if item.codex else ""),
        }
        if existing is not None:
            seen.add(existing.key)
            doc = fm.read(existing.path)
            changed = False
            for field_name, value in values.items():
                if value and doc.meta.get(field_name) != value:
                    doc.meta[field_name] = value
                    changed = True
            if changed:
                fm.write(existing.path, doc)
                report.updated.append(existing.name)
        else:
            meta = {"name": item.name, "type": "native", **{k: v for k, v in values.items() if v}}
            fm.write(_new_path(vault, item.name), fm.Document(meta, BODY.format(date=time.strftime("%Y-%m-%d"))))
            report.created.append(item.name)
            seen.add(key)
            natives[key] = None  # reserve the key so a later duplicate updates instead of re-creating
        if item.status == "needs sign-in":
            report.needs_sign_in.append(item.name)
    for key, conn in natives.items():
        if conn is None or key in seen or conn.status == "not found":
            continue
        could_check = (conn.claude and scanned_claude) or (conn.codex and scanned_codex)
        if could_check:
            doc = fm.read(conn.path)
            doc.meta["status"] = "not found"
            fm.write(conn.path, doc)
            report.missing.append(conn.name)
    agent = cfg.default_agent
    if agent is not None and not any(name.strip().lower() == ALL for name in agent.connections):
        doc = fm.read(agent.path)
        current = doc.meta.get("connections")
        others = [str(c) for c in current] if isinstance(current, list) else []
        doc.meta["connections"] = [ALL, *[c for c in others if c.strip().lower() != ALL]]
        fm.write(agent.path, doc)
        report.opened_for = agent.name
    return report


def _ask(cli: str, argv: list[str], vault: Vault, run, notes: list[str]) -> str | None:
    if shutil.which(cli) is None and run is subprocess.run:
        notes.append(f"{'Claude Code' if cli == 'claude' else 'Codex'} isn't installed, so its connectors weren't checked.")
        return None
    try:
        done = run(argv, cwd=vault.root, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        notes.append(f"Couldn't ask {cli} for its connectors ({exc.__class__.__name__}).")
        return None
    return done.stdout


def scan(vault: Vault, *, claude_text: str | None = None, codex_text: str | None = None, run=subprocess.run) -> ScanReport:
    notes: list[str] = []
    if claude_text is None:
        claude_text = _ask("claude", ["claude", "mcp", "list"], vault, run, notes)
    if codex_text is None:
        codex_text = _ask("codex", ["codex", "mcp", "list", "--json"], vault, run, notes)
    claude = parse_claude_list(claude_text) if claude_text is not None else []
    codex = parse_codex_list(codex_text) if codex_text is not None else []
    cfg = load(vault)
    skip = {key for key, conn in cfg.connections.items() if conn.type != "native"}
    report = apply_found(
        vault,
        merge(claude, codex, skip),
        scanned_claude=claude_text is not None,
        scanned_codex=codex_text is not None,
    )
    report.found_claude, report.found_codex = len(claude), len(codex)
    report.notes += notes
    return report
```

- [ ] **Step 4: Wire `bron connections scan` and re-scan after an update**

In `core/Engine/bron/cli.py`, after `sub.add_parser("update", …)`, add:

```python
    p_conn = sub.add_parser("connections", help="find the connectors set up in Claude Code and Codex")
    p_conn.add_argument("action", choices=["scan"])
```

In `main`, before the final `return _sync(...)`, add:

```python
    if args.command == "connections":
        from .scan import scan
        from .sync import run_sync

        print(scan(vault).render())
        result = run_sync(vault)
        if not result.ok:
            print("The setup couldn't be refreshed yet; run `bron check` for details.")
        return 0
```

In `core/Engine/bron/update.py`, just before the final `return 0, …` line of `run_update`, add a best-effort re-scan. It runs only in a real vault, where the shim exists:

```python
    scan_note = ""
    if vault.bron_command.is_file():
        try:
            scanned = subprocess.run([str(vault.bron_command), "connections", "scan"], capture_output=True, text=True, timeout=300)
            scan_note = "\n" + scanned.stdout.strip() if scanned.stdout.strip() else ""
        except (OSError, subprocess.TimeoutExpired):
            scan_note = "\nConnectors weren't re-checked this time."
```

Then append `{scan_note}` to the returned message, right before `\nStart a new session…`.

- [ ] **Step 5: Add the skill and the manual page**

`core/Skills/connections/SKILL.md`:

```markdown
---
name: connections
description: Find and register the connectors already set up in Claude Code and Codex, when the user asks Bron to check, refresh or list its connections, or says a connector is missing.
---

# Connections

1. From the vault folder, run `.bron/bin/bron connections scan`.
2. Tell the user in plain words what it found: new connectors, ones that need signing in again (they fix that in claude.ai connector settings or in Codex), and ones no longer found.
3. To give a team member a connector, add its name to that agent's `connections:` list in `System/Agents/<Name>/Agent.md` (show the change and get a yes first). Bron itself uses all of them (`connections: [all]`).
```

`core/Manual/connections.md`:

```markdown
# Connections

Each file in `System/Connections/` is one outside tool an agent can use.

- **Native connectors** (`type: native`) are the ones already set up in Claude Code (including claude.ai connectors and plugins) or in Codex. Bron finds them with `.bron/bin/bron connections scan` (also run after every update) and writes one file each:
  - `claude:` the name Claude Code uses (tools appear as `mcp__<claude>__<tool>`)
  - `codex:` the name in Codex's own settings
  - `status:` connected, needs sign-in, available or not found
  Bron only ever changes those lines; edit the description or add notes freely.
- **Vault connections** (`type: mcp-stdio` or `mcp-http`) are servers Bron defines itself for both CLIs.

An agent's `connections:` list decides what it may use. `all` means every connection (Bron's default). Anything not listed is switched off for that agent in both CLIs, including when it works a ticket in the background.
```

In `core/Manual/index.md`, add these rows to the table:

```markdown
| [connections.md](connections.md) | Connectors: how Bron finds them and which agent may use which |
| [tickets.md](tickets.md) | Tickets: handing work between agents, statuses, approvals |
```

(`tickets.md` arrives in Task 10. The link is added now so the index changes only once.)

- [ ] **Step 6: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS. `test_update.py` is unaffected, because its fake vault has no `.bron/bin/bron`.

- [ ] **Step 7: Commit**

```bash
git add core/Engine/bron/scan.py core/Engine/bron/cli.py core/Engine/bron/update.py core/Skills/connections core/Manual/connections.md core/Manual/index.md tests/test_scan.py
git commit -m "feat(core): discover connectors in Claude Code and Codex" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Tickets (`tickets.py`, `bron ticket …`) and locked state files

**Files:**
- Create: `core/Engine/bron/statefile.py`, `core/Engine/bron/tickets.py`, `core/Engine/bron/tickets_cli.py`
- Modify: `core/Engine/bron/cli.py`
- Test: `tests/test_tickets.py`

**Interfaces:**
- Consumes: `bron.frontmatter`, `Vault` (`tickets_dir`, `state_dir`), `load`, `slug`.
- Produces:
  - `bron.statefile`:
    - `locked(path)` (context manager)
    - `read_json(path, default)`
    - `write_json(path, data)`
    - `update_json(path, default, change)`, which returns the new data
    - `append_line(path, text)`
    - `read_lines(path) -> list[str]`
  - `bron.tickets`:
    - Constants: `STATUSES`, `OPEN = ("backlog", "todo", "in-progress", "blocked", "in-review")`, `KINDS`, `PRIORITIES`.
    - Types: `TicketError(ValueError)` and `Ticket`, a dataclass with `id, title, path, status, kind, assignee, requested_by, parent, project, priority, due, created, request, context, thread: list[str], result, problems: list[str]`.
    - Functions:
      - `normalize_id(text) -> str` (e.g. `"42"` → `"T-0042"`)
      - `new_ticket(vault, *, title, assignee, request, requested_by="you", context="", kind="task", project="", parent="", priority="normal", due="", status="todo") -> Ticket`
      - `find_ticket(vault, ticket_id) -> Path`
      - `load_ticket(path) -> Ticket`
      - `save_ticket(ticket) -> None`
      - `add_message(ticket, author, text) -> None`
      - `set_status(ticket, status, author, note="") -> None`
      - `set_result(ticket, text, author) -> None`, which sets status `in-review`
      - `list_tickets(vault) -> tuple[list[Ticket], list[str]]`, returning the tickets and any problems
  - `bron.tickets_cli`: `add_parser(sub)` and `handle(args, vault) -> int`.
  - CLI: `bron ticket new|show|say|status|result|list`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tickets.py`:

```python
import pytest

from bron.cli import main
from bron.tickets import (
    TicketError,
    add_message,
    find_ticket,
    list_tickets,
    load_ticket,
    new_ticket,
    normalize_id,
    save_ticket,
    set_result,
    set_status,
)
from vaultkit import add_agent, set_meta


def make(vault, **overrides):
    data = {"title": "Prepare Q3 LP report", "assignee": "cfo", "request": "Draft the Q3 report.", "requested_by": "bron"}
    data.update(overrides)
    return new_ticket(vault, **data)


def test_normalize_id():
    assert normalize_id("42") == "T-0042"
    assert normalize_id("t-7") == "T-0007"
    assert normalize_id("T-12345") == "T-12345"
    with pytest.raises(TicketError, match="isn't a ticket id"):
        normalize_id("Q3 report")


def test_new_ticket_file_name_sections_and_first_thread_entry(vault):
    ticket = make(vault, context="Use the 30 Sep NAV.")
    assert ticket.id == "T-0001"
    assert ticket.path == vault.tickets_dir / "T-0001 Prepare Q3 LP report.md"
    text = ticket.path.read_text(encoding="utf-8")
    assert text.index("## Request") < text.index("## Context") < text.index("## Thread") < text.index("## Result")
    loaded = load_ticket(ticket.path)
    assert (loaded.status, loaded.kind, loaded.assignee, loaded.requested_by) == ("todo", "task", "cfo", "bron")
    assert loaded.request == "Draft the Q3 report." and loaded.context == "Use the 30 Sep NAV."
    assert loaded.thread[0].endswith("· bron: created for cfo")


def test_ids_are_sequential_and_survive_a_lost_counter(vault):
    assert make(vault).id == "T-0001"
    assert make(vault, title="Second").id == "T-0002"
    (vault.state_dir / "tickets.json").unlink()
    assert make(vault, title="Third").id == "T-0003"


def test_titles_are_made_safe_for_file_names(vault):
    ticket = make(vault, title='Fund I/II: "capital call" #3?')
    assert ticket.path.name == "T-0001 Fund I-II- -capital call- -3-.md"
    assert load_ticket(ticket.path).title == 'Fund I/II: "capital call" #3?'


def test_find_accepts_short_ids_and_explains_missing(vault):
    make(vault)
    assert find_ticket(vault, "1").name.startswith("T-0001 ")
    with pytest.raises(TicketError, match="There's no ticket T-0009"):
        find_ticket(vault, "9")


def test_thread_messages_status_and_result(vault):
    ticket = make(vault)
    add_message(ticket, "cfo", "Question:\nNAV as of 30 Sep or 15 Oct?")
    set_status(ticket, "blocked", "cfo", "waiting for the NAV date")
    save_ticket(ticket)
    loaded = load_ticket(ticket.path)
    assert loaded.status == "blocked"
    assert "cfo: Question:\n  NAV as of 30 Sep or 15 Oct?" in loaded.thread[1]
    assert loaded.thread[2].endswith("cfo: status → blocked: waiting for the NAV date")
    set_result(loaded, "Draft saved to Projects/Q3/draft.md", "cfo")
    save_ticket(loaded)
    again = load_ticket(ticket.path)
    assert again.status == "in-review" and again.result == "Draft saved to Projects/Q3/draft.md"
    with pytest.raises(TicketError, match="isn't a ticket status"):
        set_status(again, "finished", "cfo")


def test_hand_edited_ticket_is_read_tolerantly(vault):
    ticket = make(vault)
    text = ticket.path.read_text(encoding="utf-8")
    text = text.replace("status: todo", "status: waiting").replace("## Context\n", "")
    text = text.replace("## Result", "I typed this without a bullet.\n\n## Result")
    ticket.path.write_text(text, encoding="utf-8")
    loaded = load_ticket(ticket.path)
    assert loaded.status == "todo"
    assert any("waiting" in p for p in loaded.problems)
    assert loaded.context == ""
    assert loaded.thread[-1] == "- I typed this without a bullet."


def test_broken_ticket_file_gives_a_plain_error(vault):
    ticket = make(vault)
    ticket.path.write_text("---\nid: [T-0001\n---\n", encoding="utf-8")
    with pytest.raises(TicketError, match="can't be read"):
        load_ticket(ticket.path)
    tickets, problems = list_tickets(vault)
    assert tickets == [] and any("T-0001" in p for p in problems)


@pytest.fixture
def team(vault, monkeypatch):
    add_agent(vault, "CFO")
    set_meta(vault.agents_dir / "Bron" / "Agent.md", can_assign_to=["CFO"])
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    return vault


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_cli_new_say_status_result_list(team, capsys):
    code, out, _ = run(capsys, "ticket", "new", "--to", "CFO", "--from", "bron", "--title", "Q3 report", "--request", "Draft it.")
    assert code == 0 and out.startswith("Created T-0001: Tickets/T-0001 Q3 report.md")
    assert run(capsys, "ticket", "say", "T-0001", "Use 30 Sep.", "--as", "bron")[0] == 0
    assert run(capsys, "ticket", "status", "1", "blocked", "--as", "cfo", "--note", "Needs your OK: send email to LPs")[0] == 0
    code, out, _ = run(capsys, "ticket", "result", "1", "--as", "cfo", "--text", "Done.")
    assert code == 0 and "T-0001 is now in-review" in out
    code, out, _ = run(capsys, "ticket", "list", "--for", "cfo", "--open")
    assert "T-0001 [in-review] cfo — Q3 report" in out
    code, out, _ = run(capsys, "ticket", "show", "1")
    assert "Needs your OK: send email to LPs" in out


def test_cli_refuses_assignment_outside_can_assign_to(team, capsys):
    add_agent(team, "COO")
    code, _, err = run(capsys, "ticket", "new", "--to", "COO", "--from", "bron", "--title", "x", "--request", "y")
    assert code == 1 and "can't hand work to COO" in err


def test_cli_explains_unknown_agent(team, capsys):
    code, _, err = run(capsys, "ticket", "new", "--to", "Nobody", "--title", "x", "--request", "y")
    assert code == 1 and "There's no agent called 'Nobody'" in err
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_tickets.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.tickets'`.

- [ ] **Step 3: Implement `statefile.py`**

`core/Engine/bron/statefile.py`:

```python
"""Small state files under .bron/state that two processes may touch at the same time."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
from pathlib import Path
from typing import Callable, Iterator


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def read_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def update_json(path: Path, default, change: Callable):
    with locked(path):
        data = read_json(path, default)
        result = change(data)
        data = data if result is None else result
        write_json(path, data)
        return data


def append_line(path: Path, text: str) -> None:
    with locked(path):
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text.rstrip("\n") + "\n")


def read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
```

- [ ] **Step 4: Implement `tickets.py`**

`core/Engine/bron/tickets.py`:

```python
"""Tickets: the notes in Tickets/ that agents and the user use to hand each other work."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter as fm
from .statefile import update_json
from .vault import Vault

STATUSES = ("backlog", "todo", "in-progress", "blocked", "in-review", "done", "cancelled")
OPEN = ("backlog", "todo", "in-progress", "blocked", "in-review")
KINDS = ("task", "chat")
PRIORITIES = ("low", "normal", "high", "urgent")
_SECTION = re.compile(r"^## (Request|Context|Thread|Result)[ \t]*$", re.M)
_ID = re.compile(r"^[Tt]?-?(\d+)$")
_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]')


class TicketError(ValueError):
    """A ticket problem to show the user as it is."""


@dataclass
class Ticket:
    id: str
    title: str
    path: Path
    status: str = "todo"
    kind: str = "task"
    assignee: str = ""
    requested_by: str = "you"
    parent: str = ""
    project: str = ""
    priority: str = "normal"
    due: str = ""
    created: str = ""
    request: str = ""
    context: str = ""
    thread: list[str] = field(default_factory=list)
    result: str = ""
    problems: list[str] = field(default_factory=list)


def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M")


def normalize_id(text: str) -> str:
    match = _ID.match(text.strip())
    if not match:
        raise TicketError(f"'{text}' isn't a ticket id (like T-0042)")
    return f"T-{int(match.group(1)):04d}"


def _safe_title(title: str) -> str:
    return _UNSAFE.sub("-", title).strip().strip(".")[:60].rstrip(" .") or "Untitled"


def _highest_existing(vault: Vault) -> int:
    best = 0
    if vault.tickets_dir.is_dir():
        for path in vault.tickets_dir.glob("T-*.md"):
            match = re.match(r"^T-(\d+)", path.name)
            if match:
                best = max(best, int(match.group(1)))
    return best


def _next_id(vault: Vault) -> str:
    holder: dict = {}

    def bump(data: dict) -> dict:
        number = max(int(data.get("next", 1)), _highest_existing(vault) + 1)
        holder["n"] = number
        data["next"] = number + 1
        return data

    update_json(vault.state_dir / "tickets.json", {}, bump)
    return f"T-{holder['n']:04d}"


def _check(value: str, allowed: tuple, what: str) -> str:
    if value not in allowed:
        raise TicketError(f"'{value}' isn't a ticket {what} ({', '.join(allowed)})")
    return value


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
) -> Ticket:
    if not title.strip():
        raise TicketError("A ticket needs a title")
    _check(kind, KINDS, "kind")
    _check(priority, PRIORITIES, "priority")
    _check(status, STATUSES, "status")
    ticket_id = _next_id(vault)
    vault.tickets_dir.mkdir(parents=True, exist_ok=True)
    ticket = Ticket(
        id=ticket_id,
        title=title.strip(),
        path=vault.tickets_dir / f"{ticket_id} {_safe_title(title)}.md",
        status=status,
        kind=kind,
        assignee=assignee,
        requested_by=requested_by,
        parent=normalize_id(parent) if parent else "",
        project=project,
        priority=priority,
        due=due,
        created=time.strftime("%Y-%m-%dT%H:%M"),
        request=request.strip(),
        context=context.strip(),
    )
    add_message(ticket, requested_by, f"created for {assignee}")
    save_ticket(ticket)
    return ticket


def find_ticket(vault: Vault, ticket_id: str) -> Path:
    tid = normalize_id(ticket_id)
    if vault.tickets_dir.is_dir():
        matches = sorted(vault.tickets_dir.glob(f"{tid} *.md")) + sorted(vault.tickets_dir.glob(f"{tid}.md"))
        if matches:
            return matches[0]
    raise TicketError(f"There's no ticket {tid} in Tickets/")


def _sections(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    marks = list(_SECTION.finditer(body))
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(body)
        out[mark.group(1)] = body[mark.end():end].strip("\n")
    return out


def _thread(text: str) -> list[str]:
    entries: list[str] = []
    for line in text.splitlines():
        if line.startswith("- "):
            entries.append(line.rstrip())
        elif line.strip() and entries and line.startswith(" "):
            entries[-1] += "\n  " + line.strip()
        elif line.strip():
            entries.append("- " + line.strip())
    return entries


def load_ticket(path: Path) -> Ticket:
    try:
        doc = fm.read(path)
    except fm.FrontmatterError as exc:
        raise TicketError(f"{path.name} can't be read: {exc}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise TicketError(f"{path.name} can't be opened ({exc.__class__.__name__})") from exc
    meta = doc.meta
    problems: list[str] = []
    raw_id = str(meta.get("id") or path.name.split(" ")[0])
    ticket_id = normalize_id(raw_id)

    def choice(key: str, allowed: tuple, default: str) -> str:
        value = str(meta.get(key) or default).strip().lower()
        if value not in allowed:
            problems.append(f"{key} '{value}' isn't one of {', '.join(allowed)}; treated as {default}")
            return default
        return value

    sections = _sections(doc.body)
    return Ticket(
        id=ticket_id,
        title=str(meta.get("title") or path.stem[len(ticket_id):].strip() or ticket_id),
        path=path,
        status=choice("status", STATUSES, "todo"),
        kind=choice("kind", KINDS, "task"),
        assignee=str(meta.get("assignee") or ""),
        requested_by=str(meta.get("requested_by") or "you"),
        parent=str(meta.get("parent") or ""),
        project=str(meta.get("project") or ""),
        priority=choice("priority", PRIORITIES, "normal"),
        due=str(meta.get("due") or ""),
        created=str(meta.get("created") or ""),
        request=sections.get("Request", "").strip(),
        context=sections.get("Context", "").strip(),
        thread=_thread(sections.get("Thread", "")),
        result=sections.get("Result", "").strip(),
        problems=problems,
    )


def render(ticket: Ticket) -> str:
    meta: dict = {
        "id": ticket.id,
        "title": ticket.title,
        "kind": ticket.kind,
        "status": ticket.status,
        "assignee": ticket.assignee,
        "requested_by": ticket.requested_by,
    }
    for key in ("parent", "project", "due"):
        value = getattr(ticket, key)
        if value:
            meta[key] = value
    meta["priority"] = ticket.priority
    meta["created"] = ticket.created
    thread = "".join(entry + "\n" for entry in ticket.thread)
    body = (
        f"\n## Request\n{ticket.request}\n\n## Context\n{ticket.context}\n\n"
        f"## Thread\n{thread}\n## Result\n{ticket.result}\n"
    )
    return fm.dump(fm.Document(meta, body))


def save_ticket(ticket: Ticket) -> None:
    ticket.path.parent.mkdir(parents=True, exist_ok=True)
    tmp = ticket.path.with_name(ticket.path.name + ".bron-tmp")
    tmp.write_text(render(ticket), encoding="utf-8")
    tmp.replace(ticket.path)


def add_message(ticket: Ticket, author: str, text: str) -> None:
    lines = text.strip().splitlines() or [""]
    entry = f"- {_stamp()} · {author}: {lines[0]}" + "".join(f"\n  {line.strip()}" for line in lines[1:])
    ticket.thread.append(entry)


def set_status(ticket: Ticket, status: str, author: str, note: str = "") -> None:
    ticket.status = _check(status.strip().lower(), STATUSES, "status")
    add_message(ticket, author, f"status → {ticket.status}" + (f": {note.strip()}" if note.strip() else ""))


def set_result(ticket: Ticket, text: str, author: str) -> None:
    ticket.result = text.strip()
    set_status(ticket, "in-review", author, "result added")


def list_tickets(vault: Vault) -> tuple[list[Ticket], list[str]]:
    tickets: list[Ticket] = []
    problems: list[str] = []
    if vault.tickets_dir.is_dir():
        for path in sorted(vault.tickets_dir.glob("T-*.md")):
            try:
                tickets.append(load_ticket(path))
            except TicketError as exc:
                problems.append(str(exc))
    return tickets, problems
```

- [ ] **Step 5: Implement `tickets_cli.py` and wire it**

`core/Engine/bron/tickets_cli.py`:

```python
"""`bron ticket …`: how agents and the user create and update tickets."""
from __future__ import annotations

import sys
from pathlib import Path


def add_parser(sub) -> None:
    parser = sub.add_parser("ticket", help="create and update tickets")
    commands = parser.add_subparsers(dest="ticket_command", required=True)

    new = commands.add_parser("new", help="create a ticket")
    new.add_argument("--to", required=True, help="the agent who should do the work")
    new.add_argument("--title", required=True)
    request = new.add_mutually_exclusive_group(required=True)
    request.add_argument("--request")
    request.add_argument("--request-file")
    context = new.add_mutually_exclusive_group()
    context.add_argument("--context")
    context.add_argument("--context-file")
    new.add_argument("--from", dest="requested_by", default="you")
    new.add_argument("--project", default="")
    new.add_argument("--parent", default="")
    new.add_argument("--priority", default="normal")
    new.add_argument("--due", default="")

    show = commands.add_parser("show", help="print a ticket")
    show.add_argument("id")

    say = commands.add_parser("say", help="add a message to a ticket's thread")
    say.add_argument("id")
    say.add_argument("text")
    say.add_argument("--as", dest="author", default="you")

    status = commands.add_parser("status", help="change a ticket's status")
    status.add_argument("id")
    status.add_argument("status")
    status.add_argument("--as", dest="author", default="you")
    status.add_argument("--note", default="")

    result = commands.add_parser("result", help="record the result and mark the ticket in-review")
    result.add_argument("id")
    given = result.add_mutually_exclusive_group(required=True)
    given.add_argument("--text")
    given.add_argument("--file")
    result.add_argument("--as", dest="author", default="you")

    listing = commands.add_parser("list", help="list tickets")
    listing.add_argument("--for", dest="for_agent", default="")
    listing.add_argument("--open", action="store_true")


def _read(value: str | None, file: str | None) -> str:
    if file:
        return Path(file).read_text(encoding="utf-8")
    return value or ""


def _agent_key(cfg, name: str) -> str:
    from .model import slug
    from .tickets import TicketError

    key = slug(name)
    if key not in cfg.agents:
        names = ", ".join(agent.name for agent in cfg.agents.values())
        raise TicketError(f"There's no agent called '{name}'. Agents: {names}")
    return key


def _author(name: str) -> str:
    from .model import slug

    return "you" if slug(name) in ("", "you") else slug(name)


def handle(args, vault) -> int:
    from .loader import load
    from .model import slug
    from .tickets import (
        OPEN,
        TicketError,
        add_message,
        find_ticket,
        list_tickets,
        load_ticket,
        new_ticket,
        save_ticket,
        set_result,
        set_status,
    )

    try:
        command = args.ticket_command
        if command == "new":
            cfg = load(vault)
            assignee = _agent_key(cfg, args.to)
            requester = "you" if slug(args.requested_by) in ("", "you") else _agent_key(cfg, args.requested_by)
            if requester != "you" and assignee not in {slug(a) for a in cfg.agents[requester].can_assign_to}:
                boss, worker = cfg.agents[requester].name, cfg.agents[assignee].name
                raise TicketError(f"{boss} can't hand work to {worker}: add {worker} to {boss}'s can_assign_to first.")
            ticket = new_ticket(
                vault,
                title=args.title,
                assignee=assignee,
                requested_by=requester,
                request=_read(args.request, args.request_file),
                context=_read(args.context, args.context_file),
                project=args.project,
                parent=args.parent,
                priority=args.priority,
                due=args.due,
            )
            print(f"Created {ticket.id}: {ticket.path.relative_to(vault.root)}")
            return 0
        if command == "list":
            tickets, problems = list_tickets(vault)
            wanted = slug(args.for_agent) if args.for_agent else ""
            for ticket in tickets:
                if wanted and ticket.assignee != wanted:
                    continue
                if args.open and ticket.status not in OPEN:
                    continue
                print(f"{ticket.id} [{ticket.status}] {ticket.assignee} — {ticket.title}")
            for problem in problems:
                print(f"! {problem}")
            return 0
        ticket = load_ticket(find_ticket(vault, args.id))
        if command == "show":
            print(ticket.path.read_text(encoding="utf-8"), end="")
            return 0
        if command == "say":
            add_message(ticket, _author(args.author), args.text)
        elif command == "status":
            set_status(ticket, args.status, _author(args.author), args.note)
        elif command == "result":
            set_result(ticket, _read(args.text, args.file), _author(args.author))
        save_ticket(ticket)
        print(f"{ticket.id} is now {ticket.status}.")
        return 0
    except (TicketError, OSError) as exc:
        print(f"bron: {exc}", file=sys.stderr)
        return 1
```

In `core/Engine/bron/cli.py`:
- After the `connections` parser lines, add `from . import tickets_cli` (imported inside `main`, next to the parser setup) and `tickets_cli.add_parser(sub)`.
- In `main`, before the final `return _sync(...)`, add:

```python
    if args.command == "ticket":
        return tickets_cli.handle(args, vault)
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add core/Engine/bron/statefile.py core/Engine/bron/tickets.py core/Engine/bron/tickets_cli.py core/Engine/bron/cli.py tests/test_tickets.py
git commit -m "feat(core): tickets and the bron ticket command" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Ticket locks

**Files:**
- Create: `core/Engine/bron/locks.py`
- Modify: `core/Engine/bron/check.py` (stale-lock warning)
- Test: `tests/test_locks.py`

**Interfaces:**
- Consumes: `Vault` (`bron_dir`), `Issue`.
- Produces: `bron.locks`:
  - `Lock(ticket_id, run_id, pid, started: float)`
  - `acquire(vault, ticket_id, run_id, *, pid=None, max_minutes=30, now=None) -> bool`
  - `read_lock(vault, ticket_id) -> Lock | None`
  - `release(vault, ticket_id, run_id=None) -> None`
  - `is_stale(lock, max_minutes, now=None) -> bool`
  - `active(vault, max_minutes, now=None) -> list[Lock]`
  - `stale(vault, max_minutes, now=None) -> list[Lock]`
  - check code `locks.stale` (warning).

- [ ] **Step 1: Write the failing tests**

`tests/test_locks.py`:

```python
import os

from bron.check import run_checks
from bron.loader import load
from bron.locks import acquire, active, is_stale, read_lock, release, stale

DEAD_PID = 999_999


def test_acquire_is_exclusive_and_release_frees_it(vault):
    assert acquire(vault, "T-0001", "run-a")
    assert not acquire(vault, "T-0001", "run-b")
    lock = read_lock(vault, "T-0001")
    assert lock.run_id == "run-a" and lock.pid == os.getpid()
    release(vault, "T-0001", "run-b")  # someone else's run can't release it
    assert read_lock(vault, "T-0001") is not None
    release(vault, "T-0001", "run-a")
    assert read_lock(vault, "T-0001") is None


def test_a_dead_process_or_old_lock_is_stale_and_recovered(vault):
    assert acquire(vault, "T-0002", "crashed", pid=DEAD_PID)
    assert is_stale(read_lock(vault, "T-0002"), 30)
    assert acquire(vault, "T-0002", "fresh")
    assert read_lock(vault, "T-0002").run_id == "fresh"
    assert acquire(vault, "T-0003", "slow", now=1000.0)
    assert is_stale(read_lock(vault, "T-0003"), 30, now=1000.0 + 36 * 60)
    assert not is_stale(read_lock(vault, "T-0003"), 30, now=1000.0 + 10 * 60)


def test_active_and_stale_lists(vault):
    acquire(vault, "T-0001", "a")
    acquire(vault, "T-0002", "b", pid=DEAD_PID)
    assert [lock.ticket_id for lock in active(vault, 30)] == ["T-0001"]
    assert [lock.ticket_id for lock in stale(vault, 30)] == ["T-0002"]


def test_unreadable_lock_counts_as_stale(vault):
    (vault.bron_dir / "locks").mkdir(parents=True)
    (vault.bron_dir / "locks" / "T-0004.lock").write_text("garbage")
    assert acquire(vault, "T-0004", "fresh")


def test_health_check_warns_about_leftover_locks(vault):
    acquire(vault, "T-0002", "b", pid=DEAD_PID)
    issues = run_checks(load(vault), include_environment=False)
    assert any(i.code == "locks.stale" and i.level == "warning" and "T-0002" in i.message for i in issues)
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_locks.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.locks'`.

- [ ] **Step 3: Implement `locks.py`**

`core/Engine/bron/locks.py`:

```python
"""One lock per ticket while a run works it. Created atomically; a crashed or expired run's lock is recovered."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .vault import Vault


@dataclass
class Lock:
    ticket_id: str
    run_id: str
    pid: int
    started: float


def _dir(vault: Vault) -> Path:
    return vault.bron_dir / "locks"


def _path(vault: Vault, ticket_id: str) -> Path:
    return _dir(vault) / f"{ticket_id}.lock"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock(vault: Vault, ticket_id: str) -> Lock | None:
    path = _path(vault, ticket_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Lock(ticket_id, str(data["run_id"]), int(data["pid"]), float(data["started"]))
    except (OSError, ValueError, KeyError, TypeError):
        return Lock(ticket_id, "", -1, 0.0)  # unreadable: treated as stale


def is_stale(lock: Lock, max_minutes: int, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    if lock.pid <= 0 or not _alive(lock.pid):
        return True
    return now - lock.started > (max_minutes + 5) * 60


def acquire(vault: Vault, ticket_id: str, run_id: str, *, pid: int | None = None, max_minutes: int = 30, now: float | None = None) -> bool:
    _dir(vault).mkdir(parents=True, exist_ok=True)
    record = json.dumps({"run_id": run_id, "pid": pid or os.getpid(), "started": time.time() if now is None else now})
    for _ in range(2):
        try:
            fd = os.open(_path(vault, ticket_id), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            current = read_lock(vault, ticket_id)
            if current is not None and is_stale(current, max_minutes, now):
                _path(vault, ticket_id).unlink(missing_ok=True)
                continue
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(record)
        return True
    return False


def release(vault: Vault, ticket_id: str, run_id: str | None = None) -> None:
    current = read_lock(vault, ticket_id)
    if current is None or (run_id is not None and current.run_id != run_id):
        return
    _path(vault, ticket_id).unlink(missing_ok=True)


def _all(vault: Vault) -> list[Lock]:
    if not _dir(vault).is_dir():
        return []
    locks = [read_lock(vault, path.stem) for path in sorted(_dir(vault).glob("*.lock"))]
    return [lock for lock in locks if lock is not None]


def active(vault: Vault, max_minutes: int, now: float | None = None) -> list[Lock]:
    return [lock for lock in _all(vault) if not is_stale(lock, max_minutes, now)]


def stale(vault: Vault, max_minutes: int, now: float | None = None) -> list[Lock]:
    return [lock for lock in _all(vault) if is_stale(lock, max_minutes, now)]
```

- [ ] **Step 4: Add the stale-lock warning to the health check**

In `core/Engine/bron/check.py` `run_checks`, add `issues += _locks(cfg)` after `issues += _connections(cfg)`, and add:

```python
def _locks(cfg: Config) -> list[Issue]:
    from .locks import stale

    leftovers = stale(cfg.vault, cfg.settings.max_minutes)
    if not leftovers:
        return []
    ids = ", ".join(lock.ticket_id for lock in leftovers)
    return [Issue("warning", "locks.stale", f"Leftover ticket locks from runs that stopped: {ids}. The next run of each ticket clears its lock automatically.")]
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add core/Engine/bron/locks.py core/Engine/bron/check.py tests/test_locks.py
git commit -m "feat(core): atomic ticket locks with stale recovery" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Launching an agent in each CLI (`launch.py`) and per-agent Claude settings

**Files:**
- Create: `core/Engine/bron/launch.py`
- Modify: `core/Engine/bron/gen_claude.py` (per-agent settings files)
- Test: `tests/test_launch.py`

**Interfaces:**
- Consumes:
  - `Config`; `agent_prompt` (Plan 1).
  - `allowed_keys`, `blocked_claude_servers`, `codex_server` (Task 2).
  - `rules(actions, cfg)` and `cfg.catalog.permissions_for` / `resolve_model`.
- Produces:
  - `bron.launch`:
    - `LaunchSpec(cli: str, argv: list[str], env: dict[str, str])`
    - `choose_cli(cfg, agent, caller_cli: str | None) -> str`
    - `agent_settings_path(vault, key) -> Path`
    - `toml_string(text) -> str`
    - `claude_flags(cfg, agent) -> list[str]`
    - `codex_flags(cfg, agent, *, with_instructions=True) -> list[str]`
    - `run_spec(cfg, agent, cli, prompt, *, session=None, ticket_id=None) -> LaunchSpec`
    - `chat_spec(cfg, agent, cli) -> LaunchSpec`
  - Sync writes `.claude/bron/agents/<key>.settings.json`.

Assumptions verified in Task 1:
- **V2:** `--permission-mode acceptEdits --allowedTools Bash` lets a background Claude agent edit files and run commands, while the project's "ask" rules still refuse those actions.
- **V3:** if `--settings` isn't remembered on resume, the resume command passes it again. This plan always passes it.

- [ ] **Step 1: Write the failing tests**

`tests/test_launch.py`:

```python
import json
import tomllib

from bron.gen_claude import generate
from bron.launch import agent_settings_path, chat_spec, choose_cli, codex_flags, run_spec, toml_string
from bron.loader import load
from bron.prompts import agent_prompt
from vaultkit import add_agent, add_connection, set_meta, write_md


def native(vault, name, **ids):
    write_md(vault.connections_dir / f"{name}.md", {"name": name, "type": "native", **ids})


def team(vault):
    native(vault, "Carta", claude="claude_ai_Carta", codex="carta")
    native(vault, "Gmail", claude="claude_ai_Gmail")
    add_connection(vault, "Time")
    add_agent(vault, "CFO", connections=["Carta"], models={"claude": "Opus 5.5", "codex": "gpt-6.1-sol"}, ask_before=["delete-files"])
    return load(vault)


def test_choose_cli_follows_runs_in_then_caller_then_settings(vault):
    add_agent(vault, "Pinned", runs_in="codex")
    cfg = load(vault)
    assert choose_cli(cfg, cfg.agents["pinned"], "claude") == "codex"
    assert choose_cli(cfg, cfg.agents["bron"], "codex") == "codex"
    assert choose_cli(cfg, cfg.agents["bron"], None) == "claude"


def test_claude_run_command(vault):
    cfg = team(vault)
    spec = run_spec(cfg, cfg.agents["cfo"], "claude", "Work ticket T-0001", ticket_id="T-0001")
    argv = spec.argv
    assert argv[:3] == ["claude", "-p", "Work ticket T-0001"]
    assert argv[argv.index("--agent") + 1] == "cfo"
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    assert argv[argv.index("--settings") + 1] == str(agent_settings_path(vault, "cfo"))
    assert argv[argv.index("--disallowedTools") + 1] == "mcp__claude_ai_Gmail,mcp__time"
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert argv[argv.index("--allowedTools") + 1] == "Bash"
    assert "--resume" not in argv
    assert spec.env == {"BRON_AGENT": "CFO", "BRON_TICKET": "T-0001"}


def test_claude_resume_passes_the_session(vault):
    cfg = team(vault)
    argv = run_spec(cfg, cfg.agents["cfo"], "claude", "Continue", session="abc-123").argv
    assert argv[argv.index("--resume") + 1] == "abc-123"


def test_codex_run_command(vault):
    cfg = team(vault)
    spec = run_spec(cfg, cfg.agents["cfo"], "codex", "Work ticket T-0001", ticket_id="T-0001")
    argv = spec.argv
    assert argv[:6] == ["codex", "exec", "--json", "--skip-git-repo-check", "--dangerously-bypass-hook-trust", "-c"]
    assert argv[-1] == "Work ticket T-0001"
    assert argv[argv.index("-m") + 1] == "gpt-6.1-sol"
    configs = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert "mcp_servers.time.enabled=false" in configs
    assert "mcp_servers.carta.enabled=false" not in configs
    assert not any("gmail" in c for c in configs)  # Gmail has no Codex name
    instructions = next(c for c in configs if c.startswith("developer_instructions="))
    assert tomllib.loads(instructions)["developer_instructions"] == agent_prompt(cfg.agents["cfo"], cfg)


def test_codex_resume_keeps_connection_limits_but_not_instructions(vault):
    cfg = team(vault)
    argv = run_spec(cfg, cfg.agents["cfo"], "codex", "Continue", session="thread-9").argv
    assert argv[:6] == ["codex", "exec", "resume", "--json", "--skip-git-repo-check", "--dangerously-bypass-hook-trust"]
    assert argv[-2:] == ["thread-9", "Continue"]
    assert "mcp_servers.time.enabled=false" in argv
    assert not any(a.startswith("developer_instructions=") for a in argv)


def test_codex_enables_a_vault_connection_the_default_agent_does_not_use(vault):
    add_connection(vault, "Time")
    set_meta(vault.agents_dir / "Bron" / "Agent.md", connections=[])
    add_agent(vault, "CFO", connections=["Time"])
    cfg = load(vault)
    assert "mcp_servers.time.enabled=true" in codex_flags(cfg, cfg.agents["cfo"])


def test_tricky_instructions_survive_toml():
    text = 'Quote " and \\ backslash, """triple""", ação, tab\tand\nnew line'
    assert tomllib.loads(f"v={toml_string(text)}")["v"] == text


def test_chat_specs(vault):
    cfg = team(vault)
    claude = chat_spec(cfg, cfg.agents["cfo"], "claude")
    assert claude.argv[0] == "claude" and "-p" not in claude.argv and "--agent" in claude.argv
    codex = chat_spec(cfg, cfg.agents["cfo"], "codex")
    assert codex.argv[0] == "codex" and "exec" not in codex.argv
    assert claude.env == codex.env == {"BRON_AGENT": "CFO"}


def test_sync_writes_per_agent_claude_permissions(vault):
    cfg = team(vault)
    files = generate(cfg)
    data = json.loads(files[".claude/bron/agents/cfo.settings.json"])
    assert "Bash(rm *)" in data["permissions"]["ask"]
    assert ".claude/bron/agents/bron.settings.json" in files
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_launch.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.launch'`.

- [ ] **Step 3: Write per-agent Claude permission files during sync**

In `core/Engine/bron/gen_claude.py` `generate`, inside the `for key, agent in sorted(cfg.agents.items()):` loop, after writing the agent file, add:

```python
        files[f".claude/bron/agents/{key}.settings.json"] = _json(_agent_permissions(cfg, agent))
```

Then add:

```python
def _agent_permissions(cfg: Config, agent: Agent) -> dict:
    """Passed with --settings when this agent runs a ticket or a direct session; merges with the project file."""
    ask, allow = cfg.catalog.permissions_for(agent)
    return {"permissions": {"ask": rules(ask, cfg), "allow": rules(allow, cfg)}}
```

- [ ] **Step 4: Implement `launch.py`**

`core/Engine/bron/launch.py`:

```python
"""How to start an agent in each CLI: background ticket runs, resumes, and direct sessions.

The command lines follow the templates verified in docs/superpowers/specs/2026-10-01-bron-plan2-cli-verification.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import tomli_w

from .access import allowed_keys, blocked_claude_servers, codex_server
from .model import CLIS, Agent
from .prompts import agent_prompt
from .vault import Vault

if TYPE_CHECKING:
    from .loader import Config

CODEX_EXEC = ["--json", "--skip-git-repo-check", "--dangerously-bypass-hook-trust"]


@dataclass
class LaunchSpec:
    cli: str
    argv: list[str]
    env: dict[str, str] = field(default_factory=dict)


def choose_cli(cfg: "Config", agent: Agent, caller_cli: str | None) -> str:
    if agent.runs_in in CLIS:
        return agent.runs_in
    if caller_cli in CLIS:
        return caller_cli
    return cfg.settings.default_cli


def agent_settings_path(vault: Vault, key: str) -> Path:
    return vault.root / ".claude" / "bron" / "agents" / f"{key}.settings.json"


def toml_string(text: str) -> str:
    """A TOML basic string literal for `-c key=<value>` (escapes quotes, backslashes and newlines)."""
    return tomli_w.dumps({"v": text}).split("=", 1)[1].strip()


def claude_flags(cfg: "Config", agent: Agent) -> list[str]:
    flags = ["--agent", agent.key, "--settings", str(agent_settings_path(cfg.vault, agent.key))]
    model = cfg.catalog.resolve_model("claude", agent.models.get("claude"))
    if model:
        flags += ["--model", model]
    blocked = blocked_claude_servers(cfg, agent.connections)
    if blocked:
        flags += ["--disallowedTools", ",".join(blocked)]
    return flags


def _codex_connection_flags(cfg: "Config", agent: Agent) -> list[str]:
    keep = allowed_keys(cfg, agent.connections)
    default = cfg.default_agent
    default_keep = allowed_keys(cfg, default.connections) if default is not None else set()
    flags: list[str] = []
    for key, conn in sorted(cfg.connections.items()):
        server = codex_server(conn)
        if not server:
            continue
        if key not in keep:
            flags += ["-c", f"mcp_servers.{server}.enabled=false"]
        elif conn.type != "native" and key not in default_keep:
            # The project config switches this server off for the default agent; switch it back on.
            flags += ["-c", f"mcp_servers.{server}.enabled=true"]
    return flags


def codex_flags(cfg: "Config", agent: Agent, *, with_instructions: bool = True) -> list[str]:
    flags: list[str] = []
    if with_instructions:
        flags += ["-c", f"developer_instructions={toml_string(agent_prompt(agent, cfg))}"]
    model = cfg.catalog.resolve_model("codex", agent.models.get("codex"))
    if model:
        flags += ["-m", model]
    return flags + _codex_connection_flags(cfg, agent)


def _env(agent: Agent, ticket_id: str | None) -> dict[str, str]:
    env = {"BRON_AGENT": agent.name}
    if ticket_id:
        env["BRON_TICKET"] = ticket_id
    return env


def run_spec(cfg: "Config", agent: Agent, cli: str, prompt: str, *, session: str | None = None, ticket_id: str | None = None) -> LaunchSpec:
    if cli == "claude":
        argv = ["claude", "-p", prompt]
        if session:
            argv += ["--resume", session]
        argv += claude_flags(cfg, agent)
        argv += ["--output-format", "json", "--permission-mode", "acceptEdits", "--allowedTools", "Bash"]
    else:
        if session:
            # The thread keeps its instructions (verification X2); connection limits are per invocation.
            argv = ["codex", "exec", "resume", *CODEX_EXEC, *codex_flags(cfg, agent, with_instructions=False), session, prompt]
        else:
            argv = ["codex", "exec", *CODEX_EXEC, *codex_flags(cfg, agent), prompt]
    return LaunchSpec(cli, argv, _env(agent, ticket_id))


def chat_spec(cfg: "Config", agent: Agent, cli: str) -> LaunchSpec:
    if cli == "claude":
        argv = ["claude", *claude_flags(cfg, agent)]
    else:
        argv = ["codex", *codex_flags(cfg, agent)]
    return LaunchSpec(cli, argv, _env(agent, None))
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS. `test_sync.py` still passes; the new `.claude/bron/agents/*.settings.json` files sit under `.claude/`, which the writer allows.

- [ ] **Step 6: Commit**

```bash
git add core/Engine/bron/launch.py core/Engine/bron/gen_claude.py tests/test_launch.py
git commit -m "feat(core): launch commands per agent and CLI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The runner (`bron run`) and notifications

**Files:**
- Create: `core/Engine/bron/runner.py`, `core/Engine/bron/notifications.py`
- Modify: `core/Engine/bron/cli.py`
- Test: `tests/test_runner.py`, `tests/test_notifications.py`

**Interfaces:**
- Consumes:
  - `load`; `choose_cli`, `run_spec` (Task 6); `acquire`, `active`, `release` (Task 5).
  - From Task 4: `find_ticket`, `load_ticket`, `save_ticket`, `add_message`, `set_status`, `set_result`, `normalize_id`, `TicketError`, plus `read_json`, `update_json`, `append_line`, `read_lines`, `locked`.
- Produces:
  - `bron.runner`:
    - `Execution(returncode, stdout, stderr, timed_out=False)`
    - `RunOutcome(ticket_id, status, cli, message)`
    - `execute(argv, *, env, cwd, timeout) -> Execution`
    - `parse_claude(stdout) -> tuple[str, str, list[str]]` and `parse_codex(stdout, stderr) -> tuple[str, str, list[str]]`, each returning (session, final text, denials)
    - `run_ticket(vault, ticket_id, *, caller_cli=None, resume=False, run=execute, which=shutil.which, sleep=time.sleep, now=time.time) -> RunOutcome`
    - `start_background(vault, ticket_id, *, caller_cli=None, resume=False, popen=subprocess.Popen) -> int`
    - Constants `NEEDS_OK = "Needs your OK:"` and `APPROVAL_SIGNAL = "approval required by policy"`
  - `bron.notifications`:
    - `record(vault, ticket) -> None`
    - `take(vault, agent_key, default_key) -> list[dict]`, which returns unseen updates for that agent and marks them seen
    - `describe(entry) -> str`
  - CLI: `bron run <id> [--resume] [--background] [--caller-cli claude|codex]`.

Assumption verified in Task 1 (V5): Codex's final answer is `item.text` on the last `item.completed` event whose item type is `agent_message`.

- [ ] **Step 1: Write the failing tests**

`tests/test_notifications.py`:

```python
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
```

`tests/test_runner.py`:

```python
import json

import pytest

from bron.locks import acquire, read_lock
from bron.runner import APPROVAL_SIGNAL, Execution, parse_claude, parse_codex, run_ticket, start_background
from bron.statefile import read_json
from bron.tickets import add_message, load_ticket, new_ticket, save_ticket, set_result, set_status
from vaultkit import add_agent, set_meta

DEAD_PID = 999_999


@pytest.fixture
def team(vault):
    add_agent(vault, "CFO")
    add_agent(vault, "Pinned", runs_in="codex")
    set_meta(vault.agents_dir / "Bron" / "Agent.md", can_assign_to=["CFO", "Pinned"])
    return vault


def ticket_for(vault, assignee="cfo"):
    return new_ticket(vault, title="Q3 report", assignee=assignee, request="Draft it.", requested_by="bron")


def claude_json(session="s1", result="Done.", denials=()):
    return json.dumps({"session_id": session, "result": result, "permission_denials": list(denials)})


def codex_jsonl(thread="th-1", text="Done."):
    events = [
        {"type": "thread.started", "thread_id": thread},
        {"type": "item.completed", "item": {"id": "a", "type": "agent_message", "text": text}},
        {"type": "turn.completed"},
    ]
    return "\n".join(json.dumps(e) for e in events) + "\n"


class FakeCLI:
    """Stands in for `claude`/`codex`; `act` may edit the ticket like the agent would."""

    def __init__(self, vault, result, act=None):
        self.vault, self.result, self.act, self.calls = vault, result, act, []

    def __call__(self, argv, *, env, cwd, timeout):
        self.calls.append({"argv": argv, "env": env, "cwd": cwd, "timeout": timeout})
        if self.act:
            ticket = load_ticket(next(self.vault.tickets_dir.glob(f"{env['BRON_TICKET']} *.md")))
            self.act(ticket)
            save_ticket(ticket)
        return self.result


def found(_cli):
    return f"/usr/bin/{_cli}"


def test_parsers():
    assert parse_claude(claude_json("s9", "Hi", [{"tool_name": "Bash", "tool_input": {"command": "rm a.txt"}}])) == ("s9", "Hi", ["Bash: rm a.txt"])
    assert parse_claude("garbage") == ("", "", [])
    assert parse_codex(codex_jsonl("th-9", "Hi"), "") == ("th-9", "Hi", [])
    assert parse_codex("", f"exec_command failed: {APPROVAL_SIGNAL}")[2]


def test_claude_run_where_the_agent_reports_through_the_ticket(team):
    ticket = ticket_for(team)
    fake = FakeCLI(team, Execution(0, claude_json(), ""), act=lambda t: set_result(t, "Draft in Projects/Q3.md", "cfo"))
    outcome = run_ticket(team, ticket.id, caller_cli="claude", run=fake, which=found)
    assert outcome.status == "in-review" and outcome.cli == "claude"
    call = fake.calls[0]
    assert call["argv"][0] == "claude" and call["argv"][call["argv"].index("--agent") + 1] == "cfo"
    assert call["env"] == {"BRON_AGENT": "CFO", "BRON_TICKET": "T-0001"}
    assert "Read the ticket first: Tickets/T-0001 Q3 report.md" in call["argv"][2]
    assert call["timeout"] == 30 * 60
    loaded = load_ticket(ticket.path)
    assert loaded.result == "Draft in Projects/Q3.md"
    assert any("CFO started in Claude Code" in e for e in loaded.thread)
    runs = read_json(team.state_dir / "runs.json", {})
    assert runs["T-0001"]["cli"] == "claude" and runs["T-0001"]["session"] == "s1"
    assert read_lock(team, "T-0001") is None
    assert (team.state_dir / "notifications.jsonl").read_text().count("T-0001") == 1


def test_pinned_agent_runs_in_its_own_cli_and_a_silent_agent_still_gets_a_result(team):
    ticket = ticket_for(team, "pinned")
    fake = FakeCLI(team, Execution(0, codex_jsonl(text="The answer is 42."), ""))
    outcome = run_ticket(team, ticket.id, caller_cli="claude", run=fake, which=found)
    assert outcome.cli == "codex" and fake.calls[0]["argv"][:2] == ["codex", "exec"]
    loaded = load_ticket(ticket.path)
    assert loaded.status == "in-review" and loaded.result == "The answer is 42."
    assert any("didn't report through the ticket" in e for e in loaded.thread)
    assert read_json(team.state_dir / "runs.json", {})["T-0001"]["session"] == "th-1"


def test_refused_action_blocks_with_needs_your_ok(team):
    ticket = ticket_for(team)
    denials = [{"tool_name": "Bash", "tool_input": {"command": "rm Projects/keep.txt"}}]
    run_ticket(team, ticket.id, caller_cli="claude", run=FakeCLI(team, Execution(0, claude_json(denials=denials), "")), which=found)
    loaded = load_ticket(ticket.path)
    assert loaded.status == "blocked"
    assert "status → blocked: Needs your OK: Bash: rm Projects/keep.txt" in loaded.thread[-1]


def test_codex_approval_signal_blocks(team):
    ticket = ticket_for(team, "pinned")
    run_ticket(team, ticket.id, run=FakeCLI(team, Execution(0, codex_jsonl(text=""), f"... {APPROVAL_SIGNAL} ..."), which=found)
    assert load_ticket(ticket.path).status == "blocked"
    assert "Needs your OK:" in load_ticket(ticket.path).thread[-1]


def test_timeout_and_silent_failure_never_leave_the_ticket_in_progress(team):
    first = ticket_for(team)
    run_ticket(team, first.id, run=FakeCLI(team, Execution(-1, "", "", timed_out=True)), which=found)
    assert load_ticket(first.path).status == "blocked"
    assert "took longer than the time limit" in load_ticket(first.path).thread[-1]
    second = new_ticket(team, title="Other", assignee="cfo", request="x", requested_by="bron")
    run_ticket(team, second.id, run=FakeCLI(team, Execution(1, "", "boom")), which=found)
    last = load_ticket(second.path).thread[-1]
    assert load_ticket(second.path).status == "blocked" and ".bron/runs/" in last
    assert any("boom" in log.read_text() for log in (team.bron_dir / "runs").glob("*.log"))


def test_agent_question_then_resume_in_the_same_session(team):
    ticket = ticket_for(team)
    ask = FakeCLI(team, Execution(0, claude_json(session="s1"), ""), act=lambda t: set_status(t, "blocked", "cfo", "NAV as of 30 Sep or 15 Oct?"))
    run_ticket(team, ticket.id, caller_cli="claude", run=ask, which=found)
    loaded = load_ticket(ticket.path)
    add_message(loaded, "bron", "Use 30 Sep.")
    save_ticket(loaded)
    answer = FakeCLI(team, Execution(0, claude_json(session="s1"), ""), act=lambda t: set_result(t, "Done with 30 Sep.", "cfo"))
    outcome = run_ticket(team, ticket.id, resume=True, run=answer, which=found)
    argv = answer.calls[0]["argv"]
    assert argv[argv.index("--resume") + 1] == "s1"
    assert "Use 30 Sep." in argv[2] and "created for cfo" not in argv[2]
    assert outcome.status == "in-review"


def test_resume_without_a_saved_session_starts_fresh(team):
    ticket = ticket_for(team)
    fake = FakeCLI(team, Execution(0, claude_json(), ""), act=lambda t: set_result(t, "ok", "cfo"))
    run_ticket(team, ticket.id, resume=True, run=fake, which=found)
    assert "--resume" not in fake.calls[0]["argv"]


def test_missing_cli_blocks_with_a_reason(team):
    ticket = ticket_for(team, "pinned")
    fake = FakeCLI(team, Execution(0, "", ""))
    run_ticket(team, ticket.id, run=fake, which=lambda name: None)
    assert fake.calls == []
    assert "Codex isn't installed" in load_ticket(ticket.path).thread[-1]


def test_a_locked_or_finished_ticket_is_not_run(team):
    ticket = ticket_for(team)
    acquire(team, ticket.id, "other-run")
    fake = FakeCLI(team, Execution(0, claude_json(), ""))
    assert "already being worked on" in run_ticket(team, ticket.id, run=fake, which=found).message
    assert fake.calls == []
    done = new_ticket(team, title="Old", assignee="cfo", request="x", requested_by="bron", status="done")
    assert "nothing to run" in run_ticket(team, done.id, run=fake, which=found).message


def test_unknown_assignee_blocks(team):
    ticket = new_ticket(team, title="Ghost", assignee="ghost", request="x", requested_by="bron")
    run_ticket(team, ticket.id, run=FakeCLI(team, Execution(0, "", "")), which=found)
    assert "isn't an agent" in load_ticket(ticket.path).thread[-1]


def test_waits_for_a_free_slot(team):
    set_meta(team.settings_file, runner={"max_parallel": 1, "max_minutes": 30})
    acquire(team, "T-0099", "busy")
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        (team.bron_dir / "locks" / "T-0099.lock").unlink()

    ticket = ticket_for(team)
    fake = FakeCLI(team, Execution(0, claude_json(), ""), act=lambda t: set_result(t, "ok", "cfo"))
    assert run_ticket(team, ticket.id, run=fake, which=found, sleep=sleep).status == "in-review"
    assert slept == [5]


def test_background_start_detaches_and_passes_options(team):
    seen = {}

    class Proc:
        pid = 4242

    def popen(argv, **kwargs):
        seen["argv"], seen["kwargs"] = argv, kwargs
        return Proc()

    assert start_background(team, "T-0001", caller_cli="codex", resume=True, popen=popen) == 4242
    assert seen["argv"] == [str(team.bron_command), "run", "T-0001", "--caller-cli", "codex", "--resume"]
    assert seen["kwargs"]["start_new_session"] is True and seen["kwargs"]["cwd"] == team.root
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_runner.py tests/test_notifications.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.runner'`.

- [ ] **Step 3: Implement `notifications.py`**

`core/Engine/bron/notifications.py`:

```python
"""Ticket updates waiting to be shown to whoever asked for the work."""
from __future__ import annotations

import json
import time

from .statefile import append_line, locked, read_json, read_lines, write_json
from .vault import Vault

FILE = "notifications.jsonl"
SEEN = "notifications-seen.json"


def record(vault: Vault, ticket) -> None:
    entry = {
        "id": ticket.id,
        "title": ticket.title,
        "status": ticket.status,
        "assignee": ticket.assignee,
        "requested_by": ticket.requested_by,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    append_line(vault.state_dir / FILE, json.dumps(entry, ensure_ascii=False))


def take(vault: Vault, agent_key: str, default_key: str) -> list[dict]:
    """Unseen updates for this agent (tickets it asked for; the user's own tickets go to the default agent)."""
    seen_path = vault.state_dir / SEEN
    with locked(seen_path):
        lines = read_lines(vault.state_dir / FILE)
        seen = read_json(seen_path, {})
        start = int(seen.get(agent_key, 0)) if str(seen.get(agent_key, 0)).isdigit() else 0
        updates: list[dict] = []
        for line in lines[start:]:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            requester = entry.get("requested_by") or "you"
            if requester == agent_key or (requester == "you" and agent_key == default_key):
                updates.append(entry)
        seen[agent_key] = len(lines)
        write_json(seen_path, seen)
    return updates


def describe(entry: dict) -> str:
    return f'{entry.get("id")} "{entry.get("title", "")}" is now {entry.get("status")} ({entry.get("assignee")})'
```

- [ ] **Step 4: Implement `runner.py`**

`core/Engine/bron/runner.py`:

```python
"""Running a ticket: start the assignee in its CLI, keep the ticket consistent, remember the session."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass

from .launch import LaunchSpec, choose_cli, run_spec
from .loader import load
from .locks import acquire, active, release
from .model import CLI_NAMES, slug
from .notifications import record
from .statefile import read_json, update_json
from .tickets import TicketError, add_message, find_ticket, load_ticket, normalize_id, save_ticket, set_result, set_status
from .vault import Vault

NEEDS_OK = "Needs your OK:"
APPROVAL_SIGNAL = "approval required by policy"

TASK_PROMPT = """You are {agent}, working ticket {id} in this Bron vault: "{title}".
Read the ticket first: {path}

Do the work it asks for. Save any files you produce in the project or routine folder the ticket links to (or in Projects/Unsorted/ if it links none) and mention them in your result.

Report only through the ticket, with these commands, run from the vault folder:
- To ask a question you need answered: .bron/bin/bron ticket status {id} blocked --as {key} --note "<your question>"   (then stop and wait)
- When you're finished: .bron/bin/bron ticket result {id} --as {key} --text "<a short summary, plus links to any files you made>"

If an action is refused or needs approval (sending, sharing, deleting, pushing, or anything on your ask-before list), don't look for a way around it. Run
.bron/bin/bron ticket status {id} blocked --as {key} --note "{needs_ok} <the exact action, with every detail needed to do it>"
and stop."""

RESUME_PROMPT = """New messages on ticket {id} since your last turn:
{messages}

Continue working the ticket with the same rules as before: report through `.bron/bin/bron ticket` commands, and mark it blocked with "{needs_ok} …" for anything that needs approval."""


@dataclass
class Execution:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class RunOutcome:
    ticket_id: str
    status: str
    cli: str
    message: str


def _text(value) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def execute(argv: list[str], *, env: dict[str, str], cwd, timeout: int) -> Execution:
    try:
        done = subprocess.run(
            argv,
            cwd=cwd,
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        return Execution(-1, _text(exc.stdout), _text(exc.stderr), timed_out=True)
    except OSError as exc:
        return Execution(-1, "", str(exc))
    return Execution(done.returncode, done.stdout, done.stderr)


def parse_claude(stdout: str) -> tuple[str, str, list[str]]:
    data = None
    for line in reversed(stdout.strip().splitlines()):
        try:
            data = json.loads(line)
            break
        except ValueError:
            continue
    if not isinstance(data, dict):
        return "", "", []
    denials: list[str] = []
    for denial in data.get("permission_denials") or []:
        if not isinstance(denial, dict):
            continue
        tool = str(denial.get("tool_name") or "a tool")
        detail = denial.get("tool_input")
        if isinstance(detail, dict):
            detail = detail.get("command") or json.dumps(detail, ensure_ascii=False)
        denials.append(f"{tool}: {str(detail)[:300]}" if detail else tool)
    return str(data.get("session_id") or ""), str(data.get("result") or ""), denials


def parse_codex(stdout: str, stderr: str) -> tuple[str, str, list[str]]:
    thread, text = "", ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "thread.started":
            thread = str(event.get("thread_id") or thread)
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict) and item.get("type") == "agent_message":
            text = str(item.get("text") or text)
    denials = ["a command that needs approval (Codex: approval required by policy)"] if APPROVAL_SIGNAL in stderr else []
    return thread, text, denials


def _block(vault: Vault, ticket, cli: str, note: str) -> RunOutcome:
    set_status(ticket, "blocked", "runner", note)
    save_ticket(ticket)
    record(vault, ticket)
    return RunOutcome(ticket.id, "blocked", cli, f"{ticket.id} is blocked: {note}")


def _wait_for_slot(vault: Vault, settings, sleep, now) -> bool:
    deadline = now() + settings.max_minutes * 60
    while len(active(vault, settings.max_minutes)) >= settings.max_parallel:
        if now() > deadline:
            return False
        sleep(5)
    return True


def _write_log(vault: Vault, run_id: str, spec: LaunchSpec, result: Execution) -> str:
    path = vault.bron_dir / "runs" / f"{run_id}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    note = " (timed out)" if result.timed_out else ""
    path.write_text(
        f"$ {' '.join(spec.argv[:3])} …\nexit: {result.returncode}{note}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}\n",
        encoding="utf-8",
    )
    return str(path.relative_to(vault.root))


def _settle(ticket, agent, result: Execution, text: str, denials: list[str], log: str) -> None:
    """Make sure the ticket never stays in-progress after a run."""
    if ticket.status != "in-progress":
        if denials and ticket.status != "blocked":
            add_message(ticket, "runner", "Some actions were refused while working: " + "; ".join(denials))
        return
    if result.timed_out:
        set_status(ticket, "blocked", "runner", f"{agent.name} took longer than the time limit and was stopped; see {log}")
    elif denials:
        set_status(ticket, "blocked", "runner", f"{NEEDS_OK} " + "; ".join(denials))
    elif text.strip():
        add_message(ticket, "runner", f"{agent.name} didn't report through the ticket; its final answer was saved as the result.")
        set_result(ticket, text, "runner")
    else:
        set_status(ticket, "blocked", "runner", f"The run ended without an answer (exit code {result.returncode}); see {log}")


def run_ticket(
    vault: Vault,
    ticket_id: str,
    *,
    caller_cli: str | None = None,
    resume: bool = False,
    run=execute,
    which=shutil.which,
    sleep=time.sleep,
    now=time.time,
) -> RunOutcome:
    cfg = load(vault)
    try:
        ticket = load_ticket(find_ticket(vault, ticket_id))
    except TicketError as exc:
        return RunOutcome(ticket_id, "error", "", str(exc))
    tid = ticket.id
    if ticket.status in ("done", "cancelled"):
        return RunOutcome(tid, ticket.status, "", f"{tid} is {ticket.status}; nothing to run.")
    agent = cfg.agents.get(slug(ticket.assignee))
    if agent is None:
        return _block(vault, ticket, "", f"The assignee '{ticket.assignee}' isn't an agent in System/Agents/.")
    runs_path = vault.state_dir / "runs.json"
    previous = read_json(runs_path, {}).get(tid, {}) if resume else {}
    cli = previous.get("cli") or choose_cli(cfg, agent, caller_cli)
    if which(cli) is None:
        return _block(vault, ticket, cli, f"{CLI_NAMES[cli]} isn't installed on this Mac, so {agent.name} can't work this ticket.")
    if not _wait_for_slot(vault, cfg.settings, sleep, now):
        return RunOutcome(tid, ticket.status, cli, "Too many tickets are running right now; try again shortly.")
    run_id = uuid.uuid4().hex[:12]
    if not acquire(vault, tid, run_id, max_minutes=cfg.settings.max_minutes):
        return RunOutcome(tid, ticket.status, cli, f"{tid} is already being worked on.")
    try:
        session = previous.get("session") or None
        if session:
            new = ticket.thread[int(previous.get("thread_len", 0)):]
            prompt = RESUME_PROMPT.format(id=tid, messages="\n".join(new) or "(no new messages; carry on)", needs_ok=NEEDS_OK)
        else:
            prompt = TASK_PROMPT.format(
                agent=agent.name,
                id=tid,
                key=agent.key,
                title=ticket.title,
                path=ticket.path.relative_to(vault.root),
                needs_ok=NEEDS_OK,
            )
        set_status(ticket, "in-progress", "runner", f"{agent.name} started in {CLI_NAMES[cli]}" + (" (continuing)" if session else ""))
        save_ticket(ticket)
        spec = run_spec(cfg, agent, cli, prompt, session=session, ticket_id=tid)
        result = run(spec.argv, env=spec.env, cwd=vault.root, timeout=cfg.settings.max_minutes * 60)
        log = _write_log(vault, run_id, spec, result)
        if cli == "claude":
            found_session, text, denials = parse_claude(result.stdout)
        else:
            found_session, text, denials = parse_codex(result.stdout, result.stderr)
        ticket = load_ticket(ticket.path)
        _settle(ticket, agent, result, text, denials, log)
        save_ticket(ticket)
        entry = {
            "cli": cli,
            "session": found_session or session or "",
            "agent": agent.key,
            "thread_len": len(ticket.thread),
            "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        update_json(runs_path, {}, lambda data: data.update({tid: entry}))
        record(vault, ticket)
        note = f": {ticket.thread[-1].split(': ', 1)[-1]}" if ticket.status == "blocked" else ""
        return RunOutcome(tid, ticket.status, cli, f"{tid} is now {ticket.status} ({agent.name}){note}")
    finally:
        release(vault, tid, run_id)


def start_background(vault: Vault, ticket_id: str, *, caller_cli: str | None = None, resume: bool = False, popen=subprocess.Popen) -> int:
    tid = normalize_id(ticket_id)
    log = vault.bron_dir / "runs" / f"background-{tid}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = [str(vault.bron_command), "run", tid]
    if caller_cli:
        argv += ["--caller-cli", caller_cli]
    if resume:
        argv.append("--resume")
    with open(log, "a", encoding="utf-8") as out:
        process = popen(argv, cwd=vault.root, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    return process.pid
```

- [ ] **Step 5: Wire `bron run`**

In `core/Engine/bron/cli.py`, after the `connections` parser, add:

```python
    p_run = sub.add_parser("run", help="have a ticket's assignee work it")
    p_run.add_argument("id")
    p_run.add_argument("--resume", action="store_true", help="continue the same conversation after new messages")
    p_run.add_argument("--background", action="store_true", help="start it and return straight away")
    p_run.add_argument("--caller-cli", choices=CLIS, help="the CLI asking (used when the agent can run in either)")
```

In `main`, before the final `return _sync(...)`, add:

```python
    if args.command == "run":
        from .runner import run_ticket, start_background

        if args.background:
            start_background(vault, args.id, caller_cli=args.caller_cli, resume=args.resume)
            print(f"Started {args.id} in the background. The update will show up in your next message or session.")
            return 0
        outcome = run_ticket(vault, args.id, caller_cli=args.caller_cli, resume=args.resume)
        print(outcome.message)
        return 1 if outcome.status == "error" else 0
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add core/Engine/bron/runner.py core/Engine/bron/notifications.py core/Engine/bron/cli.py tests/test_runner.py tests/test_notifications.py
git commit -m "feat(core): runner for ticket handoffs in both CLIs" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Ticket updates in the briefing and before each message

**Files:**
- Modify: `core/Engine/bron/briefing.py`, `core/Engine/bron/hooks.py`
- Test: `tests/test_ticket_updates.py`

**Interfaces:**
- Consumes: `take`, `describe`, `record` (Task 7); `list_tickets` (Task 4); `slug`; `bron.frontmatter`.
- Produces:
  - The briefing gains a `## Tickets` section, with tickets assigned to the running agent (todo, in-progress or blocked; at most 8) and unseen updates for tickets that agent asked for.
  - The `user-prompt` trigger prints `Ticket updates since your last message:` lines when there are any. Otherwise it prints nothing.

- [ ] **Step 1: Write the failing tests**

`tests/test_ticket_updates.py`:

```python
import io
import json

import pytest

from bron.briefing import build_briefing
from bron.hooks import main as hook
from bron.notifications import record
from bron.tickets import new_ticket
from vaultkit import add_agent


@pytest.fixture
def in_vault(vault, monkeypatch):
    add_agent(vault, "CFO")
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    return vault


def prompt(text="hi"):
    out = io.StringIO()
    assert hook("user-prompt", "claude", stdin=io.StringIO(json.dumps({"prompt": text})), stdout=out) == 0
    return out.getvalue()


def finished(vault, requested_by="bron"):
    ticket = new_ticket(vault, title="Q3 report", assignee="cfo", request="x", requested_by=requested_by)
    ticket.status = "in-review"
    record(vault, ticket)
    return ticket


def test_message_trigger_shows_new_updates_once(in_vault):
    finished(in_vault)
    first = prompt()
    assert first.startswith("Ticket updates since your last message:")
    assert 'T-0001 "Q3 report" is now in-review (cfo)' in first
    assert prompt() == ""


def test_message_trigger_is_silent_without_updates(in_vault):
    assert prompt() == ""


def test_updates_reach_the_agent_that_asked(in_vault, monkeypatch):
    finished(in_vault)
    monkeypatch.setenv("BRON_AGENT", "CFO")
    assert prompt() == ""
    monkeypatch.setenv("BRON_AGENT", "Bron")
    assert "T-0001" in prompt()


def test_briefing_lists_assigned_tickets_and_updates(in_vault, monkeypatch):
    new_ticket(in_vault, title="Fund III fees", assignee="cfo", request="x", requested_by="bron")
    monkeypatch.setenv("BRON_AGENT", "CFO")
    cfo = build_briefing(in_vault, cli="codex")
    assert "You are CFO, working in Codex" in cfo
    assert "- Assigned to you: T-0001 [todo] Fund III fees" in cfo
    monkeypatch.setenv("BRON_AGENT", "Bron")
    finished(in_vault)
    bron = build_briefing(in_vault, cli="claude")
    assert '- Update: T-0002 "Q3 report" is now in-review (cfo)' in bron
    assert "## Tickets" in bron


def test_user_tickets_report_to_the_default_agent(in_vault):
    finished(in_vault, requested_by="you")
    assert "T-0001" in prompt()
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_ticket_updates.py -q`
Expected: failures, because no tickets section or updates are printed yet.

- [ ] **Step 3: Add the tickets section to the briefing**

In `core/Engine/bron/briefing.py`:
- Add the import `from .notifications import describe, take` and the import `from .tickets import list_tickets`.
- Insert this block right after the `if notes:` block:

```python
    key = slug(agent)
    default_key = cfg.default_agent.key if cfg.default_agent else ""
    tickets, _ = list_tickets(vault)
    assigned = [t for t in tickets if t.assignee == key and t.status in ("todo", "in-progress", "blocked")][:8]
    updates = take(vault, key, default_key)
    if assigned or updates:
        lines += ["", "## Tickets"]
        lines += [f"- Assigned to you: {t.id} [{t.status}] {t.title}" for t in assigned]
        lines += [f"- Update: {describe(u)}" for u in updates]
        if any(u.get("status") == "blocked" for u in updates):
            lines.append("For blocked tickets, tell the user what is needed; for 'Needs your OK' follow the delegate skill.")
```

The existing line `key = slug(agent)` further down, in the updated-instructions block, can stay; it computes the same value.

- [ ] **Step 4: Show updates before each message**

In `core/Engine/bron/hooks.py`, replace the `user-prompt` branch with:

```python
        elif event == "user-prompt":
            _payload(stdin)  # drain the prompt; @-mention routing arrives in Plan 2b
            text = _ticket_updates()
            if text:
                try:
                    stdout.write(text)
                except Exception:  # noqa: BLE001
                    pass
```

Then add:

```python
def _ticket_updates() -> str:
    from .model import slug
    from .notifications import FILE, describe, take
    from .vault import Vault

    vault = Vault.find()
    if not (vault.state_dir / FILE).is_file():
        return ""
    default_name = _default_agent(vault)
    agent = os.environ.get("BRON_AGENT") or default_name
    updates = take(vault, slug(agent), slug(default_name))
    if not updates:
        return ""
    lines = ["Ticket updates since your last message:", *[f"- {describe(u)}" for u in updates]]
    lines.append("Read the ticket (.bron/bin/bron ticket show <id>) and tell the user what changed.")
    return "\n".join(lines) + "\n"


def _default_agent(vault) -> str:
    from . import frontmatter as fm

    try:
        return str(fm.read(vault.settings_file).meta.get("default_agent") or "Bron")
    except Exception:  # noqa: BLE001
        return "Bron"
```

This reads only `Settings.md` and the notifications file, so the trigger stays fast on every message.

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS. The existing `test_hooks.py` checks that user-prompt prints `""` still pass, since there are no notifications there.

- [ ] **Step 6: Commit**

```bash
git add core/Engine/bron/briefing.py core/Engine/bron/hooks.py tests/test_ticket_updates.py
git commit -m "feat(core): ticket updates in the briefing and before each message" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: `bron chat` and the pinned-model check

**Files:**
- Modify: `core/Engine/bron/cli.py`, `core/Engine/bron/check.py`
- Test: `tests/test_chat.py`

**Interfaces:**
- Consumes: `chat_spec` (Task 6), `load`, `slug`, `CLIS`, `CLI_NAMES`.
- Produces:
  - `bron chat [agent] [--cli claude|codex]`, which replaces the process with the CLI session (`os.execvpe`) in the vault folder.
  - Check code `agent.model-missing` (warning) for an agent pinned with `runs_in` but no model for that CLI (spec §7.7).

- [ ] **Step 1: Write the failing tests**

`tests/test_chat.py`:

```python
import pytest

from bron.check import run_checks
from bron.cli import main
from bron.loader import load
from vaultkit import add_agent


@pytest.fixture
def launched(vault, monkeypatch):
    add_agent(vault, "CFO", runs_in="codex", models={"codex": "gpt-6.1-sol"})
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    monkeypatch.chdir(vault.root)  # bron chat changes folder; this restores it after the test
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    calls = {}

    def fake_exec(file, argv, env):
        calls.update(file=file, argv=argv, env=env)
        raise SystemExit(0)

    monkeypatch.setattr("os.execvpe", fake_exec)
    return calls


def test_chat_with_the_default_agent_in_the_default_cli(launched, vault):
    with pytest.raises(SystemExit):
        main(["chat"])
    assert launched["file"] == "claude"
    assert launched["argv"][launched["argv"].index("--agent") + 1] == "bron"
    assert launched["env"]["BRON_AGENT"] == "Bron"


def test_chat_with_a_pinned_agent_uses_its_cli(launched):
    with pytest.raises(SystemExit):
        main(["chat", "cfo"])
    assert launched["file"] == "codex"
    assert launched["env"]["BRON_AGENT"] == "CFO"


def test_chat_refuses_the_wrong_cli_for_a_pinned_agent(launched, capsys):
    assert main(["chat", "CFO", "--cli", "claude"]) == 1
    assert "CFO only runs in Codex" in capsys.readouterr().out


def test_chat_explains_unknown_agent_and_missing_cli(launched, capsys, monkeypatch):
    assert main(["chat", "Nobody"]) == 1
    assert "There's no agent called 'Nobody'" in capsys.readouterr().out
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert main(["chat"]) == 1
    assert "Claude Code isn't installed" in capsys.readouterr().out


def test_pinned_agent_without_a_model_for_its_cli_is_a_warning(vault):
    add_agent(vault, "COO", runs_in="claude", models={"codex": "gpt-6.1-sol"})
    issues = [i for i in run_checks(load(vault), include_environment=False) if i.code == "agent.model-missing"]
    assert [i.level for i in issues] == ["warning"]
    assert "COO" in issues[0].message and "Claude Code" in issues[0].message
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_chat.py -q`
Expected: `argparse` exits with "invalid choice: 'chat'", and the model check is missing.

- [ ] **Step 3: Implement `bron chat`**

In `core/Engine/bron/cli.py`, after the `run` parser, add:

```python
    p_chat = sub.add_parser("chat", help="open a session as one agent")
    p_chat.add_argument("agent", nargs="?", default="")
    p_chat.add_argument("--cli", choices=CLIS)
```

In `main`, before the final `return _sync(...)`, add:

```python
    if args.command == "chat":
        return _chat(vault, args.agent, args.cli)
```

Then add the function:

```python
def _chat(vault, name: str, cli: str | None) -> int:
    import os
    import shutil

    from .launch import chat_spec
    from .loader import load
    from .model import CLI_NAMES, slug

    cfg = load(vault)
    key = slug(name) if name else (cfg.default_agent.key if cfg.default_agent else "")
    agent = cfg.agents.get(key)
    if agent is None:
        names = ", ".join(a.name for a in cfg.agents.values())
        print(f"bron: There's no agent called '{name}'. Agents: {names}")
        return 1
    pinned = agent.runs_in if agent.runs_in in CLIS else None
    if cli and pinned and cli != pinned:
        print(f"bron: {agent.name} only runs in {CLI_NAMES[pinned]}.")
        return 1
    chosen = cli or pinned or cfg.settings.default_cli
    if shutil.which(chosen) is None:
        print(f"bron: {CLI_NAMES[chosen]} isn't installed on this Mac.")
        return 1
    spec = chat_spec(cfg, agent, chosen)
    os.chdir(vault.root)
    os.execvpe(spec.argv[0], spec.argv, {**os.environ, **spec.env})
    return 0  # not reached
```

- [ ] **Step 4: Add the pinned-model warning**

In `core/Engine/bron/check.py` `_agents`, inside the per-agent loop after the action checks, add:

```python
        if agent.runs_in in CLI_NAMES and agent.runs_in not in agent.models:
            bad(
                "agent.model-missing",
                f"{agent.name} only runs in {CLI_NAMES[agent.runs_in]} but has no {agent.runs_in} model set; it will use {CLI_NAMES[agent.runs_in]}'s default model",
                "warning",
            )
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS. Earlier tests that add pinned agents without models now also get a warning, but only warnings, so nothing fails. If a test asserts an exact empty issue list for a pinned agent, give that agent a model in the test.

- [ ] **Step 6: Commit**

```bash
git add core/Engine/bron/cli.py core/Engine/bron/check.py tests/test_chat.py
git commit -m "feat(core): bron chat and pinned-model check" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The delegate skill, the tickets manual, the AGENTS.md protocol and the Tickets board

**Files:**
- Create: `core/Skills/delegate/SKILL.md`, `core/Manual/tickets.md`, `template/Tickets/Board.base`
- Modify: `core/Templates/AGENTS.md.tmpl`
- Test: `tests/test_handoff_content.py`

**Interfaces:**
- Consumes: the commands from Tasks 4 and 7 and the approval procedure from "Decisions approved".
- Produces: the user- and agent-facing instructions, and the Obsidian board.

- [ ] **Step 1: Write the failing tests**

`tests/test_handoff_content.py`:

```python
import yaml

from bron.agents_md import render_agents_md
from bron.loader import load


def test_delegate_and_connections_skills_are_published(vault):
    skills = load(vault).skills
    assert {"delegate", "connections"} <= set(skills)


def test_agents_md_has_the_ticket_protocol_and_stays_small(vault):
    text = render_agents_md(load(vault))
    assert "## Tickets" in text
    assert ".bron/bin/bron ticket" in text
    assert "Needs your OK:" in text
    assert len(text.encode()) < 8 * 1024


def test_tickets_board_is_valid_and_hides_chats(vault):
    board = yaml.safe_load((vault.tickets_dir / "Board.base").read_text(encoding="utf-8"))
    names = [view["name"] for view in board["views"]]
    assert names == ["By status", "By assignee", "Chats"]
    assert 'kind != "chat"' in str(board["views"][0]["filters"])
    assert board["views"][0]["groupBy"]["property"] == "status"


def test_manual_index_links_resolve(vault):
    index = (vault.core_manual / "index.md").read_text(encoding="utf-8")
    for page in ("models.md", "permissions.md", "connections.md", "tickets.md"):
        assert f"]({page})" in index
        assert (vault.core_manual / page).is_file()
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_handoff_content.py -q`
Expected: failures for the missing skill, missing manual page, missing board and missing protocol.

- [ ] **Step 3: Write the content**

`core/Skills/delegate/SKILL.md`:

```markdown
---
name: delegate
description: Hand work to a team member through a ticket and follow it up, including questions and approvals. Use when work belongs to another agent ("ask the CFO to…"), when a ticket update arrives, or when a ticket is blocked.
---

# Delegate through tickets

## Hand off
1. Check the team member is in your `can_assign_to` (System/Agents/<You>/Agent.md). If not, tell the user and offer to add it (show the change first).
2. Write the request so it stands on its own: what to do, what "done" looks like, and the context they need (excerpts, file links, numbers).
3. Create the ticket from the vault folder:
   `.bron/bin/bron ticket new --to <Agent> --from <your name> --title "<short title>" --request "<request>" [--context "<context>"] [--project "<Project or Routine>"]`
4. Start it in the background, naming the CLI you are in:
   `.bron/bin/bron run <ticket id> --background --caller-cli <claude|codex>`
5. Tell the user in one line who is working on what, and that you'll report back.

## When an update arrives (in your briefing or before a message)
- **in-review:** read the result (`.bron/bin/bron ticket show <id>`), check it, tell the user, then mark it done (`.bron/bin/bron ticket status <id> done --as <you>`) or send it back with a message and resume it.
- **blocked with a question:** answer it if you can, otherwise ask the user. Write the answer with `.bron/bin/bron ticket say <id> --as <you> "<answer>"`, then continue the same conversation: `.bron/bin/bron run <id> --resume --background --caller-cli <claude|codex>`.
- **blocked with "Needs your OK: …":** show the user the exact action. If they say yes, do that action yourself now (your CLI will ask them to confirm as usual), write what happened with `bron ticket say`, and resume the ticket. If they say no, say so in the ticket and resume it, or cancel it (`bron ticket status <id> cancelled`).

## Never
- Never run a team member as a subagent: tickets only.
- Never work around a refused action.
```

`core/Manual/tickets.md`:

```markdown
# Tickets

A ticket is one note in `Tickets/` (`T-0042 <Title>.md`) that hands work from one agent (or you) to another.

| Status | Meaning |
|---|---|
| todo | waiting to be worked |
| in-progress | an agent is working it right now |
| blocked | the agent needs an answer, or your OK for an action ("Needs your OK: …") |
| in-review | the agent finished; the result is in `## Result` |
| done / cancelled | closed |

The body has four parts: **Request** (what to do), **Context** (what they need to know), **Thread** (dated messages), **Result** (summary and links to outputs). You can type in a ticket in Obsidian; write new thread lines as `- your message`.

## Commands (from the vault folder)
- `.bron/bin/bron ticket new --to <Agent> --from <requester> --title "…" --request "…"`
- `.bron/bin/bron run <id> [--resume] [--background] [--caller-cli claude|codex]`: the assignee works it, in its own CLI and model
- `.bron/bin/bron ticket say|status|result|show|list …`

## How a run works
The assignee works in the background, in the CLI its `runs_in` names (or the requester's CLI). It may read and write files in the vault and run ordinary commands. Anything on its `ask_before` list is refused while it works alone; the ticket becomes blocked with "Needs your OK: <action>". The requester shows you the action, does it after your yes, and resumes the ticket, which continues the same conversation. Updates appear in the requester's next message or session.

`Tickets/Board.base` shows the tickets by status and by assignee.
```

`template/Tickets/Board.base`:

```yaml
filters:
  and:
    - file.inFolder("Tickets")
    - 'file.ext == "md"'

properties:
  file.name:
    displayName: Ticket
  requested_by:
    displayName: "From"

views:
  - type: table
    name: "By status"
    filters:
      and:
        - 'kind != "chat"'
    groupBy:
      property: status
      direction: ASC
    order:
      - file.name
      - status
      - assignee
      - requested_by
      - priority
      - due
      - project

  - type: table
    name: "By assignee"
    filters:
      and:
        - 'kind != "chat"'
        - 'status != "done"'
        - 'status != "cancelled"'
    groupBy:
      property: assignee
      direction: ASC
    order:
      - file.name
      - status
      - priority
      - due

  - type: table
    name: "Chats"
    filters: 'kind == "chat"'
    order:
      - file.name
      - assignee
      - status
```

In `core/Templates/AGENTS.md.tmpl`, add this section after "## Rules for every agent" and before "## How Bron works":

```markdown
## Tickets

Work between agents goes through tickets in `Tickets/` (see `System/Core/Manual/tickets.md`).
- To hand work to a team member, use the delegate skill.
- When you were started to work a ticket, report only with `.bron/bin/bron ticket` commands: `status … blocked --note "<question>"` to ask, `result … --text "<summary>"` when done.
- If an action is refused or needs approval, don't work around it: mark the ticket blocked with a note starting "Needs your OK:" that names the exact action.
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS. The template now has `Tickets/Board.base`. Plan 1's `test_template_has_exactly_the_approved_top_level` lists only top-level folders, so it's unaffected.

- [ ] **Step 5: Commit**

```bash
git add core/Skills/delegate core/Manual/tickets.md core/Templates/AGENTS.md.tmpl template/Tickets/Board.base tests/test_handoff_content.py
git commit -m "feat(core): delegate skill, tickets manual, ticket protocol and board" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Live handoff tests in both CLIs

**Files:**
- Create: `tests/live/test_handoff.py`

**Interfaces:**
- Consumes: everything above; `scripts/dev-vault.sh`.
- Produces: real-CLI proof of the plan's goal, run only when `BRON_LIVE=1`.

**Rules:** each test starts a few short billed sessions. Run the file once. If a test fails, compare it with the verification documents, fix the code, add a unit test that pins the fix, and re-run only the failed test.

- [ ] **Step 1: Write the live tests**

`tests/live/test_handoff.py`:

```python
"""Real ticket handoffs between Claude Code and Codex. Run with: BRON_LIVE=1 uv run --project core/Engine pytest tests/live/test_handoff.py -q"""
import os
import subprocess
from pathlib import Path

import pytest

from bron.tickets import find_ticket, load_ticket
from bron.vault import Vault

pytestmark = pytest.mark.skipif(os.environ.get("BRON_LIVE") != "1", reason="live CLI test: set BRON_LIVE=1")

REPO = Path(__file__).resolve().parents[2]


def bron(vault: Path, *args: str) -> str:
    done = subprocess.run([str(vault / ".bron" / "bin" / "bron"), *args], cwd=vault, capture_output=True, text=True, timeout=900)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


@pytest.fixture(scope="module")
def vault(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("handoff") / "Handoff Vault"
    subprocess.run([str(REPO / "scripts" / "dev-vault.sh"), str(root)], check=True)
    root = root.resolve()
    for name, runs_in, extra in (
        ("Gpt", "codex", ""),
        ("Claudia", "claude", "ask_before: [delete-files]\n"),
    ):
        folder = root / "System" / "Agents" / name
        folder.mkdir(parents=True)
        (folder / "Agent.md").write_text(
            f"---\nname: {name}\nrole: Test member\nreports_to: Bron\nruns_in: {runs_in}\n{extra}---\nYou are {name}, a careful test agent. Keep answers short.\n",
            encoding="utf-8",
        )
    agent = root / "System" / "Agents" / "Bron" / "Agent.md"
    agent.write_text(agent.read_text(encoding="utf-8").replace("can_assign_to: []", "can_assign_to: [Gpt, Claudia]"), encoding="utf-8")
    bron(root, "sync")
    return root


def ticket(vault: Path, ticket_id: str):
    return load_ticket(find_ticket(Vault(vault), ticket_id))


def new(vault: Path, to: str, request: str) -> str:
    out = bron(vault, "ticket", "new", "--to", to, "--from", "bron", "--title", f"Test for {to}", "--request", request)
    return out.split()[1].rstrip(":")


def test_claude_hands_a_ticket_to_an_agent_pinned_to_codex(vault):
    tid = new(vault, "Gpt", "What is 17 + 25? Record only the number as the ticket result.")
    bron(vault, "run", tid, "--caller-cli", "claude")
    t = ticket(vault, tid)
    assert t.status == "in-review" and "42" in t.result
    assert "started in Codex" in "\n".join(t.thread)


def test_codex_hands_a_ticket_to_an_agent_pinned_to_claude(vault):
    tid = new(vault, "Claudia", "What is 6 times 7? Record only the number as the ticket result.")
    bron(vault, "run", tid, "--caller-cli", "codex")
    t = ticket(vault, tid)
    assert t.status == "in-review" and "42" in t.result
    assert "started in Claude Code" in "\n".join(t.thread)


def test_question_then_resume_in_the_same_conversation(vault):
    tid = new(vault, "Claudia", "Before doing anything, ask me (mark the ticket blocked with your question) which number to double. After I answer, record the doubled number as the result.")
    bron(vault, "run", tid)
    assert ticket(vault, tid).status == "blocked"
    bron(vault, "ticket", "say", tid, "Double 21.", "--as", "bron")
    bron(vault, "run", tid, "--resume")
    t = ticket(vault, tid)
    assert t.status == "in-review" and "42" in t.result


def test_an_ask_before_action_becomes_needs_your_ok(vault):
    keep = vault / "Projects" / "keep.txt"
    keep.write_text("keep\n", encoding="utf-8")
    tid = new(vault, "Claudia", "Run this exact shell command: rm Projects/keep.txt  Then record what happened as the result.")
    bron(vault, "run", tid)
    t = ticket(vault, tid)
    assert keep.exists()
    assert t.status == "blocked" and "Needs your OK" in "\n".join(t.thread)


def test_connector_scan_registers_existing_connectors(vault):
    out = bron(vault, "connections", "scan")
    assert "Connectors found:" in out
    files = list((vault / "System" / "Connections").glob("*.md"))
    assert files, "no connector files were written"
    assert all("type: native" in f.read_text(encoding="utf-8") for f in files)
```

- [ ] **Step 2: Run the unit tests and the live tests**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all unit tests PASS, and the live tests are SKIPPED.

Run: `BRON_LIVE=1 uv run --project core/Engine pytest tests/live/test_handoff.py -q`
Expected: 5 PASSED.

- [ ] **Step 3: Commit**

```bash
git add tests/live/test_handoff.py
git commit -m "test(live): ticket handoffs across Claude Code and Codex" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Done when

- `uv run --project core/Engine pytest tests -q` passes.
- `BRON_LIVE=1 uv run --project core/Engine pytest tests/live -q` passes: the Plan 1 parity tests plus the 5 handoff tests.
- In the user's test vault, after "Bron, update yourself":
  - Saying "set up a test agent CFO that only runs in Codex" isn't possible yet; that's Plan 3. For now the user adds the CFO folder from a provided snippet.
  - "Ask the CFO to work out 17 + 25" in Claude Code produces a ticket that the CFO finishes in Codex. Bron reports it back on the next message, and the ticket shows up on `Tickets/Board.base`.
  - "Bron, check my connections" lists the user's claude.ai and Codex connectors and writes their files.

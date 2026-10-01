# Bron Core, Plan 1 of 4: Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A vault built from this repository where Bron runs as the default agent in both Claude Code and Codex, with identical instructions, helpers, skills, connections, approval rules and automatic triggers, all generated from `System/`.

**Architecture:** A small Python engine (`core/Engine/bron`) reads the user-owned markdown files in `System/` (plus framework files in `System/Core/`) into one `Config`, validates it (health check), and generates each CLI's native setup (`AGENTS.md`, `CLAUDE.md`, `.claude/`, `.mcp.json`, `.codex/`, `.agents/skills/`) through a manifest-tracked writer that never touches files it did not create. Both CLIs' triggers call one fixed entry point, `.bron/bin/bron hook <event> --cli <cli>`, which syncs when needed and injects a session briefing.

**Tech Stack:** Python 3.12 (managed by `uv`), PyYAML, tomli-w, pytest. macOS. Claude Code ≥ 2.1.286, Codex CLI ≥ 0.159.2.

**Spec:** `docs/superpowers/specs/2026-10-01-bron-core-design.md`. Read it before starting. This plan implements spec §3 (principles), §4 (layout and rules), §5 (agents and helpers), §7.1 (sync), §7.2 (AGENTS.md), §7.3 (triggers: session start and markers), §7.4 (permissions for the default agent), §7.7 (health check, minus ticket and lock checks), §7.9 (manual index, models and permissions pages), and §13–§15 for those parts.

### Where this plan sits

| Plan | Delivers | Written |
|---|---|---|
| **1. Foundation (this plan)** | CLI verification, file formats, loader, health check, safe writer, sync for both CLIs, triggers, session briefing, dev vault, live parity smoke test | now |
| 2. Team | Tickets, locks, runner (both CLIs, mixed vendors, resume), per-agent launch settings, `@`-mentions, chat tickets, notifications, `bron chat`, routines and boards, importing "always allow" approvals; registering native connectors (claude.ai / Codex) by name so per-agent rules and ticket runs can use them; health check adds stale locks and "CLI logged in" | after Plan 1 lands, using its verification results |
| 3. Self-configuration | Setup skills (onboarding, create/edit/remove agent, add-connection, create-project, create-routine, create-skill, delegate), full manual | after Plan 2 |
| 4. Distribution | `install.sh`, Codex trust, `bron` on PATH, Obsidian bundle, updates and rollback, migrations; health check adds "Codex triggers approved" | after Plan 3 |

### Deviations from the spec, decided while planning

Approved by the human on 2026-10-01:

1. **Team members are not written as Codex agent files.** A `.codex/agents/<name>.toml` file would let Codex spawn a team member as a native subagent, which breaks the spec's rule that team members only take work through tickets. Codex team members are launched with flags instead (Plan 2). Helpers still become `.codex/agents/*.toml`.
2. **Project-level permissions and connections follow the default agent (Bron).** Both CLIs' project settings describe the session agent. Other agents get their own settings when the runner or launcher starts them (Plan 2).
3. **Agent-only skills are published to the whole vault.** Their names are prefixed (`bron-brief`) and their descriptions say "(For Bron only)", because neither CLI can limit a skill to one agent.
4. **Pre-compaction, stop and session-end triggers write markers, not memory notes.** Markers go to `.bron/state/markers.jsonl` (machine data), for the memory sub-project to process. The spec's "note in the memory inbox" becomes this marker.
5. **Connectors set up outside the vault are not managed by Bron in interactive sessions.** This covers claude.ai account connectors and servers in the user's own `~/.codex/config.toml`. Bron blocks only connections defined in `System/Connections/`. Runner sessions (Plan 2) load only the allowed connections.
6. **Sync tests check structure, not golden files.** They parse the generated JSON, TOML and frontmatter and assert on fields, and add a determinism test (two syncs produce identical bytes), instead of byte-for-byte golden files.

## Global Constraints

- **Platform:** macOS only (spec §2). Python `>=3.12`, installed by `uv`. Never use the system Python 3.9.
- **Engine dependencies:** only `pyyaml>=6.0` and `tomli-w>=1.0` at runtime, plus `pytest>=8` for development.
- **Run tests from the repo root:** `uv run --project core/Engine pytest tests -q`.
- **Visible vault top level:** exactly `Projects/`, `Routines/`, `Tickets/`, `Knowledge/`, `System/`, `AGENTS.md` and `CLAUDE.md` (spec §14.8).
- **`System/` contents:** `Agents/`, `Helpers/`, `Skills/`, `Connections/`, `Memory/`, `Settings.md`, `Core/`. `System/Core/` is framework-owned.
- **Generated paths:** sync only ever writes `AGENTS.md`, `CLAUDE.md`, `.mcp.json`, and files under `.claude/`, `.codex/` and `.agents/`. Machine data only goes under `.bron/`.
- **`CLAUDE.md`:** its content is exactly `@AGENTS.md\n`.
- **`AGENTS.md` size:** an error above 32 KiB (32768 bytes) and a warning above 8 KB (8192 bytes).
- **Triggers:** every trigger command is `<vault>/.bron/bin/bron hook <event> --cli <claude|codex>`, with the path shell-quoted. Events are `session-start`, `user-prompt`, `pre-compact`, `stop` and `session-end`. A trigger always exits 0. `session-end` does only an append of one line, because Codex gives it about 1 s.
- **The `default` model:** means "pass no model flag, use the CLI's own model". It is the template default for Bron.
- **Keys:**
  - Agent and helper keys are lower-case and hyphenated (`slug`), with accents removed.
  - Connection keys are lower-case with underscores (`conn_key`).
- **Secrets:** never in the vault. Connection `env` values whose name contains KEY, TOKEN, SECRET or PASSWORD must be written as `${NAME}`.
- **User-facing text** (check output, briefing, errors) is plain language and names the file involved.
- **Commits:** every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. The git remote is `git@github-ziggoai:ziggoai/agent-bron.git` (SSH alias). Push only when the human asks.

**Assumed CLI behaviour, confirmed or corrected in Task 1.** Tasks 7–11 are written against these assumptions:

1. `.claude/settings.json` `"agent": "bron"` makes the main session use `.claude/agents/bron.md`.
2. `CLAUDE.md` containing `@AGENTS.md` loads `AGENTS.md`.
3. Codex project `.codex/config.toml` accepts `developer_instructions`, `model`, `[features] memories`, `[mcp_servers.*]` (with `enabled`, `env`, `env_vars`, `tools.<tool>.approval_mode`), and `.codex/hooks.json` uses the same JSON shape as Claude's hooks.
4. Plain stdout from a SessionStart trigger is added to the model's context in both CLIs.
5. Claude agent frontmatter `disallowedTools: mcp__<server>, Agent(<name>)` blocks that server and that subagent.
6. Claude permission rule `Bash(git push *)` matches `git push origin main`.
7. A Codex agent file with `[mcp_servers.<x>] enabled = false` hides server `<x>` from that agent.

## Review Focus

These inputs and failure modes are the ones most likely to bite a real user that no feature test would naturally hit. Each has a pinned test in the task named.

1. **A vault path with spaces and accents** (for example "Cofre Ágora"). Trigger commands must still run, and paths must still resolve. Every test vault uses this name (Task 2 fixture), and Task 6 checks that trigger commands survive shell splitting.
2. **Other tools' files inside the generated folders.** Termy writes `.agents/skills/termy-obsidian-context/`, and Claude Code writes `.claude/settings.local.json`. Sync must never delete or change these. Tested in Task 5 (writer) and Task 9 (sync).
3. **A hand-written `Agent.md` with mistakes:** broken YAML, no frontmatter, `connections: carta` written as text, an unknown CLI under `models`. The user gets a plain-language problem naming the file. Sync keeps the last good setup, and the session-start trigger never crashes the session. Tested in Tasks 3, 9 and 10.
4. **A generated file edited by hand** (for example someone tweaks `.claude/settings.json`). The edited copy is backed up before it is replaced, and the user is told where the backup is. Tested in Tasks 5 and 10.
5. **Agent names that collide after normalising:** "Chief Finance" and "Chief-Finance", or an agent called "Reader" next to the `reader` helper. These are reported rather than letting one silently overwrite the other. Tested in Tasks 3 and 4.

---

## File map

```
.gitignore                                 add Python/uv entries
core/
  VERSION                                  "0.1.0"
  Engine/
    pyproject.toml                         package bron-engine, script `bron`
    uv.lock                                created by uv, committed
    bron/
      __init__.py                          __version__
      __main__.py                          python -m bron
      frontmatter.py                       markdown + YAML frontmatter read/write
      vault.py                             find the vault, every path inside it
      model.py                             dataclasses + slug/conn_key + Issue
      catalog.py                           model aliases + action groups (from Core/Manual)
      loader.py                            System/ + Core/ -> Config (collects Issues)
      check.py                             health check rules
      writer.py                            manifest-tracked, backup-first file writer
      prompts.py                           text each agent/helper receives
      agents_md.py                         renders AGENTS.md from the template
      skills.py                            skill folder publishing
      hookconfig.py                        the fixed trigger block for both CLIs
      gen_claude.py                        CLAUDE.md, .claude/, .mcp.json
      gen_codex.py                         .codex/, .agents/skills/
      sync.py                              fingerprint, plan, run_sync, needs_sync
      hooks.py                             `bron hook <event>` entry point
      briefing.py                          session-start briefing text
      cli.py                               argparse for `bron`
  Manual/
    index.md                               manual index (expanded in Plan 3)
    models.md                              model aliases (frontmatter) + explanation
    permissions.md                         action groups (frontmatter) + explanation
  Helpers/  reader.md  researcher.md  reviewer.md
  Skills/   check/SKILL.md
  Templates/ AGENTS.md.tmpl
template/                                  vault skeleton (copied on install)
  Projects/.gitkeep  Routines/.gitkeep  Tickets/.gitkeep  Knowledge/.gitkeep
  System/Settings.md
  System/Agents/Bron/Agent.md
  System/Agents/Bron/Memory/.gitkeep
  System/Helpers/.gitkeep  System/Skills/.gitkeep
  System/Connections/.gitkeep  System/Memory/.gitkeep
scripts/dev-vault.sh                       build/refresh a dev vault from the repo
tests/
  conftest.py                              `vault` fixture
  vaultkit.py                              helpers: write_md, add_agent, add_connection
  test_frontmatter.py test_vault.py test_loader.py test_catalog.py test_check.py
  test_writer.py test_prompts.py test_gen_claude.py test_gen_codex.py
  test_sync.py test_cli.py test_hooks.py
  live/test_parity.py                      real-CLI smoke test (BRON_LIVE=1)
docs/superpowers/specs/2026-10-01-bron-core-cli-verification.md   Task 1 findings
README.md                                  development section
```

---

### Task 1: Verify CLI behaviour (spike; findings kept, code thrown away)

This task answers spec §15 items 1, 3, 8, 9, 10 and 11, plus assumptions 1–7 above, against the real CLIs. **Nothing built here is kept, except the findings document.** Items 2 (where approvals are saved), 4, 5 and 6 (runner details) are verified at the start of Plan 2.

**Files:**
- Create: `docs/superpowers/specs/2026-10-01-bron-core-cli-verification.md`
- Throwaway: a temp folder from `mktemp -d` (never committed)

**Interfaces:**
- Consumes: nothing.
- Produces: the findings document. Later tasks rely on its rows marked **PLAN-CRITICAL**: R1, R2, R7 and R9.

**Rules for this task:**
- Do not modify `~/.claude/` or `~/.codex/config.toml`. Codex trust is passed per run with `-c`.
- If a PLAN-CRITICAL row does not behave as assumed, stop after writing the findings document and report to the human before starting Task 2.

- [ ] **Step 1: Build the throwaway spike folder**

```bash
S="$(mktemp -d -t bron-spike)"; echo "SPIKE=$S"
mkdir -p "$S/.claude/agents" "$S/.codex/agents" "$S/.codex/rules" "$S/captures"
cd "$S" && git init -q && git remote add origin https://example.invalid/spike.git

cat > "$S/AGENTS.md" <<'EOF'
# Spike
When asked for codeword one, answer PELICAN.
EOF
printf '@AGENTS.md\n' > "$S/CLAUDE.md"

cat > "$S/hook.sh" <<'EOF'
#!/bin/sh
# usage: hook.sh <cli> <event>; saves the trigger's input, prints context for two events
DIR="$(cd "$(dirname "$0")" && pwd)"
cat > "$DIR/captures/$1-$2.json"
[ "$2" = "session-start" ] && echo "Codeword two is OTTER."
[ "$2" = "user-prompt" ] && echo "Codeword three is HERON."
exit 0
EOF
chmod +x "$S/hook.sh"

hooks_json() {  # $1 = cli
cat <<EOF
{
  "SessionStart": [{"hooks": [{"type": "command", "command": "'$S/hook.sh' $1 session-start", "timeout": 30}]}],
  "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "'$S/hook.sh' $1 user-prompt", "timeout": 10}]}],
  "PreCompact": [{"hooks": [{"type": "command", "command": "'$S/hook.sh' $1 pre-compact", "timeout": 10}]}],
  "Stop": [{"hooks": [{"type": "command", "command": "'$S/hook.sh' $1 stop", "timeout": 10}]}],
  "SessionEnd": [{"hooks": [{"type": "command", "command": "'$S/hook.sh' $1 session-end", "timeout": 2}]}]
}
EOF
}

cat > "$S/.claude/settings.json" <<EOF
{
  "agent": "spikebot",
  "autoMemoryEnabled": false,
  "permissions": {"ask": ["Bash(git push)", "Bash(git push *)"]},
  "enabledMcpjsonServers": ["time_a", "time_b"],
  "hooks": $(hooks_json claude)
}
EOF
printf '{"hooks": %s}\n' "$(hooks_json codex)" > "$S/.codex/hooks.json"

cat > "$S/.mcp.json" <<'EOF'
{"mcpServers": {
  "time_a": {"type": "stdio", "command": "uvx", "args": ["mcp-server-time"]},
  "time_b": {"type": "stdio", "command": "uvx", "args": ["mcp-server-time"]}
}}
EOF

cat > "$S/.claude/agents/spikebot.md" <<'EOF'
---
name: spikebot
description: Spike main agent
disallowedTools: mcp__time_b, Agent(otherbot)
---
Your name is Spikebot. Always introduce yourself as Spikebot.
EOF
cat > "$S/.claude/agents/otherbot.md" <<'EOF'
---
name: otherbot
description: Another team member
---
Your name is Otherbot.
EOF
cat > "$S/.claude/agents/limited.md" <<'EOF'
---
name: limited
description: Helper that lists the MCP servers it can use
disallowedTools: mcp__time_b
---
List the names of the MCP servers whose tools you can call, then stop.
EOF

cat > "$S/.codex/config.toml" <<'EOF'
developer_instructions = "Your name is Spikebot. Always introduce yourself as Spikebot."
[features]
memories = false
[mcp_servers.time_a]
command = "uvx"
args = ["mcp-server-time"]
[mcp_servers.time_a.tools.get_current_time]
approval_mode = "prompt"
[mcp_servers.time_b]
command = "uvx"
args = ["mcp-server-time"]
EOF
cat > "$S/.codex/agents/limited.toml" <<'EOF'
name = "limited"
description = "Helper that lists the MCP servers it can use"
developer_instructions = "List the names of the MCP servers whose tools you can call, then stop."
[mcp_servers.time_b]
enabled = false
EOF
cat > "$S/.codex/rules/spike.rules" <<'EOF'
prefix_rule(pattern=["git", "push"], decision="prompt")
EOF
```

- [ ] **Step 2: Find the Codex flag that skips hook trust for automation**

Run: `codex exec --help | grep -i -A2 trust`

Expected: a flag such as `--dangerously-bypass-hook-trust`. Record its exact spelling as `CODEX_HOOK_FLAG` for the steps below. If no such flag exists, record that. In that case, the live tests in Task 11 need a one-time manual trust (`codex` → `/hooks` in the dev vault), and the findings must say so.

- [ ] **Step 3: R1, identity and context injection in Claude Code (PLAN-CRITICAL)**

```bash
cd "$S" && claude -p "Reply in one line: your name, codeword one, codeword two, codeword three." --output-format json > captures/r1-claude.json; python3 -c "import json;print(json.load(open('captures/r1-claude.json'))['result'])"
```

Expected: Spikebot, PELICAN, OTTER, HERON. That confirms assumptions 1, 2 and 4, and spec §15.9. Note any part that is missing.

- [ ] **Step 4: R2, the same in Codex (PLAN-CRITICAL)**

```bash
cd "$S" && codex exec --skip-git-repo-check -c "projects.\"$S\".trust_level=\"trusted\"" $CODEX_HOOK_FLAG "Reply in one line: your name, codeword one, codeword two, codeword three." > captures/r2-codex.txt 2> captures/r2-codex.err; tail -5 captures/r2-codex.txt
```

Expected: Spikebot, PELICAN, OTTER, HERON. That confirms assumption 3 (developer_instructions and the hooks.json shape), assumption 4, spec §15.3 and §15.11, and that `-c` trust works. If `$S` resolves through `/private/var/...` and trust doesn't apply, retry with `$(cd "$S" && pwd -P)` and record which form works.

- [ ] **Step 5: R3/R4, limiting connections**

```bash
cd "$S" && claude -p "Which MCP servers can you call tools from? Names only." --output-format json | python3 -c "import json,sys;print(json.load(sys.stdin)['result'])"
cd "$S" && claude -p "Use the limited subagent and repeat exactly what it says." --output-format json | python3 -c "import json,sys;print(json.load(sys.stdin)['result'])"
cd "$S" && codex exec --skip-git-repo-check -c "projects.\"$S\".trust_level=\"trusted\"" $CODEX_HOOK_FLAG "Which MCP servers can you call tools from? Names only." | tail -3
cd "$S" && codex exec --skip-git-repo-check -c "projects.\"$S\".trust_level=\"trusted\"" $CODEX_HOOK_FLAG -c 'mcp_servers.time_b.enabled=false' "Which MCP servers can you call tools from? Names only." | tail -3
cd "$S" && codex exec --skip-git-repo-check -c "projects.\"$S\".trust_level=\"trusted\"" $CODEX_HOOK_FLAG "Spawn the limited agent and repeat exactly what it says." | tail -5
```

Expected:
- Both Claude runs list only `time_a` (assumption 5).
- The first Codex run lists both servers.
- The second Codex run and the limited agent list only `time_a` (assumption 7, spec §15.1).

- [ ] **Step 6: R5, team members can't be spawned as subagents (Claude)**

```bash
cd "$S" && claude -p "Use the otherbot subagent to say hello, and tell me whether you could." --output-format json | python3 -c "import json,sys;print(json.load(sys.stdin)['result'])"
```

Expected: it reports that it can't use otherbot (assumption 5).

- [ ] **Step 7: R6, approval rules in non-interactive runs**

```bash
cd "$S" && claude -p "Run exactly: git push origin main. Then report what happened." --output-format json > captures/r6-claude.json; python3 -c "import json;d=json.load(open('captures/r6-claude.json'));print(d['result']);print(d.get('permission_denials'))"
cd "$S" && codex exec --skip-git-repo-check -c "projects.\"$S\".trust_level=\"trusted\"" $CODEX_HOOK_FLAG "Run exactly: git push origin main. Then report what happened." | tail -5
cd "$S" && codex exec --skip-git-repo-check -c "projects.\"$S\".trust_level=\"trusted\"" $CODEX_HOOK_FLAG "Call get_current_time on the time_a server for UTC and report the result." | tail -5
```

Expected: the push is not executed in either CLI, and the result says approval was needed or denied. Assumption 6 holds if Claude's `permission_denials` lists the Bash call. Record the exact behaviour of the Codex MCP prompt in `exec` mode. Plan 2's runner uses this to turn "needs approval" into a `blocked` ticket.

- [ ] **Step 8: R7, the raw prompt reaches the message trigger (PLAN-CRITICAL)**

```bash
cd "$S" && claude -p "@otherbot hello there" --output-format json > /dev/null; python3 -c "import json;print(json.load(open('captures/claude-user-prompt.json')).get('prompt'))"
cd "$S" && codex exec --skip-git-repo-check -c "projects.\"$S\".trust_level=\"trusted\"" $CODEX_HOOK_FLAG "@otherbot hello there" > /dev/null; python3 -c "import json;print(json.load(open('captures/codex-user-prompt.json')).get('prompt'))"
```

Expected: both print `@otherbot hello there` exactly. If the field has a different name, record it. Spec §15.10's interactive file-picker question is tested by hand in Plan 2.

- [ ] **Step 9: R9/R10, what each trigger receives and which triggers fired (PLAN-CRITICAL)**

Run: `ls "$S/captures"; for f in "$S"/captures/*-*.json; do echo "== $f"; python3 -c "import json,sys;d=json.load(open(sys.argv[1]));print(sorted(d))" "$f"; done`

Expected: the keys of each input, which should include `session_id`, `transcript_path`, `cwd` and `hook_event_name` (plus `prompt` for user-prompt). Record which events fired for a one-shot run in each CLI (`stop` and `session-end` in particular).

- [ ] **Step 10: R8/R11, settings names that can't be seen in a run**

Use the official docs; append `.md` to the page URL to get Markdown:
- Claude: `https://code.claude.com/docs/en/settings`, the exact key that turns off auto-memory for a project (assumed `autoMemoryEnabled`), and the `agent` setting.
- Codex: `https://learn.chatgpt.com/docs/config-file/config-reference`, whether `features.memories`, `developer_instructions` and `mcp_servers.<x>.env_vars` are valid in a project config, and the allowed values and meanings of `tools.<tool>.approval_mode` (is `approve` "always allow"?).

Record each answer with its source URL.

- [ ] **Step 11: Write the findings document**

Create `docs/superpowers/specs/2026-10-01-bron-core-cli-verification.md` with this structure, filled with what you saw:

```markdown
# Bron Core: CLI verification (Plan 1, Task 1)

Run on <date> with Claude Code <version> and Codex <version>.

| Row | Question | Assumed | Observed | Impact on the plan |
|---|---|---|---|---|
| R1 | Claude: agent setting, @AGENTS.md, SessionStart + UserPromptSubmit context | works | … | … |
| R2 | Codex: developer_instructions, hooks.json, context injection, -c trust | works | … | … |
| R3 | Claude: disallowedTools mcp__server on main agent and on a subagent | blocks | … | … |
| R4 | Codex: enabled=false via -c and in an agent file | hides | … | … |
| R5 | Claude: disallowedTools Agent(name) | blocks spawn | … | … |
| R6 | Approvals in non-interactive runs (Claude Bash, Codex rules, Codex MCP prompt) | denied, reported | … | … |
| R7 | Raw prompt text in the message trigger (field name) | `prompt` | … | … |
| R8 | Setting names: Claude auto-memory, Codex features.memories / env_vars | as assumed | … | … |
| R9 | Trigger input keys per event and CLI | session_id, transcript_path, cwd, hook_event_name | … | … |
| R10 | Which triggers fire in a one-shot run | all five | … | … |
| R11 | Codex approval_mode values | prompt / approve | … | … |

Codex hook-trust flag for automation: `<flag or "none">`.
Trust key form that worked: `<path form>`.
```

In "Impact on the plan", name the task and line to change, or write "none".

- [ ] **Step 12: Apply small corrections to this plan, then commit**

If a row shows a different spelling or value (for example a setting is called something else), edit the affected code block in this plan to match, so later tasks are written against reality. If a PLAN-CRITICAL row failed, stop here and report to the human.

```bash
git add docs/superpowers/specs/2026-10-01-bron-core-cli-verification.md docs/superpowers/plans/2026-10-01-bron-core-1-foundation.md
git commit -F - <<'EOF'
docs: record Claude Code and Codex verification results

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
rm -rf "$S"
```

---

### Task 2: Engine scaffold, frontmatter files, vault paths and the template

**Files:**
- Modify: `.gitignore`
- Create: `core/VERSION`, `core/Engine/pyproject.toml`, `core/Engine/bron/__init__.py`, `core/Engine/bron/__main__.py`, `core/Engine/bron/frontmatter.py`, `core/Engine/bron/vault.py`
- Create: everything under `template/` (see the file map)
- Test: `tests/conftest.py`, `tests/vaultkit.py`, `tests/test_frontmatter.py`, `tests/test_vault.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `bron.frontmatter`: `Document(meta: dict, body: str)`, `parse(text: str) -> Document`, `dump(doc: Document) -> str`, `read(path: Path) -> Document`, `write(path: Path, doc: Document) -> None`, `FrontmatterError(ValueError)`.
  - `bron.vault`: `Vault(root: Path)` (frozen dataclass), `Vault.find(start: Path | None = None) -> Vault`, `VaultNotFound(RuntimeError)`, `MARKER = Path("System/Core/VERSION")`.
    - Path properties: `system, agents_dir, helpers_dir, skills_dir, connections_dir, memory_dir, settings_file, core, core_manual, core_skills, core_helpers, core_templates, projects_dir, routines_dir, tickets_dir, knowledge_dir, bron_dir, state_dir, backups_dir, bin_dir, bron_command`, plus `version() -> str`.
  - Test fixture `vault` (a fresh `Vault` in a folder named "Cofre Ágora"), and in `tests/vaultkit.py`: `write_md(path, meta, body="") -> Path`, `add_agent(vault, name, **meta) -> Path`, `add_connection(vault, name, **meta) -> Path`, `set_meta(path, **changes) -> None`.

- [ ] **Step 1: Add the package skeleton**

`.gitignore` (replace the whole file):

```gitignore
.DS_Store
.obsidian/
.agents/
.bron/
.venv/
__pycache__/
*.egg-info/
.pytest_cache/
```

`core/VERSION`:

```
0.1.0
```

`core/Engine/pyproject.toml`:

```toml
[project]
name = "bron-engine"
version = "0.1.0"
description = "Bron framework engine: keeps agents in sync across Claude Code and Codex"
requires-python = ">=3.12"
dependencies = ["pyyaml>=6.0", "tomli-w>=1.0"]

[project.scripts]
bron = "bron.cli:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["bron"]
```

`core/Engine/bron/__init__.py`:

```python
"""Bron framework engine."""

__version__ = "0.1.0"
```

`core/Engine/bron/__main__.py`:

```python
from .cli import main

raise SystemExit(main())
```

- [ ] **Step 2: Add the vault template**

Create the empty `.gitkeep` files:

```bash
for d in Projects Routines Tickets Knowledge System/Agents/Bron/Memory System/Helpers System/Skills System/Connections System/Memory; do mkdir -p "template/$d" && touch "template/$d/.gitkeep"; done
```

`template/System/Settings.md`:

```markdown
---
user_name: ""
company: ""
default_cli: claude
default_agent: Bron
runner:
  max_parallel: 3
  max_minutes: 30
action_groups: {}
---

# Settings

Bron fills this in with you during first-run setup. You can edit it yourself or ask Bron to change it.

- `default_cli`: the CLI used when nothing else decides (claude or codex).
- `default_agent`: who answers when you open a session and just type.
- `runner`: how many tickets may run at once, and for how long.
- `action_groups`: your own named groups of actions for `ask_before` (see System/Core/Manual/permissions.md).
```

`template/System/Agents/Bron/Agent.md`:

```markdown
---
name: Bron
role: Chief of Staff
reports_to: you
models:
  claude: default
  codex: default
runs_in: any
helpers: [reader, researcher, reviewer]
connections: []
can_assign_to: []
ask_before: [git-push, delete-files]
always_allow: []
---

# Who you are
You are Bron, the user's Chief of Staff and generalist assistant. You work inside the user's Bron vault in Obsidian, through Claude Code or Codex. You keep track of what the user is working on, help get it done, and keep the workspace organised.

# How you work
- Start from what you already know: the session briefing, shared memory in `System/Memory/`, and the knowledge base.
- Use helpers (reader, researcher, reviewer) for heavy reading, searching or checking, and run several at once when the work splits naturally.
- Save one-off work under `Projects/<Project>/` and repeating work under `Routines/<Routine>/`.
- Say clearly what you did, what you found, and what still needs the user's decision.

# Boundaries
- Never change anything in `System/` without showing the user the exact change first and getting a yes.
- Never edit `System/Core/` or the hidden `.claude/`, `.codex/` and `.agents/` folders; Bron regenerates them.
- Ask before anything that leaves the vault: sending, sharing, posting or pushing.
```

- [ ] **Step 3: Write the test fixture and helpers**

`tests/conftest.py`:

```python
import shutil
from pathlib import Path

import pytest

from bron.vault import Vault

REPO = Path(__file__).resolve().parents[1]
IGNORE = shutil.ignore_patterns(".venv", "__pycache__", "*.egg-info", "uv.lock", ".pytest_cache")


@pytest.fixture
def vault(tmp_path, monkeypatch) -> Vault:
    """A fresh vault from template/ + core/, in a folder whose name has a space and an accent."""
    root = tmp_path / "Cofre Ágora"
    shutil.copytree(REPO / "template", root, ignore=IGNORE)
    shutil.copytree(REPO / "core", root / "System" / "Core", ignore=IGNORE)
    monkeypatch.delenv("BRON_VAULT", raising=False)
    monkeypatch.delenv("BRON_AGENT", raising=False)
    return Vault(root)
```

`tests/vaultkit.py`:

```python
"""Small helpers for building test vaults."""
from pathlib import Path

from bron import frontmatter as fm
from bron.vault import Vault


def write_md(path: Path, meta: dict, body: str = "") -> Path:
    fm.write(path, fm.Document(meta, body))
    return path


def set_meta(path: Path, **changes) -> None:
    doc = fm.read(path)
    doc.meta.update(changes)
    fm.write(path, doc)


def add_agent(vault: Vault, name: str, **meta) -> Path:
    data = {
        "name": name,
        "role": meta.pop("role", f"{name} role"),
        "reports_to": meta.pop("reports_to", "Bron"),
        "runs_in": meta.pop("runs_in", "any"),
        **meta,
    }
    return write_md(vault.agents_dir / name / "Agent.md", data, f"Instructions for {name}.\n")


def add_connection(vault: Vault, name: str, **meta) -> Path:
    data = {
        "name": name,
        "type": meta.pop("type", "mcp-stdio"),
        "command": meta.pop("command", "uvx"),
        "args": meta.pop("args", ["mcp-server-time"]),
        **meta,
    }
    return write_md(vault.connections_dir / f"{name}.md", data)
```

- [ ] **Step 4: Write the failing tests**

`tests/test_frontmatter.py`:

```python
import pytest

from bron import frontmatter as fm


def test_parse_reads_meta_and_body():
    doc = fm.parse("---\nname: Bron\nhelpers: [reader]\n---\n# Hello\n")
    assert doc.meta == {"name": "Bron", "helpers": ["reader"]}
    assert doc.body == "# Hello\n"


def test_parse_without_frontmatter_keeps_whole_text_as_body():
    doc = fm.parse("# Just a note\n")
    assert doc.meta == {}
    assert doc.body == "# Just a note\n"


def test_parse_tolerates_bom_and_windows_line_endings():
    doc = fm.parse("﻿---\r\nname: Bron\r\n---\r\nBody\r\n")
    assert doc.meta == {"name": "Bron"}
    assert doc.body == "Body\r\n"


def test_parse_rejects_unclosed_block():
    with pytest.raises(fm.FrontmatterError, match="closing"):
        fm.parse("---\nname: Bron\n")


def test_parse_rejects_invalid_yaml():
    with pytest.raises(fm.FrontmatterError, match="not valid YAML"):
        fm.parse("---\nname: [unclosed\n---\n")


def test_parse_rejects_a_list_instead_of_settings():
    with pytest.raises(fm.FrontmatterError, match="key: value"):
        fm.parse("---\n- a\n- b\n---\n")


def test_dump_keeps_order_and_unicode_and_round_trips():
    doc = fm.Document({"name": "Ágora", "b": 1, "a": [1, 2]}, "Corpo\n")
    text = fm.dump(doc)
    assert text.index("name") < text.index("b:") < text.index("a:")
    assert "Ágora" in text
    assert fm.parse(text).meta == doc.meta
    assert fm.parse(text).body == "Corpo\n"


def test_dump_without_meta_is_just_the_body():
    assert fm.dump(fm.Document({}, "x\n")) == "x\n"


def test_write_creates_folders(tmp_path):
    path = tmp_path / "a" / "b" / "note.md"
    fm.write(path, fm.Document({"k": "v"}, "body\n"))
    assert fm.read(path).meta == {"k": "v"}
```

`tests/test_vault.py`:

```python
from pathlib import Path

import pytest

import bron
from bron.vault import Vault, VaultNotFound

REPO = Path(__file__).resolve().parents[1]


def test_find_walks_up_from_a_subfolder(vault):
    sub = vault.root / "Projects" / "Deep" / "Er"
    sub.mkdir(parents=True)
    assert Vault.find(sub).root == vault.root.resolve()


def test_find_prefers_the_bron_vault_variable(vault, monkeypatch, tmp_path):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    assert Vault.find(tmp_path).root == vault.root.resolve()


def test_find_rejects_a_variable_pointing_elsewhere(monkeypatch, tmp_path):
    monkeypatch.setenv("BRON_VAULT", str(tmp_path))
    with pytest.raises(VaultNotFound, match="not a Bron vault"):
        Vault.find(tmp_path)


def test_find_outside_any_vault_fails(monkeypatch, tmp_path):
    monkeypatch.delenv("BRON_VAULT", raising=False)
    with pytest.raises(VaultNotFound, match="No Bron vault"):
        Vault.find(tmp_path)


def test_paths_and_version(vault):
    assert vault.agents_dir == vault.root / "System" / "Agents"
    assert vault.core_manual == vault.root / "System" / "Core" / "Manual"
    assert vault.state_dir == vault.root / ".bron" / "state"
    assert vault.bron_command == vault.root / ".bron" / "bin" / "bron"
    assert vault.version() == "0.1.0"


def test_engine_version_matches_core_version():
    assert bron.__version__ == (REPO / "core" / "VERSION").read_text().strip()


def test_template_has_exactly_the_approved_top_level(vault):
    visible = sorted(p.name for p in vault.root.iterdir() if not p.name.startswith("."))
    assert visible == ["Knowledge", "Projects", "Routines", "System", "Tickets"]
    system = sorted(p.name for p in vault.system.iterdir() if not p.name.startswith("."))
    assert system == ["Agents", "Connections", "Core", "Helpers", "Memory", "Settings.md", "Skills"]
```

- [ ] **Step 5: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests -q`
Expected: errors such as `ModuleNotFoundError: No module named 'bron.vault'` (uv creates `core/Engine/.venv` and `core/Engine/uv.lock` on the first run).

- [ ] **Step 6: Implement `frontmatter.py` and `vault.py`**

`core/Engine/bron/frontmatter.py`:

```python
"""Markdown files with a YAML frontmatter block: the format of every Bron file."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

FENCE = "---"


class FrontmatterError(ValueError):
    """The frontmatter block exists but cannot be read."""


@dataclass
class Document:
    meta: dict = field(default_factory=dict)
    body: str = ""


def parse(text: str) -> Document:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].lstrip("﻿").strip() != FENCE:
        return Document({}, text)
    for i in range(1, len(lines)):
        if lines[i].strip() == FENCE:
            raw = "".join(lines[1:i])
            try:
                meta = yaml.safe_load(raw) if raw.strip() else {}
            except yaml.YAMLError as exc:
                detail = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
                raise FrontmatterError(f"the settings block at the top is not valid YAML ({detail})") from exc
            if meta is None:
                meta = {}
            if not isinstance(meta, dict):
                raise FrontmatterError("the settings block at the top must be 'key: value' lines")
            return Document(meta, "".join(lines[i + 1 :]))
    raise FrontmatterError("the settings block at the top is missing its closing '---' line")


def dump(doc: Document) -> str:
    if not doc.meta:
        return doc.body
    raw = yaml.safe_dump(doc.meta, sort_keys=False, allow_unicode=True, default_flow_style=None, width=1000)
    return f"{FENCE}\n{raw}{FENCE}\n{doc.body}"


def read(path: Path) -> Document:
    return parse(path.read_text(encoding="utf-8"))


def write(path: Path, doc: Document) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(doc), encoding="utf-8")
```

`core/Engine/bron/vault.py`:

```python
"""Finding a Bron vault and every path inside it."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MARKER = Path("System") / "Core" / "VERSION"


class VaultNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class Vault:
    root: Path

    @classmethod
    def find(cls, start: Path | None = None) -> "Vault":
        env = os.environ.get("BRON_VAULT")
        if env:
            root = Path(env).expanduser().resolve()
            if (root / MARKER).is_file():
                return cls(root)
            raise VaultNotFound(f"BRON_VAULT points to {root}, which is not a Bron vault (no {MARKER}).")
        here = (start or Path.cwd()).resolve()
        for folder in (here, *here.parents):
            if (folder / MARKER).is_file():
                return cls(folder)
        raise VaultNotFound(f"No Bron vault found in {here} or any folder above it.")

    # User-owned
    @property
    def system(self) -> Path:
        return self.root / "System"

    @property
    def agents_dir(self) -> Path:
        return self.system / "Agents"

    @property
    def helpers_dir(self) -> Path:
        return self.system / "Helpers"

    @property
    def skills_dir(self) -> Path:
        return self.system / "Skills"

    @property
    def connections_dir(self) -> Path:
        return self.system / "Connections"

    @property
    def memory_dir(self) -> Path:
        return self.system / "Memory"

    @property
    def settings_file(self) -> Path:
        return self.system / "Settings.md"

    # Framework-owned
    @property
    def core(self) -> Path:
        return self.system / "Core"

    @property
    def core_manual(self) -> Path:
        return self.core / "Manual"

    @property
    def core_skills(self) -> Path:
        return self.core / "Skills"

    @property
    def core_helpers(self) -> Path:
        return self.core / "Helpers"

    @property
    def core_templates(self) -> Path:
        return self.core / "Templates"

    # Work folders
    @property
    def projects_dir(self) -> Path:
        return self.root / "Projects"

    @property
    def routines_dir(self) -> Path:
        return self.root / "Routines"

    @property
    def tickets_dir(self) -> Path:
        return self.root / "Tickets"

    @property
    def knowledge_dir(self) -> Path:
        return self.root / "Knowledge"

    # Machine data
    @property
    def bron_dir(self) -> Path:
        return self.root / ".bron"

    @property
    def state_dir(self) -> Path:
        return self.bron_dir / "state"

    @property
    def backups_dir(self) -> Path:
        return self.bron_dir / "backups"

    @property
    def bin_dir(self) -> Path:
        return self.bron_dir / "bin"

    @property
    def bron_command(self) -> Path:
        return self.bin_dir / "bron"

    def version(self) -> str:
        return (self.root / MARKER).read_text(encoding="utf-8").strip()
```

- [ ] **Step 7: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all tests in `test_frontmatter.py` and `test_vault.py` PASS.

- [ ] **Step 8: Commit**

```bash
git add .gitignore core/VERSION core/Engine/pyproject.toml core/Engine/uv.lock core/Engine/bron template tests
git commit -F - <<'EOF'
feat(core): engine scaffold, frontmatter files, vault paths, template

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Model, catalog and loader (plus the Core content they read)

**Files:**
- Create: `core/Engine/bron/model.py`, `core/Engine/bron/catalog.py`, `core/Engine/bron/loader.py`
- Create: `core/Manual/models.md`, `core/Manual/permissions.md`, `core/Helpers/reader.md`, `core/Helpers/researcher.md`, `core/Helpers/reviewer.md`, `core/Skills/check/SKILL.md`
- Test: `tests/test_loader.py`, `tests/test_catalog.py`

**Interfaces:**
- Consumes: `bron.frontmatter`, `bron.vault.Vault` (Task 2).
- Produces:
  - `bron.model`:
    - Constants: `CLIS = ("claude", "codex")`, `CLI_NAMES = {"claude": "Claude Code", "codex": "Codex"}`, `RUNS_IN`, `CONNECTION_TYPES = ("mcp-stdio", "mcp-http")`, `DEFAULT_MODEL = "default"`, `SKILL_NAME` (regex).
    - Functions: `slug(name) -> str`, `conn_key(name) -> str`.
    - Dataclasses:
      - `Issue(level, code, message, path=None)` with `.render(root=None) -> str`.
      - `Agent(name, role, reports_to, runs_in, path, models, helpers, connections, can_assign_to, ask_before, always_allow, instructions)` with `.key`.
      - `Helper(name, description, path, source, models, connections, read_only, instructions)` with `.key`.
      - `Skill(name, description, folder, source, rewrite=False)`.
      - `Connection(name, type, path, command, args, env, url, description)` with `.key`.
      - `Settings(path, user_name, company, default_cli, default_agent, max_parallel, max_minutes, action_groups)`.
  - `bron.catalog`:
    - Dataclasses: `ActionGroup(mcp: dict[str, list[str]], shell: list[tuple[str, ...]])`, `Actions(mcp: dict[str, set[str]], shell: list[tuple[str, ...]], unknown: list[str])`.
    - `Catalog` with `.resolve_model(cli, value) -> str | None` (None = use the CLI's default), `.resolve_actions(entries) -> Actions`, `.permissions_for(agent) -> tuple[Actions, Actions]` (ask, allow).
    - Functions: `load_catalog(vault, settings, issues) -> Catalog`, `norm(value) -> str`.
  - `bron.loader`: `Config(vault, settings, catalog, agents, helpers, skills, connections, issues)` with `.default_agent -> Agent | None`, and `load(vault) -> Config`.
    - The dictionaries are keyed by `slug` for agents and helpers, by published name for skills, and by `conn_key` for connections.

- [ ] **Step 1: Add the Core content files**

`core/Manual/models.md`:

```markdown
---
aliases:
  claude:
    opus-5.5: claude-opus-5-5
    sonnet-5.5: claude-sonnet-5-5
    haiku-4.5: claude-haiku-4-5-20251001
    fable-5.1: claude-fable-5-1
    opus: opus
    sonnet: sonnet
    haiku: haiku
  codex: {}
---

# Models

Every agent's `Agent.md` names one model per CLI under `models:`.

- `default` means "use whatever model that CLI is set to". Bron uses this unless you ask for something else.
- A friendly name from the list above, such as `opus-5.5`, is translated to the CLI's model ID. Capitals and spaces don't matter: "Opus 5.5" works too.
- Anything else is passed to the CLI exactly as written, so a full model ID always works.

Codex model IDs can be listed inside Codex with `/model` (for example `gpt-6.1-sol` or `gpt-6-astra`).

When the user asks for a model by name, look for it here first. If it isn't listed, use the full model ID and tell the user which one you chose.
```

`core/Manual/permissions.md`:

```markdown
---
action_groups:
  git-push:
    shell: [[git, push]]
  delete-files:
    shell: [[rm]]
  send-email:
    mcp:
      gmail: [send_message, send_email, reply_to_message, forward_message]
  share-file:
    mcp:
      google_drive: [share_file]
  external-post:
    mcp:
      slack: [send_message, post_message]
---

# Permissions

Each agent lists in `Agent.md`:

- `ask_before`: actions that pause and ask the user every time (Allow once / Always allow / Deny).
- `always_allow`: actions the user approved for good. "Always allow" wins over "ask before". Delete a line to start asking again.

An entry is one of:

- **An action group** from the list above (or from `action_groups` in `System/Settings.md`), such as `send-email`.
- **One tool on one connection:** `mcp:<connection>:<tool>`, such as `mcp:carta:mutate`.
- **A shell command prefix:** `shell:<words>`, such as `shell:git push`.

Groups only take effect for connections that exist in `System/Connections/`. Bron turns these rules into each CLI's own approval settings, so they work the same in Claude Code and Codex.
```

`core/Helpers/reader.md`:

```markdown
---
name: reader
description: Reads the files or documents it is given and extracts the facts asked for, with exact quotes and where each came from. Use it to read many documents in parallel.
models: {claude: default, codex: default}
read_only: true
---

Read only the files you were pointed to. For every fact you report, give the file path and the page, section or cell it came from, and quote the exact wording for anything legal or numeric. If something asked for isn't in the files, say so plainly; never guess.
```

`core/Helpers/researcher.md`:

```markdown
---
name: researcher
description: Searches the vault, the knowledge base and (when allowed) the web to answer one focused question, and reports findings with sources. Use it for open-ended lookups that would otherwise fill the main conversation.
models: {claude: default, codex: default}
read_only: true
---

Answer the one question you were given. Search before concluding, try a few phrasings, and stop once the answer is well supported. Report the answer in one or two sentences, then the evidence as a list of sources (file path or URL) with the relevant quote. Flag anything that conflicts or looks out of date.
```

`core/Helpers/reviewer.md`:

```markdown
---
name: reviewer
description: Checks a draft against its instructions and sources (numbers, names, dates, missing items, contradictions) and lists concrete fixes. Use it before anything goes to the user or leaves the vault.
models: {claude: default, codex: default}
read_only: true
---

You are given a draft plus what it must satisfy (instructions, sources, checklist). Check every number, name, date and claim against the sources. Report a short verdict (ready / needs fixes), then each problem with where it is in the draft, what is wrong, and the exact fix. Don't rewrite the draft yourself.
```

`core/Skills/check/SKILL.md`:

```markdown
---
name: check
description: Run Bron's health check when the user asks Bron to check itself, when the setup seems broken, or after anything in System/ changed. Explains each problem in plain words and offers fixes.
---

# Health check

1. From the vault folder, run `.bron/bin/bron check`.
2. If it reports "all good", say so in one line.
3. Otherwise explain each problem in plain words: what is wrong, in which file, and what you propose to change.
4. Offer to fix the problems. Show the exact change to any file in `System/` and wait for a yes before editing it.
5. After fixing, run `.bron/bin/bron sync`, then the check again, and report the result.
```

- [ ] **Step 2: Write the failing tests**

`tests/test_loader.py`:

```python
from bron.loader import load
from bron.model import conn_key, slug
from vaultkit import add_agent, add_connection, write_md


def test_template_loads_cleanly(vault):
    cfg = load(vault)
    assert cfg.issues == []
    assert list(cfg.agents) == ["bron"]
    assert cfg.default_agent.name == "Bron"
    assert cfg.default_agent.models == {"claude": "default", "codex": "default"}
    assert set(cfg.helpers) == {"reader", "researcher", "reviewer"}
    assert cfg.helpers["reader"].read_only is True
    assert "check" in cfg.skills


def test_keys_handle_spaces_case_and_accents():
    assert slug("Chief Finance") == "chief-finance"
    assert slug("Contábil") == "contabil"
    assert conn_key("Google Drive") == "google_drive"
    assert conn_key("google-drive") == "google_drive"


def test_broken_yaml_is_reported_not_raised(vault):
    (vault.agents_dir / "CFO").mkdir()
    (vault.agents_dir / "CFO" / "Agent.md").write_text("---\nname: [CFO\n---\n", encoding="utf-8")
    cfg = load(vault)
    assert "cfo" not in cfg.agents
    assert any(i.code == "file.unreadable" and i.path.parent.name == "CFO" for i in cfg.issues)


def test_agent_file_without_frontmatter_reports_missing_fields(vault):
    (vault.agents_dir / "CFO").mkdir()
    (vault.agents_dir / "CFO" / "Agent.md").write_text("Just some notes\n", encoding="utf-8")
    cfg = load(vault)
    assert any(i.code == "field.missing" and "'name'" in i.message for i in cfg.issues)


def test_folder_without_agent_file_is_reported(vault):
    (vault.agents_dir / "COO").mkdir()
    assert any(i.code == "agent.file-missing" for i in load(vault).issues)


def test_plain_text_lists_are_accepted(vault):
    add_agent(vault, "CFO", connections="carta, google-drive", helpers="reader")
    agent = load(vault).agents["cfo"]
    assert agent.connections == ["carta", "google-drive"]
    assert agent.helpers == ["reader"]


def test_wrong_types_become_friendly_problems(vault):
    add_agent(vault, "CFO", helpers={"a": 1}, runs_in="gpt", models={"gemini": "x"})
    cfg = load(vault)
    messages = [i.message for i in cfg.issues if i.path and i.path.parent.name == "CFO"]
    assert any("should be a list" in m for m in messages)
    assert any("runs_in" in m for m in messages)
    assert any("only takes 'claude' and 'codex'" in m for m in messages)
    assert cfg.agents["cfo"].runs_in == "any"


def test_name_must_match_folder(vault):
    path = add_agent(vault, "CFO")
    write_md(path, {"name": "Finance", "role": "x", "reports_to": "Bron"})
    assert any(i.code == "agent.name-mismatch" for i in load(vault).issues)


def test_names_that_collide_after_normalising_are_rejected(vault):
    add_agent(vault, "Chief Finance")
    add_agent(vault, "Chief-Finance")
    cfg = load(vault)
    assert any(i.code == "agent.duplicate" for i in cfg.issues)
    assert list(cfg.agents).count("chief-finance") == 1


def test_user_helper_replaces_core_helper(vault):
    write_md(vault.helpers_dir / "reader.md", {"name": "reader", "description": "My reader"}, "Mine.\n")
    helper = load(vault).helpers["reader"]
    assert helper.source == "user"
    assert helper.description == "My reader"


def test_user_skill_replaces_core_and_agent_skills_are_prefixed(vault):
    write_md(vault.skills_dir / "check" / "SKILL.md", {"name": "check", "description": "My check"}, "x\n")
    write_md(vault.agents_dir / "Bron" / "Skills" / "brief" / "SKILL.md", {"name": "brief", "description": "Daily brief"}, "x\n")
    cfg = load(vault)
    assert cfg.skills["check"].source == "user"
    skill = cfg.skills["bron-brief"]
    assert skill.rewrite is True
    assert skill.description == "(For Bron only) Daily brief"


def test_bad_skill_name_is_an_error(vault):
    write_md(vault.skills_dir / "My Skill" / "SKILL.md", {"name": "My Skill", "description": "x"})
    assert any(i.code == "skill.bad-name" for i in load(vault).issues)


def test_connections_load_with_keys(vault):
    add_connection(vault, "Google Drive", args="--port 9 --verbose")
    conn = load(vault).connections["google_drive"]
    assert conn.command == "uvx"
    assert conn.args == ["--port", "9", "--verbose"]


def test_http_connection_needs_a_url(vault):
    write_md(vault.connections_dir / "x.md", {"name": "x", "type": "mcp-http"})
    assert any("'url' is missing" in i.message for i in load(vault).issues)


def test_missing_settings_is_an_error_with_safe_defaults(vault):
    vault.settings_file.unlink()
    cfg = load(vault)
    assert any(i.code == "settings.missing" for i in cfg.issues)
    assert cfg.settings.default_agent == "Bron"
    assert cfg.settings.max_parallel == 3
```

`tests/test_catalog.py`:

```python
from bron.loader import load
from vaultkit import add_agent, set_meta


def test_model_aliases_resolve_friendly_names(vault):
    catalog = load(vault).catalog
    assert catalog.resolve_model("claude", "Opus 5.5") == "claude-opus-5-5"
    assert catalog.resolve_model("claude", "opus") == "opus"
    assert catalog.resolve_model("claude", "default") is None
    assert catalog.resolve_model("claude", None) is None
    assert catalog.resolve_model("codex", "gpt-6.1-sol") == "gpt-6.1-sol"


def test_actions_resolve_groups_and_raw_entries(vault):
    catalog = load(vault).catalog
    acts = catalog.resolve_actions(["git-push", "send-email", "mcp:carta:mutate", "shell:rm -rf", "nonsense", "mcp:broken"])
    assert ("git", "push") in acts.shell
    assert ("rm", "-rf") in acts.shell
    assert "send_message" in acts.mcp["gmail"]
    assert acts.mcp["carta"] == {"mutate"}
    assert acts.unknown == ["nonsense", "mcp:broken"]


def test_always_allow_wins_over_ask_before(vault):
    add_agent(vault, "CFO", ask_before=["git-push", "send-email"], always_allow=["git-push", "mcp:gmail:send_message"])
    cfg = load(vault)
    ask, allow = cfg.catalog.permissions_for(cfg.agents["cfo"])
    assert ask.shell == []
    assert ("git", "push") in allow.shell
    assert "send_message" not in ask.mcp["gmail"]
    assert "reply_to_message" in ask.mcp["gmail"]


def test_settings_can_add_action_groups(vault):
    set_meta(vault.settings_file, action_groups={"wire-money": {"mcp": {"bank": ["transfer"]}}})
    catalog = load(vault).catalog
    assert catalog.resolve_actions(["wire-money"]).mcp == {"bank": {"transfer"}}


def test_malformed_group_is_reported(vault):
    set_meta(vault.settings_file, action_groups={"bad": {"shell": "git push"}})
    assert any(i.code == "permissions.bad-group" for i in load(vault).issues)
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_loader.py tests/test_catalog.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.loader'`.

- [ ] **Step 4: Implement `model.py`**

`core/Engine/bron/model.py`:

```python
"""What a Bron vault defines: agents, helpers, skills, connections and settings."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

CLIS = ("claude", "codex")
CLI_NAMES = {"claude": "Claude Code", "codex": "Codex"}
RUNS_IN = ("any", "claude", "codex")
CONNECTION_TYPES = ("mcp-stdio", "mcp-http")
DEFAULT_MODEL = "default"  # use whatever model the CLI itself is set to
SKILL_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def slug(name: str) -> str:
    """Agent/helper key for file names and @tags: 'Chief Finance' -> 'chief-finance'."""
    return re.sub(r"[^a-z0-9]+", "-", _ascii(name).strip().lower()).strip("-")


def conn_key(name: str) -> str:
    """Connection key used as the MCP server name: 'Google Drive' -> 'google_drive'."""
    return re.sub(r"[^a-z0-9]+", "_", _ascii(name).strip().lower()).strip("_")


@dataclass(frozen=True)
class Issue:
    level: str  # "error" | "warning"
    code: str
    message: str
    path: Path | None = None

    def render(self, root: Path | None = None) -> str:
        where = ""
        if self.path is not None:
            shown = self.path
            if root is not None:
                try:
                    shown = self.path.relative_to(root)
                except ValueError:
                    pass
            where = f" ({shown})"
        icon = "✗" if self.level == "error" else "!"
        return f"{icon} {self.message}{where}"


@dataclass
class Agent:
    name: str
    role: str
    reports_to: str
    runs_in: str
    path: Path
    models: dict[str, str] = field(default_factory=dict)
    helpers: list[str] = field(default_factory=list)
    connections: list[str] = field(default_factory=list)
    can_assign_to: list[str] = field(default_factory=list)
    ask_before: list[str] = field(default_factory=list)
    always_allow: list[str] = field(default_factory=list)
    instructions: str = ""

    @property
    def key(self) -> str:
        return slug(self.name)


@dataclass
class Helper:
    name: str
    description: str
    path: Path
    source: str  # "core" | "user"
    models: dict[str, str] = field(default_factory=dict)
    connections: list[str] = field(default_factory=list)
    read_only: bool = False
    instructions: str = ""

    @property
    def key(self) -> str:
        return slug(self.name)


@dataclass
class Skill:
    name: str  # published name
    description: str  # published description
    folder: Path
    source: str  # "core" | "user" | "agent:<key>"
    rewrite: bool = False  # True when name/description differ from the source SKILL.md


@dataclass
class Connection:
    name: str
    type: str
    path: Path
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    description: str = ""

    @property
    def key(self) -> str:
        return conn_key(self.name)


@dataclass
class Settings:
    path: Path
    user_name: str = ""
    company: str = ""
    default_cli: str = "claude"
    default_agent: str = "Bron"
    max_parallel: int = 3
    max_minutes: int = 30
    action_groups: dict = field(default_factory=dict)
```

- [ ] **Step 5: Implement `catalog.py`**

`core/Engine/bron/catalog.py`:

```python
"""Built-in lookups kept in Core/Manual as readable pages: model aliases and permission action groups."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter as fm
from .model import DEFAULT_MODEL, Agent, Issue, Settings, conn_key
from .vault import Vault


def norm(value: str) -> str:
    return re.sub(r"\s+", "-", value.strip().lower())


@dataclass
class ActionGroup:
    mcp: dict[str, list[str]] = field(default_factory=dict)  # connection key -> tool names
    shell: list[tuple[str, ...]] = field(default_factory=list)  # command prefixes


@dataclass
class Actions:
    mcp: dict[str, set[str]] = field(default_factory=dict)
    shell: list[tuple[str, ...]] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)

    def add_shell(self, words: tuple[str, ...]) -> None:
        if words and words not in self.shell:
            self.shell.append(words)


@dataclass
class Catalog:
    model_aliases: dict[str, dict[str, str]] = field(default_factory=dict)
    action_groups: dict[str, ActionGroup] = field(default_factory=dict)

    def resolve_model(self, cli: str, value: str | None) -> str | None:
        """The model string to pass to the CLI, or None to use the CLI's own default."""
        if value is None or not str(value).strip():
            return None
        key = norm(str(value))
        if key == DEFAULT_MODEL:
            return None
        return self.model_aliases.get(cli, {}).get(key, str(value).strip())

    def resolve_actions(self, entries: list[str]) -> Actions:
        out = Actions()
        for entry in entries:
            text = entry.strip()
            if text.startswith("mcp:"):
                parts = text.split(":")
                if len(parts) == 3 and parts[1].strip() and parts[2].strip():
                    out.mcp.setdefault(conn_key(parts[1]), set()).add(parts[2].strip())
                else:
                    out.unknown.append(entry)
            elif text.startswith("shell:"):
                words = tuple(text[len("shell:") :].split())
                if words:
                    out.add_shell(words)
                else:
                    out.unknown.append(entry)
            elif (group := self.action_groups.get(norm(text))) is not None:
                for conn, tools in group.mcp.items():
                    out.mcp.setdefault(conn, set()).update(tools)
                for words in group.shell:
                    out.add_shell(words)
            else:
                out.unknown.append(entry)
        return out

    def permissions_for(self, agent: Agent) -> tuple[Actions, Actions]:
        """(ask, allow) for an agent. 'Always allow' wins over 'ask before'."""
        allow = self.resolve_actions(agent.always_allow)
        ask = self.resolve_actions(agent.ask_before)
        for conn, tools in allow.mcp.items():
            if conn in ask.mcp:
                ask.mcp[conn] -= tools
                if not ask.mcp[conn]:
                    del ask.mcp[conn]
        ask.shell = [words for words in ask.shell if words not in allow.shell]
        return ask, allow


def load_catalog(vault: Vault, settings: Settings, issues: list[Issue]) -> Catalog:
    catalog = Catalog()
    models = _meta(vault.core_manual / "models.md", issues)
    for cli, table in (models.get("aliases") or {}).items():
        if isinstance(table, dict):
            catalog.model_aliases[str(cli)] = {norm(str(k)): str(v) for k, v in table.items()}
    permissions_page = vault.core_manual / "permissions.md"
    groups = dict(_meta(permissions_page, issues).get("action_groups") or {})
    groups.update(settings.action_groups)
    for name, spec in groups.items():
        group = _group(spec)
        if group is None:
            where = settings.path if name in settings.action_groups else permissions_page
            issues.append(Issue("error", "permissions.bad-group", f"The action group '{name}' isn't written correctly", where))
            continue
        catalog.action_groups[norm(str(name))] = group
    return catalog


def _meta(path: Path, issues: list[Issue]) -> dict:
    try:
        return fm.read(path).meta
    except FileNotFoundError:
        issues.append(Issue("error", "core.file-missing", "A framework file is missing; update or reinstall Bron", path))
    except (fm.FrontmatterError, OSError, UnicodeDecodeError) as exc:
        issues.append(Issue("error", "core.file-unreadable", f"A framework file can't be read: {exc}", path))
    return {}


def _group(spec) -> ActionGroup | None:
    if not isinstance(spec, dict):
        return None
    mcp = spec.get("mcp") or {}
    shell = spec.get("shell") or []
    if not isinstance(mcp, dict) or not isinstance(shell, list):
        return None
    group = ActionGroup()
    for conn, tools in mcp.items():
        if not isinstance(tools, list):
            return None
        group.mcp[conn_key(str(conn))] = [str(t) for t in tools]
    for prefix in shell:
        if not isinstance(prefix, list) or not prefix:
            return None
        group.shell.append(tuple(str(w) for w in prefix))
    return group
```

- [ ] **Step 6: Implement `loader.py`**

`core/Engine/bron/loader.py`:

```python
"""Reads System/ and Core/ into one Config. Problems are collected as Issues, never raised."""
from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path

from . import frontmatter as fm
from .catalog import Catalog, load_catalog
from .model import (
    CLIS,
    CONNECTION_TYPES,
    RUNS_IN,
    SKILL_NAME,
    Agent,
    Connection,
    Helper,
    Issue,
    Settings,
    Skill,
    slug,
)
from .vault import Vault


@dataclass
class Config:
    vault: Vault
    settings: Settings
    catalog: Catalog
    agents: dict[str, Agent] = field(default_factory=dict)
    helpers: dict[str, Helper] = field(default_factory=dict)
    skills: dict[str, Skill] = field(default_factory=dict)
    connections: dict[str, Connection] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)

    @property
    def default_agent(self) -> Agent | None:
        return self.agents.get(slug(self.settings.default_agent))


def load(vault: Vault) -> Config:
    issues: list[Issue] = []
    settings = _settings(vault, issues)
    cfg = Config(vault, settings, load_catalog(vault, settings, issues), issues=issues)
    _agents(cfg)
    _helpers(cfg)
    _skills(cfg)
    _connections(cfg)
    return cfg


class _Fields:
    """Typed access to one file's frontmatter, recording friendly problems."""

    def __init__(self, meta: dict, path: Path, issues: list[Issue]):
        self.meta, self.path, self.issues = meta, path, issues

    def problem(self, code: str, message: str, level: str = "error") -> None:
        self.issues.append(Issue(level, code, message, self.path))

    def text(self, key: str, *, required: bool = False, default: str = "") -> str:
        value = self.meta.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                self.problem("field.missing", f"'{key}' is missing")
            return default
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            self.problem("field.type", f"'{key}' should be plain text")
            return default
        return str(value).strip()

    def names(self, key: str) -> list[str]:
        value = self.meta.get(key)
        if value is None:
            return []
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        if isinstance(value, list) and all(isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in value):
            return [str(v).strip() for v in value if str(v).strip()]
        self.problem("field.type", f"'{key}' should be a list, like [a, b]")
        return []

    def arguments(self, key: str) -> list[str]:
        value = self.meta.get(key)
        if value is None:
            return []
        if isinstance(value, str):
            return shlex.split(value)
        if isinstance(value, list):
            return [str(v) for v in value]
        self.problem("field.type", f"'{key}' should be a list of command arguments")
        return []

    def number(self, key: str, default: int, *, minimum: int = 1) -> int:
        value = self.meta.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            self.problem("field.type", f"'{key}' should be a whole number of at least {minimum}")
            return default
        return value

    def flag(self, key: str, default: bool = False) -> bool:
        value = self.meta.get(key, default)
        if not isinstance(value, bool):
            self.problem("field.type", f"'{key}' should be true or false")
            return default
        return value

    def models(self) -> dict[str, str]:
        value = self.meta.get("models")
        if value is None:
            return {}
        if not isinstance(value, dict):
            self.problem("field.type", "'models' should name one model per CLI, like {claude: opus, codex: default}")
            return {}
        out: dict[str, str] = {}
        for cli, model in value.items():
            if cli not in CLIS:
                self.problem("field.value", f"'models' only takes 'claude' and 'codex', not '{cli}'")
                continue
            if model is None or isinstance(model, bool) or not isinstance(model, (str, int, float)) or not str(model).strip():
                self.problem("field.type", f"the {cli} model should be a model name or 'default'")
                continue
            out[cli] = str(model).strip()
        return out


def _open(path: Path, issues: list[Issue]) -> fm.Document | None:
    try:
        return fm.read(path)
    except fm.FrontmatterError as exc:
        issues.append(Issue("error", "file.unreadable", f"Bron can't read this file: {exc}", path))
    except (OSError, UnicodeDecodeError) as exc:
        issues.append(Issue("error", "file.unreadable", f"Bron can't open this file ({exc.__class__.__name__})", path))
    return None


def _subfolders(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.is_dir() and not p.name.startswith("."))


def _settings(vault: Vault, issues: list[Issue]) -> Settings:
    path = vault.settings_file
    settings = Settings(path=path)
    if not path.is_file():
        issues.append(Issue("error", "settings.missing", "System/Settings.md is missing", path))
        return settings
    doc = _open(path, issues)
    if doc is None:
        return settings
    f = _Fields(doc.meta, path, issues)
    settings.user_name = f.text("user_name")
    settings.company = f.text("company")
    settings.default_cli = f.text("default_cli", default="claude").lower()
    if settings.default_cli not in CLIS:
        f.problem("field.value", "'default_cli' should be 'claude' or 'codex'")
        settings.default_cli = "claude"
    settings.default_agent = f.text("default_agent", default="Bron")
    runner = doc.meta.get("runner") or {}
    if not isinstance(runner, dict):
        f.problem("field.type", "'runner' should hold max_parallel and max_minutes")
        runner = {}
    rf = _Fields(runner, path, issues)
    settings.max_parallel = rf.number("max_parallel", 3)
    settings.max_minutes = rf.number("max_minutes", 30)
    groups = doc.meta.get("action_groups") or {}
    if isinstance(groups, dict):
        settings.action_groups = groups
    else:
        f.problem("field.type", "'action_groups' should be a list of named groups")
    return settings


def _agents(cfg: Config) -> None:
    folder = cfg.vault.agents_dir
    if not folder.is_dir():
        cfg.issues.append(Issue("error", "agents.missing", "System/Agents/ is missing", folder))
        return
    for sub in _subfolders(folder):
        path = sub / "Agent.md"
        if not path.is_file():
            cfg.issues.append(Issue("error", "agent.file-missing", f"The agent folder '{sub.name}' has no Agent.md", sub))
            continue
        doc = _open(path, cfg.issues)
        if doc is None:
            continue
        f = _Fields(doc.meta, path, cfg.issues)
        name = f.text("name", required=True)
        if not name:
            continue
        if name != sub.name:
            f.problem("agent.name-mismatch", f"The name '{name}' must match the folder name '{sub.name}'")
        runs_in = f.text("runs_in", default="any").lower()
        if runs_in not in RUNS_IN:
            f.problem("field.value", "'runs_in' should be any, claude or codex")
            runs_in = "any"
        agent = Agent(
            name=name,
            role=f.text("role", required=True),
            reports_to=f.text("reports_to", required=True),
            runs_in=runs_in,
            path=path,
            models=f.models(),
            helpers=f.names("helpers"),
            connections=f.names("connections"),
            can_assign_to=f.names("can_assign_to"),
            ask_before=f.names("ask_before"),
            always_allow=f.names("always_allow"),
            instructions=doc.body.strip(),
        )
        if not agent.key:
            f.problem("agent.bad-name", f"The name '{name}' needs at least one letter or number")
            continue
        if agent.key in cfg.agents:
            f.problem("agent.duplicate", f"Two agents share the name '{name}' (both become '{agent.key}')")
            continue
        cfg.agents[agent.key] = agent


def _helpers(cfg: Config) -> None:
    for source, folder in (("core", cfg.vault.core_helpers), ("user", cfg.vault.helpers_dir)):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            doc = _open(path, cfg.issues)
            if doc is None:
                continue
            f = _Fields(doc.meta, path, cfg.issues)
            name = f.text("name", required=True)
            description = f.text("description", required=True)
            if not name or not description or not slug(name):
                continue
            helper = Helper(
                name=name,
                description=description,
                path=path,
                source=source,
                models=f.models(),
                connections=f.names("connections"),
                read_only=f.flag("read_only"),
                instructions=doc.body.strip(),
            )
            cfg.helpers[helper.key] = helper  # a user file replaces the core one of the same name


def _skills(cfg: Config) -> None:
    sources: list[tuple[str, Path, str]] = [("core", cfg.vault.core_skills, ""), ("user", cfg.vault.skills_dir, "")]
    for key, agent in sorted(cfg.agents.items()):
        sources.append((f"agent:{key}", agent.path.parent / "Skills", key))
    for source, folder, owner_key in sources:
        if not folder.is_dir():
            continue
        for sub in _subfolders(folder):
            path = sub / "SKILL.md"
            if not path.is_file():
                cfg.issues.append(Issue("warning", "skill.file-missing", f"The skill folder '{sub.name}' has no SKILL.md, so it is skipped", sub))
                continue
            doc = _open(path, cfg.issues)
            if doc is None:
                continue
            f = _Fields(doc.meta, path, cfg.issues)
            name = f.text("name", required=True)
            description = f.text("description", required=True)
            if not name or not description:
                continue
            if not SKILL_NAME.match(name) or len(name) > 64:
                f.problem("skill.bad-name", f"The skill name '{name}' may only use lower-case letters, numbers and hyphens (64 at most)")
                continue
            if name != sub.name:
                f.problem("skill.name-mismatch", f"The skill name '{name}' should match its folder name '{sub.name}'", level="warning")
            if owner_key:
                owner = cfg.agents[owner_key].name
                skill = Skill(f"{owner_key}-{name}", f"(For {owner} only) {description}", sub, source, rewrite=True)
            else:
                skill = Skill(name, description, sub, source)
            cfg.skills[skill.name] = skill


def _connections(cfg: Config) -> None:
    folder = cfg.vault.connections_dir
    if not folder.is_dir():
        return
    for path in sorted(folder.glob("*.md")):
        doc = _open(path, cfg.issues)
        if doc is None:
            continue
        f = _Fields(doc.meta, path, cfg.issues)
        name = f.text("name", required=True)
        kind = f.text("type", required=True).lower()
        if not name or not kind:
            continue
        if kind not in CONNECTION_TYPES:
            f.problem("field.value", "'type' should be mcp-stdio or mcp-http")
            continue
        env = doc.meta.get("env") or {}
        if not isinstance(env, dict) or not all(isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in env.values()):
            f.problem("field.type", "'env' should be 'NAME: value' lines")
            env = {}
        conn = Connection(
            name=name,
            type=kind,
            path=path,
            command=f.text("command"),
            args=f.arguments("args"),
            env={str(k): str(v) for k, v in env.items()},
            url=f.text("url"),
            description=f.text("description"),
        )
        if kind == "mcp-stdio" and not conn.command:
            f.problem("field.missing", "'command' is missing (needed for mcp-stdio)")
            continue
        if kind == "mcp-http" and not conn.url:
            f.problem("field.missing", "'url' is missing (needed for mcp-http)")
            continue
        if not conn.key or conn.key in cfg.connections:
            f.problem("connection.duplicate", f"Another connection already uses the name '{name}'")
            continue
        cfg.connections[conn.key] = conn
```

- [ ] **Step 7: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add core/Engine/bron/model.py core/Engine/bron/catalog.py core/Engine/bron/loader.py core/Manual core/Helpers core/Skills tests/test_loader.py tests/test_catalog.py
git commit -F - <<'EOF'
feat(core): load agents, helpers, skills, connections and settings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: Health check

**Files:**
- Create: `core/Engine/bron/check.py`
- Test: `tests/test_check.py`

**Interfaces:**
- Consumes: `Config`, `load` (Task 3); `Issue`, `slug`, `conn_key`, `CLI_NAMES` (Task 3).
- Produces: `bron.check`:
  - `run_checks(cfg: Config, *, include_environment: bool = True) -> list[Issue]`: includes `cfg.issues` (loader problems) first.
  - `has_errors(issues: list[Issue]) -> bool`
  - `codex_trusts(root: Path) -> bool`
  - `SECRET_WORDS`

- [ ] **Step 1: Write the failing tests**

`tests/test_check.py`:

```python
from bron.check import codex_trusts, has_errors, run_checks
from bron.loader import load
from vaultkit import add_agent, add_connection, set_meta


def codes(vault):
    return {i.code for i in run_checks(load(vault), include_environment=False)}


def test_template_passes(vault):
    assert run_checks(load(vault), include_environment=False) == []


def test_unknown_references_are_errors(vault):
    add_agent(vault, "CFO", reports_to="Nobody", helpers=["ghost"], connections=["carta"], can_assign_to=["COO", "CFO"])
    found = codes(vault)
    assert {
        "agent.reports-to-unknown",
        "agent.helper-unknown",
        "agent.connection-unknown",
        "agent.assign-unknown",
        "agent.assign-self",
    } <= found


def test_references_are_matched_loosely(vault):
    add_connection(vault, "Google Drive")
    add_agent(vault, "CFO", reports_to="bron", connections=["google-drive"], helpers=["Reader"])
    assert codes(vault) == set()


def test_reporting_cycle_is_reported_once(vault):
    add_agent(vault, "CFO", reports_to="COO")
    add_agent(vault, "COO", reports_to="CFO")
    cycles = [i for i in run_checks(load(vault), include_environment=False) if i.code == "agent.reports-cycle"]
    assert len(cycles) == 1
    assert "CFO" in cycles[0].message and "COO" in cycles[0].message


def test_default_agent_must_exist(vault):
    set_meta(vault.settings_file, default_agent="Atlas")
    assert "settings.default-agent-unknown" in codes(vault)


def test_agent_named_like_a_helper_is_an_error(vault):
    add_agent(vault, "Reader")
    assert "agent.name-taken" in codes(vault)


def test_unknown_action_is_only_a_warning(vault):
    add_agent(vault, "CFO", ask_before=["launch-rockets"])
    issues = run_checks(load(vault), include_environment=False)
    assert [i.level for i in issues if i.code == "agent.action-unknown"] == ["warning"]
    assert not has_errors(issues)


def test_secret_in_connection_env_is_an_error(vault):
    add_connection(vault, "Carta", env={"CARTA_API_KEY": "sk-123", "CARTA_TOKEN": "${CARTA_TOKEN}", "REGION": "us"})
    secrets = [i for i in run_checks(load(vault), include_environment=False) if i.code == "connection.secret-in-vault"]
    assert len(secrets) == 1
    assert "CARTA_API_KEY" in secrets[0].message


def test_helper_connection_must_exist(vault):
    from vaultkit import write_md

    write_md(vault.helpers_dir / "scout.md", {"name": "scout", "description": "x", "connections": ["nowhere"]})
    assert "helper.connection-unknown" in codes(vault)


def test_missing_cli_is_a_warning(vault, monkeypatch):
    monkeypatch.setattr("bron.check.shutil.which", lambda name: None)
    issues = run_checks(load(vault))
    assert any(i.code == "cli.missing" and i.level == "warning" for i in issues)


def test_codex_trust_is_read_from_codex_home(vault, tmp_path, monkeypatch):
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    assert not codex_trusts(vault.root)
    (home / "config.toml").write_text(f'[projects."{vault.root}"]\ntrust_level = "trusted"\n', encoding="utf-8")
    assert codex_trusts(vault.root)


def test_untrusted_codex_vault_is_a_warning(vault, tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr("bron.check.shutil.which", lambda name: f"/usr/bin/{name}")
    issues = run_checks(load(vault))
    assert any(i.code == "codex.untrusted" and i.level == "warning" for i in issues)
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_check.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.check'`.

- [ ] **Step 3: Implement `check.py`**

`core/Engine/bron/check.py`:

```python
"""The health check: everything Bron can validate without changing anything."""
from __future__ import annotations

import os
import shutil
import tomllib
from pathlib import Path

from .loader import Config
from .model import CLI_NAMES, Issue, conn_key, slug

SECRET_WORDS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def run_checks(cfg: Config, *, include_environment: bool = True) -> list[Issue]:
    issues = list(cfg.issues)
    issues += _settings(cfg)
    issues += _agents(cfg)
    issues += _cycles(cfg)
    issues += _helpers(cfg)
    issues += _connections(cfg)
    if include_environment:
        issues += _environment(cfg)
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.level == "error" for issue in issues)


def _settings(cfg: Config) -> list[Issue]:
    if cfg.default_agent is None:
        return [Issue("error", "settings.default-agent-unknown", f"The default agent '{cfg.settings.default_agent}' doesn't exist in System/Agents/", cfg.settings.path)]
    return []


def _agents(cfg: Config) -> list[Issue]:
    out: list[Issue] = []
    for key, agent in cfg.agents.items():
        def bad(code: str, message: str, level: str = "error") -> None:
            out.append(Issue(level, code, message, agent.path))

        boss = slug(agent.reports_to)
        if boss and boss != "you" and boss not in cfg.agents:
            bad("agent.reports-to-unknown", f"{agent.name} reports to '{agent.reports_to}', which isn't an agent (use 'you' or an agent's name)")
        if key in cfg.helpers:
            bad("agent.name-taken", f"{agent.name} has the same name as a helper; rename one of them")
        for helper in agent.helpers:
            if slug(helper) not in cfg.helpers:
                bad("agent.helper-unknown", f"{agent.name} uses the helper '{helper}', which doesn't exist")
        for conn in agent.connections:
            if conn_key(conn) not in cfg.connections:
                bad("agent.connection-unknown", f"{agent.name} uses the connection '{conn}', which isn't set up in System/Connections/")
        for other in agent.can_assign_to:
            other_key = slug(other)
            if other_key == key:
                bad("agent.assign-self", f"{agent.name} can't assign tickets to itself")
            elif other_key not in cfg.agents:
                bad("agent.assign-unknown", f"{agent.name} can assign work to '{other}', which isn't an agent")
        for field_name in ("ask_before", "always_allow"):
            for entry in cfg.catalog.resolve_actions(getattr(agent, field_name)).unknown:
                bad("agent.action-unknown", f"{agent.name}'s {field_name} lists '{entry}', which Bron doesn't recognise (see System/Core/Manual/permissions.md)", "warning")
    return out


def _cycles(cfg: Config) -> list[Issue]:
    out: list[Issue] = []
    reported: set[frozenset[str]] = set()
    for start in sorted(cfg.agents):
        seen: list[str] = []
        key = start
        while key in cfg.agents and key not in seen:
            seen.append(key)
            key = slug(cfg.agents[key].reports_to)
        if key in seen:
            loop = seen[seen.index(key):]
            if frozenset(loop) not in reported:
                reported.add(frozenset(loop))
                names = " → ".join(cfg.agents[k].name for k in loop) + f" → {cfg.agents[key].name}"
                out.append(Issue("error", "agent.reports-cycle", f"Reporting goes in a circle: {names}", cfg.agents[key].path))
    return out


def _helpers(cfg: Config) -> list[Issue]:
    out: list[Issue] = []
    for helper in cfg.helpers.values():
        for conn in helper.connections:
            if conn_key(conn) not in cfg.connections:
                out.append(Issue("error", "helper.connection-unknown", f"The helper '{helper.name}' uses the connection '{conn}', which isn't set up", helper.path))
    return out


def _connections(cfg: Config) -> list[Issue]:
    out: list[Issue] = []
    for conn in cfg.connections.values():
        for name, value in conn.env.items():
            if any(word in name.upper() for word in SECRET_WORDS) and not value.startswith("${"):
                out.append(Issue(
                    "error",
                    "connection.secret-in-vault",
                    f"The connection '{conn.name}' stores {name} in the vault. Keep secrets out of the vault: write it as ${{{name}}} and set it in your shell or Keychain",
                    conn.path,
                ))
    return out


def _environment(cfg: Config) -> list[Issue]:
    out: list[Issue] = []
    needed = {cfg.settings.default_cli} | {a.runs_in for a in cfg.agents.values() if a.runs_in != "any"}
    for cli in sorted(needed):
        if shutil.which(cli) is None:
            out.append(Issue("warning", "cli.missing", f"{CLI_NAMES[cli]} isn't installed (or isn't on PATH), but your setup uses it"))
    if shutil.which("codex") is not None and not codex_trusts(cfg.vault.root):
        out.append(Issue("warning", "codex.untrusted", "Codex doesn't trust this vault yet, so Codex sessions here ignore Bron's setup. Re-run the Bron installer to fix it."))
    return out


def codex_trusts(root: Path) -> bool:
    home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        data = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    projects = data.get("projects") or {}
    for candidate in {str(root), str(root.resolve())}:
        entry = projects.get(candidate)
        if isinstance(entry, dict) and entry.get("trust_level") == "trusted":
            return True
    return False
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/check.py tests/test_check.py
git commit -F - <<'EOF'
feat(core): health check for references, cycles, secrets and environment

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: Safe writer for generated files

**Files:**
- Create: `core/Engine/bron/writer.py`
- Test: `tests/test_writer.py`

**Interfaces:**
- Consumes: `Vault` (Task 2).
- Produces: `bron.writer`:
  - `GeneratedWriter(vault)`:
    - `.manifest: dict` holding `{"files": {rel: sha256}, "fingerprint": str}`.
    - `.drift() -> list[str]`.
    - `.apply(files: dict[str, bytes], fingerprint: str = "") -> WriteReport`.
  - `WriteReport(written: list[str], deleted: list[str], backed_up: list[str], backup_dir: Path | None)`.
  - `ALLOWED_ROOTS`, `sha256(data: bytes) -> str`.

- [ ] **Step 1: Write the failing tests**

`tests/test_writer.py`:

```python
import json

import pytest

from bron.writer import GeneratedWriter


def write(vault, files, fingerprint=""):
    return GeneratedWriter(vault).apply({k: v.encode() for k, v in files.items()}, fingerprint)


def test_writes_files_and_records_them(vault):
    report = write(vault, {".claude/settings.json": "{}\n", "AGENTS.md": "rules\n"}, "fp1")
    assert sorted(report.written) == [".claude/settings.json", "AGENTS.md"]
    assert (vault.root / "AGENTS.md").read_text() == "rules\n"
    manifest = json.loads((vault.state_dir / "sync.json").read_text())
    assert set(manifest["files"]) == {".claude/settings.json", "AGENTS.md"}
    assert manifest["fingerprint"] == "fp1"


def test_same_content_writes_nothing(vault):
    write(vault, {"AGENTS.md": "rules\n"})
    report = write(vault, {"AGENTS.md": "rules\n"})
    assert report.written == [] and report.deleted == [] and report.backed_up == []


def test_hand_edited_file_is_backed_up_then_replaced(vault):
    write(vault, {".claude/settings.json": "{}\n"})
    (vault.root / ".claude/settings.json").write_text('{"mine": true}\n')
    report = write(vault, {".claude/settings.json": '{"agent": "bron"}\n'})
    assert report.backed_up == [".claude/settings.json"]
    assert (report.backup_dir / ".claude/settings.json").read_text() == '{"mine": true}\n'
    assert (vault.root / ".claude/settings.json").read_text() == '{"agent": "bron"}\n'


def test_existing_file_bron_never_wrote_is_backed_up(vault):
    (vault.root / ".claude").mkdir()
    (vault.root / ".claude/settings.json").write_text('{"theirs": 1}\n')
    report = write(vault, {".claude/settings.json": "{}\n"})
    assert report.backed_up == [".claude/settings.json"]


def test_dropped_files_are_removed_but_other_tools_files_survive(vault):
    termy = vault.root / ".agents/skills/termy-obsidian-context/SKILL.md"
    termy.parent.mkdir(parents=True)
    termy.write_text("termy\n")
    local = vault.root / ".claude/settings.local.json"
    local.parent.mkdir(parents=True)
    local.write_text("{}\n")
    write(vault, {".agents/skills/check/SKILL.md": "a\n", ".claude/agents/cfo.md": "b\n"})
    report = write(vault, {})
    assert sorted(report.deleted) == [".agents/skills/check/SKILL.md", ".claude/agents/cfo.md"]
    assert not (vault.root / ".agents/skills/check").exists()
    assert termy.read_text() == "termy\n"
    assert local.read_text() == "{}\n"


def test_refuses_paths_outside_generated_places(vault):
    with pytest.raises(ValueError, match="outside"):
        write(vault, {"System/Settings.md": "x"})
    with pytest.raises(ValueError, match="outside"):
        write(vault, {".claude/../System/Settings.md": "x"})


def test_drift_detects_edits_and_deletions(vault):
    write(vault, {"AGENTS.md": "a\n", "CLAUDE.md": "@AGENTS.md\n"})
    (vault.root / "AGENTS.md").write_text("edited\n")
    (vault.root / "CLAUDE.md").unlink()
    assert GeneratedWriter(vault).drift() == ["AGENTS.md", "CLAUDE.md"]


def test_corrupt_manifest_is_treated_as_empty(vault):
    vault.state_dir.mkdir(parents=True)
    (vault.state_dir / "sync.json").write_text("{not json")
    assert GeneratedWriter(vault).drift() == []
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_writer.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.writer'`.

- [ ] **Step 3: Implement `writer.py`**

`core/Engine/bron/writer.py`:

```python
"""Writes Bron-generated files safely.

- Only paths in ALLOWED_ROOTS can be written.
- A manifest records what Bron wrote, so files from other tools are never deleted.
- Anything changed by hand (or present before Bron) is backed up before it is replaced.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .vault import Vault

MANIFEST = "sync.json"
ALLOWED_ROOTS = ("AGENTS.md", "CLAUDE.md", ".mcp.json", ".claude/", ".codex/", ".agents/")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class WriteReport:
    written: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    backed_up: list[str] = field(default_factory=list)
    backup_dir: Path | None = None


class GeneratedWriter:
    def __init__(self, vault: Vault):
        self.vault = vault
        self.manifest_path = vault.state_dir / MANIFEST
        self.manifest = self._load()

    def _load(self) -> dict:
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"files": {}, "fingerprint": ""}
        if not isinstance(data, dict) or not isinstance(data.get("files"), dict):
            return {"files": {}, "fingerprint": ""}
        data.setdefault("fingerprint", "")
        return data

    def drift(self) -> list[str]:
        changed = []
        for rel, digest in sorted(self.manifest["files"].items()):
            path = self.vault.root / rel
            if not path.is_file() or sha256(path.read_bytes()) != digest:
                changed.append(rel)
        return changed

    def apply(self, files: dict[str, bytes], fingerprint: str = "") -> WriteReport:
        for rel in files:
            _check_allowed(rel)
        report = WriteReport()
        backup_root = self.vault.backups_dir / f"sync-{time.strftime('%Y%m%d-%H%M%S')}"
        old: dict[str, str] = self.manifest["files"]
        new: dict[str, str] = {}
        for rel, data in sorted(files.items()):
            target = self.vault.root / rel
            digest = sha256(data)
            if target.is_file():
                current = target.read_bytes()
                if current == data:
                    new[rel] = digest
                    continue
                if old.get(rel) != sha256(current):
                    self._backup(target, rel, backup_root, report)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".bron-tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
            report.written.append(rel)
            new[rel] = digest
        for rel, digest in sorted(old.items()):
            if rel in files:
                continue
            target = self.vault.root / rel
            if target.is_file():
                if sha256(target.read_bytes()) != digest:
                    self._backup(target, rel, backup_root, report)
                target.unlink()
                report.deleted.append(rel)
                self._prune(target.parent)
        self.manifest = {"files": new, "fingerprint": fingerprint}
        self.vault.state_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_name(MANIFEST + ".bron-tmp")
        tmp.write_text(json.dumps(self.manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(self.manifest_path)
        if report.backed_up:
            report.backup_dir = backup_root
        return report

    def _backup(self, target: Path, rel: str, backup_root: Path, report: WriteReport) -> None:
        destination = backup_root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, destination)
        report.backed_up.append(rel)

    def _prune(self, folder: Path) -> None:
        root = self.vault.root
        while folder != root and root in folder.parents:
            try:
                folder.rmdir()  # only succeeds when empty
            except OSError:
                return
            folder = folder.parent


def _check_allowed(rel: str) -> None:
    path = PurePosixPath(rel)
    if path.is_absolute() or ".." in path.parts or not any(rel == r or (r.endswith("/") and rel.startswith(r)) for r in ALLOWED_ROOTS):
        raise ValueError(f"Bron tried to write {rel}, which is outside the generated files it manages")
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/writer.py tests/test_writer.py
git commit -F - <<'EOF'
feat(core): manifest-tracked writer that backs up hand edits

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 6: Shared generation pieces: prompts, AGENTS.md, skills, trigger block

**Files:**
- Create: `core/Engine/bron/prompts.py`, `core/Engine/bron/agents_md.py`, `core/Engine/bron/skills.py`, `core/Engine/bron/hookconfig.py`
- Create: `core/Templates/AGENTS.md.tmpl`, `core/Manual/index.md`
- Test: `tests/test_prompts.py`

**Interfaces:**
- Consumes: `Config`, `load` (Task 3); `bron.frontmatter` (Task 2).
- Produces:
  - `bron.prompts`: `agent_prompt(agent: Agent, cfg: Config) -> str` (starts with `# You are <Name>`), `helper_prompt(helper: Helper) -> str` (starts with `# You are the <name> helper`).
  - `bron.agents_md`: `render_agents_md(cfg: Config) -> str`.
  - `bron.skills`: `skill_files(cfg: Config, dest: str) -> dict[str, bytes]` (keys like `"<dest>/<skill>/<file>"`).
  - `bron.hookconfig`: `EVENTS` (tuples of CLI event, Bron event, timeout), `HOOK_NAMES`, `hooks_block(vault: Vault, cli: str) -> dict` (the value of the `hooks` key, identical shape for both CLIs).

- [ ] **Step 1: Add the template and the manual index**

`core/Templates/AGENTS.md.tmpl` (uses `$name` placeholders; write `$$` for a literal dollar sign):

```markdown
<!-- Generated by Bron from System/. Do not edit this file: change System/ or ask Bron. -->
# Bron vault

This folder is a Bron vault: an Obsidian workspace where AI agents work with $user. Every session here, in Claude Code or in Codex, follows these shared rules. Your own role and instructions come from the agent you were started as; follow them.

## Where things are

| Folder | What it holds |
|---|---|
| `Projects/` | One-off work, one folder per project (`README.md` plus its files) |
| `Routines/` | Repeating workflows: a `Runbook.md` plus one folder per period |
| `Tickets/` | Tasks handed between agents and from the user |
| `Knowledge/` | The knowledge base wiki |
| `System/` | Agents, helpers, skills, connections, memory and settings |
| `System/Core/` | The framework itself. Never edit it. |

## The team

$team

## Rules for every agent

1. Never change files in `System/` without showing the user the exact change and getting a yes.
2. Never edit `System/Core/`, `.claude/`, `.codex/`, `.agents/`, `AGENTS.md` or `CLAUDE.md`. Bron regenerates them from `System/`.
3. Team members never run as subagents. To hand work to a team member, use a ticket. Subagents are only for helpers.
4. Keep the vault tidy: one-off work in `Projects/`, repeating work in `Routines/`. Machine data lives in `.bron/`.
5. Ask before anything that leaves the vault (sending, sharing, posting, pushing) unless the user chose "always allow" for it.

## How Bron works

The framework manual is in `System/Core/Manual/`. Start with `System/Core/Manual/index.md`, and read the page you need before changing any setup.

Framework version $version.
```

`core/Manual/index.md`:

```markdown
# Bron manual

How the Bron framework works, one page per topic. Read the page you need before changing any setup.

| Page | What it covers |
|---|---|
| [models.md](models.md) | Choosing a model per agent and CLI, and the friendly names Bron understands |
| [permissions.md](permissions.md) | `ask_before`, `always_allow`, action groups, and how approvals work in both CLIs |

## The basics

- **Your files:** everything in `System/` except `System/Core/`. Agents live in `System/Agents/<Name>/Agent.md`.
- **Framework files:** `System/Core/`. Replaced on update; never edit.
- **Generated files:** `AGENTS.md`, `CLAUDE.md`, `.mcp.json`, `.claude/`, `.codex/`, `.agents/`. Rebuilt by `.bron/bin/bron sync` from `System/`, automatically at the start of each session.
- **Health check:** `.bron/bin/bron check`.
```

- [ ] **Step 2: Write the failing tests**

`tests/test_prompts.py`:

```python
import shlex

from bron import frontmatter as fm
from bron.agents_md import render_agents_md
from bron.hookconfig import hooks_block
from bron.loader import load
from bron.prompts import agent_prompt, helper_prompt
from bron.skills import skill_files
from vaultkit import add_agent, set_meta, write_md


def test_agents_md_lists_team_rules_and_manual(vault):
    add_agent(vault, "CFO", role="Chief Financial Officer")
    text = render_agents_md(load(vault))
    assert "| CFO | Chief Financial Officer | Bron | `@cfo` |" in text
    assert "| Bron | Chief of Staff | you | `@bron` |" in text
    assert "System/Core/Manual/index.md" in text
    assert "Team members never run as subagents" in text
    assert "Framework version 0.1.0." in text
    assert "work with the user" in text
    assert len(text.encode()) < 8 * 1024


def test_agents_md_uses_the_users_name(vault):
    set_meta(vault.settings_file, user_name="Alex")
    assert "work with Alex" in render_agents_md(load(vault))


def test_bron_prompt(vault):
    cfg = load(vault)
    prompt = agent_prompt(cfg.agents["bron"], cfg)
    assert prompt.startswith("# You are Bron\n")
    assert "You report to the user." in prompt
    assert "You work on your own" in prompt
    assert "reader, researcher, reviewer" in prompt
    assert "# Boundaries" in prompt


def test_team_member_prompt(vault):
    add_agent(vault, "CFO", can_assign_to=["Bron"])
    cfg = load(vault)
    prompt = agent_prompt(cfg.agents["cfo"], cfg)
    assert "You report to Bron." in prompt
    assert "You can hand work to Bron through tickets." in prompt
    assert "Instructions for CFO." in prompt


def test_helper_prompt_is_read_only(vault):
    cfg = load(vault)
    prompt = helper_prompt(cfg.helpers["reader"])
    assert prompt.startswith("# You are the reader helper\n")
    assert "never create, change or delete files" in prompt


def test_skill_files_copy_folders_and_rename_agent_skills(vault):
    folder = vault.agents_dir / "Bron" / "Skills" / "brief"
    write_md(folder / "SKILL.md", {"name": "brief", "description": "Daily brief"}, "Steps\n")
    (folder / "notes.txt").write_text("n\n")
    (folder / ".DS_Store").write_text("junk")
    files = skill_files(load(vault), ".claude/skills")
    assert ".claude/skills/check/SKILL.md" in files
    doc = fm.parse(files[".claude/skills/bron-brief/SKILL.md"].decode())
    assert doc.meta == {"name": "bron-brief", "description": "(For Bron only) Daily brief"}
    assert doc.body == "Steps\n"
    assert files[".claude/skills/bron-brief/notes.txt"] == b"n\n"
    assert not any(".DS_Store" in key for key in files)


def test_trigger_commands_are_fixed_and_survive_spaces_and_accents(vault):
    block = hooks_block(vault, "codex")
    assert set(block) == {"SessionStart", "UserPromptSubmit", "PreCompact", "Stop", "SessionEnd"}
    command = block["SessionStart"][0]["hooks"][0]["command"]
    assert command == f"{shlex.quote(str(vault.bron_command))} hook session-start --cli codex"
    assert shlex.split(command)[0] == str(vault.bron_command)
    assert block["SessionEnd"][0]["hooks"][0]["timeout"] <= 3
    assert hooks_block(vault, "codex") == block
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_prompts.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.agents_md'`.

- [ ] **Step 4: Implement the four modules**

`core/Engine/bron/prompts.py`:

```python
"""The instructions each agent and helper actually receives, built from its file."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .model import Agent, Helper, slug

if TYPE_CHECKING:
    from .loader import Config


def agent_prompt(agent: Agent, cfg: "Config") -> str:
    boss_key = slug(agent.reports_to)
    if boss_key in ("", "you"):
        boss = "the user"
    elif boss_key in cfg.agents:
        boss = cfg.agents[boss_key].name
    else:
        boss = agent.reports_to
    lines = [f"# You are {agent.name}", "", f"Role: {agent.role}. You report to {boss}."]
    if agent.can_assign_to:
        lines.append("You can hand work to " + ", ".join(agent.can_assign_to) + " through tickets.")
    else:
        lines.append("You work on your own: you don't hand work to other team members.")
    if agent.helpers:
        lines.append("Helpers you can run as subagents: " + ", ".join(agent.helpers) + ".")
    if agent.instructions:
        lines += ["", agent.instructions]
    return "\n".join(lines).rstrip() + "\n"


def helper_prompt(helper: Helper) -> str:
    lines = [
        f"# You are the {helper.name} helper",
        "",
        "Do the task you were given, then report back clearly. You have no memory of earlier work and you never hand work to anyone else.",
    ]
    if helper.read_only:
        lines.append("You only read and report: never create, change or delete files.")
    if helper.instructions:
        lines += ["", helper.instructions]
    return "\n".join(lines).rstrip() + "\n"
```

`core/Engine/bron/agents_md.py`:

```python
"""AGENTS.md: the shared rules every session loads (CLAUDE.md only imports it)."""
from __future__ import annotations

from string import Template

from .loader import Config
from .model import slug


def render_agents_md(cfg: Config) -> str:
    template = Template((cfg.vault.core_templates / "AGENTS.md.tmpl").read_text(encoding="utf-8"))
    rows = ["| Agent | Role | Reports to | Tag |", "|---|---|---|---|"]
    for key, agent in sorted(cfg.agents.items()):
        boss = "you" if slug(agent.reports_to) == "you" else agent.reports_to
        rows.append(f"| {agent.name} | {agent.role} | {boss} | `@{key}` |")
    return template.substitute(
        user=cfg.settings.user_name or "the user",
        team="\n".join(rows),
        version=cfg.vault.version(),
    )
```

`core/Engine/bron/skills.py`:

```python
"""Publishing skills. Each CLI reads skills from its own folder, so Bron copies them there."""
from __future__ import annotations

from . import frontmatter as fm
from .loader import Config


def skill_files(cfg: Config, dest: str) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for name, skill in sorted(cfg.skills.items()):
        for path in sorted(skill.folder.rglob("*")):
            rel = path.relative_to(skill.folder)
            if path.is_dir() or any(part.startswith(".") for part in rel.parts):
                continue
            data = path.read_bytes()
            if skill.rewrite and rel.as_posix() == "SKILL.md":
                doc = fm.parse(data.decode("utf-8"))
                doc.meta["name"] = skill.name
                doc.meta["description"] = skill.description
                data = fm.dump(doc).encode("utf-8")
            out[f"{dest}/{name}/{rel.as_posix()}"] = data
    return out
```

`core/Engine/bron/hookconfig.py`:

```python
"""The fixed trigger configuration both CLIs get.

It only changes if the vault folder moves, so Codex's one-time trigger approval stays valid.
"""
from __future__ import annotations

import shlex

from .vault import Vault

# (CLI event name, Bron event name, timeout in seconds)
EVENTS = (
    ("SessionStart", "session-start", 30),
    ("UserPromptSubmit", "user-prompt", 10),
    ("PreCompact", "pre-compact", 10),
    ("Stop", "stop", 10),
    ("SessionEnd", "session-end", 2),
)
HOOK_NAMES = tuple(name for _, name, _ in EVENTS)


def hooks_block(vault: Vault, cli: str) -> dict:
    command = shlex.quote(str(vault.bron_command))
    return {
        event: [{"hooks": [{"type": "command", "command": f"{command} hook {name} --cli {cli}", "timeout": timeout}]}]
        for event, name, timeout in EVENTS
    }
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add core/Engine/bron/prompts.py core/Engine/bron/agents_md.py core/Engine/bron/skills.py core/Engine/bron/hookconfig.py core/Templates core/Manual/index.md tests/test_prompts.py
git commit -F - <<'EOF'
feat(core): agent prompts, AGENTS.md, skill publishing, trigger block

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 7: Claude Code generator

**Files:**
- Create: `core/Engine/bron/gen_claude.py`
- Test: `tests/test_gen_claude.py`

**Interfaces:**
- Consumes: `Config` (Task 3); `Actions` (Task 3); `agent_prompt`, `helper_prompt`, `skill_files`, `hooks_block` (Task 6); `bron.frontmatter` (Task 2).
- Produces: `bron.gen_claude`:
  - `generate(cfg: Config) -> dict[str, bytes]`, with keys `CLAUDE.md`, `.claude/settings.json`, `.mcp.json` (only when connections exist), `.claude/agents/<key>.md` for every agent and helper, and `.claude/skills/...`.
  - `rules(actions: Actions) -> list[str]` (Claude permission rule strings).
  - Requires `cfg.default_agent` to be set; sync only calls it after the health check passes.

- [ ] **Step 1: Write the failing tests**

`tests/test_gen_claude.py`:

```python
import json

from bron import frontmatter as fm
from bron.gen_claude import generate
from bron.loader import load
from vaultkit import add_agent, add_connection, set_meta


def settings(vault):
    return json.loads(generate(load(vault))[".claude/settings.json"])


def test_claude_md_only_imports_agents_md(vault):
    assert generate(load(vault))["CLAUDE.md"] == b"@AGENTS.md\n"


def test_settings_set_default_agent_memory_off_and_triggers(vault):
    s = settings(vault)
    assert s["agent"] == "bron"
    assert s["autoMemoryEnabled"] is False
    assert s["hooks"]["SessionStart"][0]["hooks"][0]["command"].endswith("hook session-start --cli claude")
    assert "Bash(git push)" in s["permissions"]["ask"]
    assert "Bash(git push *)" in s["permissions"]["ask"]
    assert "Bash(rm *)" in s["permissions"]["ask"]
    assert s["permissions"]["allow"] == []


def test_always_allow_moves_a_rule_from_ask_to_allow(vault):
    set_meta(vault.agents_dir / "Bron" / "Agent.md", always_allow=["git-push"])
    s = settings(vault)
    assert "Bash(git push *)" not in s["permissions"]["ask"]
    assert "Bash(git push *)" in s["permissions"]["allow"]


def test_mcp_tool_rules(vault):
    add_connection(vault, "Gmail")
    set_meta(vault.agents_dir / "Bron" / "Agent.md", connections=["Gmail"], ask_before=["send-email"])
    assert "mcp__gmail__send_message" in settings(vault)["permissions"]["ask"]


def test_team_member_file(vault):
    add_connection(vault, "Carta")
    add_connection(vault, "Gmail")
    add_agent(vault, "CFO", connections=["Carta"], models={"claude": "Opus 5.5"})
    doc = fm.parse(generate(load(vault))[".claude/agents/cfo.md"].decode())
    assert doc.meta["name"] == "cfo"
    assert doc.meta["model"] == "claude-opus-5-5"
    blocked = [x.strip() for x in doc.meta["disallowedTools"].split(",")]
    assert "mcp__gmail" in blocked and "mcp__carta" not in blocked
    assert "Agent(bron)" in blocked and "Agent(cfo)" in blocked
    assert "never as a subagent" in doc.meta["description"]
    assert doc.body.lstrip().startswith("# You are CFO")


def test_default_model_is_left_out(vault):
    doc = fm.parse(generate(load(vault))[".claude/agents/bron.md"].decode())
    assert "model" not in doc.meta


def test_helpers_cannot_nest_or_write(vault):
    doc = fm.parse(generate(load(vault))[".claude/agents/reader.md"].decode())
    blocked = [x.strip() for x in doc.meta["disallowedTools"].split(",")]
    assert {"Agent", "Write", "Edit", "NotebookEdit"} <= set(blocked)
    assert doc.meta["description"].startswith("Reads the files")


def test_mcp_json_only_when_connections_exist(vault):
    assert ".mcp.json" not in generate(load(vault))
    add_connection(vault, "Carta", env={"CARTA_TOKEN": "${CARTA_TOKEN}"})
    add_connection(vault, "Docs", type="mcp-http", url="https://docs.example/mcp", command="")
    files = generate(load(vault))
    servers = json.loads(files[".mcp.json"])["mcpServers"]
    assert servers["carta"] == {"type": "stdio", "command": "uvx", "args": ["mcp-server-time"], "env": {"CARTA_TOKEN": "${CARTA_TOKEN}"}}
    assert servers["docs"] == {"type": "http", "url": "https://docs.example/mcp"}
    assert json.loads(files[".claude/settings.json"])["enabledMcpjsonServers"] == ["carta", "docs"]


def test_skills_are_published(vault):
    assert ".claude/skills/check/SKILL.md" in generate(load(vault))
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_gen_claude.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.gen_claude'`.

- [ ] **Step 3: Implement `gen_claude.py`**

`core/Engine/bron/gen_claude.py`:

```python
"""Claude Code's view of the vault: CLAUDE.md, .claude/ and .mcp.json."""
from __future__ import annotations

import json

from . import frontmatter as fm
from .catalog import Actions
from .hookconfig import hooks_block
from .loader import Config
from .model import Agent, Connection, Helper, conn_key
from .prompts import agent_prompt, helper_prompt
from .skills import skill_files


def generate(cfg: Config) -> dict[str, bytes]:
    files = {
        "CLAUDE.md": b"@AGENTS.md\n",
        ".claude/settings.json": _json(_settings(cfg)),
    }
    if cfg.connections:
        files[".mcp.json"] = _json({"mcpServers": {key: _server(c) for key, c in sorted(cfg.connections.items())}})
    team = sorted(cfg.agents)
    for key, agent in sorted(cfg.agents.items()):
        files[f".claude/agents/{key}.md"] = _agent_file(cfg, agent, team)
    for key, helper in sorted(cfg.helpers.items()):
        files[f".claude/agents/{key}.md"] = _helper_file(cfg, helper)
    files.update(skill_files(cfg, ".claude/skills"))
    return files


def rules(actions: Actions) -> list[str]:
    out = [f"mcp__{conn}__{tool}" for conn, tools in sorted(actions.mcp.items()) for tool in sorted(tools)]
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
        "permissions": {"ask": rules(ask), "allow": rules(allow)},
        "enabledMcpjsonServers": sorted(cfg.connections),
        "hooks": hooks_block(cfg.vault, "claude"),
    }


def _server(conn: Connection) -> dict:
    if conn.type == "mcp-http":
        return {"type": "http", "url": conn.url}
    server: dict = {"type": "stdio", "command": conn.command, "args": list(conn.args)}
    if conn.env:
        server["env"] = dict(conn.env)
    return server


def _blocked_servers(cfg: Config, allowed: list[str]) -> list[str]:
    keep = {conn_key(c) for c in allowed}
    return [f"mcp__{key}" for key in sorted(cfg.connections) if key not in keep]


def _agent_file(cfg: Config, agent: Agent, team: list[str]) -> bytes:
    meta: dict = {
        "name": agent.key,
        "description": f"{agent.role}. Bron team member: reach them through a ticket, never as a subagent.",
    }
    model = cfg.catalog.resolve_model("claude", agent.models.get("claude"))
    if model:
        meta["model"] = model
    blocked = _blocked_servers(cfg, agent.connections) + [f"Agent({key})" for key in team]
    meta["disallowedTools"] = ", ".join(blocked)
    return fm.dump(fm.Document(meta, "\n" + agent_prompt(agent, cfg))).encode("utf-8")


def _helper_file(cfg: Config, helper: Helper) -> bytes:
    meta: dict = {"name": helper.key, "description": helper.description}
    model = cfg.catalog.resolve_model("claude", helper.models.get("claude"))
    if model:
        meta["model"] = model
    blocked = _blocked_servers(cfg, helper.connections) + ["Agent"]
    if helper.read_only:
        blocked += ["Write", "Edit", "NotebookEdit"]
    meta["disallowedTools"] = ", ".join(blocked)
    return fm.dump(fm.Document(meta, "\n" + helper_prompt(helper))).encode("utf-8")


def _json(data: dict) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/gen_claude.py tests/test_gen_claude.py
git commit -F - <<'EOF'
feat(core): generate the Claude Code setup from System/

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 8: Codex generator

**Files:**
- Create: `core/Engine/bron/gen_codex.py`
- Test: `tests/test_gen_codex.py`

**Interfaces:**
- Consumes: `Config` (Task 3); `Actions` (Task 3); `agent_prompt`, `helper_prompt`, `skill_files`, `hooks_block` (Task 6).
- Produces: `bron.gen_codex`:
  - `generate(cfg: Config) -> dict[str, bytes]`, with keys `.codex/config.toml`, `.codex/hooks.json`, `.codex/rules/bron.rules` (only when shell rules exist), `.codex/agents/<helper>.toml` (helpers only, never team members), and `.agents/skills/...`.
  - `HEADER`: the comment line at the top of every generated TOML and rules file.
  - Shared `AGENTS.md` comes from `agents_md.py` (Task 6), not from here.

- [ ] **Step 1: Write the failing tests**

`tests/test_gen_codex.py`:

```python
import json
import tomllib

from bron.gen_codex import generate
from bron.loader import load
from bron.prompts import agent_prompt
from vaultkit import add_agent, add_connection, set_meta

BRON = ("System", "Agents", "Bron", "Agent.md")


def config(vault):
    raw = generate(load(vault))[".codex/config.toml"].decode()
    assert raw.startswith("# Generated by Bron")
    return tomllib.loads(raw)


def test_config_carries_bron_instructions_and_memory_off(vault):
    cfg = config(vault)
    assert cfg["developer_instructions"].startswith("# You are Bron\n")
    assert "model" not in cfg
    assert cfg["features"]["memories"] is False
    assert "mcp_servers" not in cfg


def test_pinned_codex_model(vault):
    set_meta(vault.root.joinpath(*BRON), models={"claude": "default", "codex": "gpt-6.1-sol"})
    assert config(vault)["model"] == "gpt-6.1-sol"


def test_servers_are_disabled_unless_allowed_and_tools_get_approvals(vault):
    add_connection(vault, "Gmail")
    add_connection(vault, "Carta", env={"CARTA_TOKEN": "${CARTA_TOKEN}", "REGION": "us"})
    set_meta(vault.root.joinpath(*BRON), connections=["Gmail"], ask_before=["send-email"], always_allow=["mcp:gmail:reply_to_message"])
    servers = config(vault)["mcp_servers"]
    gmail = servers["gmail"]
    assert "enabled" not in gmail
    assert gmail["command"] == "uvx" and gmail["args"] == ["mcp-server-time"]
    assert gmail["tools"]["send_message"]["approval_mode"] == "prompt"
    assert gmail["tools"]["reply_to_message"]["approval_mode"] == "approve"
    carta = servers["carta"]
    assert carta["enabled"] is False
    assert carta["env"] == {"REGION": "us"}
    assert carta["env_vars"] == ["CARTA_TOKEN"]


def test_http_server(vault):
    add_connection(vault, "Docs", type="mcp-http", url="https://docs.example/mcp", command="")
    set_meta(vault.root.joinpath(*BRON), connections=["Docs"])
    assert config(vault)["mcp_servers"]["docs"] == {"url": "https://docs.example/mcp"}


def test_shell_rules_file(vault):
    rules = generate(load(vault))[".codex/rules/bron.rules"].decode()
    assert rules.startswith("# Generated by Bron")
    assert 'prefix_rule(pattern=["git", "push"], decision="prompt")' in rules
    assert 'prefix_rule(pattern=["rm"], decision="prompt")' in rules


def test_no_rules_file_without_shell_rules(vault):
    set_meta(vault.root.joinpath(*BRON), ask_before=[])
    assert ".codex/rules/bron.rules" not in generate(load(vault))


def test_hooks_json_has_the_fixed_triggers(vault):
    hooks = json.loads(generate(load(vault))[".codex/hooks.json"])["hooks"]
    assert hooks["SessionStart"][0]["hooks"][0]["command"].endswith("hook session-start --cli codex")
    assert hooks["SessionEnd"][0]["hooks"][0]["timeout"] <= 3


def test_helpers_become_codex_agents_but_team_members_do_not(vault):
    add_agent(vault, "CFO")
    add_connection(vault, "Carta")
    files = generate(load(vault))
    assert ".codex/agents/reader.toml" in files
    assert ".codex/agents/cfo.toml" not in files and ".codex/agents/bron.toml" not in files
    reader = tomllib.loads(files[".codex/agents/reader.toml"].decode())
    assert reader["name"] == "reader"
    assert reader["sandbox_mode"] == "read-only"
    assert reader["developer_instructions"].startswith("# You are the reader helper")
    assert reader["mcp_servers"] == {"carta": {"enabled": False}}


def test_skills_go_to_the_agents_folder(vault):
    assert ".agents/skills/check/SKILL.md" in generate(load(vault))


def test_tricky_instructions_survive_toml(vault):
    path = vault.root.joinpath(*BRON)
    path.write_text(path.read_text() + '\nQuote: """triple""" and \\backslash and "quotes" and ção.\n', encoding="utf-8")
    loaded = load(vault)
    assert config(vault)["developer_instructions"] == agent_prompt(loaded.agents["bron"], loaded)
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_gen_codex.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.gen_codex'`.

- [ ] **Step 3: Implement `gen_codex.py`**

`core/Engine/bron/gen_codex.py`:

```python
"""Codex's view of the vault: .codex/ and .agents/skills/ (AGENTS.md is shared, see agents_md.py).

Team members are deliberately not written as .codex/agents files, so Codex can't spawn them as
subagents; the runner and launcher start them with flags instead.
"""
from __future__ import annotations

import json

import tomli_w

from .catalog import Actions
from .hookconfig import hooks_block
from .loader import Config
from .model import Helper, conn_key
from .prompts import agent_prompt, helper_prompt
from .skills import skill_files

HEADER = "# Generated by Bron from System/. Do not edit: change System/ or ask Bron.\n"


def generate(cfg: Config) -> dict[str, bytes]:
    agent = cfg.default_agent
    ask, allow = cfg.catalog.permissions_for(agent)
    files = {
        ".codex/config.toml": _toml(_config(cfg, ask, allow)),
        ".codex/hooks.json": (json.dumps({"hooks": hooks_block(cfg.vault, "codex")}, indent=2) + "\n").encode("utf-8"),
    }
    rules = _rules(ask, allow)
    if rules:
        files[".codex/rules/bron.rules"] = rules.encode("utf-8")
    for key, helper in sorted(cfg.helpers.items()):
        files[f".codex/agents/{key}.toml"] = _toml(_helper(cfg, helper))
    files.update(skill_files(cfg, ".agents/skills"))
    return files


def _config(cfg: Config, ask: Actions, allow: Actions) -> dict:
    agent = cfg.default_agent
    doc: dict = {}
    model = cfg.catalog.resolve_model("codex", agent.models.get("codex"))
    if model:
        doc["model"] = model
    doc["developer_instructions"] = agent_prompt(agent, cfg)
    doc["features"] = {"memories": False}
    servers = _servers(cfg, agent.connections, ask, allow)
    if servers:
        doc["mcp_servers"] = servers
    return doc


def _servers(cfg: Config, allowed: list[str], ask: Actions, allow: Actions) -> dict:
    keep = {conn_key(c) for c in allowed}
    out: dict = {}
    for key, conn in sorted(cfg.connections.items()):
        if conn.type == "mcp-http":
            server: dict = {"url": conn.url}
        else:
            server = {"command": conn.command, "args": list(conn.args)}
        literal = {k: v for k, v in conn.env.items() if v != f"${{{k}}}"}
        passthrough = sorted(k for k, v in conn.env.items() if v == f"${{{k}}}")
        if literal:
            server["env"] = literal
        if passthrough:
            server["env_vars"] = passthrough
        if key not in keep:
            server["enabled"] = False
        tools = {tool: {"approval_mode": "prompt"} for tool in sorted(ask.mcp.get(key, ()))}
        tools.update({tool: {"approval_mode": "approve"} for tool in sorted(allow.mcp.get(key, ()))})
        if tools:
            server["tools"] = tools
        out[key] = server
    return out


def _rules(ask: Actions, allow: Actions) -> str:
    lines = [f'prefix_rule(pattern={json.dumps(list(words), ensure_ascii=False)}, decision="prompt")' for words in ask.shell]
    lines += [f'prefix_rule(pattern={json.dumps(list(words), ensure_ascii=False)}, decision="allow")' for words in allow.shell]
    return HEADER + "\n".join(lines) + "\n" if lines else ""


def _helper(cfg: Config, helper: Helper) -> dict:
    doc: dict = {"name": helper.key, "description": helper.description, "developer_instructions": helper_prompt(helper)}
    model = cfg.catalog.resolve_model("codex", helper.models.get("codex"))
    if model:
        doc["model"] = model
    if helper.read_only:
        doc["sandbox_mode"] = "read-only"
    keep = {conn_key(c) for c in helper.connections}
    off = {key: {"enabled": False} for key in sorted(cfg.connections) if key not in keep}
    if off:
        doc["mcp_servers"] = off
    return doc


def _toml(doc: dict) -> bytes:
    return (HEADER + tomli_w.dumps(doc, multiline_strings=True)).encode("utf-8")
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add core/Engine/bron/gen_codex.py tests/test_gen_codex.py
git commit -F - <<'EOF'
feat(core): generate the Codex setup from System/

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 9: Sync and the `bron` command

**Files:**
- Create: `core/Engine/bron/sync.py`, `core/Engine/bron/cli.py`
- Test: `tests/test_sync.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes:
  - `load`, `Config` (Task 3); `run_checks`, `has_errors` (Task 4).
  - `GeneratedWriter`, `WriteReport` (Task 5); `render_agents_md`, `HOOK_NAMES` (Task 6).
  - `gen_claude.generate` (Task 7); `gen_codex.generate` (Task 8).
- Produces:
  - `bron.sync`:
    - `fingerprint(vault) -> str`
    - `plan_files(cfg) -> dict[str, bytes]`
    - `output_issues(files) -> list[Issue]`
    - `drift_issues(vault) -> list[Issue]`
    - `SyncResult(ok: bool, issues: list[Issue], report: WriteReport | None)`
    - `run_sync(vault, *, dry_run=False) -> SyncResult`
    - `needs_sync(vault) -> bool`
  - `bron.cli.main(argv: list[str] | None = None) -> int`, with subcommands `sync [--dry-run]`, `check`, `hook <event> --cli <cli>` and `version`.
  - Exit codes: 0 means OK, 1 means there are problems, 2 means no vault was found.

- [ ] **Step 1: Write the failing tests**

`tests/test_sync.py`:

```python
import shutil

from bron.sync import needs_sync, run_sync
from vaultkit import add_agent

EXPECTED = (
    "AGENTS.md",
    "CLAUDE.md",
    ".claude/settings.json",
    ".claude/agents/bron.md",
    ".claude/agents/reader.md",
    ".claude/skills/check/SKILL.md",
    ".codex/config.toml",
    ".codex/hooks.json",
    ".codex/rules/bron.rules",
    ".codex/agents/reader.toml",
    ".agents/skills/check/SKILL.md",
)


def snapshot(vault):
    return {p: p.read_bytes() for p in vault.root.rglob("*") if p.is_file() and ".bron" not in p.parts}


def test_sync_writes_both_setups_and_is_idempotent(vault):
    first = run_sync(vault)
    assert first.ok, first.issues
    for rel in EXPECTED:
        assert (vault.root / rel).is_file(), rel
    before = snapshot(vault)
    second = run_sync(vault)
    assert second.ok and second.report.written == [] and second.report.deleted == []
    assert snapshot(vault) == before


def test_visible_top_level_after_sync(vault):
    run_sync(vault)
    visible = sorted(p.name for p in vault.root.iterdir() if not p.name.startswith("."))
    assert visible == ["AGENTS.md", "CLAUDE.md", "Knowledge", "Projects", "Routines", "System", "Tickets"]


def test_needs_sync_follows_setup_changes_only(vault):
    assert needs_sync(vault)
    run_sync(vault)
    assert not needs_sync(vault)
    (vault.agents_dir / "Bron" / "Memory" / "2026-10-01.md").write_text("today\n")
    (vault.memory_dir / "Summary.md").write_text("summary\n")
    (vault.projects_dir / "Audit").mkdir()
    assert not needs_sync(vault)
    add_agent(vault, "CFO")
    assert needs_sync(vault)


def test_hand_edit_triggers_a_resync_with_backup(vault):
    run_sync(vault)
    (vault.root / ".claude/settings.json").write_text("{}\n")
    assert needs_sync(vault)
    result = run_sync(vault)
    assert result.report.backed_up == [".claude/settings.json"]


def test_errors_keep_the_last_good_setup(vault):
    run_sync(vault)
    before = (vault.root / ".claude/settings.json").read_bytes()
    add_agent(vault, "CFO", reports_to="Nobody")
    result = run_sync(vault)
    assert not result.ok
    assert any(i.code == "agent.reports-to-unknown" for i in result.issues)
    assert (vault.root / ".claude/settings.json").read_bytes() == before
    assert not (vault.root / ".claude/agents/cfo.md").exists()


def test_removed_agent_files_are_cleaned_up(vault):
    add_agent(vault, "CFO")
    run_sync(vault)
    assert (vault.root / ".claude/agents/cfo.md").is_file()
    shutil.rmtree(vault.agents_dir / "CFO")
    run_sync(vault)
    assert not (vault.root / ".claude/agents/cfo.md").exists()


def test_other_tools_files_survive_sync(vault):
    termy = vault.root / ".agents/skills/termy-obsidian-context/SKILL.md"
    termy.parent.mkdir(parents=True)
    termy.write_text("termy\n")
    local = vault.root / ".claude/settings.local.json"
    local.parent.mkdir(parents=True)
    local.write_text("{}\n")
    run_sync(vault)
    run_sync(vault)
    assert termy.read_text() == "termy\n"
    assert local.read_text() == "{}\n"


def test_oversized_agents_md_stops_sync(vault):
    for i in range(200):
        add_agent(vault, f"Agent{i:03d}", role="r" * 200)
    result = run_sync(vault)
    assert not result.ok
    assert any(i.code == "agents-md.too-large" for i in result.issues)


def test_dry_run_writes_nothing(vault):
    result = run_sync(vault, dry_run=True)
    assert result.ok and result.report is None
    assert not (vault.root / "AGENTS.md").exists()
```

`tests/test_cli.py`:

```python
import pytest

from bron.cli import main
from vaultkit import add_agent


@pytest.fixture
def run(vault, monkeypatch, capsys):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    monkeypatch.setattr("bron.check.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("bron.check.codex_trusts", lambda root: True)

    def _run(*args):
        code = main(list(args))
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


def test_sync_then_check(run):
    code, out, _ = run("sync")
    assert code == 0 and "Synced:" in out
    code, out, _ = run("check")
    assert code == 0 and "all good" in out


def test_check_explains_problems_with_the_file(run, vault):
    add_agent(vault, "CFO", reports_to="Nobody")
    code, out, _ = run("check")
    assert code == 1
    assert "problem" in out
    assert "reports to 'Nobody'" in out
    assert "System/Agents/CFO/Agent.md" in out


def test_check_warns_about_drift(run, vault):
    run("sync")
    (vault.root / "AGENTS.md").write_text("edited\n")
    code, out, _ = run("check")
    assert code == 0 and "changed or removed by hand" in out


def test_failed_sync_says_the_old_setup_is_kept(run, vault):
    add_agent(vault, "CFO", reports_to="Nobody")
    code, out, _ = run("sync")
    assert code == 1 and "last working setup is still in place" in out


def test_dry_run(run, vault):
    code, out, _ = run("sync", "--dry-run")
    assert code == 0 and "Dry run" in out
    assert not (vault.root / "AGENTS.md").exists()


def test_version(run):
    assert run("version")[:2] == (0, "0.1.0\n")


def test_outside_a_vault(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("BRON_VAULT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["check"]) == 2
    assert "No Bron vault" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_sync.py tests/test_cli.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.sync'`.

- [ ] **Step 3: Implement `sync.py`**

`core/Engine/bron/sync.py`:

```python
"""Sync: turn System/ into each CLI's own setup, safely and only when something changed."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from . import gen_claude, gen_codex
from .agents_md import render_agents_md
from .check import has_errors, run_checks
from .loader import Config, load
from .model import Issue
from .vault import MARKER, Vault
from .writer import GeneratedWriter, WriteReport

AGENTS_MD_MAX = 32 * 1024
AGENTS_MD_TARGET = 8 * 1024


def fingerprint(vault: Vault) -> str:
    """Cheap signature of every source file sync reads (size + modification time), excluding memory."""
    digest = hashlib.sha256(str(vault.root).encode("utf-8"))
    paths = [vault.settings_file, vault.root / MARKER]
    for folder in (
        vault.agents_dir,
        vault.helpers_dir,
        vault.skills_dir,
        vault.connections_dir,
        vault.core_manual,
        vault.core_skills,
        vault.core_helpers,
        vault.core_templates,
    ):
        if folder.is_dir():
            paths += [p for p in folder.rglob("*") if p.is_file()]
    for path in sorted(paths):
        rel = path.relative_to(vault.root)
        if rel.parts[:2] == ("System", "Agents") and len(rel.parts) > 3 and rel.parts[3] == "Memory":
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        digest.update(f"{rel.as_posix()}\0{st.st_size}\0{st.st_mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()


def plan_files(cfg: Config) -> dict[str, bytes]:
    files = {"AGENTS.md": render_agents_md(cfg).encode("utf-8")}
    files.update(gen_claude.generate(cfg))
    files.update(gen_codex.generate(cfg))
    return files


def output_issues(files: dict[str, bytes]) -> list[Issue]:
    size = len(files["AGENTS.md"])
    if size > AGENTS_MD_MAX:
        return [Issue("error", "agents-md.too-large", f"AGENTS.md would be {size // 1024} KB, but Codex reads at most 32 KB. Shorten agent roles or move detail into the manual.")]
    if size > AGENTS_MD_TARGET:
        return [Issue("warning", "agents-md.large", f"AGENTS.md is {size // 1024} KB; keeping it under 8 KB keeps every session fast.")]
    return []


def drift_issues(vault: Vault) -> list[Issue]:
    drift = GeneratedWriter(vault).drift()
    if not drift:
        return []
    shown = ", ".join(drift[:5]) + (f" and {len(drift) - 5} more" if len(drift) > 5 else "")
    return [Issue("warning", "generated.drift", f"Generated files were changed or removed by hand: {shown}. The next sync restores them and keeps a backup of any edits.")]


@dataclass
class SyncResult:
    ok: bool
    issues: list[Issue] = field(default_factory=list)
    report: WriteReport | None = None


def run_sync(vault: Vault, *, dry_run: bool = False) -> SyncResult:
    cfg = load(vault)
    issues = run_checks(cfg, include_environment=False)
    if has_errors(issues):
        return SyncResult(False, issues)
    try:
        files = plan_files(cfg)
    except (OSError, KeyError, ValueError) as exc:
        return SyncResult(False, issues + [Issue("error", "sync.failed", f"Bron couldn't build the CLI setup ({exc.__class__.__name__}: {exc})")])
    issues += output_issues(files)
    if has_errors(issues) or dry_run:
        return SyncResult(not has_errors(issues), issues)
    report = GeneratedWriter(vault).apply(files, fingerprint(vault))
    return SyncResult(True, issues, report)


def needs_sync(vault: Vault) -> bool:
    writer = GeneratedWriter(vault)
    return writer.manifest.get("fingerprint") != fingerprint(vault) or bool(writer.drift())
```

- [ ] **Step 4: Implement `cli.py`**

`core/Engine/bron/cli.py`:

```python
"""The `bron` command."""
from __future__ import annotations

import argparse
import sys

from .hookconfig import HOOK_NAMES
from .model import CLIS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bron", description="Bron keeps your agents' setup in sync across Claude Code and Codex.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_sync = sub.add_parser("sync", help="regenerate the Claude Code and Codex setup from System/")
    p_sync.add_argument("--dry-run", action="store_true", help="check and report, without writing anything")
    sub.add_parser("check", help="run the health check")
    p_hook = sub.add_parser("hook", help="entry point for the CLIs' automatic triggers")
    p_hook.add_argument("event", choices=HOOK_NAMES)
    p_hook.add_argument("--cli", choices=CLIS, required=True)
    sub.add_parser("version", help="show the framework version")
    args = parser.parse_args(argv)

    if args.command == "hook":
        from .hooks import main as hook_main

        return hook_main(args.event, args.cli)

    from .vault import Vault, VaultNotFound

    try:
        vault = Vault.find()
    except VaultNotFound as exc:
        print(f"bron: {exc}", file=sys.stderr)
        return 2
    if args.command == "version":
        print(vault.version())
        return 0
    if args.command == "check":
        return _check(vault)
    return _sync(vault, dry_run=args.dry_run)


def _print_issues(vault, issues) -> None:
    for issue in issues:
        print("  " + issue.render(vault.root))


def _check(vault) -> int:
    from .check import has_errors, run_checks
    from .loader import load
    from .model import Issue
    from .sync import drift_issues, output_issues, plan_files

    cfg = load(vault)
    issues = run_checks(cfg)
    if not has_errors(issues):
        try:
            issues += output_issues(plan_files(cfg))
        except (OSError, KeyError, ValueError) as exc:
            issues.append(Issue("error", "sync.failed", f"Bron couldn't build the CLI setup ({exc.__class__.__name__}: {exc})"))
    issues += drift_issues(vault)
    if not issues:
        print("Bron health check: all good.")
        return 0
    errors = sum(issue.level == "error" for issue in issues)
    print(f"Bron health check: {errors} problem(s), {len(issues) - errors} warning(s)")
    _print_issues(vault, issues)
    return 1 if errors else 0


def _sync(vault, *, dry_run: bool) -> int:
    from .sync import run_sync

    result = run_sync(vault, dry_run=dry_run)
    if not result.ok:
        print("Sync stopped. Fix these first; your last working setup is still in place:")
        _print_issues(vault, result.issues)
        return 1
    if dry_run:
        print("Dry run: the setup is valid and would be regenerated.")
    else:
        report = result.report
        print(f"Synced: {len(report.written)} file(s) written, {len(report.deleted)} removed.")
        if report.backup_dir:
            print(f"Hand-edited files were backed up to {report.backup_dir.relative_to(vault.root)}.")
    _print_issues(vault, result.issues)
    return 0
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS. (`test_cli.py` imports `bron.hooks` only for the `hook` command, which Task 10 adds; none of these tests call it.)

- [ ] **Step 6: Commit**

```bash
git add core/Engine/bron/sync.py core/Engine/bron/cli.py tests/test_sync.py tests/test_cli.py
git commit -F - <<'EOF'
feat(core): sync both CLI setups and add the bron command

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 10: Triggers and the session briefing

**Files:**
- Create: `core/Engine/bron/hooks.py`, `core/Engine/bron/briefing.py`
- Test: `tests/test_hooks.py`

**Interfaces:**
- Consumes: `Vault` (Task 2); `load`, `CLI_NAMES` (Task 3); `needs_sync`, `run_sync` (Task 9); `bron.frontmatter` (Task 2).
- Produces:
  - `bron.hooks`: `main(event: str, cli: str, stdin=None, stdout=None) -> int` always returns 0, and `QUICK = ("pre-compact", "stop", "session-end")`.
    - Marker records are appended to `.bron/state/markers.jsonl` as `{"time", "event", "cli", "agent", "session_id", "transcript_path"}`.
    - Errors are appended to `.bron/state/hook-errors.log`.
  - `bron.briefing`: `build_briefing(vault, *, cli: str, notes: list[str] | None = None) -> str`, which starts with `# Bron briefing` and is at most 6000 characters.
  - Plan 2 extends `user-prompt` (`@`-mentions) and the briefing (tickets, routines).

- [ ] **Step 1: Write the failing tests**

`tests/test_hooks.py`:

```python
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
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `uv run --project core/Engine pytest tests/test_hooks.py -q`
Expected: `ModuleNotFoundError: No module named 'bron.hooks'`.

- [ ] **Step 3: Implement `briefing.py`**

`core/Engine/bron/briefing.py`:

```python
"""The short briefing injected at the start of every session."""
from __future__ import annotations

import os

from . import frontmatter as fm
from .loader import load
from .model import CLI_NAMES
from .vault import Vault

MAX_CHARS = 6000
MEMORY_CHARS = 2500


def build_briefing(vault: Vault, *, cli: str, notes: list[str] | None = None) -> str:
    cfg = load(vault)
    agent = os.environ.get("BRON_AGENT") or cfg.settings.default_agent
    settings = cfg.settings
    lines = ["# Bron briefing", f"You are {agent}, working in {CLI_NAMES.get(cli, cli)} in the user's Bron vault."]
    if settings.user_name:
        lines.append(f"You're working with {settings.user_name}" + (f" at {settings.company}" if settings.company else "") + ".")
    else:
        lines.append("First-run setup isn't done yet (no name in System/Settings.md). Offer to run it before anything else.")
    if notes:
        lines += ["", *notes]
    summary = vault.memory_dir / "Summary.md"
    if summary.is_file():
        try:
            text = fm.read(summary).body.strip()
        except (fm.FrontmatterError, OSError, UnicodeDecodeError):
            text = ""
        if text:
            lines += ["", "## What you remember", _clip(text, MEMORY_CHARS)]
    return _clip("\n".join(lines).rstrip() + "\n", MAX_CHARS)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 2].rstrip() + "…\n"
```

- [ ] **Step 4: Implement `hooks.py`**

`core/Engine/bron/hooks.py`:

```python
"""Entry point for both CLIs' automatic triggers. A trigger must never break the user's session."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

QUICK = ("pre-compact", "stop", "session-end")


def main(event: str, cli: str, stdin=None, stdout=None) -> int:
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    try:
        payload = _payload(stdin)
        if event in QUICK:
            _marker(event, cli, payload)
        elif event == "session-start":
            stdout.write(_session_start(cli))
        # "user-prompt": @-mention routing arrives with tickets in Plan 2.
    except Exception as exc:  # noqa: BLE001 - a trigger must never fail the session
        _log_error(event, cli, exc)
        if event == "session-start":
            stdout.write(f"Bron: the startup check failed ({exc.__class__.__name__}). Ask Bron to run `.bron/bin/bron check`.\n")
    return 0


def _payload(stdin) -> dict:
    try:
        if hasattr(stdin, "isatty") and stdin.isatty():
            return {}
        raw = stdin.read()
    except (OSError, ValueError):
        return {}
    try:
        data = json.loads(raw) if raw and raw.strip() else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _state_dir() -> Path:
    from .vault import Vault

    path = Vault.find().state_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def _marker(event: str, cli: str, payload: dict) -> None:
    record = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": event,
        "cli": cli,
        "agent": os.environ.get("BRON_AGENT", ""),
        "session_id": str(payload.get("session_id", "")),
        "transcript_path": str(payload.get("transcript_path", "")),
    }
    with open(_state_dir() / "markers.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _session_start(cli: str) -> str:
    from .briefing import build_briefing
    from .sync import needs_sync, run_sync
    from .vault import Vault

    vault = Vault.find()
    notes: list[str] = []
    if needs_sync(vault):
        result = run_sync(vault)
        if not result.ok:
            notes.append("Bron couldn't apply recent setup changes; the previous setup is still active. Problems:")
            notes += ["- " + issue.render(vault.root) for issue in result.issues if issue.level == "error"]
        elif result.report and (result.report.written or result.report.deleted):
            notes.append("Bron applied recent setup changes. Some take effect from the next session.")
            if result.report.backup_dir:
                notes.append(f"A hand-edited generated file was replaced; the edited copy is in {result.report.backup_dir.relative_to(vault.root)}.")
    return build_briefing(vault, cli=cli, notes=notes)


def _log_error(event: str, cli: str, exc: Exception) -> None:
    try:
        with open(_state_dir() / "hook-errors.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {cli} {event} {exc.__class__.__name__}: {exc}\n")
    except Exception:  # noqa: BLE001
        pass
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add core/Engine/bron/hooks.py core/Engine/bron/briefing.py tests/test_hooks.py
git commit -F - <<'EOF'
feat(core): trigger entry point, session briefing and markers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 11: Dev vault and the live parity smoke test

**Files:**
- Create: `scripts/dev-vault.sh`, `tests/live/test_parity.py`, `README.md`

**Interfaces:**
- Consumes: the whole engine; `template/` and `core/`; the Task 1 findings (the Codex hook-trust flag and the trust path form).
- Produces:
  - `scripts/dev-vault.sh <path>`, which creates or refreshes a dev vault with `.bron/venv` and the `.bron/bin/bron` shim. The shim sets `BRON_VAULT` and runs `python -m bron`. Plan 4's installer reuses this logic.
  - Live tests that only run when `BRON_LIVE=1`.

- [ ] **Step 1: Write the dev vault script**

`scripts/dev-vault.sh`:

```bash
#!/usr/bin/env bash
# Create or refresh a development Bron vault from this repository.
# Usage: scripts/dev-vault.sh <vault-path>
# - Your files (template/) are only copied where missing; nothing of yours is overwritten.
# - System/Core is always replaced with the repository's core/.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:?usage: scripts/dev-vault.sh <vault-path>}"
mkdir -p "$TARGET"
VAULT="$(cd "$TARGET" && pwd)"

rsync -a --ignore-existing "$REPO/template/" "$VAULT/"
rm -rf "$VAULT/System/Core"
rsync -a --exclude '.venv' --exclude '__pycache__' --exclude '*.egg-info' --exclude '.pytest_cache' "$REPO/core/" "$VAULT/System/Core/"

uv venv --quiet --allow-existing --python 3.12 "$VAULT/.bron/venv"
uv pip install --quiet --python "$VAULT/.bron/venv/bin/python" --reinstall-package bron-engine "$VAULT/System/Core/Engine"

mkdir -p "$VAULT/.bron/bin"
cat > "$VAULT/.bron/bin/bron" <<'SHIM'
#!/bin/sh
VAULT="$(cd "$(dirname "$0")/../.." && pwd)"
export BRON_VAULT="$VAULT"
exec "$VAULT/.bron/venv/bin/python" -m bron "$@"
SHIM
chmod +x "$VAULT/.bron/bin/bron"

"$VAULT/.bron/bin/bron" sync
"$VAULT/.bron/bin/bron" check || true
echo "Dev vault ready: $VAULT"
```

Run: `chmod +x scripts/dev-vault.sh`

- [ ] **Step 2: Build a dev vault and check it by hand**

Run: `scripts/dev-vault.sh "$TMPDIR/Bron Dev Vault" && ls -a "$TMPDIR/Bron Dev Vault" && echo '{}' | "$TMPDIR/Bron Dev Vault/.bron/bin/bron" hook session-start --cli claude`

Expected:
- `Synced: … file(s) written`.
- A health check that shows at most the warning `codex.untrusted`.
- The listing shows `AGENTS.md CLAUDE.md Knowledge Projects Routines System Tickets` plus the hidden folders.
- The hook prints a briefing starting with `# Bron briefing`.

- [ ] **Step 3: Write the live smoke test**

`tests/live/test_parity.py`. Set `CODEX_HOOK_FLAG` to the flag recorded in Task 1 Step 2, or to `None` if there is none. In that case, run `codex` once in the dev vault and approve Bron's triggers with `/hooks` before running this test.

```python
"""Real Claude Code and Codex sessions in a fresh dev vault. Run with: BRON_LIVE=1 uv run --project core/Engine pytest tests/live -q"""
import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("BRON_LIVE") != "1", reason="live CLI test: set BRON_LIVE=1")

REPO = Path(__file__).resolve().parents[2]
CODEX_HOOK_FLAG = "--dangerously-bypass-hook-trust"  # from Task 1 Step 2; None if there is no such flag
QUESTION = "Answer in one line and nothing else: your name, then the exact first line of your Bron briefing, then the names of the helpers you can use."


@pytest.fixture(scope="module")
def dev_vault(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("live") / "Live Vault"
    subprocess.run([str(REPO / "scripts" / "dev-vault.sh"), str(root)], check=True)
    return root.resolve()


def check_answer(text: str) -> None:
    assert "Bron" in text
    assert "# Bron briefing" in text or "Bron briefing" in text
    assert "reader" in text.lower()


def test_claude_session_is_bron(dev_vault):
    done = subprocess.run(["claude", "-p", QUESTION, "--output-format", "json"], cwd=dev_vault, capture_output=True, text=True, timeout=300, check=True)
    check_answer(json.loads(done.stdout)["result"])


def test_codex_session_is_bron(dev_vault):
    command = ["codex", "exec", "--skip-git-repo-check", "-c", f'projects."{dev_vault}".trust_level="trusted"']
    if CODEX_HOOK_FLAG:
        command.append(CODEX_HOOK_FLAG)
    done = subprocess.run([*command, QUESTION], cwd=dev_vault, capture_output=True, text=True, timeout=300, check=True)
    check_answer(done.stdout)
```

- [ ] **Step 4: Run the unit tests and the live tests**

Run: `uv run --project core/Engine pytest tests -q`
Expected: all unit tests PASS and the live tests are SKIPPED.

Run: `BRON_LIVE=1 uv run --project core/Engine pytest tests/live -q`
Expected: 2 PASSED. If one CLI fails, compare its behaviour with the Task 1 findings, fix the generator, and add a unit test that pins the fix before re-running.

- [ ] **Step 5: Add the development README**

`README.md`:

```markdown
# Agent Bron

A framework for AI agents that run entirely in Claude Code and Codex, with an Obsidian vault as the workspace. You define agents once in plain markdown under `System/`; Bron generates each CLI's setup so both behave the same.

Design: `docs/superpowers/specs/2026-10-01-bron-core-design.md`.

## Development

Requirements: macOS, [uv](https://docs.astral.sh/uv/), and Claude Code and/or Codex for the live tests.

- Unit tests: `uv run --project core/Engine pytest tests -q`
- Live tests (real CLI sessions, uses your logins): `BRON_LIVE=1 uv run --project core/Engine pytest tests/live -q`
- Build or refresh a dev vault: `scripts/dev-vault.sh "<path>"`. Open it in Obsidian or start `claude` / `codex` inside it.

Layout: `core/` becomes `System/Core` in every vault (framework-owned, replaced on update); `template/` is the starting vault; `core/Engine/bron` is the engine behind the `bron` command.
```

- [ ] **Step 6: Commit**

```bash
git add scripts/dev-vault.sh tests/live/test_parity.py README.md
git commit -F - <<'EOF'
feat(core): dev vault script and live parity smoke test

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

## Done when

- `uv run --project core/Engine pytest tests -q` passes.
- `BRON_LIVE=1 uv run --project core/Engine pytest tests/live -q` passes in both CLIs.
- A dev vault opened in Claude Code and in Codex answers as Bron, shows the Bron briefing, knows its helpers, and asks before `git push`.
- `docs/superpowers/specs/2026-10-01-bron-core-cli-verification.md` records every row, including the items deferred to Plan 2.

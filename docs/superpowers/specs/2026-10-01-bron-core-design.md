# Bron Core: design spec

- **Date:** 2026-10-01
- **Status:** draft for review
- **Sub-project:** 1 of 7 (Core)
- **Owner:** Alex

---

## 1. Purpose

Bron is an AI agent framework that runs entirely in two command-line tools, **Claude Code** and **OpenAI Codex**, with an **Obsidian vault** as the workspace. It is shared on GitHub with the user's team and a few friends.

The framework starts with one generalist agent, **Bron**. The user can keep Bron general or give it a role, and later add a team of agents. Every agent gets:

- the right instructions
- memory and context
- tools and connections
- a way to learn from corrections

**Bron Core** is the foundation every other part plugs into:

- the folder structure
- the agent and ticket formats
- the engine that keeps both CLIs identical
- how work is handed between agents
- install, first-run setup and updates

## 2. Scope

### In scope (this spec)
- Vault folder structure and ownership rules.
- The agent format (team members and helpers).
- The ticket format and lifecycle.
- The engine: sync, automatic triggers, permissions, runner, launcher, health check and setup skills.
- The `AGENTS.md` / `CLAUDE.md` contract.
- Install, onboarding interview, updates and rollback.
- The Obsidian bundle (theme and plugins).
- **Reserved interfaces** that later sub-projects fill in: knowledge base, memory, learning.

### Out of scope (each later sub-project gets its own spec → plan → build)
| # | Sub-project | Core provides |
|---|---|---|
| 2 | Memory: what is captured, when, and how it is recalled | Folders, the four trigger points, native memory features disabled |
| 3 | Knowledge base: ingest, wiki, hybrid search (**critical and speed-sensitive**) | `Knowledge/`, `.bron/kb/`, one search tool used the same way in both CLIs |
| 4 | Projects and Routines: runbooks, run records, scheduling later | Folders and `create-project` / `create-routine` setup skills |
| 5 | Learning: corrections become lessons, lessons become skill proposals you approve | Session-end and pre-compaction markers, override rule for skills |
| 6 | Connections catalogue (Carta, Drive, Gmail…) | `System/Connections/` format, per-agent allowlists |
| 7 | Team features beyond core (budgets, org views) | Agent format, tickets, runner, mixed vendors |

### Explicitly not now
- Agents that wake up on their own (schedules, heartbeats).
- Agents chatting with each other in real time. Tickets are the only channel.
- Shared team knowledge across vaults (possible later; Core does not block it).
- Windows and Linux support. Version 1 is Mac only.

## 3. Principles

1. **Files are the system.** Everything a person or agent needs to understand is a readable markdown file in the vault.
2. **Define once, generate both.** You edit only `System/`. Bron generates the Claude Code and Codex setups from it. **Both CLIs work the same way across everything**, multi-agent included.
3. **Framework and user stay separate.** `System/Core/` belongs to the framework and an update replaces it. Everything else belongs to the user, and updates never touch it without a previewed migration.
4. **A clean tree.** The visible top level holds only work folders, `System/`, and the two instruction files.
5. **Bron configures itself.** Any setup change can be requested in plain words. It is always previewed and approved before it is written.
6. **Fast by default.** Lean sessions for handoffs, and resumed sessions for follow-ups. Speed targets apply to the knowledge base (sub-project 3).
7. **Private by default.** Document content leaves the Mac only through the model calls the CLIs already make, or through connections and steps the user has opted into. Those are logged.

## 4. Vault layout

```
Vault/
├── AGENTS.md              generated; the shared instructions file (source of truth)
├── CLAUDE.md              one line: @AGENTS.md
│
├── Projects/              one-off work, one folder per project
│   └── <Project>/
│       ├── README.md        goal, status, key decisions
│       └── …                working files and outputs
├── Routines/              repeating workflows, one folder each
│   └── <Routine>/
│       ├── Runbook.md       steps, inputs, checks
│       └── Runs/            one record per run (e.g. 2026-Q3.md)
├── Tickets/               one note per ticket + Board.base (Bases board view)
├── Knowledge/             readable wiki pages (internals: sub-project 3)
│
└── System/
    ├── Agents/
    │   └── Bron/
    │       ├── Agent.md       identity, instructions, settings (§5.3)
    │       ├── Memory/        this agent's memory (internals: sub-project 2)
    │       └── Skills/        skills only this agent uses (optional)
    ├── Helpers/           your helper definitions (overrides Core's defaults)
    ├── Skills/            skills all agents can use (overrides Core's by name)
    ├── Connections/       outside tools and their settings (§7.4)
    ├── Memory/            shared memory: about you, your firm, cross-agent decisions
    ├── Settings.md        your name, default CLI, preferences, runner limits
    └── Core/              FRAMEWORK-OWNED; replaced on update
        ├── Manual/          Bron's documentation of the framework, one page per concept
        ├── Skills/          built-in skills, incl. setup skills (§7.8)
        ├── Helpers/         built-in helpers (reader, researcher, reviewer)
        ├── Templates/       agent, ticket, project, routine, settings templates
        ├── Engine/          sync, runner, launcher, check, hook entry, migrations
        └── VERSION

Hidden (Obsidian does not show dot-folders):
.obsidian/                 theme + plugins (§11)
.claude/                   GENERATED for Claude Code; never hand-edited
.codex/                    GENERATED for Codex; never hand-edited
.agents/                   GENERATED (Codex skills); never hand-edited
.bron/                     machine data: state, locks, run logs, backups, kb index
```

### Rules
1. **Ownership.** `System/Core/` belongs to the framework. Everything else belongs to the user.
2. **Generation.** `.claude/`, `.codex/`, `.agents/`, `AGENTS.md` and `CLAUDE.md` are written only by sync. If one is hand-edited, the health check warns and the next sync overwrites it, keeping a backup in `.bron/backups/`.
3. **Overrides.** A skill or helper in `System/Skills/` or `System/Helpers/` with the same name as one in `Core/` replaces the built-in one.
4. **Machine data.** Run logs, locks, caches, backups and the search index live in `.bron/` and never clutter the visible tree.

## 5. Agents

### 5.1 Two kinds of agent
| | **Team member** | **Helper** |
|---|---|---|
| What | Permanent role: instructions, memory, model, tools, connections | Temporary worker with no identity or memory |
| Defined in | `System/Agents/<Name>/Agent.md` | `System/Helpers/<name>.md` or `Core/Helpers/` |
| Used by | You (direct session) or another team member (ticket) | Any team member, including a solo Bron |
| Runs as | A full session in the CLI chosen by `runs_in` | Each CLI's built-in subagents (parallel) |

A solo Bron is a team of one and uses helpers from day one. Adding a team member means adding a folder; nothing is restructured. The framework ships **only Bron**. Roles such as CFO, COO and CCO are user configuration.

### 5.2 The agent folder
- `Agent.md` is required.
- `Memory/` is created by the template.
- `Skills/` is optional. Its skills are visible only to that agent.

### 5.3 `Agent.md`

```markdown
---
name: Bron
role: Chief of Staff
reports_to: you              # "you" or another agent's name
models:
  claude: opus               # alias or full model ID
  codex: gpt-5               # alias or full model ID (example)
runs_in: any                 # any | claude | codex
helpers: [reader, researcher, reviewer]
connections: [carta, google-drive]
can_assign_to: []            # agent names; empty = works alone
ask_before: [send-email, share-file, external-post]
always_allow: []             # rules you approved with "Always allow" (§7.4)
---

# Who you are
# How you work
# Boundaries
```

| Field | Required | Meaning / validation |
|---|---|---|
| `name` | yes | Unique and the same as the folder name. Used in tickets and commands. |
| `role` | yes | Short role description. Also used as the subagent description. |
| `reports_to` | yes | `you` or an existing agent. No cycles. |
| `models.claude` / `models.codex` | at least the one(s) `runs_in` allows | An alias resolved through Core's model map (updates can move aliases to newer models), or a full model ID. |
| `runs_in` | yes | `any` runs the agent in the CLI that started the handoff (fastest, no second login). `claude` or `codex` pins it to that CLI, which is how vendors are mixed. |
| `helpers` | no | Helper names that must exist. |
| `connections` | no | Names that must exist in `System/Connections/`. Every other connection is blocked for this agent. |
| `can_assign_to` | no | Agents this agent may give tickets to. You can always assign to anyone. |
| `ask_before` | no | Action groups (defined in `Core/Manual/permissions.md`) or raw tool patterns. Each needs your approval every time unless it is in `always_allow`. |
| `always_allow` | no | Written by Bron when you choose "Always allow". You can delete any line. |

The body is plain instructions, edited by you or by Bron through `edit-agent`.

### 5.4 Helpers
`System/Helpers/<name>.md` holds a frontmatter `name`, `description`, `models` (claude, codex), `connections` and an optional `read_only: true`, followed by instructions. Core ships three:

- **reader:** extracts facts from given files
- **researcher:** searches the knowledge base and the web
- **reviewer:** checks a draft against instructions and sources

Sync turns each helper into a Claude subagent file and a Codex agent file.

## 6. Tickets

### 6.1 Format: `Tickets/T-0042 <Title>.md`

```markdown
---
id: T-0042
status: todo            # backlog | todo | in-progress | blocked | in-review | done | cancelled
assignee: cfo
requested_by: bron      # agent name or "you"
parent: T-0040          # optional
project: "[[Quarterly LP Report]]"   # optional link to a Project or Routine
priority: normal        # low | normal | high | urgent
due: 2026-10-15         # optional
created: 2026-10-01T10:40
---

## Request
What to do and what "done" looks like.

## Context
Excerpts and links the assignee needs, packed by the requester.

## Thread
- 2026-10-01 10:42 · bron: handed to cfo
- 2026-10-01 10:45 · cfo: question: NAV as of 30 Sep or 15 Oct?
- 2026-10-01 10:46 · bron: 30 Sep

## Result
Summary and links to outputs.
```

### 6.2 Rules
- **IDs** are sequential. The counter lives in `.bron/state/tickets.json`.
- **One assignee per ticket.** Agents communicate only through tickets: the Thread and the Result.
- **Outputs** are saved in the linked project or routine folder. If there is none, they go to `Projects/Unsorted/`. The ticket links to them.
- **Lock.** Starting work creates `.bron/locks/T-0042.lock` atomically, recording the run ID, process ID and start time. If a lock already exists, the run does not start and does not retry (Paperclip's rule). A lock whose process has died, or that has outlived its timeout, is treated as stale and cleared by the runner or the health check.
- **Status flow:**
  1. `todo`
  2. `in-progress`: the runner has started.
  3. Either `blocked`, with the question written in the Thread (once answered, it returns to `in-progress` and resumes the same session), or `in-review`.
  4. `done` once you or the requester accept it.
  - A ticket can be moved to `cancelled` at any time.
- **Subtasks** use `parent:`. A parent's Result summarises its children.
- **Your own work queue.** You can create tickets for any agent, Bron included, as a to-do list.
- **Board.** `Tickets/Board.base` ships with views by status and by assignee.

## 7. Engine (`System/Core/Engine`)

The engine is written in Python and installed with its own Python by `uv`, so nobody installs Python by hand. Core's own dependencies stay small. The knowledge base adds its own later.

### 7.1 Sync: one source, two CLIs

| Source in `System/` | Claude Code output | Codex output |
|---|---|---|
| Shared rules + vault map | `AGENTS.md` (generated) + `CLAUDE.md` = `@AGENTS.md` | `AGENTS.md` |
| Default agent (Bron) | `.claude/settings.json` → `agent: bron` + `.claude/agents/bron.md` | `.codex/config.toml` → Bron's model + `developer_instructions` |
| Team members | `.claude/agents/<name>.md` | `.codex/agents/<name>.toml` + launcher/runner flags |
| Helpers | `.claude/agents/<helper>.md` | `.codex/agents/<helper>.toml` |
| Skills (Core + System + agent) | `.claude/skills/<name>/` | `.agents/skills/<name>/` |
| Connections | `.mcp.json` + per-agent `mcpServers` / tool allowlists | `[mcp_servers.*]` in `.codex/config.toml`, **explicitly disabled** for agents not allowed them |
| `ask_before` / `always_allow` | `permissions.ask` / `permissions.allow` | MCP `approval_mode = "prompt"` + `.codex/rules/*.rules` `prefix_rule(decision="prompt")` |
| Triggers | `hooks` in `.claude/settings.json` (fixed content) | `.codex/hooks.json` (fixed content) |
| Native memory | auto-memory off for this project | `memories` stays off |

How sync behaves:
- **When it runs:** after every setup skill, at the start of each session (a fast hash comparison that regenerates only on change), and on `bron sync`.
- **Validation first:** sync runs the health check (§7.7) before writing. If the check fails, the last good generated setup stays in place and Bron reports the problem.
- **Manifest:** a hash of every generated file is stored in `.bron/state/sync.json`, which is how drift is detected.
- **Skills:** copied into each CLI's folder (no symlinks) for robustness. Only the portable Agent Skills fields are relied on: `name` and `description`, plus the optional standard fields.
- **Imported approvals:** any approval a CLI saved locally (for example a "don't ask again" choice) is moved into the agent's `always_allow` on the next sync, with a notice. The local copy is then cleared, so `Agent.md` stays the only record.

### 7.2 `AGENTS.md` contract
- It is **agent-neutral**. Every session in either CLI loads it, whichever agent is running.
- **Contents:**
  - what the vault is
  - the folder map and ownership rules
  - the ticket protocol
  - how to find the manual (`System/Core/Manual/index.md`)
  - "follow the instructions of the agent you were started as"
- **Size:** kept well under Codex's 32 KiB cap, with a target under 8 KB. Detail lives in the manual and is read when needed.
- The default session agent is Bron, through the CLI settings in §7.1. Other agents are selected by the launcher (§7.6) or the runner (§7.5).

### 7.3 Automatic triggers
The trigger configuration never changes after install. Every trigger calls one stable entry point, `bron hook <event>`, and behaviour changes happen inside the engine. This matters because Codex asks the user to re-approve a trigger whenever its configuration changes, so the user approves once, at install.

| Point | Claude event | Codex event | Core behaviour (later sub-projects extend it) |
|---|---|---|---|
| Session start | SessionStart | SessionStart | Sync check; inject a short briefing (who you are, recent memory summary, open and finished tickets for this agent) |
| Before compression | PreCompact | PreCompact | Write a "save what matters" note to the agent's memory inbox |
| After each turn | Stop | Stop | Light capture marker (cheap) |
| Session end | SessionEnd | SessionEnd | Marker only (Codex allows ~1 s). Processing happens at the next session start. |

### 7.4 Permissions
- **Approval choices.** An `ask_before` action pauses with three options: **Allow once / Always allow / Deny**.
- **Where approvals happen.** They use each CLI's own approval system, because Codex triggers can block an action but cannot ask the user. Claude uses `permissions.ask`. Codex uses MCP tool `approval_mode` and shell `.rules`.
- **Always allow** is recorded in the agent's `always_allow` (§7.1, imported approvals).
- **Action groups.** These map friendly names to tool patterns, for example `send-email` → Gmail send tools and `share-file` → Drive share tool. They are defined in `Core/Manual/permissions.md` and can be extended in `Settings.md`.
- **Changes to `System/`** always go through a preview and approval, by rule in `AGENTS.md` and inside every setup skill.
- **Connections** (`System/Connections/<name>.md`): frontmatter holds `name`, `type` (mcp-stdio | mcp-http), `command`/`url`, `env` and `description`. **Secrets are never stored in the vault.** They stay in each CLI's login or the macOS Keychain. Sync turns connections into each CLI's MCP setup and enforces each agent's `connections` allowlist.

### 7.5 Runner: ticket handoffs
Started by the `delegate` skill, `bron run T-0042`, or `bron run --resume T-0042`.

1. Lock the ticket (§6.2) and set it to `in-progress`.
2. Read the assignee's `Agent.md`. Choose the CLI: `runs_in`, or the caller's CLI when `runs_in: any`. If you started the ticket yourself (from Obsidian, with `bron run`, or by asking an agent), the caller's CLI is the default CLI in `Settings.md`.
3. Check that CLI is installed and logged in. If not, set the ticket to `blocked` with the reason.
4. Start a **lean background session**:
   - **Claude:** `claude -p --bare --agent <name> --model <model> --mcp-config <generated> --strict-mcp-config --output-format json`, with the ticket as the prompt.
   - **Codex:** `codex exec --json -m <model> -c developer_instructions=… -c mcp_servers.<x>.enabled=false …`, with the ticket as the prompt.
5. Record the session ID (Claude `session_id`, Codex `thread_id`) in `.bron/state/runs.json`. Stream the log to `.bron/runs/<run-id>.log`.
6. When the session ends:
   - Confirm the ticket was updated. If it wasn't, set it to `blocked` with a link to the log.
   - Release the lock.
   - Notify the requester: the CLI's background-task notice where available, and the next session-start briefing in every case.
7. **Resume:** `--resume` continues the saved session (`claude -p --resume <id>` / `codex exec resume <id>`) with the new Thread entries as the prompt.

**Speed measures:**
- Only the assignee's instructions, connections and the ticket are loaded.
- The requester packs the context into the ticket.
- Follow-ups resume the same session.
- Several tickets run in parallel, up to `Settings.md → runner.max_parallel` (default 3, sized for an 18 GB Mac).
- Model choice per agent.

**Limits** (per ticket, optional in `Agent.md` or the ticket): `max_minutes` (default 30) and Claude's `max_budget_usd` where supported.

### 7.6 Launcher: talk to any agent directly
`bron chat [agent] [--cli claude|codex]`. The agent defaults to Bron and the CLI defaults to the one in `Settings.md`.

- **Claude:** `claude --agent <name>`.
- **Codex:** `codex -m <model> -c developer_instructions=<agent instructions> -c mcp_servers…`. Codex has no agent flag, so the launcher passes these settings.

Bron Terminal can call the launcher, for example through an agent picker. That plugin change is a follow-up and is not required for Core.

### 7.7 Health check: `bron check`, or "Bron, check yourself"
It validates:
- **Formats:** every `Agent.md`, helper, connection and ticket file is well formed.
- **References:**
  - names are unique
  - `reports_to`, `helpers`, `connections` and `can_assign_to` point at things that exist
  - there are no reporting cycles
- **Models and CLIs:**
  - the models needed by `runs_in` are set
  - each CLI an agent needs is installed and logged in
- **Generated setup:**
  - no drift between the generated setup and `System/`
  - Codex trust is set and Bron's triggers are approved
  - `AGENTS.md` is within its size cap
- **Machine state:** stale locks.

It reports in plain language and offers to fix each problem.

### 7.8 Setup skills (in `Core/Skills/`)
Each one previews the full change and waits for your yes. Then it writes, runs check and sync, and reports.

| Skill | Example request |
|---|---|
| `onboarding` | first run; "Bron, let's redo setup" |
| `create-agent` | "Set up a CFO on Opus 5.5 that reports to you" (infers `runs_in: claude`, `reports_to: bron`, adds `cfo` to Bron's `can_assign_to`, asks only for what's missing, drafts instructions from memory and the knowledge base, then runs a test ticket) |
| `edit-agent` | "Give the CFO access to Carta" |
| `remove-agent` | "Retire the COO" (open tickets are reassigned first) |
| `add-connection` | "Connect Google Drive" |
| `create-project` | "Start a project for the Fund III audit" |
| `create-routine` | "Make the quarterly LP report a routine" |
| `create-skill` | "Turn what we just did into a skill" |
| `delegate` | used by agents to write a ticket and start the runner |
| `update` | "Bron, update yourself" / "undo the update" |
| `check` | "Bron, check yourself" |

### 7.9 Manual (`Core/Manual/`)
One page per concept:
- index
- folders
- agents
- helpers
- tickets
- permissions
- connections
- sync
- runner
- skills
- updates
- troubleshooting

`AGENTS.md` points to the index, and Bron reads pages when it needs them. This is how Bron "understands its own setup".

## 8. Reserved interfaces for later sub-projects

### 8.1 Knowledge base (sub-project 3, critical)
- **Visible:** `Knowledge/` holds the readable wiki: one page per portfolio company, fund and LP, plus topics, each fact linked to its source.
- **Hidden:** `.bron/kb/` holds converted text, the manifest and the search index. Originals stay in Google Drive and are never copied into the vault, except one-off uploads.
- **Search tool:** one local tool, `bron-kb`, served as an MCP server and available to every agent in both CLIs. The same search is available as `bron search` for scripts.
- **Requirements carried forward:**
  - Fast ingest (OCR happens once, at ingest) and fast search (target of about 0.1–0.15 s for a typical query; deeper re-ranking is opt-in).
  - English and Portuguese, including searching across the two languages and matching amounts and dates in either format.
  - Reuse proven open-source pieces.
  - Opt-in and logged for any step that sends document text off the Mac.

### 8.2 Memory (sub-project 2)
- **Locations:** `System/Memory/` (shared) and `System/Agents/<Name>/Memory/` (per agent).
- **Hooks:** the four trigger points in §7.3.
- **Native memory:** both CLIs' built-in memory features stay disabled inside the vault, so there is a single memory.

### 8.3 Learning (sub-project 5)
- Lessons arrive through the trigger markers.
- Improvements land as **proposals you approve, each of which can be undone**.
- An approved skill change is written to `System/Skills/`, which overrides Core.

## 9. Framework source repository

This folder (`agent-bron/`) becomes the framework's source repository. The user's own working vault is installed from it, the same way a teammate's is, so the user is the first real user of every update.

```
agent-bron/                    (GitHub repository)
├── install.sh                 one-command installer
├── core/                      becomes System/Core in each vault
├── template/                  vault skeleton copied on install
│   ├── Projects/ Routines/ Tickets/ Knowledge/
│   ├── System/ (Agents/Bron, Helpers, Skills, Connections, Memory, Settings.md)
│   └── .obsidian/             theme + plugins (§11)
├── tests/
├── docs/                      specs, plans, changelog
└── README.md
```

## 10. Install, onboarding, updates

### 10.1 Install (`install.sh`)
**Prerequisites:** a Mac, and Claude Code and/or Codex installed and logged in. Obsidian is strongly recommended.

The installer:
1. Asks where to create the vault and what to call it.
2. Copies `template/` and puts `core/` at `System/Core/`.
3. Installs `uv`, which installs the engine's Python and dependencies into `.bron/`.
4. Marks the vault as trusted in Codex (`~/.codex/config.toml` → `[projects."<path>"] trust_level = "trusted"`).
5. Puts the `bron` command on the PATH.
6. Runs the first sync and the health check.
7. Prints the next step: open the vault in Obsidian and start Bron.

The installer is safe to run again and repairs a broken install. It never overwrites user files.

### 10.2 Onboarding (`onboarding` skill, about 5 minutes)
Triggered when `Settings.md` is unfilled. Bron covers:
- who you are, your role and your company
- what Bron should be (generalist or a role)
- tone and preferences
- your default CLI
- which connections to set up
- which Drive folders feed the knowledge base

Bron previews `Settings.md`, the shared memory and its own `Agent.md`, and writes them on your yes. In Codex, it guides you through the one-time trigger approval.

### 10.3 Updates (`update` skill)
- **Daily check:** once a day at session start, Bron compares `Core/VERSION` with the latest GitHub release. It **only notifies**.
- **Applying an update:** on request, Bron shows the changelog and asks for your yes. It then backs up `System/Core` to `.bron/backups/core-<version>/`, replaces `System/Core`, runs any migrations, then runs the health check and sync.
- **Migrations** (format changes to user files) are previewed and back up the affected files first.
- **Rollback:** "Undo the update" restores the backup and syncs. A failed update rolls back automatically.
- **History:** Bron can set up the vault as a private git repository for a full change history. This is optional; updates do not depend on it.

## 11. Obsidian bundle

Every vault opens looking and working the same way.

- **Theme:** Bron, the `appearance.json` settings, and the snippets and icons in use.
- **Plugins enabled:**
  - Bron Workspace
  - Bron Terminal
  - Colored Tags
  - File Explorer Note Count
  - Termy
  - Style Settings
  - Data Files Editor
  - XLSX Viewer
- **Plugins included but kept disabled:** Iconize, matching the source vault.
- **Plugins left out:** File Color.
- **Scrubbed before shipping:**
  - `workspace.json` and `workspace-mobile.json`
  - `devin-backups/`
  - personal paths, IDs and section shortcuts in each plugin's `data.json`, reset to clean defaults (each plugin's defaults are reviewed during implementation)
- **Third-party plugins** are shipped as pinned copies. A framework update can refresh them.

## 12. Error handling

| Situation | Behaviour |
|---|---|
| Health check fails before sync | The last good generated setup stays in place. Bron explains the problem and offers a fix. |
| A generated file was hand-edited | Warn, back it up, and regenerate on the next sync. |
| The required CLI is missing or logged out | The ticket goes to `blocked` with a plain-language reason. |
| A run crashes or times out | The lock is released (stale-lock detection) and the ticket goes to `blocked` with a log link. |
| The assignee didn't update the ticket | It goes to `blocked` with the log link, and the requester decides. |
| Ticket already locked | Do not start and do not retry. Report it. |
| An update fails | Automatic rollback, with a report. |
| The installer is interrupted | Re-running it resumes and repairs. |

## 13. Testing

- **Unit tests:**
  - parsing and validating agents, helpers, connections and tickets
  - the health-check rules
  - ticket IDs and locks, including stale locks
- **Golden-file tests for sync:** a fixed `System/` produces exactly the expected `.claude/`, `.codex/`, `.agents/`, `AGENTS.md` and `CLAUDE.md`.
- **Parity smoke tests, run headless in both CLIs:**
  1. The default session is Bron.
  2. A skill is visible.
  3. An `ask_before` action prompts, and "Always allow" lands in `Agent.md`.
  4. A connection is blocked for an agent not allowed it.
  5. A helper runs in parallel.
- **Handoff tests:**
  - Same vendor: Bron to the CFO with `runs_in: any`.
  - **Cross-vendor:** Claude Bron to a Codex CFO, and the reverse.
  - `blocked` then resume of the same session.
  - Parallel tickets.
  - A stale lock is recovered.
- **Install tests:** a clean install into a temporary folder, a re-run that repairs, update, and undo, with user files compared byte for byte.
- **Speed baseline:** measure the time from handoff to the first ticket update, and the time to resume, in each CLI. Record the baseline in the plan and track it on every release.

## 14. Success criteria

1. **Install:** on a Mac with a logged-in CLI, install plus onboarding gets Bron working in about 10 minutes.
2. **Parity:** the same request in Claude Code and in Codex uses the same instructions, skills, connections, approvals, memory locations and ticket behaviour.
3. **Self-configuration:** "Set up a new CFO on Opus 5.5 that reports to you" produces a working CFO after one approval, and the test ticket succeeds.
4. **Cross-vendor handoff:** Claude Bron hands a ticket to a GPT CFO in Codex and gets the result back, including a `blocked` → resume round trip.
5. **Updates:** update and undo leave every user file unchanged.
6. **Clean tree:** the visible vault top level shows only `Projects/`, `Routines/`, `Tickets/`, `Knowledge/`, `System/`, `AGENTS.md` and `CLAUDE.md`.
7. **Health check:** a deliberately broken setup (a bad reference, a hand-edited generated file, a stale lock) is detected and fixed.

## 15. Verify during implementation

These came out of research and could not be fully confirmed. The plan tests each one first and adjusts the design if needed:

1. **Codex agent MCP layering.** Confirm that `enabled = false` reliably blocks a parent's MCP servers for an agent.
2. **Importing approvals.** Confirm where each CLI saves "always allow" choices (Claude `settings.local.json`; Codex rules amendments) so sync can import them.
3. **Codex project config.** Confirm `developer_instructions` and the model can be set in the project-level `.codex/config.toml`.
4. **Resuming with settings.** Confirm that `codex exec resume` keeps the original session's settings, given it doesn't accept `-p`, `-s` or `--add-dir`.
5. **Background completion notice in Codex.** Fall back to the session-start briefing if there isn't one.
6. **Claude `--bare` with `--agent` and `--mcp-config`.** Confirm the subset of hooks and skills a lean run should still load.
7. **Plugin data.** Confirm the bundled plugins' `data.json` defaults contain nothing personal.
8. **Turning off native memory.** Confirm the exact project-level setting that disables Claude Code's auto-memory inside the vault, and that Codex `memories` stays off for this project.
9. **Default agent in Claude settings.** Confirm that the `agent` setting in project `.claude/settings.json` makes Bron the default session agent.

## 16. Glossary

| Term | Meaning |
|---|---|
| **Team member** | A permanent agent with its own folder in `System/Agents/` |
| **Helper** | A temporary subagent any team member can use |
| **Ticket** | A task note in `Tickets/`. The only way agents hand each other work. |
| **Sync** | Bron turning `System/` into each CLI's own hidden setup |
| **Runner** | The engine part that starts an agent to work a ticket |
| **Launcher** | `bron chat`: start a conversation as any agent in either CLI |
| **Health check** | `bron check`: validates the whole setup |
| **Core** | `System/Core/`, the framework's own files, replaced on update |

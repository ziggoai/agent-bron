# Bron Core, Plan 2b: @-mentions, routines, saved approvals

Status: design approved in conversation on 2026-10-02. This spec refines the core spec (`2026-10-01-bron-core-design.md`) §6.2 (chat tickets), §6.3 (routines), §7.1 (imported approvals) and §7.6 (@-mentions), and builds on Plan 2a as built (framework 0.2.3). Where they disagree, this spec wins.

## 1. Purpose

1. **@-mentions.** The user writes `@cfo …` in any session and the CFO answers quickly, in its own words, on its own model and CLI. Untagged messages go to the session's agent (Bron by default).
2. **Routines.** Repeating work (monthly, quarterly, annual) is tracked per period, with steps done for different lists (each portfolio company, once, each fund) and steps that wait for others. Bron says what's due; nothing runs on its own.
3. **Saved approvals.** A "don't ask again" choice in Claude Code is no longer wiped by sync; it moves into the agent's `always_allow`.

Out of scope: `create-routine` and the other setup skills (Plan 3); step-by-step automation of a routine's work (sub-project 4); anything that runs on a schedule.

## 2. Decisions (approved by the user)

- **D1. The tagged agent starts at once.** The message trigger starts the tagged agent's run the moment the message is sent, with the user's exact words. The session's agent only waits and shows the reply word for word, labelled with the agent's name. Expected: the agent's own time plus about 3 seconds (10–15 s for a short answer).
- **D2. Context.** The tagged agent gets the message plus the last few exchanges of the chat (option A).
- **D3. A whole session as an agent** stays `bron chat <agent>` (exists).
- **D4. Routine lists come from a source.** A list in a runbook is either a fixed list or a plain-language source that Bron resolves when a period starts and the user confirms. For this user: Carta is the source of truth for portfolio companies and funds; reports count only active companies (FMV > 0). That is user configuration, not framework code.
- **D5. Routine steps** each say what they are done for (a list, or once) and what they wait for. One Tracking note per period holds a checklist per step.
- **D6. Starting a period** is offered by Bron in the first session after the period ends; Bron sets it up only after the user's yes and confirmation of the lists. The lists are fixed for that period once confirmed.
- **D7. Claude "don't ask again"** choices are imported into `always_allow` of the default agent, with a plain notice and no preview (the click is the user's yes). Codex keeps its approvals in its own user-level rules; Bron leaves them alone.

## 3. @-mentions

### 3.1 Detection (message trigger, `bron hook user-prompt`)
- A tag is `@<name>` where `<name>` matches an agent's key or name, case-insensitive, and the `@` is not preceded by a letter, digit, `.` or `@` (so `someone@example.com` is not a tag). Unknown names are ignored (no routing).
- Tags for the session's own agent are ignored. Nothing is routed inside a headless ticket run (`BRON_TICKET` set).
- No tag: the trigger behaves as today (ticket updates only).

### 3.2 Chat tickets
- One chat ticket per (CLI session, tagged agent): `kind: chat`, `assignee: <agent>`, `requested_by: <session agent>`, new frontmatter `chat_session: <cli>:<session_id>`. Title: `Chat with <Agent>: <first words of the first message>` (max 60 chars).
- **First message:** the ticket's Request is the user's message as written; its Context is the last exchanges (§3.3). **Follow-up** (an open chat ticket exists for this session and agent): the message is added to the Thread as `you: <message>` and the run resumes the agent's saved session, so the agent remembers the conversation.
- Chat tickets are hidden from the board's main views (Board.base already has a Chats view).
- **Closing:** the session-end trigger marks the session's chat tickets `done` (file edits only, within Codex's ~1 s budget). Fallback at session start: any chat ticket untouched for 12 hours is marked `done`. A chat Bron closed this way is reopened if the same session tags that agent again (a resumed session is the same conversation); chats closed by the user or an agent stay closed.

### 3.3 Context: last exchanges
- Read from the trigger's `transcript_path` (both CLIs provide it; formats verified in Task 1).
- Up to the last 3 user/assistant exchanges before this message, text only (no tool calls or outputs), each message cut to 1,500 characters, 6,000 characters in total, newest kept first when cutting.
- If the transcript can't be read, the ticket says "(no earlier chat available)" and the run goes ahead.

### 3.4 Starting the run
- The trigger creates or updates the chat ticket, then starts the run detached (`bron run <id> [--resume] --caller-cli <cli>`, in its own process group, surviving the trigger's exit). The trigger must finish well within its 10 s timeout; it never waits for the run.
- A chat run is recorded as **shown** (Plan 2a `shown` flag): the session agent displays it, so it is not announced again in a later message.
- Several tags in one message start one run per agent, in parallel (subject to `max_parallel`).
- The chat run prompt differs from the task prompt: the agent is talking to the user directly; its final reply is shown to the user word for word; it uses ticket commands only to ask for approval ("Needs your OK: …") or when it truly can't answer.

### 3.5 What the session agent is told and does
The trigger adds to the message's context, for example:

> @CFO is answering this in T-0007 (chat). Don't answer the question yourself. Run `.bron/bin/bron ticket wait T-0007` as an ordinary command and wait for it, then show the reply word for word, starting with "**CFO:**". You may add one short note of your own after it if it helps.

- New command `bron ticket wait <id> [<id> …]`: waits until each ticket's run has finished (no run lock and status not `in-progress`; a 15-second grace period covers a run that hasn't taken its lock yet), then prints for each ticket `<Agent>: <result>`, or the blocked note (a question or "Needs your OK: …"), or the runner's failure note. It gives up after `max_minutes` with a plain message.
- **Needs your OK** in a chat: the session agent handles it as in the delegate skill (show the action, do it after the user's yes, `ticket say`, resume with `--wait`).
- **Unreachable agent** (CLI missing, not logged in, setup problems): the runner blocks the ticket with its plain note; `ticket wait` prints it; the session agent passes it on.

### 3.6 Speed
- The run starts before the session agent starts thinking, so the session agent's turn overlaps the agent's run.
- The chat prompt carries the message and context inline (no file reads), and the agent's final reply is the answer (one model turn for a simple answer).
- Follow-ups resume the agent's session.

## 4. Routines

### 4.1 Runbook: `Routines/<Routine>/Runbook.md`
```markdown
---
cadence: quarterly                 # monthly | quarterly | annual
owner: bron                        # agent that looks after it
due: 45 days after period end      # plain rule; "N days after period end" is understood by the engine
lists:
  companies: active portfolio companies of each fund in Carta (FMV > 0), grouped by fund
  funds: funds in Carta
steps:
  - name: Collect financials and KPIs
    for: companies
  - name: Stacked ranking
    for: once
  - name: One-pager
    for: funds
    after: [Collect financials and KPIs, Stacked ranking]
---

## How to do each step
(plain instructions per step: where the template is, what to update, who to send to)
```
- A list value is either a YAML list (fixed items) or a string (a source Bron resolves at period start).
- `for` is a list name or `once`. `after` names earlier steps. Steps without `after` can run at the same time.
- A runbook without `steps` is one checklist of its lists' items (the simple case from the core spec).

### 4.2 Periods
- Names: `2026-09` (monthly), `2026-Q3` (quarterly), `2026` (annual). Folders sit directly in the routine folder.
- **The period to run** is the latest period that has ended (Q3's run starts on 1 October).
- `due` is computed when the period starts: "N days after period end" gives a date; any other rule is turned into a date by Bron, who asks the user if unsure. The date is written into the Tracking note.

### 4.3 Tracking note: `Routines/<Routine>/<Period>/Tracking.md`
```markdown
---
routine: Portco Monitoring
period: 2026-Q3
due: 2026-11-14
status: in-progress                # todo | in-progress | done
progress: "Collect 14/20 · Ranking 2/2 · One-pager 0/3"   # written by the engine
---
## Collect financials and KPIs
### Fund I
- [x] Company A
- [ ] Company B
### Fund II
- [ ] Company C

## Stacked ranking
- [x] Sent to the investment team
- [x] Back from the investment team

## One-pager
- [ ] Fund I
- [ ] Fund II
- [ ] Fund III
```
- One `##` section per step, in runbook order; items are Markdown checkboxes, optionally grouped under `###` headings (for example by fund). A `once` step gets the checkboxes Bron writes for it (default: one item named after the step).
- The user or an agent ticks items in Obsidian or by editing the file; notes may follow an item on the same line (`- [x] Company A: received 12 Oct`).
- The engine counts checkboxes per step. A step is done when all its items are ticked; a step whose `after` steps aren't done is "waiting". `status` becomes `done` when every step is done (the engine updates `status` and `progress`; it never touches the checkboxes).
- Outputs for the period (one-pagers, exports) sit next to the Tracking note.

### 4.4 Commands
- `bron routine list`: each routine, its current period, progress and due date.
- `bron routine start <Routine> [--period 2026-Q3] [--list <name>=<file>]…`: creates the period folder and its Tracking note from the runbook. Each list file has one item per line, optionally `Group: item` to group items under `###` headings. Fixed lists from the runbook are used as they are. Refuses if the period already has a Tracking note.
- `bron routine refresh [<Routine>]`: recomputes `status` and `progress` in Tracking notes (also run by the session-start briefing).

### 4.5 Briefing and board
- The session-start briefing has a **Routines** block for the session's agent if it owns routines (the default agent also sees routines owned by agents that no longer exist):
  - a period that has ended but has no Tracking note: `Q3 Portco Monitoring can start (due 14 Nov). Offer to set it up.`
  - a period in progress: `Q3 Portco Monitoring: Collect 14/20 · Ranking 2/2 · One-pager waiting; due in 12 days` (or `overdue by 3 days`).
  - Done periods are not mentioned. The block is capped like the tickets block (8 lines, then "and N more").
- `Routines/Board.base` (shipped in `template/`) lists Tracking notes with routine, period, status, progress and due, grouped by status.

### 4.6 Bron's instructions
- A core skill `routines` covers: starting a period (resolve each list from its source, show the lists to the user and wait for a yes, write the list files, run `bron routine start`), ticking items, "who's still missing?", handing a step to a team member as a ticket linked to the routine (`--project '<Routine>'`), and writing a runbook when the user asks (shown first, like any setup change).
- A manual page `routines.md` documents the runbook and Tracking formats.

### 4.7 Health check
- Errors: invalid `cadence`; a step `for` naming a missing list; `after` naming a missing or later step; duplicate step names.
- Warnings: a runbook with no `owner`, or an owner that isn't an agent (the default agent looks after it); a Tracking note that can't be read.

## 5. Saved approvals

- **When:** at the start of sync, before anything is regenerated.
- **What:** entries in `permissions.allow` of `.claude/settings.json` that Bron did not generate (compared with what sync would generate now), and all entries in `.claude/settings.local.json` `permissions.allow` (where Claude saves them inside a git repo).
- **Mapping:**
  - `Bash(<words>:*)`, `Bash(<words> *)`, `Bash(<words>)` → `shell:<words>`
  - `mcp__<server>__<tool>` → `mcp:<Connection name>:<tool>` when `<server>` is a known connection's Claude id; otherwise kept as is (next point)
  - anything else (for example `WebFetch(domain:…)`, `Read(…)`) has no Codex equivalent: it is kept in `.claude/settings.local.json`, which sync never writes, so Claude keeps honouring it.
- **Who gets it:** the default agent's `always_allow` (project settings apply to the default agent; Plan 2a I5 already re-asks team members).
- **Writes:** `Agent.md` frontmatter is updated in place (the rest of the file untouched); duplicates are skipped; the imported entries are removed from the CLI file they came from (except the Claude-only ones, which stay in `settings.local.json`).
- **Notice:** shown once in the next briefing: `Saved your "always allow" choices for Bron: shell git push; Gmail reply.`
- **Codex:** approvals are saved by Codex in `~/.codex/rules/default.rules` (user level, outside the vault, not per agent); Bron leaves them.
- If an import fails (unreadable file, `Agent.md` can't be parsed), sync leaves the CLI file untouched, reports it in the health check, and regenerates nothing that would drop the approval.

## 6. Error handling (summary)
- Nothing in the message trigger may block or crash the user's message: every failure there degrades to "no routing" plus a one-line note in the context.
- A tagged agent's run follows Plan 2a's rules: never left in-progress; refusals become "Needs your OK"; failures become a plain blocked note that `ticket wait` prints.
- Routine commands never change checkboxes; a malformed Tracking note is reported, not rewritten.
- The approvals import never loses an approval: it writes `Agent.md` first, then removes the entry from the CLI file.

## 7. Testing
- Unit tests for: tag detection (emails, unknown names, self-tags, several tags), transcript parsing (both CLIs, fixtures from Task 1), chat ticket create/follow-up/close, the trigger's context text, `ticket wait` (finished, blocked, not yet started, timeout), routine periods and due dates, runbook validation, Tracking creation from list files, progress counting with groups and `after`, briefing lines, approvals mapping and import (settings.json and settings.local.json, unknown kinds, duplicates, failure).
- Live tests (`BRON_LIVE=1`): `@` tag in a Claude session to a Codex agent and in a Codex session to a Claude agent, with a follow-up that relies on the first answer; a Claude "always allow" survives a sync and becomes `always_allow`.

## 8. Verify first (Task 1)
1. The transcript formats at `transcript_path` for Claude Code and Codex, and how to pick out user and assistant text.
2. A process started by the message trigger survives the trigger's exit in both CLIs.
3. The message trigger's output reaches the model in Codex as context (Plan 2a notifications suggest yes).
4. Where and in what exact format Claude Code saves "don't ask again" for a Bash command and for an MCP tool, in a vault that isn't a git repository.
5. Time from Enter to the shown reply for a short `@` question, both directions.

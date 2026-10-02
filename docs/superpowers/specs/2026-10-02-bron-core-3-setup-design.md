# Bron Core, Plan 3: setup skills

Status: design approved in conversation on 2026-10-02. This spec refines the core spec (`2026-10-01-bron-core-design.md`) §7.8 (setup skills) and §10.2 (onboarding), and builds on Plans 1, 2a and 2b as built (framework 0.3.1). Where they disagree, this spec wins.

## 1. Purpose

The user sets Bron up in plain sentences: "Set up a COO on Opus 5.5 that reports to you", "Give the CFO access to Drive", "Retire the COO", "Connect Notion", "Start a project for the Fund III audit", "Make the quarterly LP report a routine", "Turn what we just did into a skill", and a short first-run onboarding. Each change is previewed in plain language, saved only after a yes, and done in one step that is fast and can't leave a broken setup.

Out of scope: choosing Drive folders for the knowledge base (knowledge-base sub-project); the installer and Obsidian bundle (Plan 4); memory internals (sub-project 2).

## 2. Decisions (approved by the user)

- **D1. Previews are plain-language summaries**, for example *"New agent: COO, runs on Opus 5.5 in Claude Code, reports to Bron, can use Google Drive, asks before sending email or deleting files. OK?"*. "Show me the file" shows the exact text.
- **D2. Safety defaults:** every new agent asks before deleting files, pushing (git), and every send/share/post action group that touches one of its connections. Read-only connections add nothing. The summary lists them; the user can remove any.
- **D3. Retiring archives:** open tickets are handed to the agent's boss (or whoever the user names), then the folder moves to `System/Archive/Agents/<Name>/`. "Bring back <Name>" restores it.
- **D4. Onboarding is quick (about 2 minutes):** the user's name, role and company; Bron's name and role; Bron's model (default Opus 5.5 in Claude Code; Codex keeps its own default unless the user names one); the user's main app; a connector check. It ends by asking whether to set tone and preferences now or later, and whether to set up team members.
- **D5. Commands do the changes:** each skill gathers what's missing, shows the engine's summary, and runs one `bron` command that writes the files, syncs and runs the health check. No hand-editing of setup files.

## 3. How every setup skill works

1. **Understand the request.** Fill in what can be inferred (§4.2), ask only for what's missing, one question at a time.
2. **Preview.** Run the command with `--preview`: it validates the change against the current setup and prints the plain-language summary (and the exact file text with `--show-files`). Nothing is written. Show the summary to the user and wait for a yes.
3. **Apply.** Run the same command without `--preview`. It writes the files, runs sync, runs the health check, and prints a one-line result plus any problem in plain words. If validation or sync fails, nothing is left half-changed: files written by the command are restored from a copy taken before writing.
4. **Report** in one or two lines.

Every command's free text follows the existing quoting rule (single quotes; a file option when the text contains a single quote).

## 4. Commands

### 4.1 Agents: `bron agent …`
- `create --name <Name> --role '<role>' [--reports-to <Agent|you>] [--model claude=<m>] [--model codex=<m>] [--runs-in any|claude|codex] [--connections '<A>, <B>'] [--ask-before '<entries>'] [--helpers '<h>, …'] [--instructions-file <path>] [--no-defaults] [--preview [--show-files]]`
  - Writes `System/Agents/<Name>/Agent.md` (instructions from the file, or a default body built from the role: Who you are / How you work / Boundaries) and an empty `Memory/` folder.
  - Adds the new agent to its boss's `can_assign_to` (unless the boss is `you`).
  - Adds the safety defaults (D2) unless `--no-defaults`.
- `set <Name> [--role …] [--reports-to …] [--model cli=<m>] [--runs-in …] [--add-connection <A>]… [--remove-connection <A>]… [--add-ask <entry>]… [--remove-ask <entry>]… [--instructions-file <path>] [--preview]`: changes only the named settings; other lines and the body are kept (same in-place editing approach as the approvals import).
- `rename <Name> <NewName> [--preview]`: renames the folder and `name`, and updates every reference: other agents' `reports_to` and `can_assign_to`, routine `owner`s, and `default_agent` in Settings.md when it is the default agent. Existing tickets keep the old name as history.
- `retire <Name> [--hand-to <Agent|you>] [--preview]`: refuses for the default agent. Reassigns open tickets (not chats) to `--hand-to` (default: the agent's boss) with a Thread note; closes its open chat tickets; removes it from every `can_assign_to`; agents that reported to it now report to its boss; routines it owned move to its boss; then moves the folder to `System/Archive/Agents/<Name>/`.
- `restore <Name> [--preview]`: moves it back (refusing if an agent with that name exists) and adds it to its boss's `can_assign_to`.

### 4.2 Filling in what the user didn't say
- **Model → CLI:** a model alias or ID that belongs to one vendor sets `runs_in` to that CLI (Claude models → `claude`, OpenAI models → `codex`), using the aliases in `Core/Manual/models.md`. No model → `runs_in: any` and both models `default`.
- **Reports to:** the agent creating it (normally the default agent) unless the user says otherwise.
- **Connections:** none unless named. Names are matched to `System/Connections/` case-insensitively; an unknown name is an error with the list of known ones.
- **Helpers:** reader, researcher, reviewer (the defaults the template already uses).

### 4.3 Projects: `bron project new '<Name>' [--goal '<goal>'] [--preview]`
Creates `Projects/<Name>/README.md` with Goal, Status (`active`) and Key decisions sections. Refuses if the folder exists.

### 4.4 Routines: `bron routine create --file <draft.md> [--preview]`
The skill drafts the runbook (format in `Core/Manual/routines.md`) to a file under `.bron/tmp/`; the command validates it with the same checks as `bron check`, prints the summary (cadence, owner, due rule, lists and their sources, steps and what each waits for), and on apply writes `Routines/<Name>/Runbook.md`. Refuses if the routine exists. Editing an existing runbook stays a plain file edit shown to the user first.

### 4.5 Skills: `bron skill new <name> --description '<when to use it>' --file <body.md> [--agent <Name>] [--preview]`
Writes `System/Skills/<name>/SKILL.md` (shared) or `System/Agents/<Name>/Skills/<name>/SKILL.md` (one agent). Validates the name rules the loader enforces (lower-case letters, numbers, hyphens; 64 characters at most) and that the frontmatter is valid. Refuses if it exists.

### 4.6 Connections: `bron connection add --name '<Name>' (--command '<cmd>' [--args '<args>'] | --url <url>) [--description '<…>'] [--preview]`
For tools that run on the Mac (`mcp-stdio`) or a plain web address (`mcp-http`). Secrets are never written: an `env` value that looks like a secret is refused with a plain explanation (consistent with the existing health check). Connectors the user signs in to (Notion, Slack, Gmail…) are added in claude.ai / Claude Code or Codex by the user; the skill gives the exact steps, then runs the existing connector scan (`bron connections scan`). Either way it ends by asking which agents may use the new connector (`bron agent set … --add-connection`).

### 4.7 Settings: `bron settings set [--name '<user name>'] [--role '<user role>'] [--company '<company>'] [--default-cli claude|codex] [--tone '<…>'] [--preferences '<…>'] [--preview]`
Writes those fields in `System/Settings.md` (in place; other lines kept). New fields: `user_role`, `tone`, `preferences`.

### 4.8 About the user, for every agent
`AGENTS.md` gets a short "About the user" section rendered from Settings: name, role, company, tone and preferences (only the fields that are set). It stays within the 8 KB target.

## 5. Skills (Core/Skills)
Each is a short instruction file that says when it applies, what to infer, what to ask, which command to preview and apply, and how to report:
- `onboarding`: triggered by the briefing's first-run line (no user name yet) or "let's redo setup". Order: the user's name, role and company → Bron's name and role (renaming through `bron agent rename` when changed) → Bron's model: "I'll run on Opus 5.5 in Claude Code — OK, or another model?" (`bron agent set <Bron> --model claude=<model>`; a Codex model only if the user names one) → the main app → connector check (`bron connections scan`, then "Use these?") → "Tone and preferences now or later?" → "Want to set up any team members now?" (hands over to `create-agent`). In Codex it explains the one-time trigger approval (`/hooks`). The existing "save the name straight away" exception stays.
- `create-agent`, `edit-agent`, `remove-agent` (retire and bring back), `add-connection`, `create-project`, `create-routine` (replaces the "A new routine" part of the `routines` skill), `create-skill`.
- After `create-agent` applies, the skill runs the quick ask from the shared rules: *"Introduce yourself in one sentence."* and shows the answer, so the user sees the new agent working.

The briefing's first-run line points to the onboarding skill. The manual gets a `setup.md` page listing the commands; `index.md` links it.

The framework's template gives the default agent `models: {claude: opus-5.5, codex: default}` for new installs.

## 6. Error handling
- Every command validates first; a change that would make the health check report an error is refused with the problem in plain words, and nothing is written.
- Apply copies every file it will change to `.bron/backups/setup-<time>/` first; if writing, sync or the health check fails, it restores them and says so.
- Names are checked against existing agents, helpers, skills, projects and routines (case-insensitively) before anything is written.
- The default agent can't be retired; renaming it updates `default_agent`.

## 7. Testing
Unit tests for every command: preview writes nothing; apply writes exactly the expected files; inference (model → CLI, defaults, safety defaults by connection); rename and retire update every reference; retire hands over tickets and archives; restore; refusals (duplicates, unknown connections, the default agent, secrets, invalid skill names, existing folders); rollback when sync fails. Content tests: every documented command parses; skills are published. One live test: create an agent pinned to Codex through the command and run its introduce-yourself quick ask.

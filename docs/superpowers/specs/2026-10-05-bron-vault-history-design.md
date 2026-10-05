# Bron Vault History

Status: design approved in conversation on 2026-10-05, section by section. Builds on 0.8.2. Ships as 0.9.0. Fills in the one line the core design promised (`2026-10-01-bron-core-design.md` §10.3, "History"): Bron keeps the vault as a private git repository for a full change history.

## 1. Purpose

Three goals, chosen by the user:
- **Undo agent mistakes:** see what an agent changed and put back the earlier version.
- **Audit trail:** a dated record of every change, saying who made it (the user or a named agent), in which conversation or ticket, and why.
- **Off-Mac backup (optional):** a copy of the history outside the Mac, so the vault survives a lost or broken Mac.

Not a goal: comparing the wiki over time as a feature of its own (the history makes it possible, but nothing is built for it).

Hard constraint from the user: it must not add noticeable time to a turn. Everything below is designed around measured costs (§9).

## 2. Decisions (approved by the user)

- **D1. Local by default.** History stays on the Mac. The off-Mac copy is off until the user turns it on and picks where it goes.
- **D2. On for every vault.** New vaults start with history on. Existing vaults turn it on at the 0.9.0 update, with one line in the next briefing. `history: enabled: false` in Settings turns it off.
- **D3. Save at each turn, with who did it** (approach A, over timed autosave and saving only on Bron's commands):
  - when the user sends a message, changes made since the last save are saved as the user's;
  - when the agent finishes, that turn's changes are saved as the agent's.
- **D4. History is never rewritten.** Restoring and undoing make new saves. No reset, no force-push, no deleting saves.
- **D5. Plain words, not git.** The user asks in words. Saves are numbered (#1, #2…), and the `history` skill turns requests into `bron history` commands.
- **D6. Backup destinations:** a folder (for example in Google Drive), written as a single bundle file; or a private git repository (for example on GitHub), pushed to.

## 3. The repository

- **Location:** a git repository at the vault root (`<vault>/.git`).
- **Identity:** set in the repository's own config, never the global one: `user.name = Bron`, `user.email = bron@vault.local`. Each save's author names who made the change (§4.3); the committer is always Bron.
- **Local config Bron sets:** `commit.gpgsign=false`, `core.hooksPath=` (empty, so personal git hooks never run), `core.fsmonitor=false`, `core.quotepath=false` (accented file names stay readable), `gc.auto=0`. Packing is done by `bron history` maintenance during the daily check, never inside a turn.
- **Branch:** one branch, `main`.
- **Already a git repository:** if the vault already has a `.git` that Bron didn't create (there's no `bron.history = true` in its config), Bron leaves it alone and its history stays off. The health check says why and how to proceed.

### 3.1 What is kept

Everything in the vault except what's left out below. That covers `Knowledge/` (including `Knowledge/Files/`, kept copies of Mac files that exist nowhere else), `Projects/`, `Routines/`, `Tickets/`, `System/` (agents, memory, settings, skills, connections, and `System/Core` too, so an update shows up as one save), and `.obsidian/` settings.

### 3.2 What is left out

Bron owns a section of the vault's `.gitignore` between two marker lines and rewrites it on every sync. The user's lines outside the markers are kept.

```
# >>> Bron (managed; edit outside these lines)
.bron/
.claude/
.codex/
.agents/
AGENTS.md
CLAUDE.md
.obsidian/workspace.json
.obsidian/workspace-mobile.json
.obsidian/workspaces.json
.trash/
.DS_Store
# <<< Bron
```

The generated files (`.claude/`, `.codex/`, `.agents/`, `AGENTS.md`, `CLAUDE.md`) are rebuilt from `System/`, so the history of `System/` already records every setup change, permissions included.

### 3.3 Finding git without a pop-up

On a Mac without Apple's command line tools, running `/usr/bin/git` opens an "install developer tools" window. A trigger must never do that. Bron picks git once, caches the choice in `.bron/state/history.json`, and re-checks during the daily health check:
1. a `git` on `PATH` that isn't `/usr/bin/git` (for example Homebrew's);
2. otherwise `/usr/bin/git`, but only if `xcode-select -p` prints a folder that contains `usr/bin/git`.

If neither works, history is unavailable. Saves are skipped silently, and the health check says how to install the tools (`xcode-select --install`).

## 4. Saving

### 4.1 When the user sends a message (synchronous, budget 50 ms)

In the `user-prompt` trigger, before anything else:
1. If history is off or unavailable, stop.
2. Run `git status --porcelain=v1 -z --untracked-files=all`. If it's empty, stop (~15 ms).
3. Otherwise `git add -A` and commit as the user (§4.3), message `You: edits in the vault`.
4. Record the prompt's first 80 characters, the session id and the agent in `.bron/state/history-turns.json` for the save at the end of the turn.

This runs before the agent can write, so the user's edits are never mixed into an agent's save.

### 4.2 When the agent finishes (background, no waiting)

The `stop` trigger starts a detached `bron history save --turn` (through the existing `spawn_detached`) and returns at once. The detached save:
1. takes the history lock (§4.4);
2. checks status; if nothing changed, stops;
3. `git add -A` and commits as the agent, with the message and trailers in §4.3.

Background ticket runs fire the same `stop` trigger, so their saves carry the agent and the ticket.

### 4.3 Who a save is credited to

| Save | Author | Subject line |
|---|---|---|
| user's edits | `<user name from Settings> <user@vault.local>` ("You" if no name) | `You: edits in the vault` |
| agent's turn | `<agent name> <agent-key@vault.local>` | `<Agent> (<Claude Code\|Codex>): <first 80 characters of the request>` |
| ticket run | `<agent name> <agent-key@vault.local>` | `<Agent> (<app>), ticket <id>: <ticket title>` |
| restore or undo | the agent that ran it | `<Agent>: restored "<page>" to #<n>, asked by <user name>` / `<Agent>: undid #<n>, asked by <user name>` |
| first save | Bron | `Bron: vault created` / `Bron: history started (0.9.0)` |
| update | Bron | `Bron: updated to <version>` |

Every save also carries git trailers that `bron history` uses to filter:
- `Bron-Agent: <key>`
- `Bron-App: <claude|codex>`
- `Bron-Session: <session id>`
- `Bron-Ticket: <id>`, when there is one
- `Bron-Also-Running: <ticket ids>`, when a background ticket run was active during the turn, since its changes can then land in this save (the known imperfection of D3)

The agent is resolved the way the briefing does it: `BRON_AGENT`, else the default agent.

### 4.4 The lock

- Saves take `.bron/state/history.lock` (the existing `statefile.locked`).
- A save that can't get it within 2 s gives up; the next save picks up its changes.
- The synchronous user-prompt save waits at most 0.5 s and otherwise skips. This keeps the turn fast.
- A skip is recorded in `history-turns.json`. The agent's save at the end of that turn then carries `Bron-Includes-User-Edits: yes`, so the user's edits are never silently credited to an agent.

### 4.5 Failures

A failed save never fails a turn: errors go to `.bron/logs/history.log`. The health check reports repeated failures, the last error and the last successful save.

## 5. Looking back and putting back (`bron history`)

All output is in plain words, in local time, and newest first.

| Command | What it does |
|---|---|
| `bron history [<page or folder>] [--since <date or time>] [--agent <name>] [--ticket <id>] [--limit N]` | One line per save: `#142  Oct 5 16:47  Bron (Claude Code): Talisman position has closed…  3 pages` |
| `bron history show <n>` | The pages a save touched and, for each, the lines removed and added (a capped diff). |
| `bron history restore '<page>' --to <n or date/time> [--preview]` | Puts one page (or a folder) back as it was at that save or time; brings back a deleted page. The preview shows the difference. |
| `bron history undo <n> [--preview]` | Reverses exactly the changes of save #n. If any page it touched was changed again after #n, it refuses and names those pages; the user can then restore them one by one or leave them. |
| `bron history status` | On or off, the number of saves, size, last save, the backup destination and the last successful backup. |
| `bron history backup --to '<folder or repo>' [--preview]` / `--off` | Sets or removes the off-Mac copy (§6). |
| `bron history recover --from '<bundle file or repo>' '<new vault folder>'` | Rebuilds a vault from a backup (§6.4). |

**Save numbers:** #n is the position of the save on `main`, counted from #1. They stay fixed because history is never rewritten (D4).

**Restore and undo:** like every change, these are previewed and applied only after the user's yes. Restoring a file in `System/` also falls under rule 1 (show the change, get a yes). After applying, Bron makes the save immediately with the subject in §4.3.

**`--to` accepts** `#n`, `n`, `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`, meaning the last save at or before that time. The agent turns "this morning" into a time.

## 6. The off-Mac copy (optional)

### 6.1 Setting it

- "Back up my history to Drive" (or "to GitHub"): the agent asks where, then runs `bron history backup --to '<folder or repo>' --preview` and applies after a yes.
- This writes `history: backup: <destination>` in Settings.
- It counts as the user's one explicit approval for that destination (rule 5), so later backups don't ask. Changing or removing it previews and asks again.

### 6.2 Destinations

- **A folder:** the whole history is written as one file, `<vault folder name>.history.bundle` (`git bundle create --all`).
  - Bron writes it as `.<name>.tmp` in the same folder, checks it with `git bundle verify`, then renames it into place, so a sync tool never sees half a file.
  - One file is also safer than a git folder inside a synced folder.
- **A git repository** (an `ssh` or `https` address): `git push <destination> main`, which sends only what's new.
  - It runs with `GIT_TERMINAL_PROMPT=0` and `ssh -o BatchMode=yes`, so a missing key or login fails at once instead of waiting for input.

### 6.3 When it runs

- At the end of each session (`session-end` trigger), and from the `stop` trigger at most every 30 minutes.
- Always detached, and only when there are saves since the last backup.
- `.bron/state/history.json` records the last attempt, the last success and the last error.
- A failure never stops work. The next briefing says it once ("History backup to Google Drive failed: the folder wasn't found"), and the health check reports it until a backup succeeds.

### 6.4 Recovering on a new Mac

`bron history recover --from '<file or repo>' '<folder>'`:
1. clones into a new folder (refusing a folder that isn't empty);
2. applies the local config of §3;
3. installs Bron's machine part (`.bron/`, as the installer does) and runs sync.

The search index and models then rebuild on first use, as in any fresh vault. Wiki pages are text in the history, so nothing needs reading again.

## 7. Settings, setup and updates

- **Settings:** `System/Settings.md` gets:

  ```yaml
  history:
    enabled: true
    backup: ""
  ```

  It also gets an explanation line in the body, like the other settings.
- **New vault:** the installer (and `dev-vault.sh`) creates the repository, writes the ignore section and makes the first save `Bron: vault created`.
- **Existing vault:** a 0.9.0 migration does the same, with `Bron: history started (0.9.0)`. The migration's one-line notice goes to the next briefing ("Bron now keeps a change history of this vault, on this Mac only. Say 'what changed today?' or 'undo that'.").
- **Updates:** after an update is applied, Bron saves `Bron: updated to <version>`, so an update is one clearly labelled save. An undone update ("undo the update") is a save too.
- **Health check** (`bron check`):
  - history on and working;
  - git available;
  - an untouched foreign repository (§3);
  - repeated save failures;
  - backup failures;
  - history over 1 GB;
  - packing (`git gc --auto`, at most once a day).

## 8. Instructions for agents

- **New core skill `history`:** what changed, show a save, restore a page, undo a turn, set up or remove the backup, recover. Covers previews and the yes before restore, undo and backup changes, and the refusal path of undo.
- **AGENTS.md:** one line, "Change history and undo: the history skill." It must stay under the 8 KB limit (the test exists).
- **Manual:** new `System/Core/Manual/history.md`, linked from `index.md`.

## 9. Speed

Measured on a copy of a real vault (296 files) on 2026-10-05:

| Step | Time |
|---|---|
| status, nothing changed | 15 ms |
| save one changed page | 32 ms |
| save 7 changed pages | 36 ms |
| first save of the whole vault (once) | 235 ms |
| history size | 1.2 MB |

**Budgets, enforced by a speed test:**
- the user-prompt step must take under 50 ms when nothing changed, and under 100 ms with a few changed pages, on a 300-file vault;
- the stop trigger must return without waiting for git.

**Further rules:**
- `bron.history` imports nothing heavy; the triggers already pay for starting Python.
- No backup, packing or diff work ever happens inside a turn.

## 10. Both apps

- Claude Code and Codex fire the same four triggers (`session-start`, `user-prompt`, `stop`, `session-end`), so both behave identically.
- The app is recorded in each save (`Bron-App`).

## 11. Testing

**Unit tests, test-first:**
- creating the repository and its local config; leaving a foreign repository alone;
- the ignore section, keeping the user's lines;
- picking git without the shim (the shim simulated);
- the user's save before the agent's; credit, trailers and subjects for each kind of save; nothing to save;
- the lock: the 2 s give-up, and the 0.5 s skip on user-prompt;
- save numbers; `history` filters by page, time, agent and ticket;
- `show`;
- `restore`, by number and by time, of a deleted page and of a folder, with preview;
- `undo`, with preview, and its refusal when a page changed later;
- backup to a folder (atomic rename; `git bundle verify`), backup to a repository (a local bare repository standing in for GitHub), the time gate, and failures recorded and reported once;
- `recover` from a bundle and from a repository;
- the migration (on, first save, briefing note) and the update save;
- settings: `enabled: false` stops saves.

**Hook tests:** the user-prompt trigger saves the user's edits before routing; the stop trigger spawns the detached save and returns.

**Speed test:** the budgets in §9 (marked slow, like the knowledge base's).

**Live test, both apps:** one turn that edits a page produces one save credited to the right agent and app; "undo that" previews and restores the page; a Drive-folder backup produces a bundle that `recover` turns back into a working vault.

## 12. Out of scope

- browsing history inside Obsidian;
- branches;
- sharing history between team members;
- the Obsidian Git plugin;
- a separate "compare over time" feature (the user didn't choose it; `history show` and `restore --preview` cover single pages).

## 13. Risks

- **Mixed saves:** a background ticket that writes during an interactive turn lands in that turn's save. This is marked with `Bron-Also-Running`. Accepted by the user as the cost of approach A.
- **Big kept files:** many large PDFs in `Knowledge/Files/` grow the history and the bundle (the bundle is rewritten whole each time). The 1 GB warning flags it; a later version could make bundles incremental.
- **A user who already uses git in the vault:** left alone (§3), with no history from Bron. They keep their own setup.

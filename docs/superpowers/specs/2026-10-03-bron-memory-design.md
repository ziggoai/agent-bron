# Bron Memory (sub-project 2)

Status: design approved in conversation on 2026-10-03. Fills the reserved interface in the core spec (`2026-10-01-bron-core-design.md` §8.2) and builds on the framework as shipped in 0.5.0. Where they disagree, this spec wins.

## 1. Purpose

You never have to repeat yourself. Bron and every agent remember your preferences, decisions and key facts about you and the fund, and can pick up where you left off, in Claude Code and in Codex alike, without slowing conversations down. Everything remembered is a readable note in the vault that you can open, edit or delete.

## 2. Decisions (approved by the user)

- **D1. What is kept:** lasting facts, plus a short searchable summary of every conversation (not full transcripts).
- **D2. Saving facts:** the agent saves a fact itself and says so in one line ("Noted: …"). "Forget that" / "that's wrong" removes or corrects it at any time.
- **D3. Who sees what:** shared facts (about you, the firm, decisions everyone follows) are seen by every agent; each agent also keeps its own work notes.
- **D4. Summaries:** written automatically in the background by a small fast model when a conversation ends; conversations that end without notice are caught up at the next session start.
- **D5. Start-up:** each agent starts with the facts and the titles of its last few conversations; older history is searched on demand.
- **D6. Storage:** readable notes in the vault are the truth; a hidden search index follows them.

## 3. Files

### 3.1 Facts
- Shared: `System/Memory/Facts.md`. Per agent: `System/Agents/<Name>/Memory/Facts.md`. Created on first save (and by the template for Bron).
- Four fixed sections, in this order: `## About you`, `## Your firm`, `## Decisions`, `## How you like things done`. One fact per line:
  `- <fact>. (<YYYY-MM-DD>, <Agent name>)`
- No frontmatter. The user may edit freely; Bron reads the file as it is (lines that aren't facts are kept untouched; facts under an unknown heading still count).
- Limits: the shared file aims at about 40 facts (≈4,000 characters), an agent's file at about 25 (≈2,500). Saving never fails because of size; at 90% the save message adds "Memory is getting long; I can tidy it" and the health check warns.

### 3.2 Conversation summaries
- `System/Agents/<Name>/Memory/Conversations/<YYYY-MM>/<YYYY-MM-DD HH.MM> <Title>.md`, under the agent the conversation was with (the session's agent; the default agent when none was named).
- Frontmatter: `date`, `cli`, `agent`, `session_id`, `transcript` (path to the CLI's own transcript file), `messages` (count summarised). Body: `## Asked`, `## Decided`, `## Open` (short bullets; "Nothing" when empty). Title: at most 6 words.
- One note per conversation, keyed by `session_id`: a resumed or compacted conversation updates its note (same file; renamed if the title changes).
- Not summarised: ticket runs and @-mention chats (already recorded in `Tickets/`), and conversations with no real exchange (fewer than one user message and one reply).

### 3.3 Hidden state
- `.bron/memory/index.db`: SQLite FTS5 search index (tokenizer `unicode61 remove_diacritics 2`), rebuilt incrementally from the notes.
- `.bron/memory/summaries.json`: per session: status (`pending`, `done`, `failed`), attempts, last transcript size/mtime summarised, note path.
- `System/Memory/Summary.md` (read by the 0.5.0 briefing, never written) is no longer read.

## 4. Commands (`bron memory …`)

All are plain commands any agent runs in either CLI; all output is plain English.

| Command | What it does |
|---|---|
| `remember "<fact>" --as <agent> [--shared\|--mine] [--section about-you\|firm\|decisions\|how] [--replaces "<old text>"]` | Adds the fact (default `--shared`, section `decisions`); with `--replaces`, swaps the matching line. Prints "Noted: …" or "Updated: …". Refuses secrets (§7). `--shared` from a ticket run is refused ("Only a conversation with you can change shared memory; saved to my own notes instead" → saved with `--mine`). |
| `forget "<text>" --as <agent>` | Removes the one fact line containing the text (shared or the agent's own). Several matches → lists them and changes nothing. Prints "Forgotten: …". |
| `forget --conversation "<title or date>" --as <agent>` | Deletes that conversation's summary note (one match only). |
| `search "<words>" --as <agent> [--all] [--limit 8]` | Searches shared facts, the agent's own facts and its conversations (`--all`: every agent's). Each result: date, where (shared / own / conversation title), a short excerpt, the note path. |
| `tidy --as <agent> [--shared\|--mine] --file <draft> [--preview]` | Replaces a facts file with a reviewed draft the agent wrote; `--preview` shows what changes (kept / merged / dropped counts and the dropped lines); applied only after the user's yes, through the setup change runner (lock, backup, rollback). |
| `summarize [--pending] [--session <id>]` | Internal: writes or updates summaries (§5). |

Writes go through one lock (`.bron/state/memory.json`) so two sessions can't clobber a file. Saving a memory is the one change to `System/` (besides the user's name/role/company) that needs no separate yes; the "Noted:" line is the notice.

## 5. Automatic summaries

- **Trigger:** the existing `session-end` and `pre-compact` triggers (both CLIs) start `bron memory summarize --session <id>` as a detached background process and return at once. At session start, Bron starts `bron memory summarize --pending` in the background, which picks up: sessions whose transcript grew since its last summary and that have been quiet for 30 minutes, and `pending`/`failed` sessions with fewer than 3 attempts. Only one summarizer runs at a time (lock); others exit quietly.
- **Which sessions:** taken from `.bron/state/markers.jsonl` (session id, CLI, agent, transcript path). Markers from ticket runs (`BRON_TICKET` set) and summarizer runs (§5 below) are skipped.
- **Input:** only the typed messages and replies (the existing transcript reader), not tool calls or file contents. Long conversations: the first 20,000 and the last 60,000 characters, with a marker in between.
- **Model:** the conversation's own CLI with its small model, run headless, with no tools, from a temporary folder outside the vault (so the vault's triggers, settings and memory never load), with `BRON_MEMORY_JOB=1` set. Settings: `memory.summary_model` (defaults: Claude Code `haiku`; Codex `gpt-6-luna` with low reasoning effort). `memory.summaries: false` turns summaries off.
- **Output contract:** the model returns a title and the three sections; Bron writes the note itself (the model never writes files). Unusable output counts as a failed attempt.
- **Failures:** offline, logged out, or a bad answer → `failed`, retried at the next session start; after 3 attempts it stops and the health check mentions it once. Nothing is ever shown in the conversation.
- **Privacy:** the text goes only to the provider that already handled the conversation. Nothing new leaves the Mac.

## 6. Recall

- **Briefing (session start):** a `## What you remember` section with the shared facts, then `### Your own notes`, then `### Recent conversations` (date + title of the agent's last 5 summaries). Caps: shared 4,000 characters, own 2,500, recents 5 lines; anything cut ends with "…and N more; search memory". The briefing's total limit rises from 6,000 to 10,000 characters. Ticket runs get the facts but not the recent conversations.
- **Rules in AGENTS.md** (a short "Memory" section, so no skill has to be loaded):
  1. When the user states a lasting preference, decision or fact, or corrects you, save it (`remember`) and say "Noted: …" in one line. Shared for facts about the user, the firm and decisions everyone follows; `--mine` for how you do your own work. If it contradicts a saved fact, use `--replaces`.
  2. When the user says "forget that" / "that's wrong", use `forget` (and `remember` the correction if they gave one).
  3. When the user refers to something from before ("last time", "what did we decide"), run `search` before asking them.
  4. Never save passwords, keys, tokens, account numbers or sensitive personal details about other people.
- **Search speed:** under 0.2 s for thousands of notes; the index refreshes from file modification times on each search (no background service).

## 7. Safety

- `remember` refuses text that looks like a secret: known key prefixes (`sk-`, `ghp_`, `xox`, `AKIA`, `-----BEGIN`), long random tokens (24+ characters mixing letters and digits), card numbers (13–19 digits passing Luhn), IBANs, and "password/senha: …" forms. Message: "That looks like a password or key, so I didn't save it."
- Memory lines are plain text: when facts are put into the briefing, they are quoted as data under a heading that says they are notes, not instructions.
- Deleting a summary note never touches the CLI's own transcript.

## 8. Health check additions

- A facts file at 90% of its limit or more (warning, offers tidy).
- Summaries that failed 3 times (warning, once per session).
- A facts file that can't be read (error).
- Settings: `memory.summary_model` names a model the CLI doesn't know (warning, when checkable).

## 9. Error handling

Every memory command prints a plain reason on failure and changes nothing. The background summarizer never writes to the conversation and logs to `.bron/logs/memory.log`.

## 10. Testing

- Unit: remember / update / forget / ambiguous forget / secret refusal / ticket-run shared refusal; facts file parsing with user edits; tidy preview and apply with rollback; search (English, Portuguese, accents, both scopes, `--all`); briefing caps and ticket-run variant; summarizer with stand-in transcripts from both CLIs and a stand-in model (success, update on resume, skip rules, failure and retry, give-up after 3, one-at-a-time lock); markers from ticket and summarizer runs skipped.
- Live (one per CLI): save a fact, end the conversation, see the summary note appear, start a new session and get the fact and the title in the briefing, and find the conversation with search.

## 11. Verified before planning (2026-10-03)

1. Claude Code: `claude -p --model haiku --tools "" --no-session-persistence --setting-sources ""`, prompt on stdin, run from a temporary folder: one-line summary in about 4 s, no session saved, no settings or triggers loaded.
2. Codex: `codex exec --ephemeral --skip-git-repo-check -s read-only -m gpt-6-luna -c model_reasoning_effort=low -`, prompt on stdin, from a temporary folder: about 9 s, nothing saved. Default Codex summary model: `gpt-6-luna` ("fast and affordable model for easier tasks"), overridable in Settings.
3. FTS5 with `unicode61 remove_diacritics 2` works in the uv-managed Python 3.12 ("relatorio" finds "Relatório").
4. Both CLIs already write `session-end` markers with session id and transcript path (seen in the test vault: 42 session-end, 77 stop markers). A closed window may skip `session-end`; the catch-up at session start covers it.

## 12. Release

Ships as 0.6.0 with a CHANGELOG entry. No migration is needed (the memory folders are empty in existing vaults).

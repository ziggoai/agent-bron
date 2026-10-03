# Memory

What Bron remembers between conversations, and where it keeps it.

## Facts

- When you tell Bron something lasting (a preference, a decision, a fact about you or the fund), it saves one line and says "Noted: ...". If the new fact replaces an old one it says "Updated: ...".
- "Forget that" removes the line and Bron says "Forgotten: ...".
- Shared facts live in `System/Memory/Facts.md` and every agent sees them. Only a conversation with you can change them. Each agent also keeps its own work notes in `System/Agents/<Name>/Memory/Facts.md`.
- A file has four sections: `## About you`, `## Your firm`, `## Decisions`, `## How you like things done`. A line looks like `- <fact>. (2026-10-03, Bron)`.
- They are ordinary notes. Open them in Obsidian and edit or delete lines freely; Bron keeps your wording and anything else you add.

## Conversation summaries

- After a conversation ends, a small model writes a short summary in the background: what was asked, decided and left open. It is saved as a note in `System/Agents/<Name>/Memory/Conversations/<year-month>/`.
- A conversation you resume updates its note instead of adding a second one.
- Settings, in `System/Settings.md`:

```yaml
memory:
  summaries: true
  summary_model:
    claude: haiku
    codex: gpt-6-luna
```

- Turn summaries off with `summaries: false`. Change the model per app with `summary_model`.
- Summaries use the same login and plan as the app the conversation was in (Claude Code or Codex), so they count towards that plan's usage. If you set `ANTHROPIC_API_KEY` for Claude Code, summaries use that key too.
- After an update, conversations from the last two weeks get summaries gradually, a few at the start of each session.
- A conversation you forget ("forget the conversation about …") is never summarised again, even if you resume it.
- If a summary can't be written (offline, logged out), Bron retries later and gives up after 3 tries. The health check tells you when that happens, and the details are in `.bron/logs/memory.log`.

## Searching

- Ask "what did we decide about ...?". Bron searches facts and summaries, in English or Portuguese, with or without accents ("relatorio" finds "Relatório").
- Command: `.bron/bin/bron memory search "<words>" --as <Agent>` (add `--all` to search every agent's notes).

## Limits and tidying

- Shared facts hold about 4,000 characters, an agent's own notes about 2,500. Saving never fails because of size. At 90% Bron says memory is getting long and the health check warns.
- Ask Bron to "tidy memory": it shows a shortened version, names the file it will replace and lists any fact it no longer keeps as written, then waits for your yes. If a fact is saved in between, Bron shows the tidy again instead of dropping it.
- The briefing at the start of a session shows the facts and the 5 most recent conversations; the rest is found by searching.

## What is never saved

- Passwords, keys and tokens. If you tell Bron one, it says "That looks like a password or key, so I didn't save it." Conversation summaries leave them out too.
- Ticket runs read facts but don't write summaries.

## Where things are

- Your notes: `System/Memory/` and `System/Agents/<Name>/Memory/`.
- Hidden helpers (search index, summary progress): `.bron/memory/`. The search index is rebuilt by Bron if you delete it.
- `System/Memory/Summary.md` from earlier versions is no longer read. The health check reminds you while it exists; ask Bron to move what matters into `Facts.md`.

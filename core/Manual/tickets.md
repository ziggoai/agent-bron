# Tickets

A ticket is one note in `Tickets/` (`T-0042 <Title>.md`) that hands work from one agent (or you) to another.

| Status | Meaning |
|---|---|
| backlog | not scheduled yet |
| todo | waiting to be worked |
| in-progress | an agent is working it right now |
| blocked | the agent needs an answer, or your OK for an action ("Needs your OK: …") |
| in-review | the agent finished; the result is in `## Result` (continues only with `--resume`) |
| done / cancelled | closed |

The body has four parts: **Request** (what to do), **Context** (what they need to know), **Thread** (dated messages), **Result** (summary and links to outputs). You can type in a ticket in Obsidian; write new thread lines as `- your message`. When you're done typing, ask Bron to resume it (`.bron/bin/bron run <id> --resume --background --caller-cli <your-cli>`).

## Commands (from the vault folder)
Put free text in single quotes; if the text contains a single quote, write it to a file and use `--file` (result) or `--note-file` (status).
- `.bron/bin/bron ticket new --to <Agent> --from <requester> --title '…' --request '…' [--context '…'] [--project '…']` (or `--request-file` / `--context-file`)
- `.bron/bin/bron run <id> [--resume] [--background] [--caller-cli claude|codex]`: the assignee works it, in its own CLI and model
- `.bron/bin/bron ticket say <id> '<text>' --as <name>`
- `.bron/bin/bron ticket status <id> <status> [--note '…' | --note-file <path>] --as <name>` (`--note-file -` reads standard input)
- `.bron/bin/bron ticket result <id> --text '…' | --file <path> --as <name>`
- `.bron/bin/bron ticket show <id>`
- `.bron/bin/bron ticket list [--for <agent>] [--open]`

## How a run works
The assignee works in the background, in the CLI its `runs_in` names (or the requester's CLI). It may read and write files in the vault and run ordinary commands. Anything on its `ask_before` list is refused while it works alone; the ticket becomes blocked with "Needs your OK: <action>". The requester shows you the action, does it after your yes, and resumes the ticket, which continues the same conversation. Updates appear in the requester's next message or session.

`Tickets/Board.base` shows the tickets by status and by assignee.

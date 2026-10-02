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

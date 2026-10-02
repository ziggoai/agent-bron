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
- `.bron/bin/bron ticket new --to <Agent> --from <requester> --title '…' --request '…' [--context '…'] [--project '…'] [--run --caller-cli claude|codex]` (or `--request-file` / `--context-file`); `--run` starts it straight away and waits for the answer
- `.bron/bin/bron run <id> [--resume] [--wait | --background] [--caller-cli claude|codex]`: the assignee works it, in its own CLI and model. `--wait` prints the answer when it's ready; `--background` returns straight away and the update arrives in the requester's next message
- `.bron/bin/bron ticket say <id> '<text>' --as <name>`
- `.bron/bin/bron ticket status <id> <status> [--note '…' | --note-file <path>] --as <name>` (`--note-file -` reads standard input)
- `.bron/bin/bron ticket result <id> --text '…' | --file <path> --as <name>`
- `.bron/bin/bron ticket show <id>`
- `.bron/bin/bron ticket list [--for <agent>] [--open]`
- `.bron/bin/bron ticket wait <id> [<id> …]`: wait for those tickets' runs to finish and print each answer

## How a run works
The assignee works in the CLI its `runs_in` names (or the requester's CLI). The ticket's request and context are in its instructions, and its final reply becomes the Result, so a simple request takes one step (about 10–20 seconds). It may read and write files in the vault and run ordinary commands. Anything on its `ask_before` list is refused while it works alone; the ticket becomes blocked with "Needs your OK: <action>". The requester shows you the action, does it after your yes, and resumes the ticket, which continues the same conversation.

The requester normally waits for the answer and shows it to you as soon as it's ready: in Claude Code it runs the command as a background task, which wakes it when the answer arrives (you can keep talking meanwhile); in Codex it waits for the command. For long work you don't want to wait for, it uses `--background`, and the update appears in its next message or session.

## Chats with @-mentions
Write `@cfo` (any agent's name) in a message in any session and that agent answers it. The message trigger starts the agent straight away, with your message and the last few exchanges of the chat, on its own model and CLI. The session's agent waits with `.bron/bin/bron ticket wait <id>` and shows the reply word for word. Follow-ups to the same agent in the same session continue the same conversation. Tag several agents and each answers separately. Each conversation is a chat ticket (`kind: chat`), hidden from the board's main views, closed when the session ends (or after 12 hours without activity). A message without a tag goes to the session's own agent.

`Tickets/Board.base` shows the tickets by status and by assignee.

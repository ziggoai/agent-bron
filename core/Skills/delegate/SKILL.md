---
name: delegate
description: Hand work to a team member through a ticket and follow it up, including questions and approvals. Use for longer work that belongs to another agent ("ask the CFO to prepare…"), when a ticket update arrives, or when a ticket is blocked. Quick questions use the one command in the shared rules instead.
---

# Delegate through tickets

`<you>` and `<your name>` in commands below mean your agent name (e.g. Bron, or cfo in lower case with hyphens for flags).

Put free text in single quotes; if the text contains a single quote, write it to a file and use `--file` (result) or `--note-file` (status), or `--request-file` / `--context-file` for a new ticket.

## Hand off
1. Don't look anything up first: the command below refuses if you aren't allowed to hand work to that team member. If it says so, tell the user and offer to add them to your `can_assign_to` (show the change first).
2. Write the request so it stands on its own: what to do, what "done" looks like, and the context they need (excerpts, file links, numbers).
3. Create the ticket and start it in one command, from the vault folder, naming the CLI you are in:
   `.bron/bin/bron ticket new --to <Agent> --from <your name> --title '<short title>' --request '<request>' [--context '<context>'] [--project '<Project or Routine>'] --run --caller-cli <claude|codex>`
   It prints "Created T-…", waits for the team member, then prints the outcome and, when finished, the Result.
   - **Quick work** (a question, a short check, anything you expect back within a couple of minutes): run it as an ordinary command and wait for it, in either CLI (give it a timeout of 10 minutes if your command tool takes one). The answer comes back in the same turn.
   - **Longer work in Claude Code:** run it with your Bash tool's `run_in_background: true` (timeout 1800000). Tell the user in one line who is working on what, then end your turn: Claude Code wakes you with the output as soon as it's ready. Never poll or sleep while waiting.
   - **Longer work in Codex:** run it and wait for it to finish (give it a timeout of at least 30 minutes if your command tool takes one).
   - In Codex, `bron` starts another program that needs the network; if Codex asks for permission to run it outside the sandbox, approve it (or ask the user to).
4. When the output arrives, handle it right away as below. For in-review, give the user the answer first, then mark it done. This update won't be repeated in a later message.
5. For long work the user doesn't want to wait for, create the ticket without `--run`, then start it with `.bron/bin/bron run <ticket id> --background --caller-cli <claude|codex>` (if the output doesn't start with "Started", tell the user what it said instead). Its update arrives in your next message or session.

## When an update arrives (in your briefing or before a message)
- **in-review:** read the Result (it's in the output when you waited; otherwise `.bron/bin/bron ticket show <id>`) and check it. If it's good, give the user the answer first, then mark it done (`.bron/bin/bron ticket status <id> done --as <you>`) or send it back with a message and resume it.
- **blocked with a question:** answer it if you can, otherwise ask the user. Write the answer with `.bron/bin/bron ticket say <id> --as <you> '<answer>'`, then continue the same conversation: `.bron/bin/bron run <id> --resume --wait --caller-cli <claude|codex>` (run it the same way as in step 3).
- **blocked with "Needs your OK: …":** show the user the exact action. If they say yes, do that action yourself now (your CLI will ask them to confirm as usual), write what happened with `.bron/bin/bron ticket say <id> --as <you> '<what you did>'`, and resume the ticket. If they say no, say so in the ticket and resume it, or cancel it (`.bron/bin/bron ticket status <id> cancelled --as <you>`).
- **blocked by the runner** (no question, no "Needs your OK", a note such as "isn't installed", "took longer than the time limit", "ended without an answer", "The run failed", "The run stopped before it finished" or "setup has problems"): read the last thread line (and the `.bron/runs/…` log it names), tell the user plainly what happened, then fix the cause and resume, or cancel.

## Never
- Never run a team member as a subagent: tickets only.
- Never work around a refused action.

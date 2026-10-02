---
name: delegate
description: Hand work to a team member through a ticket and follow it up, including questions and approvals. Use when work belongs to another agent ("ask the CFO to…"), when a ticket update arrives, or when a ticket is blocked.
---

# Delegate through tickets

`<you>` and `<your name>` in commands below mean your agent name (e.g. Bron, or cfo in lower case with hyphens for flags).

## Hand off
1. Check the team member is in your `can_assign_to` (System/Agents/<You>/Agent.md). If not, tell the user and offer to add it (show the change first).
2. Write the request so it stands on its own: what to do, what "done" looks like, and the context they need (excerpts, file links, numbers).
3. Create the ticket from the vault folder:
   `.bron/bin/bron ticket new --to <Agent> --from <your name> --title "<short title>" --request "<request>" [--context "<context>"] [--project "<Project or Routine>"]`
4. Start it in the background, naming the CLI you are in:
   `.bron/bin/bron run <ticket id> --background --caller-cli <claude|codex>`
   If the output doesn't start with "Started", tell the user what it said instead.
   In Codex, `bron run` starts another program that needs the network; if Codex asks for permission to run it outside the sandbox, approve it (or ask the user to).
5. Tell the user in one line who is working on what, and that you'll report back.

## When an update arrives (in your briefing or before a message)
- **in-review:** read the result (`.bron/bin/bron ticket show <id>`), check it, tell the user, then mark it done (`.bron/bin/bron ticket status <id> done --as <you>`) or send it back with a message and resume it.
- **blocked with a question:** answer it if you can, otherwise ask the user. Write the answer with `.bron/bin/bron ticket say <id> --as <you> "<answer>"`, then continue the same conversation: `.bron/bin/bron run <id> --resume --background --caller-cli <claude|codex>`.
- **blocked with "Needs your OK: …":** show the user the exact action. If they say yes, do that action yourself now (your CLI will ask them to confirm as usual), write what happened with `.bron/bin/bron ticket say <id> --as <you> "<what you did>"`, and resume the ticket. If they say no, say so in the ticket and resume it, or cancel it (`.bron/bin/bron ticket status <id> cancelled --as <you>`).
- **blocked by the runner** (no question, no "Needs your OK", a note such as "isn't installed", "took longer than the time limit", "ended without an answer" or "setup has problems"): read the last thread line (and the `.bron/runs/…` log it names), tell the user plainly what happened, then fix the cause and resume, or cancel.

## Never
- Never run a team member as a subagent: tickets only.
- Never work around a refused action.

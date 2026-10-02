---
name: create-agent
description: Set up a new team member from a plain request, like "set up a COO on Opus 5.5 that reports to you and can use Drive". Previews a plain summary, creates it after a yes, then has it introduce itself.
---

# Create an agent

1. Work out from the request: name, role, model (a Claude model means it runs in Claude Code, a GPT model means Codex), who it reports to (leave `--reports-to` out and it reports to the main agent; `--reports-to you` means the user), and which connectors it uses. Ask only for what's missing, one question at a time. Connector names must exist: check with `.bron/bin/bron connections scan` if unsure.
2. Optionally write its instructions to `.bron/tmp/<Name>-instructions.md` (Who you are / How you work / Boundaries) when the user described how it should work; otherwise Bron writes standard ones from the role.
3. Preview: `.bron/bin/bron agent create --name '<Name>' --role '<role>' [--model '<model>'] [--reports-to '<Name>'] [--connections '<connections>'] [--instructions-file <path>] --preview`
4. Show the summary as it is. It already lists the safety defaults (asking before deleting files, pushing, and sending or sharing through its connectors). Wait for a yes. If they want a change, adjust the options and preview again.
5. Apply: the same command without `--preview`.
6. Then run the quick ask: `.bron/bin/bron ticket new --to '<Name>' --from <your name> --title 'Introduce yourself' --request 'Introduce yourself in one sentence.' --run --caller-cli <claude|codex>` and show its answer, so the user sees the new agent working.

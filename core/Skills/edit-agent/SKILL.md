---
name: edit-agent
description: Change a team member (or Bron itself) — model, app, connectors, ask-first list, who it reports to, role, instructions, or its name. Use for requests like "give the CFO access to Drive", "stop using a connector" or "make the CFO run on GPT".
---

# Change an agent

1. Pick the options that match the request:
   - model: `--model '<model>'` (or `claude=<model>` / `codex=<model>`); a model for the other app also moves the agent to that app
   - app: `--runs-in any|claude|codex`
   - connectors: `--add-connection '<connection>'`, `--remove-connection '<connection>'` (adding one also adds its send/share safety entries). When the user says not to use a connector, remove it here rather than saving a memory; if the list is `all`, use `--remove-connection all` plus an `--add-connection` for each one to keep
   - ask-first list: `--add-ask '<entry>'`, `--remove-ask '<entry>'`
   - boss: `--reports-to '<Name>'`
   - role: a new role also needs new instructions, so rewrite "Who you are" for the new role (keep the rest), write the text to `.bron/tmp/<Name>-instructions.md` and pass both: `--role '<role>' --instructions-file .bron/tmp/<Name>-instructions.md`
   - instructions: write the new text to `.bron/tmp/<Name>-instructions.md`, then `--instructions-file <path>`
2. Preview: `.bron/bin/bron agent set '<Name>' <options> --preview`. Show the summary and wait for a yes.
3. Apply: the same command without `--preview`.
4. A new name: `.bron/bin/bron agent rename '<Name>' '<NewName>' --preview`, show it, wait for a yes, apply. It updates every reference, including your settings when it's Bron.

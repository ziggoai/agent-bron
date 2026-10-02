---
action_groups:
  git-push:
    shell: [[git, push]]
  delete-files:
    shell: [[rm]]
  send-email:
    mcp:
      gmail: [send_message, send_email, reply_to_message, forward_message]
  share-file:
    mcp:
      google_drive: [share_file]
  external-post:
    mcp:
      slack: [send_message, post_message]
---

# Permissions

Each agent lists in `Agent.md`:

- `ask_before`: actions that pause and ask the user every time (Allow once / Always allow / Deny).
- `always_allow`: actions the user approved for good. "Always allow" wins over "ask before". Delete a line to start asking again.

An entry is one of:

- **An action group** from the list above (or from `action_groups` in `System/Settings.md`), such as `send-email`.
- **One tool on one connection:** `mcp:<connection>:<tool>`, such as `mcp:carta:mutate`.
- **A shell command prefix:** `shell:<words>`, such as `shell:git push`.

Groups only take effect for connections that exist in `System/Connections/`. Bron turns these rules into each CLI's own approval settings, so they work the same in Claude Code and Codex.

## Codex notes

- Codex can't ask before a native connector's tool in an interactive session, so an ask-before on a native connector isn't prompted there. Bron still enforces it in background ticket runs (the tool is switched off and the agent asks through the ticket) and in Claude Code.
- All Codex sessions in the vault share one set of shell rules: a shell command any agent asks before is asked for every agent in Codex, and a shell "always allow" only applies in Codex when every agent allows it.

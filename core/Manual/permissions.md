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

---
user_name: ""
company: ""
default_cli: claude
default_agent: Bron
runner:
  max_parallel: 3
  max_minutes: 30
action_groups: {}
---

# Settings

Bron fills this in with you during first-run setup. You can edit it yourself or ask Bron to change it.

- `default_cli`: the CLI used when nothing else decides (claude or codex).
- `default_agent`: who answers when you open a session and just type.
- `runner`: how many tickets may run at once, and for how long.
- `action_groups`: your own named groups of actions for `ask_before` (see System/Core/Manual/permissions.md).

---
user_name: ""
company: ""
default_cli: claude
default_agent: Bron
runner:
  max_parallel: 3
  max_minutes: 30
update_check: true
action_groups: {}
---

# Settings

Bron fills this in with you during first-run setup. You can edit it yourself or ask Bron to change it.

- `default_cli`: the CLI used when nothing else decides (claude or codex).
- `default_agent`: who answers when you open a session and just type.
- `runner`: how many tickets may run at once, and for how long.
- `update_check`: Bron checks once a day whether a new version is out and tells you; set it to false to stop that.
- `action_groups`: your own named groups of actions for `ask_before` (see System/Core/Manual/permissions.md).

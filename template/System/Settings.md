---
user_name: ""
company: ""
default_cli: claude
default_agent: Bron
runner:
  max_parallel: 3
  max_minutes: 30
update_check: true
memory:
  summaries: true
  summary_model:
    claude: haiku
    codex: gpt-6-luna
knowledge:
  model_pages: true
  max_model_pages: 20
action_groups: {}
---

# Settings

Bron fills this in with you during first-run setup. You can edit it yourself or ask Bron to change it.

- `default_cli`: the CLI used when nothing else decides (claude or codex).
- `default_agent`: who answers when you open a session and just type.
- `runner`: how many tickets may run at once, and for how long.
- `update_check`: Bron checks once a day whether a new version is out and tells you; set it to false to stop that.
- `memory`: Bron writes a short summary of each conversation in the background with a small model; set `summaries: false` to stop, or change the model per app.
- `knowledge`: when a page is a scan or too messy to read directly, Bron may ask a model to read it (`model_pages`), for at most `max_model_pages` pages per document. The wiki's rules, including your document types, are in `Knowledge/Schema.md` (see System/Core/Manual/knowledge.md).
- `action_groups`: your own named groups of actions for `ask_before` (see System/Core/Manual/permissions.md).

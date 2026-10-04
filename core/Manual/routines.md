# Routines

A routine is repeating work: monthly, quarterly or annual, often once per client or per team. Nothing runs on its own: the briefing says what can start and what's due, and Bron does the work when you ask.

## Runbook: `Routines/<Routine>/Runbook.md`
```markdown
---
cadence: quarterly                 # monthly | quarterly | annual
owner: bron                        # the agent that looks after it
due: 45 days after period end      # "N days after period end" becomes a date; any other rule, Bron asks
lists:
  clients: active clients in the CRM, grouped by region
  teams: [Sales, Operations, Finance]
steps:
  - name: Collect figures
    for: clients
  - name: Review
    for: once
    items: [Sent to the managers, Back from the managers]
  - name: Summary page
    for: teams
    after: [Collect figures, Review]
---

## How to do each step
Plain instructions per step: where the template is, what to update, who to send to.
```
- A list is either fixed items or a sentence saying where the items come from; Bron gets those items when a period starts and shows them to you first. They stay fixed for that period.
- `for` is a list or `once`. `after` names earlier steps that must be finished first. A runbook without `steps` is one checklist of its first list.

## Periods and the Tracking note
- Period folders sit in the routine folder: `2026-09`, `2026-Q3`, `2026`. The period to run is the latest one that has ended.
- `<Period>/Tracking.md` has one `##` section per step and a checkbox per item, grouped under `###` headings when the list is grouped. Tick items in Obsidian or ask Bron. Notes may follow an item on the same line.
- Bron keeps `status` (todo, in-progress, done) and `progress` at the top up to date; it never changes the checkboxes.
- Outputs for the period go next to the Tracking note. `Routines/Board.base` shows every period by status.

## Commands (from the vault folder)
- `.bron/bin/bron routine list`
- `.bron/bin/bron routine start '<Routine>' [--period <period>] [--list <name>=<path>] [--due <date>]` (`--due` takes a date as YYYY-MM-DD and replaces the runbook's due rule for that period; use it when the rule isn't "N days after period end")
- `.bron/bin/bron routine refresh ['<Routine>']`

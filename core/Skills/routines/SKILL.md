---
name: routines
description: Look after repeating work (monthly, quarterly or annual routines). Start a period, track who has sent what, say what's due, hand steps to team members, and write a new routine's runbook. Use when the briefing says a routine can start or is due, or the user asks about a routine.
---

# Routines

A routine is a folder in `Routines/` with a `Runbook.md`: how often it runs, who owns it, when it's due, its lists and its steps. Each period has its own folder (`2026-09`, `2026-Q3`, `2026`) with a `Tracking.md` checklist and that period's outputs. Formats: `System/Core/Manual/routines.md`.

Put free text in single quotes; if the text contains a single quote, write it to a file and use `--file` (result) or `--note-file` (status).

## Start a period (when the briefing says "can start", and only after the user says yes)
1. Read the runbook. For each list that is a sentence (a source), get the items from that source (for example Carta), grouped the way the runbook says, and show the user the full lists. Wait for their yes or corrections.
2. Write each confirmed list to `.bron/tmp/<name>.txt`, one item per line, as `Group: item` when grouped (for example `Fund I: Company A`).
3. Run `.bron/bin/bron routine start '<Routine>' --list <name>=.bron/tmp/<name>.txt` with one `--list` per list from a source (add `--period <period>` for a period other than the latest one that ended).
4. Tell the user in one line what was set up and when it's due.

## During the period
- Tick items in the Tracking note (`- [ ]` → `- [x]`) when they're done; you may add a short note after the item (`- [x] Company A: received 12 Oct`). Never untick or remove items without the user's say-so.
- "Who's still missing?": read the Tracking note and list the unticked items of the step asked about.
- Progress and due dates: `.bron/bin/bron routine list`.
- A step for a team member: hand it off with a ticket linked to the routine (`--project '<Routine>'`), as in the delegate skill. Outputs go in the period folder.

## A new routine
Write `Routines/<Routine>/Runbook.md` in the manual's format, show the user the whole file first, and write it only after their yes.

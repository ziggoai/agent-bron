---
name: create-routine
description: 'Turn repeating work into a routine ("make the quarterly LP report a routine"): how often, who looks after it, when it''s due, its lists and steps.'
---

# Create a routine

1. From the user's description, draft `.bron/tmp/<Name>-runbook.md` in the format of `System/Core/Manual/routines.md`: cadence, owner (you, unless they say otherwise), due rule, lists (fixed items, or a sentence saying where the items come from), steps (what each is done for, and what it waits for), then "How to do each step".
2. Preview: `.bron/bin/bron routine create --name '<Name>' --file <path> --preview`. Show the summary and wait for a yes. Adjust the draft and preview again if they want changes.
3. Apply: the same command without `--preview`.
4. Offer to start the latest period now (the routines skill).

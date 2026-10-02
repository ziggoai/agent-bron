---
name: remove-agent
description: Retire a team member ("retire the COO") or bring one back ("bring back the COO"). Retired agents hand their open work over and are archived, never deleted.
---

# Retire or bring back an agent

Retire:
1. Ask who should take over its open work if the user hasn't said (by default, the agent it reports to).
2. Preview: `.bron/bin/bron agent retire '<Name>' [--hand-to '<Name>'] --preview`. Show the summary (open work handed over, team lists, routines, where the files go) and wait for a yes.
3. Apply: the same command without `--preview`. Bron itself can't be retired; offer to rename it instead.

Bring back:
1. Preview: `.bron/bin/bron agent restore '<Name>' --preview`, show it, wait for a yes.
2. Apply: the same command without `--preview`.

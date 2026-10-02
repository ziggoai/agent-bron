---
name: create-skill
description: Save what was just done as a reusable skill ("turn what we just did into a skill"), shared by every agent or kept for one.
---

# Turn work into a skill

1. Write the steps you just followed as a short, general how-to in `.bron/tmp/<skill-name>.md`: when to use it, the steps, the checks. No one-off details (dates, amounts) unless they always apply.
2. Choose a name in lower-case letters and hyphens (for example `lp-report`) and one sentence saying when to use it. Ask whether it's for every agent or only one, if that isn't clear.
3. Preview: `.bron/bin/bron skill new <skill-name> --description '<description>' --file <path> [--agent '<Name>'] --preview`, show it, wait for a yes.
4. Apply: the same command without `--preview`. It's available from the next session.

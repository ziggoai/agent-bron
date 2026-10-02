---
name: create-project
description: Start a project folder for one-off work ("start a project for the Fund III audit") with a README for its goal, status and key decisions.
---

# Start a project

1. Ask for the goal in one sentence if the user hasn't given it.
2. Preview: `.bron/bin/bron project new '<Name>' --goal '<goal>' --preview`, show it, wait for a yes.
3. Apply: the same command without `--preview`.
4. Save the project's work in `Projects/<Name>/`, and link tickets to it with `--project '<Name>'`.

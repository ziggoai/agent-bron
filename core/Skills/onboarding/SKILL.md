---
name: onboarding
description: First-run setup, about two minutes, or when the user says "let's redo setup". Learns who the user is, names Bron and its model, picks the main app and checks connectors.
---

# Onboarding

Ask one thing at a time, in plain words, and keep it short. Every change is previewed with `--preview` and saved only after the user's yes, except the name and company, which you save straight away.

1. **The user's name, role and company.** As soon as they say, run `.bron/bin/bron settings set --name '<user name>' --role '<user role>' --company '<company>'` (no preview needed for these).
2. **Bron's name and role.** "I'm Bron, your Chief of Staff. Keep that, or call me something else?" To rename: `.bron/bin/bron agent rename Bron '<NewName>' --preview`, show the summary, wait for a yes, then run it without `--preview`. For a different role: `.bron/bin/bron agent set Bron --role '<role>'` (preview first).
3. **Bron's model.** "I'll run on Opus 5.5 in Claude Code. OK, or another model?" If they want another: `.bron/bin/bron agent set Bron --model 'claude=<model>' --preview`, then apply after a yes. Only set a Codex model if they name one (`--model 'codex=<model>'`); otherwise Codex keeps its own default.
4. **The main app.** "Do you mostly work in Claude Code or Codex?" Then `.bron/bin/bron settings set --default-cli <cli>`.
5. **Connectors.** Run `.bron/bin/bron connections scan` and tell them which connectors you found ("I found Gmail, Drive and Carta"). Ask "Use these?". You use every connector; team members only get the ones they're given later.
6. **In Codex only:** explain that Codex asks once to approve Bron's triggers: type `/hooks` and approve the ones that run Bron's hook command (their command ends with `hook session-start`, `hook user-prompt` and so on).
7. Ask: **"Tone and preferences now or later?"** If now, ask how they like answers (for example "brief, numbers first") and anything else to remember, then `.bron/bin/bron settings set --tone '<tone>' --preferences '<preferences>' --preview`, show it, wait for a yes, and apply.
8. Ask: **"Want to set up any team members now?"** If yes, follow the create-agent skill.
9. Finish with one line: what's set up, and that they can change any of it by asking.

Put free text in single quotes; if the text contains a single quote, write it to a file or leave that word out.

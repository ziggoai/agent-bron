---
name: onboarding
description: First-run setup, about two minutes, or when the user says "let's redo setup". Learns who the user is, names Bron and its model, picks the main app and checks connectors.
---

# Onboarding

Ask one thing at a time, in plain words, and keep it short. Every change is previewed with `--preview` and saved only after the user's yes, except the user's own name, role and company, which you save straight away.

1. **The user's name, role and company.** As soon as they say, run `.bron/bin/bron settings set --name '<user name>' --role '<user role>' --company '<company>'` (no preview needed for these).
2. **Your name and role.** Introduce yourself with your own name and role ("I'm Bron, your Chief of Staff. Keep that, or call me something else?"). To rename: `.bron/bin/bron agent rename '<your name>' '<NewName>' --preview`, show the summary, wait for a yes, then run it without `--preview`. For a different role, also rewrite "Who you are" for the new role: copy your instructions (the text under the properties in `System/Agents/<your name>/Agent.md`) to `.bron/tmp/<your name>-instructions.md`, rewrite that section and keep the rest. Then `.bron/bin/bron agent set '<your name>' --role '<role>' --instructions-file .bron/tmp/<your name>-instructions.md --preview`, show the summary, wait for a yes, then run it without `--preview`.
3. **Your model.** "I'll run on Opus 5.5 in Claude Code. OK, or another model?" If they want another: `.bron/bin/bron agent set '<your name>' --model 'claude=<model>' --preview`, then apply after a yes. Only set a Codex model if they name one (`--model 'codex=<model>'`); otherwise Codex keeps its own default.
4. **The main app.** "Do you mostly work in Claude Code or Codex?" Then preview `.bron/bin/bron settings set --default-cli <cli> --preview`, show it, wait for a yes, then apply without `--preview`.
5. **Connectors.** Run `.bron/bin/bron connections scan` and tell them which connectors you found, work tools first ("I found Gmail, Drive, Slack and Carta, and also Spotify and Booking.com"). When it found the same app twice (a connector and a plugin's copy of it, like "Gmail" and "gmail (small-business)"), say so and suggest keeping one. Ask "Which of these should I use?". All of them: nothing to change. Some: `.bron/bin/bron agent set '<your name>' --remove-connection all --add-connection '<connection>' --preview`, with one `--add-connection` for each connector to keep, named as the scan printed it; show the summary, wait for a yes, then run it without `--preview`. The ones left out are switched off for you in both apps; this is a setup change, not a memory. Team members only get the connectors they're given later.
6. **In Codex only:** explain that Codex asks once to approve Bron's triggers: type `/hooks` and approve the ones that run Bron's hook command (their command ends with `hook session-start`, `hook user-prompt` and so on).
7. Ask: **"Tone and preferences now or later?"** If now, ask how they like answers (for example "brief, numbers first") and anything else to remember, then `.bron/bin/bron settings set --tone '<tone>' --preferences '<preferences>' --preview`, show it, wait for a yes, and apply.
8. Ask: **"Want to set up any team members now?"** If yes, follow the create-agent skill.
9. Finish with one line: what's set up, and that they can change any of it by asking.

Put free text in single quotes; if the text contains a single quote, write it to a file or leave that word out.

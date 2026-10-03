# Changelog

What changed in each version of Bron, newest first. Bron shows the new sections when you ask it to update itself.

## 0.6.0
- Bron remembers. Tell it a preference, a decision or a fact about you or the fund once; it saves it ("Noted: …") and every agent knows it from then on. "Forget that" works any time, and everything it remembers is a note you can open and edit.
- Each agent also keeps its own work notes.
- Every conversation gets a short summary, written in the background by a small model, so "what did we decide last week?" has an answer. Turn it off with `memory: summaries: false` in System/Settings.md.
- Search past conversations and facts in English or Portuguese, with or without accents.

## 0.5.0
- Install Bron with one line pasted into Terminal, into the folder you choose (or `~/Documents/Bron`). Running it again repairs a vault and never changes your files.
- New vaults come with Bron's Obsidian look: the Bron theme, Bron Terminal, Bron Workspace and a few helpful plugins. Your own Obsidian settings are always kept.
- "Bron, update yourself" now gets the newest release from GitHub: Bron shows what's new and waits for your yes, backs up the current version, goes back by itself if anything fails, and "undo the update" returns to the previous version.
- Once a day Bron tells you when a new version is out. Set `update_check: false` in System/Settings.md to stop that.
- A `bron` command that works from any folder inside your vault.
- Bron Terminal 0.6.0 ships with Bron: a standalone terminal for Claude Code and Codex inside Obsidian (no other terminal plugin needed).
- Bron is open source under the MIT licence.

## 0.4.1
- Safer connector setup: more kinds of passwords and keys are refused, harmless options are allowed, and programs whose path has spaces work.
- Setup changes stay correct when you click "don't ask again" while Bron is making a change.
- Bringing back a retired agent works even when one of its helpers was removed.

## 0.4.0
- Setup by conversation: first-run onboarding, and creating, editing and retiring agents, projects, routines, skills and connectors. Every change is previewed in plain words before it's made.
- Bron uses Opus 5.5 by default.

## 0.3.1
- Picking an agent from the @ list (for example `@"cfo (agent)"`) now reaches that agent.
- Codex agents can use their connectors in background work without being stopped by approval prompts.

## 0.3.0
- @-mention an agent to bring it into the conversation.
- Routines: repeating work per period, with checklists and due dates.
- "Don't ask again" approvals are saved and apply in both Claude Code and Codex.

## 0.2.3
- Versions 0.2.0 to 0.2.3: much faster handoffs between agents, quick questions answered straight in the chat, and results always delivered back to you.

## 0.1.0
- The first version: agents defined once in plain markdown, kept in sync across Claude Code and Codex, tickets for handing work between agents, and a health check.

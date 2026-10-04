# Changelog

What changed in each version of Bron, newest first. Bron shows the new sections when you ask it to update itself.

## 0.7.1
- Bron starts general: the knowledge base sorts documents into everyday types (contract, invoice, report…), and you can give it your own list with `knowledge: doc_types:` in System/Settings.md.
- The separate fund label and the `--fund` search filter are gone: the company label covers any company or organisation a document is about. A fund label you set before now shows as the company.

## 0.7.0
- Bron reads the documents you point it to: Google Drive links, files, folders, web links and a Knowledge/Inbox folder. Big folders are read in the background and Bron tells you when they are done.
- Ask about your documents in English or Portuguese; every agent searches what Bron read and answers with the document, page and link. If the documents don't say, it tells you.
- Scanned pages are read on your Mac. Search finds numbers and dates in either format (1.500.000,00 or 1,500,000.00).
- A one-time setup of about 300 MB the first time you add or search.
- Two things go to your Claude or Codex plan: the first part of each document's text (about 3,000 characters) so Bron can label it with a company, type and date, and the image of a page that is too messy to read directly. Each one is logged in .bron/kb/model-log.jsonl. Turn them off with `knowledge: labels: false` and `knowledge: model_pages: false` in System/Settings.md; labels then come from file and folder names.
- A document Bron already read is skipped when it hasn't changed, so nothing is read or sent twice; `bron kb add --again` reads it anyway. The first reading, scans, photos and anything over 50 pages are read in the background.
- Fix a wrong company, type or date with `bron kb label`, remove a document with `bron kb forget`, and see what couldn't be read with `bron kb list --failed`. The health check warns about documents that couldn't be read.

## 0.6.1
- After an update that changes Bron's Obsidian theme or plugins, Bron tells you to quit and reopen Obsidian so it loads them.

## 0.6.0
- Bron remembers. Tell it a preference, a decision or a fact about you or your work once; it saves it ("Noted: …") and every agent knows it from then on. "Forget that" works any time, and everything it remembers is a note you can open and edit.
- Each agent also keeps its own work notes.
- Every conversation gets a short summary, written in the background by a small model, so "what did we decide last week?" has an answer. Turn it off with `memory: summaries: false` in System/Settings.md.
- Search past conversations and facts in English or Portuguese, with or without accents.
- Conversations from the last two weeks get their summaries gradually, a few at a time, after you update.
- Summaries use your Claude or Codex plan, the same login as the app you talk to Bron in.
- Agents save what you tell them to remember without asking first.

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

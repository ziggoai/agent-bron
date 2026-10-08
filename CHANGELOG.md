# Changelog

What changed in each version of Bron, newest first. Bron shows the new sections when you ask it to update itself.

## 0.8.7
- New vaults start Bron on `gpt-6-astra` in Codex, as it starts on Opus 5.5 in Claude Code, instead of whatever model Codex is set to. An existing vault keeps its setting; to change it, ask Bron or run `.bron/bin/bron agent set Bron --model codex=gpt-6-astra`.
- One wiki page can cover several documents (copies, drafts, a set of the same form), and the check reports a document that two pages claim.
- The wiki check tells a page over about 15,000 characters to tidy, and flags a summary over 300 characters. Agents keep growing pages short and move long lists to their own topic page. Summaries in `index.md` are cut at 200 characters.
- `bron wiki check --all` and `bron wiki done` show a "worth a look" list: a note saying something isn't checked yet, numbers in spreadsheet form, a timeline out of order. It never stops `wiki done`.
- Agents write pages from the reader helpers' notes, and never wait with `sleep`. Shell commands follow a simpler rule, so fewer background runs stop for your OK.
- Background reading is honest about Codex: it says a Mac notification will come. A folder that is queued says it starts right after the current one, and a ticket's title names the parent folder.
- Search is faster on a big wiki. `index.md` is now written by `bron wiki done`, not by each search.
- Search ranks a number with the word before it ("Section 10.9"), ignores common words, shows at most two passages per document, and shows the best part (about 600 characters) of each passage. Identical passages from copies show once, with "Also in: ...".

## 0.8.6
- A background run that finished its work no longer stops as "blocked" when a command on its own scratch files was refused, so Bron doesn't run the batch a second time. Scratch files stay in `.bron/tmp/`, and Bron clears the ones older than a day after each run instead of asking you to approve each delete. Reader helpers keep document text inside the vault too.
- Bron closes each batch's ticket once its wiki pages are written, so there are no reading tickets left for you to close. When a ticket changes twice before you hear about it, you get one update with its latest status.
- When two conversations read folders at the same time, each one reports its own reading when it ends, even if the other conversation heard first.
- Bron splits a folder into even batches. Eleven documents become six and five, not ten and one, because every run costs a few minutes before it writes anything.
- A new conversation that starts before your last one's summary is written now gets that summary with your next message (Claude Code). The briefing also tells Bron to check tickets and reading status before saying something is still to do.
- The wiki check now flags organisation, person and topic pages over 20,000 characters, which catches pages that collect a line per document. Document pages keep the 30,000 limit. It also flags a name that two pages answer to, since a link with that name can't tell them apart. Summaries in `index.md` are cut to one line.
- Wiki pages show a share that a spreadsheet stores as a fraction (0.0831903962) as a percentage (8.32%). Bron removes a document it leaves out on purpose from the knowledge base, so the check stops listing it. After checking a fact against another source, Bron updates every page that still says "not checked yet".
- Bron shows a little less of a document per command, so the text still fits when another command runs alongside it. Agents keep shell commands simple, because variables and loops stop a background run for your OK. They also talk to you in plain words, as themselves.

## 0.8.5
- In Claude Code, a background run closes as soon as it replies. It can no longer set itself a reminder: a reminder kept a finished run open until it went off, and the next documents waited up to 20 minutes behind it. Your conversations with Bron can still set reminders.

## 0.8.4
- In Claude Code, Bron tells you as soon as a folder is read into the wiki, without you asking: it waits for the background work with the new `bron kb wait` and reports when it ends. Codex can't wake a conversation, so there the Mac notification and your next message still bring the news.
- Showing a document's text stops before the output gets too long to be shown in full, and says where to go on; a very long page (a big spreadsheet) comes in parts. Bron no longer saves document text in files outside the vault to read it, which left copies on the computer and stopped background runs for your OK.
- A background run that finished its work no longer stops as "blocked" because one file read was refused, so the batch isn't run a second time.
- People and organisations that appear in many documents keep their roles and changes on their page, not a line per document; long pages are tidied as they grow, so background runs don't slow down as the wiki gets bigger.
- "Nothing changed in the wiki" now says when the check's log line was still recorded. Cutting `bron kb show` short (`| head`) is no longer logged as an error. Long ticket titles keep their "(part 2 of 3)" in the file name.

## 0.8.3
- A zip of files that are read on their own (in the same folder, or before) is skipped as a copy instead of counting as a document Bron couldn't read. Any other zip says to unzip it and add the folder.
- System files such as desktop.ini and Thumbs.db are skipped when a folder is read. Updating clears the ones earlier versions listed as "couldn't be read", so the health check stops warning about them.
- The reading report no longer labels each document with its folder's name (such as "Finals · other") before its wiki page exists; it shows the date in the file name, and the page's labels once there is one.
- A fact the user gives about one thing that has a wiki page goes on that page, not into shared memory, so memory stays short.
- No more empty .lock files next to tickets in Tickets/; updating removes the old ones. index.md and log.md are saved readable like every other page.

## 0.8.2
- Fix: the briefing's list of open items no longer shows "Nothing" from a conversation that left nothing open.

## 0.8.1
- First-run setup asks which connectors Bron should use and switches the rest off, instead of using every connector it finds. It points out when the same app was found twice (a connector and a plugin's copy of it). Later, "stop using Spotify" changes Bron's connectors rather than saving a note.
- Giving an agent a new role also rewrites the "Who you are" part of its instructions. When only the role changes, the preview says so.
- The session briefing lists what was still open at the end of your last three conversations, so loose ends come back without asking.
- Wiki pages stay current after a correction: the page's one-line summary is checked, and an answered question moves out of "Open questions" into the page.
- Aliases in wiki pages are always quoted, so a name with a comma ("Acme, Inc.") stays one alias.
- The wiki index counts a page's sources properly: the documents it cites as well as the documents linking to it. Topic pages no longer show "0 sources".
- Confirming something Bron saved as "to confirm" replaces the old line instead of adding a second one.

## 0.8.0
- Reading a document now builds a wiki in Knowledge/: a page per document, plus pages for the organisations, people and topics in it, linked to each other and citing the document and page. After reading, Bron tells you in a few lines what it learned, what changed or contradicted earlier pages, and which pages it touched.
- A folder, or more than three documents, is read and written into the wiki in the background while you keep working, ten documents at a time; a Mac notification tells you when it's done and how long it took, and each batch's summary arrives as a ticket update. Up to three documents are read right away, scans and the first-time setup included.
- Copies are read once: a document with the same text as one already read (a "(1)" download, the same file in two folders) is skipped, so it gets no second page. Reader helpers run on Sonnet in Claude Code, which is faster for pulling facts out of long documents.
- Search shows wiki pages first, then the exact passages in the documents. `--organisation` narrows it (`--company` still works) and `--pages-only` shows only pages. After an answer that combined several documents, Bron offers to save it as a page.
- Knowledge/Schema.md holds the wiki's rules: page types, document types and naming. Edit it to fit your work; the document types you set in System/Settings.md move there.
- `bron wiki check` and the health check find broken links, pages nothing links to, documents without a page and probable duplicates. Say "check the wiki" for a full checkup.
- No document text is sent to a model just to label it any more: a document's organisation, type and date come from its wiki page. `bron kb label` and the `knowledge: labels` setting are gone; edit the page's properties instead.
- Fixes: folders shared with you in Google Drive are found; `bron kb add --file` takes only exported text; `bron kb status` says "Nothing is being read." when nothing is.
- Measured on a Mac: a 2-page PDF is read in about 1–2 s; reading it into the wiki in a conversation takes about 40 s in Claude Code and about 65 s in Codex at high reasoning effort (most of it the model writing the pages).
- Your knowledge base becomes a wiki: Knowledge/ gets Schema.md (its rules, with your document types), index.md, log.md and folders for documents, organisations, people and topics.

## 0.7.1
- Bron starts general: the knowledge base sorts documents into everyday types (contract, invoice, report…), and you can give it your own list with `knowledge: doc_types:` in System/Settings.md.
- The company label now covers any company or organisation a document is about (0.7.0's separate fund label is folded into it).

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

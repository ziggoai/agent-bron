# Bron Knowledge Wiki (sub-project 3, redesigned)

Status: design approved in conversation on 2026-10-04 (the user asked to build without reviewing the written spec). Replaces the "piece 1 / piece 2" split of `2026-10-03-bron-knowledge-ingest-design.md`: reading a document now builds the wiki. Everything that spec built (sources, readers, passages, index, search, jobs) stays as the lower layer unless this spec changes it. Builds on 0.7.1. Ships as 0.8.0.

## 1. Purpose

Bron follows Andrej Karpathy's LLM wiki pattern (gist `karpathy/442a6bf555914893e9891c11519de94f`, April 2026):
- the **raw sources** are immutable documents (here: the user's files, which stay in Google Drive);
- the **wiki** is a set of interlinked Markdown pages the model writes and keeps current: one page per document, plus pages for organisations, people and topics, with `index.md` (catalogue) and `log.md` (dated record);
- the **schema** is the rules file that makes the model a disciplined wiki maintainer.

Three operations: **ingest** (read a source, write its page, update the 10–15 pages it touches, update index and log), **query** (find pages, answer with citations, file good answers back as pages), **lint** (contradictions, stale claims, orphans, missing pages, gaps). Knowledge is compiled once and kept current, not re-derived on every question.

Bron's own search database (built in 0.7.0) is the "search tool at scale" Karpathy mentions: the full text of every document, with page numbers, for exact citations and for what the pages don't cover.

## 2. Decisions (approved by the user)

- **D1. Pages:** one page per document, plus organisation, person and topic pages (Karpathy as written), with a rule that controls the file count (§4.3).
- **D2. Involvement:** Bron reads, writes the pages, then tells the user in a few lines what it learned, what changed or contradicted, and which pages it touched. No approval step before writing.
- **D3. Folders** (10–15 documents in practice): one background agent works through them one after another; the user keeps chatting; a summary arrives when done.
- **D4. Answers:** after an answer that combined several documents, the agent offers "Save this as a page?"; saved only on a yes.
- **D5. Checkups:** mechanical checks in the daily health check; a judgement checkup automatically after each folder, over the pages that folder touched; a full checkup when asked.
- **D6. Approach:** the agent writes the wiki (model owns the wiki); Bron's code does the mechanical work (finding files, extracting text, the database, index and log, checks, background runs).
- **D7. Drive files stay in Drive.** Never downloaded, never copied into the vault. Only one-off files from the Mac (inbox or a path) are kept in `Knowledge/Files/`.
- **D8. General framework:** page types and document types live in the vault's `Knowledge/Schema.md`; a fresh install is domain-neutral.

## 3. What the user's test showed (2026-10-04) and the fixes

1. The 8 minutes were an agent wait loop: it polled `bron kb status` every 15 s and grepped for "reading", which the idle line ("No documents are being read right now. Last reading finished…") also contains. The read itself took 25 s including first-time setup.
   - Fix: single documents are read in the foreground; folders report when done; `status` says "Nothing is being read." with no other wording that matches "reading"; AGENTS.md says never poll.
2. The Drive file was in the mount under `.shortcut-targets-by-id/<folder id>/…` (folders shared with the user), which the walk skipped as hidden.
   - Fix: the walk includes `.shortcut-targets-by-id` (other hidden folders stay skipped). A folder link goes straight to `.shortcut-targets-by-id/<folder id>` when that exists.
3. The agent applied the Google Docs export rule to a PDF and downloaded it via the connector; `--file` read the PDF bytes as text (garbage); then it copied the PDF into the inbox.
   - Fix: AGENTS.md and the skill say a Drive link is always given to `bron kb add` first; the connector export is only for Google Docs/Sheets/Slides; a Drive file Bron can't find is reported to the user ("make sure Google Drive for desktop shows this file"), never downloaded or copied. `bron kb add --file` refuses anything that isn't text (NUL bytes, `%PDF`, not UTF-8 decodable): "--file is only for text exported from a Google Doc, Sheet or Slides; give Bron the Drive link instead."

## 4. The wiki

### 4.1 Layout

```
Knowledge/
  Schema.md        rules: page types, document types, names, what goes where (the user's to edit)
  index.md         catalogue, one line per page, grouped by type (written by Bron's code)
  log.md           append-only dated record (written by Bron's code)
  Documents/       one page per document
  Organisations/
  People/
  Topics/
  Inbox/           one-off files from the Mac
  Files/           kept copies of inbox / path files only
```

A vault may add page types in `Schema.md` (e.g. `Funds/`, `Portfolio companies/`); each type is a folder under `Knowledge/`. Bron's code treats every `.md` under `Knowledge/` except `Schema.md`, `index.md`, `log.md`, `Inbox/` and `Files/` as a wiki page; its type is its first folder.

### 4.2 Pages

Properties (frontmatter) every page has: `type` (the folder's type, singular, e.g. `document`, `organisation`), `summary` (one line, used by the index and search), `aliases` (other names; optional; Obsidian's own key). Document pages also have: `doc` (Bron's document id), `source` (Drive link, URL or kept-copy path), `organisation` (the organisation the document is mainly about; a `[[link]]` or text), `doc_type` (one of the schema's document types), `date` (YYYY-MM-DD or empty).

Document page body: what the document is; key facts, each with its page (`p. 3`); parties as links; what it changes or contradicts. Other pages: facts grouped under headings, each citing the document page and page number: `… (see [[<Document page>]], p. 3)`. A fact superseded by a newer document is updated with a short "previously …" note; never silently deleted.

File names: the page title, as the user would say it; document pages `<Title> (<YYYY-MM-DD>).md` when a date is known. Characters not allowed in file names are replaced.

### 4.3 When a page is created (file count)

An organisation, person or topic gets its own page when a document is mainly about it, when it appears in 2 or more documents, or when the user asks. A one-off mention stays as plain text on the document page; when a second document mentions it, the page is created and the earlier mention becomes a link. Expected: a 10–15 document folder → 10–15 document pages plus roughly 5–15 others.

### 4.4 Schema.md (template)

Shipped in `template/Knowledge/Schema.md`, plain English, domain-neutral:
- the four page types and their folders, what each holds, suggested headings per type;
- the document types list (the 0.7.1 general list: contract, invoice, receipt, statement, report, financial statements, budget, presentation, meeting minutes, policy, letter, form, spreadsheet, other);
- the page-creation rule (§4.3), citation format, "previously" rule, naming;
- "Your edits win": agents keep what the user wrote and treat a user correction as the newest source.

The user (or Bron, on request, through the usual change flow) edits it to fit their work. `knowledge.doc_types` in Settings (0.7.1) moves here (§8).

### 4.5 index.md and log.md (code-maintained)

- `index.md`: header line, then one section per page type (Schema order, then others alphabetically), each line `- [[Page]] — <summary> (<N> sources, updated <YYYY-MM-DD>)`. "N sources" counts distinct document pages that link to the page (document pages show their date instead). Regenerated whenever `bron wiki done` or a search notices changed pages. Never edited by agents.
- `log.md`: newest last; entries `## [YYYY-MM-DD HH:MM] <kind> | <text>` with kinds `ingest` (a document page appeared or its document was read again), `update` (other pages changed, listed), `save` (an answer saved as a page), `check` (a checkup ran, counts), `forget`. Written only by Bron's code.

## 5. Reading (ingest)

### 5.1 One to three documents, in the conversation

1. The agent runs `.bron/bin/bron kb add '<link|path|url>' [...]` (or `--inbox`). Bron resolves, extracts, stores — foreground, including first-time setup (the agent uses a 10-minute command timeout). **No label model call** (§7). Output per document: `Read <name> (<N> pages, <S> scanned) — doc <id>`, and an already-read unchanged document: `Already read <name> — doc <id> (page: [[…]])`. Target: a 2-page text PDF in under 5 s after setup; scans ~0.2 s per page.
2. The agent loads the `read-documents` skill (the wiki maintainer procedure), reads the text (`bron kb show <id>`, in sections for long documents), searches the wiki for the names it finds (`bron kb search '<name>' --pages-only`), reads `Schema.md` and the pages it will touch, writes the document page and creates/updates the other pages.
3. The agent runs `.bron/bin/bron wiki done` (§5.3) and fixes what it reports (e.g. a broken link).
4. The agent tells the user in a few lines: what it learned, what changed or contradicted earlier pages, which pages it created/updated.

Target: under a minute end to end for a short document.

### 5.2 A folder, or more than three documents: background

`bron kb add` resolves and extracts in the existing background job (one at a time; queue), then — in the same background job — runs one agent run to write the wiki: a ticket assigned to the default agent ("Read <folder or N documents> into the wiki"), run through the existing ticket runner (`runner.run_ticket`) in either CLI, with the document ids in the request. The agent follows the same skill, document by document, then runs the judgement checkup (§6.2) on the pages it touched, runs `bron wiki done --log 'check | …'`, and its final reply is the summary (learned, conflicts, pages touched, documents that couldn't be read). The summary reaches the user like any ticket update (next message or briefing). Output of `kb add`: "Reading N documents into the wiki in the background (about M minutes); I'll report when it's done."

One wiki writer at a time: while a background wiki run is active, a new `kb add` from a conversation extracts the documents and queues them as a background wiki job behind the current one ("A folder is being written into the wiki; I'll add these after it (about M minutes)."). `bron kb status` shows the queue.

### 5.3 `bron wiki done [--log '<text>']`

Run by the agent after writing pages. It:
1. finds wiki pages changed since the last run (mtime against `.bron/kb/wiki-state.json`) and new/removed pages;
2. for document pages with a `doc` property: records the page as that document's page, and takes `organisation`, `doc_type`, `date` into the search filters (the labels that the model call used to produce); an unknown `doc` id is reported;
3. indexes changed pages into the search database (§6.1);
4. rewrites `index.md`; appends `log.md` entries (`ingest` per new document page, one `update` line listing other changed pages, plus `--log` text when given);
5. runs the mechanical checks on the changed pages and the pages that link to them, and prints problems in plain lines (or "Wiki updated: N pages (M new).").

### 5.4 Sources (unchanged except as stated)

Drive link (file or folder) → found in the mount by Drive id, including `.shortcut-targets-by-id`; Google Docs/Sheets/Slides → connector export to a text file then `kb add --file <text> --source <link> --name '<title>'` (text only, §3 item 3); a path or the inbox → kept copy in `Knowledge/Files/<YYYY-MM>/`; a web page → fetched text. Reading a known identity again replaces its text; the agent then updates its document page.

## 6. Answering (query)

### 6.1 One search for pages and passages

`bron kb search '<question>' [--organisation X] [--type T] [--after D] [--before D] [--limit 8] [--pages-only]` returns:
1. **Wiki pages** (up to 3): title, summary, path, and the best-matching excerpt.
2. **Document passages** (up to `--limit`): as today (title, labels, page, source link, text).

Wiki pages are indexed into the same SQLite database (own FTS table and meaning vectors, same embedder), refreshed on each search from file mtimes (cheap stat of `Knowledge/**/*.md`) and by `wiki done`; the warm search helper serves both. `--company` stays as an alias of `--organisation`. Target unchanged: ~0.2 s warm.

### 6.2 How agents answer (AGENTS.md rules, short)

Search; open the one or two most relevant pages when the excerpt isn't enough; answer from the pages and check numbers and key terms against the passages; cite the document page, page number and Drive link; say plainly when neither answers it. After an answer that combined several documents, ask "Save this as a page?"; on yes, write a topic page with its citations, link it from the pages it drew on, run `bron wiki done --log 'save | <title>'`.

## 7. Checkups (lint)

### 7.1 Mechanical (code, free): `bron wiki check [--all]` and the health check

- links to pages that don't exist;
- pages nothing links to (except from `index.md`);
- pages missing `type` or `summary`;
- documents read without a document page ("read but no page yet" — e.g. an interrupted run);
- document pages whose `doc` isn't in the database (forgotten or never read);
- probable duplicates: two pages of the same type whose titles/aliases match after folding case, accents and company suffixes (Ltda, LLC, Inc, S.A., LP);
- pages over 30,000 characters (suggest a split).

The health check shows counts and the first three of each (warnings); `wiki check --all` lists everything; `wiki done` checks only what changed.

### 7.2 Judgement (model): after each folder, and on "check the wiki"

Part of the `read-documents` skill (and a `check` section for the full checkup): reread the touched pages and their linked pages; resolve contradictions where a later document clearly supersedes an earlier one ("now X, <source>; previously Y"); flag real conflicts to the user, never decide them; create pages for organisations/people now in 2+ documents; list gaps ("the side letter is referenced but wasn't read") as suggestions, never fetch on its own. Logged as `check`.

## 8. Changes to what exists

- **Label model call removed** (`models.labels`, the prompt, `knowledge.labels` setting, the label log kind). Labels for search filters come from document page properties (§5.3). Documents not yet given a page are found by name and text; `labels_from_names` stays as the fallback filter values until a page exists.
- **`bron kb label` removed**; the user edits the document page's properties instead (the next search or `wiki done` takes them in). Stored 0.7.x user labels stay effective until the document has a page.
- **`knowledge.doc_types` moves to Schema.md.** A migration (0.8.0) copies a vault's list into `Knowledge/Schema.md`'s document types and removes the key; Settings keeps `model_pages` and `max_model_pages`.
- **`bron kb forget <doc>`** also reports the document page (it isn't deleted automatically: "Its page [[…]] is still there; delete it or keep it"). The mechanical check then flags it until resolved. Logged as `forget`.
- **Foreground / background thresholds:** up to 3 documents → foreground (including scans and first-time setup); a folder or more → background with the wiki run (§5.2).
- **`kb status`:** "Nothing is being read." when idle; otherwise the running/queued jobs, including wiki runs.
- **AGENTS.md Knowledge section** rewritten (≤ 1,600 characters): read with `kb add` (Drive links always first; connector export only for Google Docs/Sheets/Slides; never download or copy a Drive file; never poll); write pages by loading the `read-documents` skill; answer per §6.2.
- **Manual** `core/Manual/knowledge.md` rewritten for the wiki; CHANGELOG 0.8.0 section.

## 9. Migration (0.8.0)

Through the existing migrations registry (setup change runner): create `Knowledge/Schema.md` (template, with the vault's `doc_types` if set), `index.md`, `log.md`, and the four type folders when missing; remove `knowledge.labels` and `knowledge.doc_types` from Settings. Documents already read show up as "read but no page yet"; the agent offers to write their pages. Nothing is deleted.

## 10. Error handling

Every failure is a plain sentence. `wiki done` never fails because of one bad page (reports it, continues). A background wiki run that fails leaves the extracted documents in the database and reports which documents got pages; running `kb add` on the same folder again (unchanged documents are skipped) or "finish the wiki pages" picks up the rest via the "read but no page yet" list. A page with broken frontmatter is reported by the check and skipped by the index.

## 11. Testing

- Unit: shared-folder lookup (`.shortcut-targets-by-id`, direct folder-id path); `--file` refuses PDF/binary; no label call anywhere; thresholds (≤3 foreground, folder → background job with wiki run using a stand-in runner); one-writer queue; `wiki done` (labels from properties, index.md content and order, log entries, changed-page detection, bad frontmatter); search returns pages then passages, `--pages-only`, refresh on page edit; each mechanical check; migration (Schema.md created, doc_types moved, keys removed); status idle wording has no "reading"; forget reports the page.
- Live (`BRON_LIVE=1`, each CLI): a fake Drive mount with a 2-page PDF under `.shortcut-targets-by-id` and a 3-document folder; read the single document in a conversation-style run and the folder through the background run; check pages exist with citations and links, `index.md`/`log.md` entries, nothing copied into the vault, a question answered from the pages with a citation; record timings (extract < 5 s; single document < 60 s).

## 12. Release

0.8.0 with CHANGELOG (domain-neutral wording), manual page, template files, migration. After release, offer the user: remove the kept copy from the 2026-10-04 test in the test vault, read the document again from its Drive link, and write their own fund version of `Schema.md` in their vault.

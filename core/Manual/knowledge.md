# Knowledge base

Bron reads the documents you point it to and keeps what they say in a wiki in `Knowledge/`: a page per document, plus pages for the organisations, people and topics in them, linked to each other. Every fact on a page says which document and page it comes from. Agents answer your questions from the wiki and check the details against the documents themselves.

## How it works

- **The documents** are the sources and stay where they are. Files in Google Drive stay in Drive: Bron reads them through Google Drive for desktop and never copies them into your vault. Web pages stay on the web. Only files from your Mac (the inbox, or a path you give) are kept in `Knowledge/Files/`.
- **The wiki** is written by your agents, following the `read-documents` skill: they read a document, write its page, update the pages it touches, note what changed or contradicts earlier pages, and link everything together.
- **`Knowledge/Schema.md`** holds the wiki's rules: the page types, the document types, how pages are named. It's yours to change.
- **Bron's code** does the bookkeeping: finding files, reading their text (scans included), the search database, `index.md` (the catalogue of pages), `log.md` (the record of what happened) and the checks.

This follows Andrej Karpathy's "LLM wiki" idea: knowledge is compiled once and kept current, not worked out again for every question.

## Reading documents

- Say "read this: <Google Drive link>", give a file or folder path or a web link, or say "read the inbox". Several at once is fine.
- **Up to three documents** are read right away, in the conversation. The agent writes their pages and then tells you in a few lines what it learned, what changed or contradicted earlier pages, and which pages it created or updated. A short document takes under a minute.
- **A folder, or more than three documents,** is read and written into the wiki in the background; you keep working. An agent works through the documents ten at a time, one batch after another, and checks the pages it touched; each batch's summary reaches you like any ticket update, in your next message or briefing. When it's all done, a Mac notification says so and how long it took. In Claude Code the agent also waits for it in the background (`bron kb wait`) and tells you itself as soon as it's done; Codex can't wake a conversation, so there you hear it in your next message; `bron kb status` and the ticket show how long reading and writing took. One folder is written at a time: anything you add meanwhile, even in the conversation, waits its turn ("A folder is being written into the wiki; I'll add these after it").
- The very first reading sets up the reading and search tools (about 300 MB, a few minutes).
- A document Bron already read is skipped when it hasn't changed; `--again` reads it again anyway. Reading a document again replaces its text, and the agent updates its page. A copy of a document already read (a "(1)" download, the same file in two folders) is skipped too: same text, no second page.
- More than 300 documents or 3,000 pages: Bron asks first (`--yes` goes ahead).
- Command: `.bron/bin/bron kb add '<link or path>'` (`--inbox` for the inbox). It prints one line per document, like `Read Office lease.pdf (2 pages, 0 scanned) — doc 3f2a…`.

## What can be read

- PDFs (text or scanned), Word, Excel and CSV, PowerPoint, text and Markdown files, images (PNG, JPG, HEIC and similar), and web pages.
- Google Docs, Sheets and Slides, through your Google Drive connection (below).
- Portuguese and English, including Brazilian number and date formats.
- A file that is password-protected, damaged or empty is reported by name and the rest carry on.

## Google Drive

- Bron finds Drive links through Google Drive for desktop on your Mac, so the app must be running. Folders shared with you are found too. Online-only files are downloaded as they're read by Google Drive for desktop; you don't need to make them available offline.
- If a link can't be found, Bron says so: make sure Google Drive for desktop shows the file. Agents never download a Drive file or copy it into the vault themselves.
- Google Docs, Sheets and Slides exist only online, so the agent exports one to a text file through your Google Drive connection and reads that: `.bron/bin/bron kb add --file <file> --source '<link>' --name '<title>'`. `--file` takes only exported text; a PDF or any other file is always given by its Drive link.

## Inbox and files

- Drop files into `Knowledge/Inbox/` and say "read the inbox". Bron keeps a copy in `Knowledge/Files/<year-month>/` and empties the inbox. A file you point to on your Mac outside Google Drive is copied there too; its original is never changed.

## The wiki

```
Knowledge/
  Schema.md      the rules (yours to edit)
  index.md       every page, by type (written by Bron)
  log.md         what happened, newest last (written by Bron)
  Documents/     one page per document
  Organisations/
  People/
  Topics/
  Inbox/  Files/
```

- Every page has `type` and a one-line `summary` (and `aliases` for other names). A document page also has `doc` (Bron's id for the document), `source` (its link or path), `organisation` (the organisation it is mainly about), `doc_type` and `date`.
- Facts cite their source: "(see [[Office lease (2025-03-01)]], p. 2)". When a newer document changes a fact, the page keeps the old value as a "previously" note; when it isn't clear which is right, both stay, marked as a conflict, and the agent asks you.
- An organisation, person or topic gets its own page when a document is mainly about it, when it appears in two or more documents, or when you ask. A folder of 10–15 documents usually gives 10–15 document pages plus about 5–15 others.
- Your edits win: agents keep what you wrote and treat your corrections as the newest source. To correct a document's organisation, type or date, edit its page's properties; search uses them from then on.
- `Knowledge/Schema.md` lists the page types and document types at the top. Add your own, for example:
  ```yaml
  page_types: [Documents, Properties, Organisations, People, Topics]
  doc_types: [lease, utility bill, insurance policy, invoice, other]
  ```
  Each page type is a folder under `Knowledge/`. Ask Bron to change the schema for you if you prefer.

## Asking questions

- Just ask: "what is the rent for shop 4 now?" The agent searches, reads the pages it needs, checks the numbers against the documents, and answers with the document page, page number and link. If nothing answers it, it says so instead of guessing.
- Search finds wiki pages first, then the exact passages in the documents, in English and Portuguese, with or without accents, and numbers in either format (`1.500.000,00` and `1,500,000.00`).
- Narrow it down: `.bron/bin/bron kb search '<question>' --organisation 'Harbor Bakery' --type contract --after 2025-01-01` (`--company` works too); `--pages-only` shows only wiki pages.
- See the text around a passage: `.bron/bin/bron kb show '<document>' --pages 14-16`.
- After an answer that combined several documents, the agent offers "Save this as a page?"; on a yes it becomes a topic page with its citations.

## Checking the wiki

- The health check counts wiki problems (if the check itself fails, it says "The wiki couldn't be checked; run `bron wiki check` for details."): links to pages that don't exist (a link like `[[Organisations/Acme Ltda]]` counts when that path exists, as in Obsidian), pages nothing links to, pages missing `type` or `summary`, documents read without a page, pages whose document was forgotten, probable duplicates (Acme, Acme Ltda.) and pages over 30,000 characters. `.bron/bin/bron wiki check` shows them; `--all` lists every one.
- After each folder, the agent rereads the pages it touched: it settles changes a newer document clearly makes, flags real conflicts to you, creates pages for names that now appear in two or more documents, and lists gaps (a document that's referred to but wasn't read) as suggestions.
- Say "check the wiki" for a full checkup, or "finish the wiki pages" to write the pages of documents that were read without one (an interrupted run, or documents read before the wiki existed).

## Looking after it

- `.bron/bin/bron kb list` shows what was read (`--failed` only what couldn't be, `--organisation` and `--type` narrow it).
- `.bron/bin/bron kb forget '<document>'` removes a document from the knowledge base; the original is never touched. Its wiki page stays until you delete it or keep it (the check reminds you).
- `.bron/bin/bron kb wait` waits until everything is read and written, then prints what you'd be told (and it isn't told again).
- `.bron/bin/bron kb status` shows what's being read or written; `--cancel` stops what is waiting; a run already writing pages finishes, so no page is left half-written. When nothing is happening it says "Nothing is being read."

## Privacy

- Everything stays in your vault: the text and search database in `.bron/kb/`, the wiki in `Knowledge/`. Scanned pages are read on your Mac; search runs on your Mac.
- Your agents read the documents' text and write the pages with your Claude or Codex plan (the same login you use to talk to Bron). A folder in the background is one agent run per ten documents.
- A page too messy for Mac text recognition (a bad scan, a photo) is sent as an image to your plan's model. Turn it off with `knowledge: model_pages: false` in `System/Settings.md`; `max_model_pages` (default 20) limits the pages per document. Each one is logged in `.bron/kb/model-log.jsonl`.
- No document text is sent to a model just to label it: a document's organisation, type and date come from its wiki page (before it has one, from its file and folder names).

## Limits

- A short page (under 50 words, like a cover or signature page) is joined to the next page in search results; the text then shows `[p. N]` where each page starts, and the agent cites that page.
- A badly scanned page can still contain misread characters, so check the numbers that matter against the original.
- Charts and pictures inside documents are not described.
- Each background run writes ten documents, well inside the time limit in `System/Settings.md` (`runner: max_minutes`, 30 by default). A run that stops or fails is tried once more; if it fails again, what was read stays searchable, the documents without a page show up in the check, and "finish the wiki pages" picks them up.
- If the meaning-search model can't be downloaded (no internet, say), documents are still read and found by their words; meaning search starts once the model downloads.

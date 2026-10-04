# Knowledge base

Bron reads the documents you point it to, and every agent can search them and quote them back with the document, page and link.

## What can be read

- PDFs (text or scanned), Word, Excel and CSV, PowerPoint, text and Markdown files, images (PNG, JPG, HEIC and similar), and web pages.
- Google Docs, Sheets and Slides, through your Google Drive connection (see below).
- Portuguese and English, including Brazilian number and date formats.
- A file that is password-protected, damaged or empty is reported by name and the rest carry on.

## Pointing Bron to things

- Say "read this: <Google Drive link>", or give a file or folder path, or a web link. Several at once is fine.
- Bron finds Drive links through Google Drive for desktop on your Mac, so the app must be running. Online-only files are downloaded as they're read; you don't need to make them available offline. If a file isn't there, Bron says which link it couldn't find. A link without `https://` works too.
- A few files are read right away. A big folder, more than 50 pages, or a scan or photo is read in the background and Bron tells you when it is done. The very first reading also sets up the tools in the background. More than 300 documents or 3,000 pages, Bron asks first. The first reading of a large folder can take a while.
- A document Bron already read is skipped if it hasn't changed since, so nothing is read or sent twice. Add `--again` to read it anyway; if its text is the same, its labels are kept without asking the model.
- Command: `.bron/bin/bron kb add '<link or path>'`. Add `--yes` to go ahead with a big folder without being asked.

## Google Docs, Sheets and Slides

Those exist only online, so Bron exports one to a text file through the Google Drive connection and reads that: `.bron/bin/bron kb add --file <file> --source '<link>' --name '<title>'`. Ask the agent to do it; you only paste the link.

## Inbox and files

- Drop files into `Knowledge/Inbox/` and say "read the inbox" (`.bron/bin/bron kb add --inbox`). Bron keeps a copy in `Knowledge/Files/<year-month>/` and the inbox is emptied. A file you point to on your Mac outside Google Drive is copied there too; its original is never changed.
- Files in Google Drive stay in Drive; Bron only reads them.
- Reading the same file again replaces its text. Corrections you made to labels are kept.

## Privacy

- Everything is kept in your vault, in `.bron/kb/`. Scanned pages are read on your Mac. Search runs on your Mac too.
- Two things are sent to your Claude or Codex plan (the same login you use to talk to Bron, so they count towards that plan's usage):
  - **Labels:** the first part of each document's text (about 3,000 characters), so a small model can work out its company, type, date and title. Turn it off with `knowledge: labels: false` in `System/Settings.md`; labels then come from file and folder names only (the company from the parent folder, a date written like 2025.01.21 or 2025-01-21 in the file name, type "other"). You can always correct them with `bron kb label`.
  - **Hard pages:** when a page is too messy for Mac text recognition (a bad scan, a photo), that one page is sent as an image. Turn it off with `knowledge: model_pages: false`; those pages are then left as read. `max_model_pages` (default 20) limits the pages per document.
- Every such call is written to `.bron/kb/model-log.jsonl` (document, app, time, and the page for hard pages or `"kind": "labels"`).
- The one-time setup downloads about 300 MB of reading and search tools the first time you add or search.

## Searching

- Just ask: "what is the purchase price in the Acme SPA?" The agent searches, then answers with the document, page and link. If the documents don't say, it tells you instead of guessing.
- Search works in English and Portuguese, with or without accents, and finds numbers in either format (`1.500.000,00` and `1,500,000.00`).
- Narrow it down: `.bron/bin/bron kb search '<question>' --company Acme --type SPA --after 2025-01-01`.
- See more around a hit: `.bron/bin/bron kb show '<document>' --pages 14-16`.

## Looking after it

- `.bron/bin/bron kb list` shows what was read (`--failed` shows only what couldn't be, `--company` and `--type` narrow it).
- `.bron/bin/bron kb label '<document>' --company … --type … --date … --title …` fixes a wrong label; an empty value undoes your correction. Types: LPA, side letter, subscription agreement, SPA, SHA, term sheet, convertible note, cap table, board minutes, board deck, financial statements, management report, K-1, capital call, distribution notice, valuation, legal opinion, other.
- `.bron/bin/bron kb forget '<document>'` removes it from the knowledge base. The original is never touched.
- `.bron/bin/bron kb status` shows progress; `--cancel` stops a reading.
- The health check warns when documents couldn't be read.

## Limits

- A short page (under 50 words, like a cover or signature page) is joined to the next page in the search results; the text then shows `[p. N]` where each page starts, and Bron cites that page.
- Bron quotes what the text says. A badly scanned page can still contain misread characters, so check the numbers that matter against the original.
- Charts and pictures inside documents are not described.
- Only one reading runs at a time; files that change after being read are read again only when you add them again.
- If the meaning-search model can't be downloaded (no internet, say), documents are still read and found by their words; meaning search for them starts once the model downloads.

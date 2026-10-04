# Bron Knowledge Base, piece 1: reading and searching documents (sub-project 3a)

Status: design approved in conversation on 2026-10-03. Fills the core spec's reserved interface (§8.1) for the reading and search half; the readable company pages in `Knowledge/` are piece 2 (a later spec). Builds on 0.6.1. Where they disagree, this spec wins.

## 1. Purpose

Any agent can answer questions from the fund's documents, with the exact passage, document and page, in a fraction of a second, in English and Portuguese. Bron reads only what the user points it to; originals stay in Google Drive.

## 2. Decisions (approved by the user)

- **D1. Piece 1 is reading + search;** company pages come later.
- **D2. Only what the user points to:** a Drive link (file or folder), a file path, the vault inbox (`Knowledge/Inbox/`), or a web link. No background watching; a folder is read once.
- **D3. New versions:** pointing to a document Bron has read (same Drive ID or same path) replaces its text; a different file (e.g. an amendment) is a separate document.
- **D4. Labels:** a small model suggests company/fund, document type, date, title and language per document; Bron confirms in one summary line; the user's corrections always win.
- **D5. Difficult pages:** read on the Mac first; only pages that still come out badly go to the model (once per page, logged); `knowledge.model_pages: false` turns that off.
- **D6. Search:** keyword + meaning search, on the Mac, across English and Portuguese.
- **D7. Every agent can search everything.**
- **D8. Built from small, permissively licensed parts** (no all-in-one toolkit, no external search service); agents use plain `bron kb …` commands (no MCP server).

## 3. Verified before planning (2026-10-03, on the user's Mac)

1. **Drive for desktop** is installed (`~/Library/CloudStorage/GoogleDrive-<account>/My Drive`, `Shared drives`). Every file and folder carries its Drive ID in the extended attribute `com.google.drivefs.item-id#S` (the ID in a Drive link). Google Docs/Sheets/Slides are stub files (`.gdoc/.gsheet/.gslides`) that can't be read locally.
2. **Mac text recognition** (`ocrmac`, Apple Vision, `recognition_level="accurate"`, `language_preference=["pt-BR","en-US"]`) read a Portuguese contract page perfectly (accents, "R$ 1.500.000,00") in 0.1–0.2 s per page once warm (first call in a process ≈ 30 s framework load). Tables lose their columns (→ model fallback).
3. **Meaning-search model:** `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` via `fastembed` (ONNX, Apache-2.0, 220 MB, 384 dimensions): best of the candidates on an English-question / Portuguese-passage test (7/8 first-hit), 150 passages/s, 2 ms per query. (Qwen3-Embedding-0.6B-Q: 6/8 at 9 passages/s; potion-multilingual: 4/8.) Its input limit is 128 tokens, so meaning search embeds ~100-word windows of each passage.
4. **Hard pages by model:** both CLIs transcribed a page image with a table into exact Markdown:
   - Claude Code: `claude -p --model haiku --tools Read --strict-mcp-config --disable-slash-commands --no-session-persistence --setting-sources ""` from a temporary folder holding only the image (~7 s);
   - Codex: `codex exec --ephemeral --skip-git-repo-check -s read-only -m gpt-6-luna -c model_reasoning_effort=low --ignore-user-config --disable shell_tool --disable apps -i <image> -` (~10 s).

## 4. Sources (how documents come in)

| Source | How |
|---|---|
| Drive link to a file or folder | Bron extracts the ID from the link, finds the item under the Drive mount by its ID attribute (a cached ID→path map in `.bron/kb/drive-ids.json`, filled by walking the mount from the account roots; folders first), and reads files in place. "Online only" files are downloaded by Drive as they're read. |
| Google Docs / Sheets / Slides | Not readable locally. The agent exports them through the user's Google Drive connector and passes the text with `bron kb add --file <exported text> --source <drive link> --name '<title>'`; Bron treats the result as that document (same ID rules). For a folder, Bron lists the Google-native files it found and the agent exports each. |
| Inbox / file path | `Knowledge/Inbox/` (created by the template) or any path. Copied to `Knowledge/Files/<YYYY-MM>/` after reading (the only copies Bron keeps); the inbox is emptied of files that were read. |
| Web page | `bron kb add <url>`: fetched with `curl`, main text extracted (`trafilatura`), saved with URL and read date. |

Identity: Drive files by Drive ID; local files by absolute path of the kept copy; web pages by URL. Reading a known identity again replaces the old text, labels (except user corrections) and index entries.

Folders larger than 300 documents or 3,000 pages ask first: "This folder has N documents (about P pages). The first reading takes about T in the background. Go ahead?"

## 5. Reading

Per file type (all in-process Python unless noted):

| Type | Reader |
|---|---|
| PDF | `pypdfium2` text per page; a page whose text is missing or garbled (too few characters for its area, or a high share of replacement/odd characters) is rendered and read with Mac text recognition |
| Image (png, jpg, heic, tiff) | Mac text recognition |
| Excel (xlsx, xls, xlsm) / CSV | `python-calamine`: each sheet with its name, header row and values (formula results) as a Markdown table, split into row blocks of ~50 rows that repeat the header |
| Word (docx) | `python-docx`: headings, paragraphs and tables in order |
| PowerPoint (pptx) | `python-pptx`: text per slide (titles, bodies, tables, notes) |
| Text / Markdown / HTML file | as text (HTML through the same main-text extractor) |
| Other | reported as "can't read this kind of file" |

**Hard pages:** after Mac text recognition, a page is "hard" when it looks like a table whose columns didn't survive (many short numeric fragments on separate lines) or recognition confidence is low. Hard pages go to the model of the default CLI (headless, as in §3.4) at most `knowledge.max_model_pages` per document (default 20), result cached by page-image hash in `.bron/kb/pages/`, each call logged in `.bron/kb/model-log.jsonl` (time, document, page, CLI). With `knowledge.model_pages: false` the Mac result is kept.

**Labels:** one small-model call per document (the summary model from memory settings, headless, no tools) given the file name, folder path and first ~3,000 characters; it returns `company` (or fund), `doc_type` (from a fixed list: LPA, side letter, subscription agreement, SPA, SHA, term sheet, convertible note, cap table, board minutes, board deck, financial statements, management report, K-1, capital call, distribution notice, valuation, legal opinion, other), `date` (YYYY-MM-DD or empty), `title`, `language`. User corrections (`bron kb label <doc> --company … --type … --date …`) are stored separately and always win.

**Passages:** split by the document's structure: headings, numbered clauses (`Cláusula 4.2`, `Section 4.2(b)`, `4.2.`, `Art. 5º`), slides, sheet row blocks; about 300–500 words; a table is never split mid-row; each passage stores page (or slide/sheet), section heading, and a header line `[Company | Type | Date | Title | p. N | Section]` that is indexed with it.

**Normalisation for search:** amounts (`1.500.000,00`, `1,500,000.00`, `R$ 1,5 mi`, `1.5M`) and dates (`21/01/2025`, `2025-01-21`, `21 de janeiro de 2025`, `January 21, 2025`) get extra normalised tokens indexed alongside the passage, so either form finds the other.

## 6. Storage (`.bron/kb/`)

- `docs/<doc-id>/meta.json` (source, identity, labels, user labels, read date, page count, status), `pages.jsonl` (text per page), `passages.jsonl`.
- `index.db`: SQLite with FTS5 (`unicode61 remove_diacritics 2`) over passages + headers + normalised tokens, and the meaning vectors (384-dim float32 per ~100-word window, stored as blobs; search by brute-force cosine in numpy over the filtered set — tens of thousands of windows stay well under 0.1 s; `sqlite-vec` only if measurement shows it's needed).
- Rebuildable: the index can be rebuilt from `docs/` without re-reading any original.
- `jobs/<job-id>.json`: background reading jobs (pending items, done, failed with reasons).

## 7. Searching

- `bron kb search '<question>' [--company X] [--fund X] [--type T] [--after YYYY-MM-DD] [--before YYYY-MM-DD] [--limit 8]`: filters first; keyword top 50 + meaning top 50 merged by reciprocal-rank fusion (k = 60); returns passages with document title, labels, page/section, source (Drive link or path) and text. Target ~0.2 s warm.
- **Warm search service:** the meaning model takes a few seconds to load, so the first search starts a small background helper (`bron kb serve`, a Unix socket in `.bron/kb/`) that keeps the model loaded and exits after 30 minutes without searches; later searches talk to it. If the helper can't start, search falls back to loading the model in-process (slower, still correct) or to keyword-only with a one-line note.
- `bron kb show <doc> [--pages 14-16]`: the text Bron read (to read around a passage).
- `bron kb list [--company X] [--type T]`, `bron kb forget <doc>`, `bron kb label <doc> …`, `bron kb status` (reading jobs and their progress).
- **Rules in AGENTS.md** (short): search the knowledge base before answering questions about fund or company documents; cite document and page with the link; copy numbers exactly; say plainly when the passages don't answer; use `show` for more context.

## 8. Reading jobs

`bron kb add <link|path|url|--inbox> [...]` resolves the sources, asks first above the size threshold (§4), then reads in a detached background job (one at a time; others queue) and prints "Reading N documents in the background; I'll report when it's done." Small requests (≤ 5 documents) run in the foreground. Each document is committed when done, so an interrupted job resumes without re-reading finished documents. When a job finishes, the result summary (read, scanned, model pages, labels, failures with reasons) is delivered like ticket updates: in the next briefing or message (`bron kb status` any time).

## 9. Setup and dependencies

The reading and search dependencies (`pypdfium2`, `ocrmac`, `python-calamine`, `python-docx`, `python-pptx`, `trafilatura`, `fastembed`, `numpy`) are an optional extra of the engine (`bron-engine[kb]`), installed the first time a `bron kb` command runs (one line before: "Setting up the knowledge base tools (about 300 MB, one time)…"), into the vault's `.bron/venv` with uv; the model files cache under `.bron/kb/models/`. `bron update` keeps the extra installed when it was installed before. All licences permit use in an MIT project (no AGPL parts).

## 10. Settings (`System/Settings.md`)

```yaml
knowledge:
  model_pages: true        # send hard pages to the model
  max_model_pages: 20      # per document
```

## 11. Health check

Documents that failed to read (warning, with count); index missing or unreadable (warning: "Bron will rebuild it from the stored text on the next search"); tools not installed yet (info line in `bron kb status`, not a warning).

## 12. Error handling

Every failure is a plain sentence and never stops a batch: password-protected, damaged, unsupported type, Drive file couldn't download, link not found under the Drive mount ("open Google Drive for desktop and make sure this file is available"), web page unreachable. A crash mid-job resumes. Model steps that fail fall back to the Mac result (hard pages) or empty labels (labels) and are retried on the next read of that document.

## 13. Testing

- Sample documents generated by the tests (no real files): English and Portuguese PDFs with text, a scanned page (image-only PDF), a page with a table, xlsx with two sheets, docx with headings and a table, pptx, an HTML page; a fake Drive mount with ID attributes.
- Unit tests: source resolution (links, IDs, paths, inbox, URL), each reader, hard-page detection, label parsing and user-label override, passage splitting (clauses, tables kept whole), normalisation (amounts, dates both ways), index build and rebuild, search with filters, keyword/meaning fusion, cross-language retrieval on the sample set, re-reading replaces, forget, jobs (resume after interruption, failure reporting, queueing), warm helper (start, reuse, idle exit, fallback). Unit tests never call a real model (stand-in model) and use a tiny stand-in embedding function unless marked slow.
- Speed test (marked slow): ~1,000 generated pages read and indexed; search under 0.2 s warm.
- Live test (`BRON_LIVE=1`): in each CLI, read the sample documents, ask two questions (one cross-language), check citations.

## 14. Release

Ships as 0.7.0 with a CHANGELOG entry and a manual page (`core/Manual/knowledge.md`). Template adds `Knowledge/Inbox/` and `Knowledge/Files/`.

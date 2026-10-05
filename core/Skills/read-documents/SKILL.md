---
name: read-documents
description: Keep the wiki in Knowledge/. Use right after `bron kb add` reads documents (write their pages), when a background run asks you to read documents into the wiki, when the user says "save this as a page", "finish the wiki pages" or "check the wiki", and when a document was read again or forgotten.
---

# Read documents into the wiki

`Knowledge/` is a wiki that you keep: Markdown pages that compile what the user's documents say, linked to each other, so knowledge is worked out once and kept current instead of being worked out again for every question.
- **The documents** are the sources. They never change and stay where they are (Google Drive, the web, or `Knowledge/Files/`). Bron has their text, page by page: `bron kb show` and `bron kb search` (below).
- **The wiki** is yours to write: a page per document, plus pages for organisations, people and topics.
- **`Knowledge/Schema.md`** is the rulebook: page types, document types, names. The user can change it; when it says something different from this skill, it wins.
- Bron's code does the bookkeeping: `index.md` (the catalogue), `log.md` (the record of what happened), the search database and the mechanical checks. Never edit `index.md` or `log.md`.

## Read documents (ingest)

Read `Knowledge/Schema.md` first. Then take each document `bron kb add` printed (`Read <name> … — doc <id>`, or `Already read … (no page yet)`), one at a time:

1. **Read it.** `.bron/bin/bron kb show <doc id>` prints the first 20 pages, each starting with `--- p. N ---`; continue with `--pages 21-40` and so on. Read every page of a document up to about 60 pages; for a longer one, read the beginning, the contents and the sections that matter, and use `.bron/bin/bron kb search '<words>'` for the rest.
2. **See what the wiki already knows.** Note the organisations, people, topics and other documents it mentions. For each name run `.bron/bin/bron kb search '<name>' --pages-only` and open the pages it finds. Read every page you are going to change before you change it.
3. **Write the document page** in `Knowledge/Documents/` (format below): what the document is, its key facts each with its page number, the parties, and what it changes or contradicts in the wiki.
4. **Update the pages it touches.** A rich document often touches 10–15 pages. For each organisation, person or topic that has a page, or now needs one (see "When a page is created"), add what this document says under the right heading, each fact with its citation. Add what's new; don't repeat what's there.
5. **Handle contradictions.** When this document says something different from a page:
   - if it clearly supersedes the earlier one (newer, an amendment, a correction), update the fact and keep the old one as a short note: "now USD 4,450.00 (see [[Rent increase (2026-01-10)]], p. 1); previously USD 4,200.00 (see [[Office lease (2025-03-01)]], p. 2)";
   - otherwise it's a real conflict: keep both with their citations, mark it **Conflict:** and tell the user. Never decide it yourself.
   Never delete a fact silently.
6. **Cross-link.** Every page you add a fact to cites the document page; the document page links to the organisation, person and topic pages it touches. When you create a page for a name that earlier pages mention as plain text, turn those mentions into links (a `--pages-only` search for the name finds them).
7. Go on to the next document.

When all the documents are done, run `.bron/bin/bron wiki done`. It records the document pages, updates the search database, `index.md` and `log.md`, and checks what changed. Fix every problem it lists (a broken link, a missing `summary`…) and run it again until it lists none. The exception is a page nothing links to (an orphan) that you can't fix: link every document page from the page of its main organisation, and if an orphan is still unavoidable, leave it for the user and don't keep running `wiki done` to clear it.

Then tell the user, in a few lines: what you learned, what changed or contradicted earlier pages, which pages you created and which you updated, and any document that couldn't be read. Don't paste whole pages.

If `bron kb add` said "A folder is being written into the wiki; I'll add these after it", don't write pages for those documents: the background run will. Never poll `bron kb status` while you wait.

### When a page is created

An organisation, person or topic gets its own page when:
- a document is mainly about it, or
- it appears in two or more documents, or
- the user asks for one.

A one-off mention stays plain text on the document page. When a second document mentions it, create its page and turn the earlier mention into a link. A folder of 10–15 documents usually gives 10–15 document pages plus about 5–15 others.

### Document page

File: `Knowledge/Documents/<Title> (<YYYY-MM-DD>).md`: the title as the user would say it ("Office lease", not "scan_0042"), with the document's date; without a known date, just `<Title>.md`. Replace characters that can't be in a file name (`/ \ : * ? " < > | # ^ [ ]`) with a dash.

```markdown
---
type: document
summary: <one line: what it is, between whom, what it does>
aliases: []
doc: "<doc id from bron kb add>"
source: <the link or path `bron kb show` prints under the title>
organisation: "[[<the organisation it is mainly about>]]"
doc_type: <one of the doc_types in Knowledge/Schema.md>
date: <YYYY-MM-DD, or leave it empty>
---

# <Title>

<Two or three sentences: what this document is and why it matters.>

## Key facts
- <fact, with numbers and terms exactly as written> (p. 3)

## Parties
- [[<Organisation with a page>]] — <role>
- <Name mentioned only here> — <role>

## What it changes
- <what it adds to, changes in or contradicts in earlier pages, with links; or "Nothing earlier in the wiki.">
```

Put links and the doc id in properties in quotes (`"[[Name]]"`, `"3f2a…"`) so they're read correctly. Always keep `doc` in quotes: an all-digit id without quotes is read as a number and loses its leading zeros.

### Other pages

Organisation, person and topic pages (and any type `Knowledge/Schema.md` adds) live in their type's folder, named the way the user would say it ("Acme Ltda", "Jane Doe", "Office move"). Use the headings the schema suggests for the type.

```markdown
---
type: organisation
summary: <one line>
aliases: [<other names, abbreviations>]
---

# <Name>

## <Heading>
- <fact> (see [[<Document page>]], p. 3)
```

### Citations

Every fact on a page other than the document's own page ends with `(see [[<Document page>]], p. N)`; on the document page itself, `(p. N)` is enough. Copy numbers, dates and names exactly as the document writes them. A fact without a source is a guess: leave it out.

### Your edits win (the user's)

Keep what the user wrote on a page, word for word, unless they ask you to change it. A correction from the user (on a page, in its properties or in the conversation) counts as the newest source: cite it as "(the user, YYYY-MM-DD)" and keep it over what an older document says.

## Background runs

A ticket may ask you to read several documents into the wiki. Do the same as above, document by document. Nobody is waiting, so don't ask questions: note real conflicts and open questions in your final reply. When the documents are done, run the judgement checkup below over the pages you touched, then `.bron/bin/bron wiki done --log 'check | <what the checkup found and fixed>'`. Your final reply is the summary the user reads: what you learned, what changed or contradicted, the pages created and updated, and the documents that couldn't be read.

## Judgement checkup

After a folder, and as part of "check the wiki", over the pages you touched and the pages they link to:
1. Reread them.
2. Contradictions: where a later document clearly supersedes an earlier one, write "now X (…); previously Y (…)". Where it doesn't, mark **Conflict:** with both citations and tell the user; never decide it.
3. Organisations and people that now appear in two or more documents without a page: create their pages and link the mentions.
4. Gaps: documents that are referred to but weren't read ("the amendment of June 2025 is referred to but wasn't read"), missing dates, missing parties. List them for the user as suggestions; never go and fetch anything yourself.
5. Run `.bron/bin/bron wiki done --log 'check | <pages checked, what you fixed, what you flagged>'`.

## "Check the wiki" (full checkup)

1. `.bron/bin/bron wiki check --all` lists the mechanical problems: broken links, pages nothing links to, missing `type` or `summary`, documents read without a page, pages whose document was forgotten, probable duplicates, pages over 30,000 characters.
2. Fix them: create or relink missing pages; add properties; merge duplicates (keep one page, move the facts with their citations, list the other names under `aliases`, point the links to the page you kept); split long pages by heading. Ask the user before deleting a page.
3. Documents "read but no page yet": write their pages as in the ingest steps. This is also what "finish the wiki pages" means.
4. Run the judgement checkup over the whole wiki, one type folder at a time.
5. Tell the user what you fixed and what needs their decision.

## Save an answer as a page

After an answer that combined several documents, offer: "Save this as a page?" Only on a yes: write a topic page in `Knowledge/Topics/` with the answer, every fact cited, link it from the pages it drew on, and run `.bron/bin/bron wiki done --log 'save | <page title>'`.

## A document read again, or forgotten

- **Read again** (`bron kb add` printed `Read …` for a document that already has a page): read it, update its page and the pages it touches, and mark what changed with "previously". Then `.bron/bin/bron wiki done`.
  `--again` rereads a document that hasn't changed (`kb add` otherwise says it's already read and unchanged).
- **Forgotten** (`bron kb forget` said its page is still there): ask the user whether to delete the page. If they keep it, remove its `doc` property so the check stops flagging it, and say in its summary that the document was removed.

## Never

- download or copy a Drive file, or put a document into `Knowledge/` yourself (only `bron kb add` keeps copies, in `Knowledge/Files/`);
- edit `index.md` or `log.md`;
- poll `bron kb status`;
- invent a fact, a number or a citation;
- decide a real conflict for the user.

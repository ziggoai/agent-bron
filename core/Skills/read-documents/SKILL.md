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

Read `Knowledge/Schema.md` first. Then take each document `bron kb add` printed (`Read <name> … — doc <id>`, or `Already read … (no page yet)`), one at a time (a `Skipped <name>: same text as …` line is a copy of a document already read: it gets no page; just tell the user it was skipped):

1. **Read it.** `.bron/bin/bron kb show <doc id>` prints the first pages, each starting with `--- p. N ---`, as many as fit in one output it can show in full, and ends with the command for the next ones (`--pages 9-28`, or `--pages 4 --part 2` inside one very long page). Read the text where the command prints it; don't save it to files. Run each `kb show` on its own: anything else in the same command (a `cat`, a second `show`) makes the output too long to be shown, and it gets cut. Read every page of a document up to about 60 pages; for a longer one, read the beginning, the contents and the sections that matter, and use `.bron/bin/bron kb search '<words>'` for the rest.
2. **See what the wiki already knows.** Note the organisations, people, topics and other documents it mentions. For each name run `.bron/bin/bron kb search '<name>' --pages-only` and open the pages it finds. Read every page you are going to change before you change it.
3. **Write the document page** in `Knowledge/Documents/` (format below): what the document is, its key facts each with its page number, the parties, and what it changes or contradicts in the wiki.
4. **Update the pages it touches.** A rich document often touches 10–15 pages. For each organisation, person or topic that has a page, or now needs one (see "When a page is created"), add what this document says under the right heading, each fact with its citation. Add what's new; don't repeat what's there.
   Put each fact on the page it is most about. A person or organisation that appears in many documents (someone who signs most of them, a law firm, the user's own company) gets their roles, relationships and changes, not a line per document. **Never add a "signed …", "attended …" or "party to …" line to their page:** who signed what stays under the document page's Parties, and a role they already have gets the new document as one more citation on its line. A page that lists many things of one kind (contracts, projects, holdings) keeps one short line each, linking to the thing's own page, where the detail goes; when a topic page already lists them, link the topic instead of repeating it. When such a list passes about 20 lines, move it to its own topic page ("<Name> <things>", for example "Acme Ltda contracts") with one line per item, and leave one line on the page linking it. The user's own organisation, a person who signs most documents and a firm that serves many clients are the usual cases.
5. **Handle contradictions.** When this document says something different from a page:
   - if it clearly supersedes the earlier one (newer, an amendment, a correction), update the fact and keep the old one as a short note: "now USD 4,450.00 (see [[Rent increase (2026-01-10)]], p. 1); previously USD 4,200.00 (see [[Office lease (2025-03-01)]], p. 2)";
   - otherwise it's a real conflict: keep both with their citations, mark it **Conflict:** and tell the user. Never decide it yourself.
   Never delete a fact silently.
6. **Cross-link.** Every page you add a fact to cites the document page; the document page links to the organisation, person and topic pages it touches. When you create a page for a name that earlier pages mention as plain text, turn those mentions into links (a `--pages-only` search for the name finds them).
7. Go on to the next document.

A document you leave out on purpose (the user's rule says to skip that kind, a blank form) gets no page: run `.bron/bin/bron kb forget <doc id>` so the check stops listing it, and say in your reply what you left out and why.

When all the documents are done, run `.bron/bin/bron wiki done`. It records the document pages, updates the search database, `index.md` and `log.md`, and checks what changed. Fix every problem it lists (a broken link, a missing `summary`…) and run it again until it lists none. The exception is a page nothing links to (an orphan) that you can't fix: link every document page from the page of its main organisation, and if an orphan is still unavoidable, leave it for the user and don't keep running `wiki done` to clear it.

Then tell the user, in a few lines: what you learned, what changed or contradicted earlier pages, which pages you created and which you updated, and any document that couldn't be read. Don't paste whole pages.

If `bron kb add` said "A folder is being written into the wiki; I'll add these after it", don't write pages for those documents: the background run will. Never poll `bron kb status` while you wait, and never wait for it with `sleep` or by reading the documents yourself: tell the user it's being written and go on.

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
aliases: ["<other name>", "<abbreviation>"]
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

Put links and the doc id in properties in quotes (`"[[Name]]"`, `"3f2a…"`) so they're read correctly. Put every alias in double quotes too: an alias with a comma ("Acme, Inc.") splits in two without them. With no other names, write `aliases: []`. Always keep `doc` in quotes: an all-digit id without quotes is read as a number and loses its leading zeros.

**One page for several documents.** Copies and drafts of a document that has a page, and a set of near-identical documents (the same form signed by different people, a batch of standard agreements), share one page: list every doc id under `doc` (`doc: ["3f2a…", "9b1c…"]`), add a short table or list with one line per document (its date, the parties, what differs, its link), and keep the facts that only one of them has. Don't write a page per copy or per form.

### Other pages

Organisation, person and topic pages (and any type `Knowledge/Schema.md` adds) live in their type's folder, named the way the user would say it ("Acme Ltda", "Jane Doe", "Office move"). Use the headings the schema suggests for the type.

```markdown
---
type: organisation
summary: <one line>
aliases: ["<other name>", "<abbreviation>"]
---

# <Name>

## <Heading>
- <fact> (see [[<Document page>]], p. 3)
```

### Citations

Every fact on a page other than the document's own page ends with `(see [[<Document page>]], p. N)`; on the document page itself, `(p. N)` is enough. Copy numbers, dates and names exactly as the document writes them, except that a share a spreadsheet stores as a fraction (0.0831903962) is written as a percentage with two decimals (8.32%). A fact without a source is a guess: leave it out.

### Your edits win (the user's)

Keep what the user wrote on a page, word for word, unless they ask you to change it. A correction from the user (on a page, in its properties or in the conversation) counts as the newest source: cite it as "(the user, YYYY-MM-DD)" and keep it over what an older document says.

### Keeping pages current

Whenever a fact on a page changes (a newer document, a correction from the user, an answer):
- check that the page's `summary` still holds, and fix it if it repeats the old fact: it is what `index.md` and search show;
- when it answers an open question, put the answer where it belongs on the page, with its source, and delete the question. "Open questions" lists only what is still open;
- when you check a fact against another source (a system the user connected, the user), update every page that says it hasn't been checked yet: search for the phrase, not just the page in front of you;
- when a page grows past 20,000 characters (a document page 30,000), tidy it to about 15,000 characters (a document page: split it): merge lines that say the same thing (one line, several citations) and move detail to the pages it is about. `wiki done` lists such pages. Every later run reads the page again, so a long page slows every one of them. Keep `summary` to one line under 300 characters: it's what `index.md` and search show.

## Background runs

A ticket may ask you to read several documents into the wiki. Do the same as above, document by document. Nobody is waiting, so don't ask questions: note real conflicts and open questions in your final reply. When the documents are done, run the judgement checkup below over the pages you touched, then `.bron/bin/bron wiki done --log 'check | <what the checkup found and fixed>'`. Your final reply is the summary the user reads: what you learned, what changed or contradicted, the pages created and updated, and the documents that couldn't be read.

Reader helpers: give each a few documents and ask for the facts the page needs, with page numbers and exact wording. Write the pages from the readers' notes; open a document yourself only to check a fact you are about to cite. Reading it all again yourself doubles the cost.

## Judgement checkup

After a folder, and as part of "check the wiki", over the pages you touched and the pages they link to:
1. Reread them.
2. Contradictions: where a later document clearly supersedes an earlier one, write "now X (…); previously Y (…)". Where it doesn't, mark **Conflict:** with both citations and tell the user; never decide it.
3. Organisations and people that now appear in two or more documents without a page: create their pages and link the mentions.
4. Gaps: documents that are referred to but weren't read ("the amendment of June 2025 is referred to but wasn't read"), missing dates, missing parties. List them for the user as suggestions; never go and fetch anything yourself.
5. Run `.bron/bin/bron wiki done --log 'check | <pages checked, what you fixed, what you flagged>'`.

## "Check the wiki" (full checkup)

1. `.bron/bin/bron wiki check --all` lists the mechanical problems: broken links, pages nothing links to, missing `type` or `summary`, documents read without a page, pages whose document was forgotten, probable duplicates, names two pages answer to, pages over 20,000 characters (document pages 30,000), summaries over 300 characters. It also prints a "worth a look" list (notes saying something isn't checked yet, numbers in spreadsheet form, timelines out of order; timelines are expected oldest first); each item may be a false alarm, so check before changing anything.
2. Fix them: create or relink missing pages; add properties; merge duplicates (keep one page, move the facts with their citations, list the other names under `aliases`, point the links to the page you kept); keep a shared name on one page only; tidy long pages (one line per fact, detail on the pages it is about) and split a long document page by heading. Ask the user before deleting a page.
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
- save document text in a file outside the vault (`/tmp` and the like): it is left there for anyone on the computer to read, and reading it back needs the user's OK. If you really need a scratch file, use `.bron/tmp/` (`mkdir -p .bron/tmp` first) and leave it there: Bron clears it, and deleting a file needs the user's OK, which stops a background run;
- write complicated shell commands (variables such as `$d`, loops, `cd ..`, several commands chained): run one simple command at a time, so it's clear what each does and a conversation doesn't stop for the user's OK; quote separators (`echo '---'`: a bare `=====` fails in zsh);
- edit `index.md` or `log.md`;
- poll `bron kb status`;
- invent a fact, a number or a citation;
- decide a real conflict for the user.

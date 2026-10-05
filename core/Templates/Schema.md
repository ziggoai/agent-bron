---
page_types: [Documents, Organisations, People, Topics]
doc_types: [contract, invoice, receipt, statement, report, financial statements, budget, presentation, meeting minutes, policy, letter, form, spreadsheet, other]
---

# Wiki schema

The rules for the wiki in `Knowledge/`. Agents read this file before they write pages. It's yours: change it to fit your work, or ask Bron to change it. The two lists at the top are what Bron's code reads: `page_types` (the page folders, in the order `index.md` shows them) and `doc_types` (the kinds of document a document page can be).

## Page types

| Folder | `type` | One page per | Suggested headings |
|---|---|---|---|
| `Documents/` | document | document read (a contract, a report, a letter…) | Key facts · Parties · What it changes |
| `Organisations/` | organisation | company, public body, association or other organisation | Overview · Relationships · Key facts · Timeline |
| `People/` | person | person | Role · Organisations · Key facts |
| `Topics/` | topic | subject that runs across documents (a project, a policy, a question you asked) | Summary · Details · Open questions |

To add a type, add its folder to `page_types` above and a row to this table: for example `Properties` (type `property`, one page per building) or `Projects` (type `project`). Every page lives in its type's folder.

## Properties

Every page has `type` (from the table), `summary` (one line; it shows in `index.md` and in search) and, when it has other names, `aliases`.

Document pages also have `doc` (in quotes; Bron's document id), `source` (the Drive link, web link or kept-copy path), `organisation` (the organisation the document is mainly about, as a link), `doc_type` (one of `doc_types` above) and `date` (YYYY-MM-DD, or empty). Search uses `organisation`, `doc_type` and `date` as its filters, so correcting them on the page corrects the search.

## Names

- Pages are named the way you would say them: "Office lease (2025-03-01)", "Acme Ltda", "Jane Doe", "Office move".
- Document pages end with the document's date in brackets, when it has one.
- One page per thing: other spellings and abbreviations go in `aliases`, not in a second page.

## When a page is created

An organisation, person or topic gets its own page when a document is mainly about it, when it appears in two or more documents, or when you ask for one. A one-off mention stays as plain text on the document page; when a second document mentions it, its page is created and the earlier mention becomes a link.

## Citations

Each fact says where it comes from: `(see [[<Document page>]], p. 3)` on other pages, `(p. 3)` on the document's own page. Numbers, dates and names are copied exactly as the document writes them.

## When documents disagree

A fact replaced by a newer document is updated with a short "previously" note, never silently deleted: "now 30 days (see [[Amendment (2025-06-01)]], p. 1); previously 60 days (see [[Service agreement (2024-01-15)]], p. 4)". When it isn't clear which one is right, both stay, marked **Conflict:**, and the agent asks you.

## Your edits win

Agents keep what you wrote on a page and never rewrite it unasked. A correction from you counts as the newest source.

## Not part of the wiki

- `index.md` (the catalogue) and `log.md` (the record of what happened) are written by Bron; don't edit them.
- `Inbox/` holds files waiting to be read; `Files/` keeps Bron's copies of files that came from this Mac. Files in Google Drive stay in Drive.

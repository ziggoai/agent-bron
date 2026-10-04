# Bron Knowledge Wiki (0.8.0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reading a document builds a Karpathy-style wiki in `Knowledge/` (a page per document plus organisation, person and topic pages, with `index.md` and `log.md`), agents answer from those pages and check details against the document passages, and Bron's code does the bookkeeping (finding files, extracting text, indexing pages, index/log, mechanical checks, background wiki runs).

**Architecture:** The 0.7 reading layer (`core/Engine/bron/kb/`: sources, readers, passages, store, index, search, jobs, warm helper) stays and loses its label model call. New modules: `kb/schema.py` (Schema.md, index/log headers), `kb/wiki.py` (pages, their links and properties, index.md, log.md, document page ↔ document mapping), `kb/wiki_index.py` (pages in the same SQLite database, searched beside passages), `kb/wiki_check.py` (mechanical checks), `kb/wiki_done.py` + `kb/wiki_cli.py` (`bron wiki done|check`), `kb/wiki_run.py` (the background wiki run: one ticket through `runner.run_ticket`, inside the existing kb job), and `migrations/knowledge_wiki.py`. Agents do the writing by following the new `read-documents` skill; `AGENTS.md` carries the short rules.

**Tech Stack:** Python 3.12 engine (uv), SQLite FTS5 + numpy vectors (existing), PyYAML frontmatter (existing `bron.frontmatter` / `bron.fmedit`), pytest. Claude Code and Codex through the existing ticket runner.

**Spec:** `docs/superpowers/specs/2026-10-04-bron-knowledge-wiki-design.md` (binding). Context: `docs/superpowers/specs/2026-10-03-bron-knowledge-ingest-design.md`.

## Global Constraints

- No personal data anywhere (code, tests, fixtures, docs, commit messages): no real names, companies or emails. Use invented names such as Acme Ltda, Northwind Properties Ltd, Harbor Bakery LLC, Jane Doe.
- Shipped text is domain-neutral: no fund/VC/investment wording (no "fund", "portfolio", "investor", "LPA", "capital call", "cap table", "term sheet", "side letter", "K-1") in `core/Skills/read-documents/SKILL.md`, `core/Templates/Schema.md`, `template/Knowledge/*`, `core/Manual/knowledge.md`, the CHANGELOG 0.8.0 section and the AGENTS.md Knowledge base section. Task 10 adds a test that scans them.
- Drive files are never copied or downloaded by Bron: Drive files are read where Google Drive for desktop keeps them; only inbox / Mac-path files get a kept copy in `Knowledge/Files/<YYYY-MM>/` (spec D7). `--file` takes only exported text (spec §3 item 3).
- User-facing messages are plain English; every failure is one plain sentence (never a traceback; unexpected errors go to `.bron/logs/kb-errors.log`, as `kb/cli.py:104-115` does).
- `wiki done` never fails because of one bad page: it reports it and carries on (spec §10).
- The AGENTS.md "Knowledge base" section stays ≤ 1,600 characters and every `.bron/bin/bron …` command in it parses (`tests/test_kb_health.py:79-104`). The template is a `string.Template`: a literal `$` must be written `$$`.
- Unit tests never touch the real home, the real Drive, a real model or a real CLI: stand-ins from `tests/kbkit.py` (`FakeEmbedder`/`fake_embed`, `FakeOcr`, `FakeModel`, `hook_reads`, `FakeTicketRunner`, `fake_drive`, `set_drive_id`) and monkeypatches. `~/Library/Caches/Bron` is never touched by tests: `BRON_KB_SOCKET_DIR` is set for every unit test by `tests/conftest.py:14-24`; keep it that way. Slow tests need `BRON_SLOW=1`, live tests `BRON_LIVE=1`.
- Tests: `uv run --project core/Engine pytest tests -q` must pass at the end of every task.
- Releases go through `scripts/release.sh 0.8.0` — not part of this plan; the controller releases after the last task. Do not bump versions in tasks.
- Git: work on `main`; plain separate git commands; never push; never stage `Bron Framework/` or `.claude/`. Every commit message ends with a blank line then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. The repo-local author is "Ziggo AI" (already configured; don't change it).
- Follow the existing code's style: `from __future__ import annotations`, lazy imports inside CLI handlers, module docstrings in plain words, `statefile` helpers for JSON state, `store._write` for atomic writes.

## Rulings (spec ambiguities resolved here)

- **Ruling 1 — foreground budget.** Spec §8 says "up to 3 documents → foreground (including scans and first-time setup)". A `kb add` stays in the foreground when it names ≤ 3 documents, no folder, and their estimated reading time is ≤ 300 s (text pages 0.05 s each, scanned pages 1 s each); otherwise it goes to the background with a wiki run. Why: the agent's command timeout is 10 minutes (spec §5.1); three 1,000-page scans would blow it. This replaces 0.7's 50-page rule.
- **Ruling 2 — the inbox counts by documents.** `--inbox` is not a "folder" for the threshold (spec §5.1 lists `--inbox` with the 1–3 document path); a Drive folder link or a local folder path is.
- **Ruling 3 — every background job writes the wiki.** Whatever is read in the background (a folder, more than 3 documents, or ≤ 3 over the time budget, or behind another reader) gets the background wiki run, because no agent is waiting to write its pages.
- **Ruling 4 — Schema.md's machine-read lists live in its properties.** `page_types` (folder names, in index order) and `doc_types` are frontmatter lists; the rest is plain English. Why: robust to parse, shown by Obsidian as editable properties, the user edits either.
- **Ruling 5 — where Schema.md's text ships.** The canonical text is `core/Templates/Schema.md` (vaults receive `System/Core/Templates/` on update, so the migration can create the file); `template/Knowledge/Schema.md` is an identical copy for fresh installs, pinned by a test.
- **Ruling 6 — two "changed since" records.** The search refresh compares pages against the `pages` table in `index.db`; `bron wiki done` compares against `.bron/kb/wiki-state.json` (spec §5.3). So a search run between writing pages and `wiki done` can't swallow the log entries and checks.
- **Ruling 7 — `wiki done` indexes words only.** It puts changed pages' words into the database at once and leaves their meaning vectors for the next search (the warm helper already has the model loaded). Why: `wiki done` stays fast and never loads the 220 MB model itself.
- **Ruling 8 — no index rebuild for 0.8.0.** The page tables are added to an existing `index.db` on open (`CREATE … IF NOT EXISTS`) without bumping `index.SCHEMA_VERSION`, matching 0.7.1's "keep working without a rebuild" rule.
- **Ruling 9 — filters and pages.** `--organisation/--type/--after/--before` narrow the document passages and the document pages (through their document); organisation, person and topic pages are matched by the question alone.
- **Ruling 10 — `bron wiki check` without `--all`** prints the counts and the first three of each kind, like the health check; `--all` lists everything (spec §7.1 only defines the two ends).
- **Ruling 11 — links and orphans.** A link is fine when any file in the vault has that name or path (Obsidian resolves by name); "nothing links to it" counts links from other wiki pages (index.md never counts), in the body or in properties.
- **Ruling 12 — the document ↔ page record** is `.bron/kb/docs/<id>/page.json` (beside `user-labels.json`), so reading a document again keeps its page. Once a document has a page, the page's properties replace the 0.7.x stored user labels for search; before that, those labels stay effective (spec §8).
- **Ruling 13 — how a background wiki run reports.** Success: only the ticket update (its Result is the summary, spec §5.2). Failure (blocked, error, crash twice): the ticket update plus a kb notice with the reading report and "say "finish the wiki pages" to write the rest" (spec §10).
- **Ruling 14 — cancel.** `bron kb status --cancel` also cancels wiki runs that are waiting; a run already writing finishes (stopping a CLI mid-page could leave half-written pages).
- **Ruling 15 — `--log` text** is `"<kind> | <text>"` with a kind from `ingest, update, save, check, forget`; anything else is logged as `update | <text>`.
- **Ruling 16 — idle status wording.** Idle `kb status` prints "Nothing is being read." and its "last batch" line ("Last batch finished … : N documents read, M couldn't be read.") and the missing-tools line contain no "reading" (spec §3 item 1).
- **Ruling 17 — a wiki run is tried at most twice** (like `jobs.MAX_ATTEMPTS` for reading); after that it reports and the documents show as "read but no page yet".
- **Ruling 18 — `bron kb list`** also takes `--organisation` (with `--company` as its alias), like `search` (spec §6.1).
- **Ruling 19 — foreground output for a failed document** is `Couldn't read <name>: <reason>` (spec §5.1 defines only the read / already-read lines), followed by the not-found sentences.

## Review Focus

1. **A folder link shared with the user** (it exists only under `<account>/.shortcut-targets-by-id/<folder id>/`, not in My Drive): found straight away and read in the background, never reported as missing. Pinned by Task 1 `test_a_shared_folder_link_goes_straight_to_its_shortcut_folder`.
2. **The user fixes a document page's organisation or type in Obsidian** and searches without anyone running `wiki done`: the filters use the new value. Pinned by Task 5 `test_an_edited_document_page_changes_the_filters_on_the_next_search`.
3. **A page with broken properties** (a YAML typo by the user or an agent): `wiki done` reports it in one line, still indexes, logs and checks the other pages, and index.md leaves it out. Pinned by Task 6 `test_a_page_with_broken_properties_is_reported_and_the_rest_carry_on`.
4. **`organisation: [[Acme Ltda]]` written without quotes** (YAML reads it as a list in a list): still a link, still the organisation filter. Pinned by Task 4 `test_an_unquoted_link_in_a_property_still_counts`.
5. **The background wiki run is interrupted or its CLI fails**: it is picked up once more, then reported in plain words with the reading report; the documents stay searchable and show as "read but no page yet". Pinned by Task 7 `test_an_interrupted_wiki_run_resumes_then_gives_up_plainly`.

---

## Files

| File | Responsibility | Task |
|---|---|---|
| `core/Engine/bron/kb/sources.py` (modify) | `.shortcut-targets-by-id` in the walk, direct folder-id path, `resolve_targets` (folders asked for) | 1 |
| `core/Engine/bron/kb/ingest.py` (modify) | `--file` text check; labels from names only; `lines()` (foreground output) | 1, 2, 8 |
| `core/Engine/bron/kb/models.py` (modify) | label model call removed; hard pages and `labels_from_names` stay | 2 |
| `core/Engine/bron/kb/schema.py` (create) | Schema.md lists, template text, index/log headers | 3 |
| `core/Templates/Schema.md`, `template/Knowledge/{Schema.md,index.md,log.md,Documents,Organisations,People,Topics}` (create) | the shipped wiki | 3 |
| `core/Engine/bron/migrations/knowledge_wiki.py` (create) + registry | 0.8.0 migration | 3 |
| `core/Engine/bron/kb/store.py` (modify) | `page.json` record; page labels in `effective_labels` | 4 |
| `core/Engine/bron/kb/wiki.py` (create) | pages, links, properties, index.md, log.md, document page records | 4 |
| `core/Engine/bron/kb/index.py` (modify) | page tables; `set_labels` | 5 |
| `core/Engine/bron/kb/wiki_index.py` (create) | pages indexed and searched | 5 |
| `core/Engine/bron/kb/search.py`, `service.py`, `cli.py` (modify) | `find` (pages then passages), `--pages-only`, `--organisation` | 5 |
| `core/Engine/bron/kb/wiki_check.py`, `wiki_done.py`, `wiki_cli.py` (create); `kb/health.py`, `bron/cli.py` (modify) | checks, `bron wiki done|check`, health check | 6 |
| `core/Engine/bron/kb/wiki_run.py` (create), `kb/jobs.py` (modify) | background wiki run, one writer at a time, queue, status, cancel, resume | 7 |
| `core/Engine/bron/kb/cli.py` (modify) | thresholds, foreground setup, output, queue messages, forget/show/status | 8 |
| `core/Skills/read-documents/SKILL.md` (create), `core/Templates/AGENTS.md.tmpl` (modify) | the wiki maintainer procedure; short rules | 9 |
| `core/Manual/knowledge.md`, `CHANGELOG.md`, `tests/live/test_knowledge.py` | manual, release notes, live test | 10 |
| `tests/kbkit.py` (modify) | `hook_reads`, `write_page`, `later`, `stored_doc`, `FakeTicketRunner` | 2, 4, 7 |

### Task 1: Drive folders shared with the user, and `--file` takes only text (spec §3 items 2–3, §5.4)

**Files:**
- Modify: `core/Engine/bron/kb/sources.py:19-28` (constant), `:68-81` (`drive_roots`), `:113-114` (`_hidden`), `:228-264` (`resolve` → `resolve_targets`)
- Modify: `core/Engine/bron/kb/ingest.py:315-328` (`export_item`), `:353-364` (`add_export` reading)
- Test: `tests/test_kb_sources.py`, `tests/test_kb_ingest.py`, `tests/test_kb_cli.py`

**Interfaces:**
- Consumes: `sources._search(vault, ids, roots=None) -> (dict[str, Path], bool)`, `sources._files_under`, `sources._item_for_file`, `sources.is_under` (all existing).
- Produces:
  - `sources.SHORTCUTS = ".shortcut-targets-by-id"`
  - `sources.shortcut_dirs(home: Path | None = None) -> list[Path]` — existing `<account>/.shortcut-targets-by-id` folders (with `BRON_DRIVE_ROOT`: under it or beside it).
  - `sources.shared_folder(item_id: str) -> Path | None` — `<shortcuts>/<item_id>` when it is a folder.
  - `sources.Resolved(items: list[Item], failed: list[str], folders: list[str])` and `sources.resolve_targets(vault, targets: list[str], *, inbox: bool = False) -> Resolved` (`folders`: the names of the folder targets, in order; the inbox is not a folder). `sources.resolve(...)` keeps returning `(items, failed)`.
  - `ingest.NOT_TEXT: str` (exact text below) and `ingest.read_text_file(text_file: Path | str) -> str` (raises `KbError(NOT_TEXT)` for NUL bytes, a `%PDF` start or bytes that aren't UTF-8; `KbError("There's no readable file at …")` when it can't be opened).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_kb_sources.py`:

```python
def _shared_layout(tmp_path, monkeypatch):
    """Drive for desktop's layout: My Drive beside .shortcut-targets-by-id/<folder id>/<folder name>/."""
    account = tmp_path / "GoogleDrive-test"
    my_drive = account / "My Drive"
    my_drive.mkdir(parents=True)
    shared = account / sources.SHORTCUTS / "SHARED1" / "Leases"
    shared.mkdir(parents=True)
    lease = shared / "lease.pdf"
    lease.write_bytes(b"%PDF-1.4")
    set_drive_id(lease, "LEASE1")
    set_drive_id(shared, "SHARED1")
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(my_drive))
    return account, shared, lease


def test_a_file_in_a_folder_shared_with_the_user_is_found(vault, tmp_path, monkeypatch):
    _, _, lease = _shared_layout(tmp_path, monkeypatch)
    items, failed = sources.resolve(vault, ["https://drive.google.com/file/d/LEASE1/view"])
    assert failed == [] and items[0].path == str(lease) and items[0].identity == "drive:LEASE1"


def test_a_shared_folder_link_goes_straight_to_its_shortcut_folder(vault, tmp_path, monkeypatch):
    _, _, lease = _shared_layout(tmp_path, monkeypatch)
    walked = []
    real = sources._search
    monkeypatch.setattr(sources, "_search", lambda vault, ids, roots=None: walked.append(set(ids)) or real(vault, ids, roots))
    found = sources.resolve_targets(vault, ["https://drive.google.com/drive/folders/SHARED1"])
    assert [i.path for i in found.items] == [str(lease)] and found.failed == [] and found.folders == ["Leases"]
    assert walked == []  # found by its id at once: no walk through the whole Drive


def test_the_real_drive_layout_includes_shared_folders(tmp_path, monkeypatch):
    monkeypatch.delenv("BRON_DRIVE_ROOT", raising=False)
    account = tmp_path / "Library" / "CloudStorage" / "GoogleDrive-someone@example.com"
    for sub in ("My Drive", ".shortcut-targets-by-id/ABC/Team", ".Trash"):
        (account / sub).mkdir(parents=True)
    roots = sources.drive_roots(home=tmp_path)
    assert account / "My Drive" in roots and account / sources.SHORTCUTS in roots
    assert all(r.name != ".Trash" for r in roots)
    assert sources.shortcut_dirs(home=tmp_path) == [account / sources.SHORTCUTS]


def test_other_hidden_folders_stay_skipped_and_shortcuts_are_walked(vault, tmp_path, monkeypatch):
    root = fake_drive(tmp_path)
    (root / ".hidden").mkdir()
    (root / ".hidden" / "x.pdf").write_bytes(b"x")
    set_drive_id(root / ".hidden" / "x.pdf", "HID1")
    inner = root / sources.SHORTCUTS / "F9" / "Shared"
    inner.mkdir(parents=True)
    (inner / "y.pdf").write_bytes(b"y")
    set_drive_id(inner / "y.pdf", "SH1")
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(root))
    assert sources.find_drive_item(vault, "HID1") is None
    assert sources.find_drive_item(vault, "SH1") == inner / "y.pdf"


def test_folders_asked_for_are_named(vault, tmp_path):
    folder = tmp_path / "Receipts"
    folder.mkdir()
    (folder / "a.txt").write_text("a")
    single = tmp_path / "b.txt"
    single.write_text("b")
    found = sources.resolve_targets(vault, [str(folder), str(single)])
    assert found.folders == ["Receipts"] and len(found.items) == 2
    assert sources.resolve_targets(vault, [], inbox=True).folders == []
```

Append to `tests/test_kb_ingest.py`:

```python
def test_exported_text_is_checked_before_reading(tmp_path):
    good = tmp_path / "ok.txt"
    good.write_bytes("﻿Minutes of the meeting, São Paulo".encode("utf-8"))
    assert ingest.read_text_file(good) == "Minutes of the meeting, São Paulo"
    pdf = make_text_pdf(tmp_path / "x.pdf", ["x"])
    with pytest.raises(KbError) as err:
        ingest.export_item(pdf, "https://docs.google.com/document/d/G1/edit", "X")
    assert str(err.value) == ingest.NOT_TEXT
    with pytest.raises(KbError, match="no readable file"):
        ingest.read_text_file(tmp_path / "missing.txt")
```

Append to `tests/test_kb_cli.py`:

```python
@pytest.mark.parametrize("kind", ["pdf", "nul", "cp1252"])
def test_file_takes_only_exported_text(env, capsys, tmp_path, kind):
    path = tmp_path / "export.txt"
    if kind == "pdf":
        make_text_pdf(path, [SPA_TEXT])
    elif kind == "nul":
        path.write_bytes(b"PK\x03\x04\x00\x00binary")
    else:
        path.write_bytes("Relatório de 2025".encode("cp1252"))
    code, out = run(env, capsys, "add", "--file", str(path), "--source", "https://docs.google.com/document/d/GDOC1/edit",
                    "--name", "Memo")
    assert code == 1 and out.strip() == ingest.NOT_TEXT
    assert store.all_docs(env.vault) == [] and env.spawned == []
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_kb_sources.py tests/test_kb_ingest.py::test_exported_text_is_checked_before_reading tests/test_kb_cli.py::test_file_takes_only_exported_text -q`
Expected: FAIL — `AttributeError: module 'bron.kb.sources' has no attribute 'SHORTCUTS'` / `'resolve_targets'`, `ingest` has no `read_text_file` / `NOT_TEXT`.

- [ ] **Step 3: Implement**

`core/Engine/bron/kb/sources.py` — after `NATIVE = {...}` (line 23) add:

```python
SHORTCUTS = ".shortcut-targets-by-id"  # Drive for desktop keeps folders shared with the user here, by folder id
```

Replace `drive_roots` (lines 68-81) with:

```python
def shortcut_dirs(home: Path | None = None) -> list[Path]:
    """Where Google Drive for desktop keeps the folders shared with the user: <account>/.shortcut-targets-by-id."""
    override = os.environ.get("BRON_DRIVE_ROOT")
    if override:
        candidates = [Path(override) / SHORTCUTS, Path(override).parent / SHORTCUTS]
    else:
        base = (home or Path.home()) / "Library" / "CloudStorage"
        candidates = [account / SHORTCUTS for account in sorted(base.glob("GoogleDrive-*"))] if base.is_dir() else []
    return [c for c in candidates if c.is_dir()]


def drive_roots(home: Path | None = None) -> list[Path]:
    override = os.environ.get("BRON_DRIVE_ROOT")
    if override:
        p = Path(override)
        if not p.is_dir():
            return []
        return [p] + [s for s in shortcut_dirs() if not is_under(s, p)]  # one inside p is walked from p
    base = (home or Path.home()) / "Library" / "CloudStorage"
    roots: list[Path] = []
    if base.is_dir():
        for account in sorted(base.glob("GoogleDrive-*")):
            # "My Drive" and "Shared drives" first; the names are localised ("Meu Drive"), so every top folder counts
            subs = [s for s in sorted(account.iterdir(), key=lambda s: s.name not in ("My Drive", "Shared drives"))
                    if s.is_dir() and not s.name.startswith(".")]
            roots += subs
    return roots + shortcut_dirs(home)


def shared_folder(item_id: str) -> Path | None:
    """A folder shared with the user, straight from its id, without a walk: .shortcut-targets-by-id/<folder id>."""
    for base in shortcut_dirs():
        candidate = base / item_id
        if candidate.is_dir():
            return candidate
    return None
```

Replace `_hidden` (lines 113-114) with:

```python
def _hidden(name: str) -> bool:
    return name.startswith(".") and name != SHORTCUTS  # folders shared with the user live in .shortcut-targets-by-id
```

Replace `resolve` (lines 228-264) with:

```python
@dataclass
class Resolved:
    items: list[Item]
    failed: list[str]
    folders: list[str]  # the names of the folders asked for (a folder is read in the background)


def _folder_name(path: Path) -> str:
    """The folder's own name; a shared folder's id folder is named after the one folder inside it."""
    if path.parent.name == SHORTCUTS:
        try:
            inside = [p for p in path.iterdir() if p.is_dir() and not _hidden(p.name)]
        except OSError:
            inside = []
        if len(inside) == 1:
            return inside[0].name
    return path.name


def resolve(vault: Vault, targets: list[str], *, inbox: bool = False) -> tuple[list[Item], list[str]]:
    found = resolve_targets(vault, targets, inbox=inbox)
    return found.items, found.failed


def resolve_targets(vault: Vault, targets: list[str], *, inbox: bool = False) -> Resolved:
    targets = [as_link(t.strip()) for t in targets if t.strip()]
    wanted = {drive_id(t) for t in targets if _is_drive_link(t)} - {None}
    direct = {i: p for i in wanted if (p := shared_folder(i)) is not None}
    rest = wanted - set(direct)
    located, out_of_budget = _search(vault, rest) if rest else ({}, False)
    located = {**located, **direct}
    items: list[Item] = []
    failed: list[str] = []
    folders: list[str] = []
    for target in targets:
        if _is_drive_link(target):
            did = drive_id(target)
            path = located.get(did) if did else None
            if path is None:
                note = " (searched for 2 minutes)" if out_of_budget else ""
                failed.append(f"Couldn't find {target} in Google Drive on this Mac{note}. "
                              "Open Google Drive for desktop and make sure the file is available.")
            elif path.is_dir():
                folders.append(_folder_name(path))
                items += [_item_for_file(f) for f in _files_under(path)]
            else:
                items.append(_item_for_file(path, from_drive_id=did))
        elif _is_web(target):
            url = target.split("#", 1)[0]
            items.append(Item("web", f"web:{url}", url, url, "", url))
        else:
            path = Path(os.path.expanduser(target))
            if not path.is_absolute():
                path = Path.cwd() / path
            keep = is_under(path, inbox_dir(vault))
            if path.is_dir():
                folders.append(path.name)
                items += [_item_for_file(f, keep=keep) for f in _files_under(path)]
            elif path.is_file():
                items.append(_item_for_file(path, keep=keep))
            else:
                failed.append(f"There's no file at {target}.")
    if inbox:
        folder = inbox_dir(vault)
        if folder.is_dir():
            items += [_item_for_file(f, keep=True) for f in _files_under(folder)]
    return Resolved(items, failed, folders)
```

`core/Engine/bron/kb/ingest.py` — after `EXPORT_SOURCE = (...)` (lines 315-316) add:

```python
NOT_TEXT = "--file is only for text exported from a Google Doc, Sheet or Slides; give Bron the Drive link instead."


def read_text_file(text_file: Path | str) -> str:
    """The text of an exported Google file. Anything that isn't UTF-8 text (a PDF, an image, a Word file…) is refused:
    a Drive file is always given to `bron kb add` by its link."""
    try:
        data = Path(text_file).read_bytes()
    except OSError as exc:
        raise KbError(f"There's no readable file at {text_file}.") from exc
    if b"\x00" in data or data.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"%PDF"):
        raise KbError(NOT_TEXT)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise KbError(NOT_TEXT) from None
```

In `export_item` replace

```python
    if not Path(text_file).is_file():
        raise KbError(f"There's no readable file at {text_file}.")
```

with

```python
    read_text_file(text_file)  # a plain error now: missing, or not exported text
```

In `add_export` replace

```python
    from .readers import decode

    ...
    try:
        text = decode(Path(text_file).read_bytes())
    except OSError as exc:
        raise KbError(f"There's no readable file at {text_file}.") from exc
```

with

```python
    text = read_text_file(text_file)
```

(keep the `source`/`did` checks in between exactly as they are, and remove the now-unused `from .readers import decode` line of `add_export`).

- [ ] **Step 4: Run the tests**

Run: `uv run --project core/Engine pytest tests/test_kb_sources.py tests/test_kb_ingest.py tests/test_kb_cli.py -q`
Expected: PASS (including the existing `test_hidden_items_skipped_in_folder_link`, `test_add_an_exported_google_doc`, `test_an_export_can_wait_in_a_job`).

- [ ] **Step 5: Run everything and commit**

Run: `uv run --project core/Engine pytest tests -q` — Expected: PASS.

```bash
git add core/Engine/bron/kb/sources.py core/Engine/bron/kb/ingest.py tests/test_kb_sources.py tests/test_kb_ingest.py tests/test_kb_cli.py
git commit -m "Find Drive folders shared with you; --file takes only exported text

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Remove the label model call, `bron kb label` and the 0.7 label settings (spec §8)

**Files:**
- Modify: `core/Engine/bron/kb/models.py:1` (docstring), `:21-61` (label constants and helpers), `:103-115` (`_log`), `:211-236` (`labels`)
- Modify: `core/Engine/bron/kb/ingest.py:1` (docstring), `:26` (`LABEL_CHARS`), `:174-176` (`_folder_hint` docstring), `:203-230` (`_text_hash`, `_process` labels), `:281-312` (`read_item`), `:331-335` (`_read_export`), `:353` and `:370-371` (`add_export`)
- Modify: `core/Engine/bron/kb/jobs.py:268`, `:295-296`, `:310`, `:318` (`label_call` removed)
- Modify: `core/Engine/bron/kb/cli.py:53-56` (`label` parser), `:89-90` (dispatch), `:360` and `:397-453` (`_label`)
- Modify: `core/Engine/bron/model.py:134-135`, `core/Engine/bron/loader.py:144-171` and `:222-238`
- Modify: `template/System/Settings.md:15-18`, `:31`
- Modify: `tests/kbkit.py:209-222` (`FakeLabels` → `hook_reads`), `tests/test_kb_ingest.py`, `tests/test_kb_cli.py`, `tests/test_kb_models.py`, `tests/test_kb_store.py:104-127`, `tests/test_kb_speed.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `models.labels_from_names(name: str, folder: str, *, web: bool = False) -> dict` (unchanged; now the only source of `Doc.labels` for new reads: `{"company", "doc_type": "other", "date", "title": "", "language": "other"}`).
  - `ingest.read_item(vault, cfg, item, *, readers_ocr=None, model_call=None, embedder, again=False) -> Doc`; `ingest.add_export(vault, cfg, text_file, source, name, *, embedder) -> Doc`; `jobs.run(vault, job_id, *, embedder=None, readers_ocr=None, model_call=None, cfg=None) -> bool` (no `label_call` anywhere).
  - `models._log(vault, doc_name, page, cli, failed=False)` (no `kind`).
  - `kbkit.hook_reads(monkeypatch, before: Callable[[str], None]) -> None` — calls `before(item.name)` each time Bron starts reading a document (replaces the 0.7 label stand-in as the test hook).
  - `Settings` no longer has `kb_labels` / `kb_doc_types`; `knowledge.labels` and `knowledge.doc_types` in Settings.md are ignored (the Task 3 migration removes them).

- [ ] **Step 1: Write the failing tests**

In `tests/kbkit.py` replace the whole `class FakeLabels` (lines 209-222) with:

```python
def hook_reads(monkeypatch, before) -> None:
    """Run before(<document name>) each time Bron starts reading a document (raise in it to stop the reader there)."""
    from bron.kb import ingest

    real = ingest._read

    def hooked(item, ocr, work):
        before(item.name)
        return real(item, ocr, work)

    monkeypatch.setattr(ingest, "_read", hooked)
```

Add to `tests/test_kb_models.py` (and in its `cfg()` helper delete the two lines `s.kb_labels = …` and `s.kb_doc_types = …`):

```python
def test_the_label_model_call_is_gone():
    import inspect

    from bron.kb import ingest, jobs

    for name in ("labels", "label_prompt", "doc_types", "match_type", "DOC_TYPES"):
        assert not hasattr(models, name), name
    settings = Settings(Path("settings.md"))
    assert not hasattr(settings, "kb_labels") and not hasattr(settings, "kb_doc_types")
    assert "label_call" not in inspect.signature(ingest.read_item).parameters
    assert "label_call" not in inspect.signature(ingest.add_export).parameters
    assert "label_call" not in inspect.signature(jobs.run).parameters


def test_labels_from_names():
    got = models.labels_from_names("Lease 2025.01.21.pdf", "Contracts/Acme")
    assert got == {"company": "Acme", "doc_type": "other", "date": "2025-01-21", "title": "", "language": "other"}
    assert models.labels_from_names("notes 2025-02-03.pdf", "Downloads") == {
        "company": "", "doc_type": "other", "date": "2025-02-03", "title": "", "language": "other"}
    assert models.labels_from_names("page", "example.com", web=True)["company"] == ""
    assert models.labels_from_names("x.pdf", "Bad [name] | here")["company"] == "Bad name here"
```

Delete from `tests/test_kb_models.py`: `GOOD_LABELS`, `test_labels_parse_and_defaults`, `test_labels_unknown_type_bad_date_and_failures`, `test_labels_default_call_uses_summaries`, `test_labels_are_sanitised`, `test_a_label_call_is_logged`, `test_labels_off_makes_no_model_call_and_uses_names`, `test_the_label_prompt_fences_the_document`, `test_the_default_types_are_general`, `test_your_own_doc_types_replace_the_default`.

Add to `tests/test_kb_ingest.py` (replacing `test_the_label_prompt_never_carries_the_users_name`):

```python
def test_labels_come_from_the_folder_name_never_from_a_model(kb, tmp_path, monkeypatch):
    from pathlib import Path as P

    from bron.memory import summaries

    monkeypatch.setattr(summaries, "call_model", lambda *a, **k: pytest.fail("no text is sent to a model to label documents"))
    fake_home = tmp_path / "Users" / "someone"
    folder = fake_home / "Downloads" / "Acme"
    folder.mkdir(parents=True)
    monkeypatch.setattr(P, "home", classmethod(lambda cls: fake_home))
    pdf = make_text_pdf(folder / "2025.01.21 spa.pdf", [SPA_TEXT])
    doc = kb.read(sources.resolve(kb.vault, [str(pdf)])[0][0])
    assert doc.status == "read" and doc.labels["company"] == "Acme" and doc.labels["date"] == "2025-01-21"
    assert kb.model.calls == [] and not (store.kb_dir(kb.vault) / "model-log.jsonl").exists()
```

Update the rest of `tests/test_kb_ingest.py`:
- imports (line 14): `from kbkit import (FakeModel, FakeOcr, fake_drive, fake_embed, hook_reads, make_scanned_pdf, make_text_pdf, set_drive_id)`.
- `kb` fixture (lines 32-33): delete `env.labels = …`; `env.deps = dict(readers_ocr=env.ocr, model_call=env.model, embedder=fake_embed)`.
- `drive_pdf` (lines 44-49): put the file in a folder named Acme so its labels name the company:

```python
def drive_pdf(kb, name="spa.pdf", text=SPA_TEXT, item_id="SPA1"):
    folder = kb.root / "Acme"
    folder.mkdir(exist_ok=True)
    path = make_text_pdf(folder / name, [text])
    set_drive_id(path, item_id)
    items, failed = sources.resolve(kb.vault, [f"https://drive.google.com/file/d/{item_id}/view"])
    assert failed == []
    return path, items[0]
```

- `test_drive_file_is_read_in_place_labelled_and_searchable` → rename `test_drive_file_is_read_in_place_labelled_from_names_and_searchable`; replace its labels assertion with `assert doc.labels == {"company": "Acme", "doc_type": "other", "date": "", "title": "", "language": "other"}` and delete the `kb.labels.calls` line.
- `test_export_is_read_as_that_document`: drop `, label_call=kb.labels` from the `add_export` call.
- `test_summary_lists_labels_and_reasons`: expect `"- spa.pdf — Acme · other"`.
- Replace the four hook tests and the unchanged-document test:

```python
def test_interrupted_job_resumes(kb, tmp_path, monkeypatch):
    items = items_in(kb, tmp_path, 3)
    job = jobs.create(kb.vault, items)
    calls = []

    def lid_closes(name):
        calls.append(name)
        if len(calls) == 2:
            raise KeyboardInterrupt  # the laptop lid closes during the second document

    hook_reads(monkeypatch, lid_closes)
    with pytest.raises(KeyboardInterrupt):
        jobs.run(kb.vault, job.job_id, **kb.deps)
    half = jobs.load(kb.vault, job.job_id)
    assert half.status == "running" and len(half.done) == 1 and notices.take(kb.vault) == []
    jobs.run(kb.vault, job.job_id, **kb.deps)
    finished = jobs.load(kb.vault, job.job_id)
    assert finished.status == "done" and len(finished.done) == 3
    assert calls.count("doc0.pdf") == 1  # the first document wasn't read again
    told = notices.take(kb.vault)
    assert len(told) == 1 and told[0].startswith("Read 3 documents")


def test_a_document_that_stops_the_reader_twice_is_skipped(kb, tmp_path, monkeypatch):
    items = items_in(kb, tmp_path, 2)
    job = jobs.create(kb.vault, items)

    def crashes(name):
        if name == "doc0.pdf":
            raise KeyboardInterrupt  # this file takes the whole process down every time

    hook_reads(monkeypatch, crashes)
    for _ in range(2):
        with pytest.raises(KeyboardInterrupt):
            jobs.run(kb.vault, job.job_id, **kb.deps)
    jobs.run(kb.vault, job.job_id, **kb.deps)
    finished = jobs.load(kb.vault, job.job_id)
    assert finished.status == "done" and len(finished.done) == 1
    assert finished.failed[0]["error"] == "Bron stopped while reading this file twice; skipped it."
    assert "doc0.pdf (Bron stopped while reading this file twice; skipped it)" in notices.take(kb.vault)[0]


def test_cancel_reaches_a_running_job_after_the_current_document(kb, tmp_path, monkeypatch):
    job = jobs.create(kb.vault, items_in(kb, tmp_path, 3))

    def cancel_during_first(name):
        if name == "doc0.pdf":
            assert jobs.runner_active(kb.vault)
            jobs.cancel(kb.vault)

    hook_reads(monkeypatch, cancel_during_first)
    jobs.run(kb.vault, job.job_id, **kb.deps)
    finished = jobs.load(kb.vault, job.job_id)
    assert finished.status == "cancelled" and len(finished.done) == 1 and len(finished.cancelled) == 2
    told = notices.take(kb.vault)
    assert len(told) == 1 and told[0].startswith("Read 1 document (") and "Cancelled: 2 documents" in told[0]


def test_runner_active_never_takes_the_runner_lock(kb, tmp_path, monkeypatch):
    assert not jobs.runner_active(kb.vault)
    job = jobs.create(kb.vault, items_in(kb, tmp_path, 1))
    seen = []
    real_flock = fcntl.flock

    def watch(name):
        monkeypatch.setattr(jobs.fcntl, "flock", lambda *a: pytest.fail("runner_active touched the lock"))
        seen.append(jobs.runner_active(kb.vault))
        monkeypatch.setattr(jobs.fcntl, "flock", real_flock)

    hook_reads(monkeypatch, watch)
    jobs.run(kb.vault, job.job_id, **kb.deps)
    assert seen == [True] and not jobs.runner_active(kb.vault)
    (store.kb_dir(kb.vault) / "jobs" / "runner.status").write_text(json.dumps({"pid": 999999, "beat": 0}))
    assert not jobs.runner_active(kb.vault)  # a runner that died is not at work


def test_an_unchanged_document_is_not_read_again(kb, monkeypatch):
    path, item = drive_pdf(kb)
    reads = []
    hook_reads(monkeypatch, reads.append)
    first = kb.read(item)
    meta = json.loads((store.kb_dir(kb.vault) / "docs" / first.doc_id / "meta.json").read_text())
    assert meta["source_size"] == path.stat().st_size and meta["source_mtime"] == path.stat().st_mtime
    again = kb.read(item)
    assert again.status == "unchanged" and again.doc_id == first.doc_id and again.name == "spa.pdf"
    assert reads == ["spa.pdf"]  # nothing was read again
    assert store.load(kb.vault, first.doc_id).status == "read"
    forced = ingest.read_item(kb.vault, kb.cfg, item, again=True, **kb.deps)
    assert forced.status == "read" and reads == ["spa.pdf", "spa.pdf"] and forced.labels == first.labels
    make_text_pdf(path, ["Amended agreement: the purchase price is now USD 2,500,000.00 with an earn-out clause."])
    changed = kb.read(item)
    assert changed.status == "read" and len(reads) == 3
```

- `test_web_pages_are_always_read_again_but_their_labels_are_reused` → rename `test_web_pages_are_always_read_again`; its last line becomes `assert len(fetched) == 2`.

Update `tests/test_kb_cli.py`:
- line 11: `from kbkit import FakeModel, FakeOcr, fake_drive, fake_embed, make_docx, make_scanned_pdf, make_text_pdf, set_drive_id`; delete the `LABELS` dict (lines 14-18).
- `env` fixture line 29: `monkeypatch.setattr(summaries, "call_model", lambda *a, **k: pytest.fail("no text is sent to a model to label documents"))`.
- Replace `test_add_a_drive_folder_then_search_with_citations` and `test_show_list_forget` with:

```python
def test_add_a_drive_folder_then_search_with_citations(env, capsys):
    out = add_all(env, capsys)
    assert out.startswith("Read 3 documents (1 scanned page, 0 pages read by the model).")
    assert "- spa.pdf — Acme · other" in out and "- memo.docx — Acme · other" in out
    assert len(env.spawned) == 1
    code, out = run(env, capsys, "search", "purchase price")
    assert code == 0 and "spa.pdf · Acme · other · p. 1" in out
    assert "https://drive.google.com/open?id=SPA1" in out
    code, out = run(env, capsys, "search", "1,500,000.00", "--company", "acme")
    assert "scan.pdf" in out and "https://drive.google.com/open?id=SCAN1" in out
    code, out = run(env, capsys, "search", "budget", "--type", "contract")
    assert out.strip() == kb_cli.NOTHING


def test_show_list_forget(env, capsys):
    add_all(env, capsys)
    code, out = run(env, capsys, "list")
    assert code == 0 and len(out.strip().splitlines()) == 3 and "spa.pdf — Acme · other" in out
    code, out = run(env, capsys, "list", "--company", "beta")
    assert out.strip() == "No documents match."
    code, out = run(env, capsys, "list", "--type", "other")
    assert len(out.strip().splitlines()) == 3
    code, out = run(env, capsys, "show", "spa.pdf", "--pages", "2")
    assert code == 0 and "Schedule 1" in out and "purchase price" not in out and "https://drive.google.com/open?id=SPA1" in out
    code, out = run(env, capsys, "show", "spa", "--pages", "1-2")
    assert "--- p. 1 ---" in out and "--- p. 2 ---" in out
    code, out = run(env, capsys, "show", "spa.pdf", "--pages", "9")
    assert code == 1 and "spa.pdf has 2 pages." in out
    code, out = run(env, capsys, "forget", "SPA.PDF")
    assert code == 0 and "Forgot spa.pdf" in out
    code, out = run(env, capsys, "search", "purchase price")
    assert "spa.pdf" not in out
    assert len(store.all_docs(env.vault)) == 2
```

- Delete `test_label_corrections_are_reindexed` and `test_your_own_doc_types_are_used_for_corrections`; replace `test_a_070_fund_correction_becomes_the_company` with:

```python
def test_a_070_fund_correction_still_counts_as_the_company(env, capsys):
    add_all(env, capsys)
    memo = next(d for d in store.all_docs(env.vault) if d.name == "memo.docx")
    memo.labels = {**memo.labels, "company": ""}
    store.save_meta(env.vault, memo)
    store.save_user_labels(env.vault, memo.doc_id, {"fund": "Group II"})  # as `bron kb label --fund` saved it in 0.7.0
    code, out = run(env, capsys, "list", "--company", "group ii")
    assert "memo.docx — Group II · other" in out
    with pytest.raises(SystemExit):
        bron_cli.build_parser().parse_args(["kb", "label", "memo.docx", "--company", "x"])
```

- In `test_an_ambiguous_document_changes_nothing` replace the first two lines' query `"acme"` with `"pdf"` (it matches spa.pdf and scan.pdf): `code, out = run(env, capsys, "forget", "pdf")` and `assert code == 1 and "Several documents match 'pdf'" in out and "spa.pdf" in out and "scan.pdf" in out`.
- In `test_internal_commands_are_hidden` drop `"label"` from the names tuple and add `assert "label" not in kb.format_usage().split("{", 1)[1]`.

Update `tests/test_kb_store.py`: replace `test_knowledge_settings` and delete `test_doc_types_setting` (the list cleaning moves to `schema.clean_list` in Task 3):

```python
def test_knowledge_settings(vault):
    s = load(vault).settings
    assert (s.kb_model_pages, s.kb_max_model_pages) == (True, 20)
    set_meta(vault.settings_file, knowledge={"model_pages": False, "max_model_pages": 5, "labels": False, "doc_types": ["x"]})
    cfg = load(vault)
    assert (cfg.settings.kb_model_pages, cfg.settings.kb_max_model_pages) == (False, 5)
    assert not [i for i in cfg.issues if "knowledge" in i.message]  # 0.7 keys are ignored until the migration removes them
```

Update `tests/test_kb_speed.py`: import `from kbkit import make_text_pdf`; delete `labels = FakeLabels()`; call `ingest.read_item(vault, cfg, item, embedder=embedder)`.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_kb_models.py tests/test_kb_ingest.py tests/test_kb_cli.py tests/test_kb_store.py -q`
Expected: FAIL — `test_the_label_model_call_is_gone` (models still has `labels`), the CLI tests fail on `pytest.fail("no text is sent to a model…")`, `test_labels_come_from_the_folder_name_never_from_a_model` fails the same way.

- [ ] **Step 3: Implement**

`core/Engine/bron/kb/models.py`:
- line 1 docstring → `"""Hard pages, sent to the user's own model CLI (every call is logged; failures fall back quietly), and labels worked out from file and folder names without any model: search filters until a document has its wiki page."""`
- delete lines 23-49 (`# The general default…`, `DOC_TYPES`, `doc_types`, `match_type`, `label_prompt`) and lines 59-61 (`_LABEL_CHARS`, `_OPEN, _CLOSE`, `_LABEL_GUARD`).
- replace `_log` (lines 103-115) with:

```python
def _log(vault: Vault, doc_name: str, page: int, cli: str, failed: bool = False) -> None:
    path = kb_dir(vault) / "model-log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"time": time.strftime("%Y-%m-%dT%H:%M:%S"), "doc": doc_name, "page": page, "cli": cli}
    if failed:
        row["failed"] = True
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
```

- delete `labels()` (lines 211-236). Keep `_date`, `clean`, `NAME_DATE`, `PLAIN_FOLDERS`, `labels_from_names`, `_BAD_LABEL`, `_CONTROL` (used by `clean`).

`core/Engine/bron/kb/ingest.py`:
- line 1 → `"""Reading one thing the user pointed to: read it, fix hard pages, label it from its file and folder names, cut it into passages, store and index it.`
- delete `LABEL_CHARS = 3000` (line 26) and `_text_hash` (lines 203-204).
- `_folder_hint` docstring (lines 175-176) → `"""Where the file sits, for the labels worked out from folder names: at most the last two folder names below the Drive root, the vault or a home folder, so nothing above them (a user name, say) is ever used."""`
- `_process` signature (lines 207-208) → `def _process(vault: Vault, cfg, item: Item, doc: Doc, previous: Doc | None, get_pages, *, model_call, embedder, keep: tuple[Path, Path] | None = None) -> Doc:`; replace lines 225-230 with:

```python
        doc.labels = models.labels_from_names(doc.name, _folder_hint(vault, item), web=item.kind == "web")
```

- `read_item` (line 281) → `def read_item(vault: Vault, cfg, item: Item, *, readers_ocr=None, model_call=None, embedder, again: bool = False) -> Doc:`; line 286 → `return _read_export(vault, cfg, item, embedder=embedder)`; lines 311-312 → `return _process(vault, cfg, item, doc, previous, lambda work: _read(read_from, readers_ocr, work).pages, model_call=model_call, embedder=embedder, keep=keep)`.
- `_read_export` (lines 331-335):

```python
def _read_export(vault: Vault, cfg, item: Item, *, embedder) -> Doc:
    try:
        return add_export(vault, cfg, Path(item.path), item.source, item.name, embedder=embedder)
    except Exception as exc:  # noqa: BLE001 - the text file is gone, say: one failure in the job
        return _failed(vault, item, exc)
```

- `add_export` signature → `def add_export(vault: Vault, cfg, text_file: Path, source: str, name: str, *, embedder) -> Doc:`; its last call → `return _process(vault, cfg, item, doc, previous, lambda work: _export_pages(text), model_call=None, embedder=embedder)`.

`core/Engine/bron/kb/jobs.py`:
- `_work` (line 268) → `def _work(vault: Vault, cfg, job: Job, *, embedder, readers_ocr, model_call) -> None:`; lines 295-296 → `doc = ingest.read_item(vault, cfg, item, readers_ocr=readers_ocr, model_call=model_call, embedder=embedder, again=job.again)`.
- `run` (line 310) → `def run(vault: Vault, job_id: str, *, embedder=None, readers_ocr=None, model_call=None, cfg=None) -> bool:`; line 318 → `deps = dict(embedder=embedder, readers_ocr=readers_ocr, model_call=model_call)`.

`core/Engine/bron/kb/cli.py`:
- delete the `label` sub-parser (lines 53-56).
- line 89 dict → `{"add": _add, "show": _show, "list": _list, "forget": _forget, "status": _status, "run-job": _run_job}`.
- line 360 comment → `# ---- forget ----`; delete `_label` (lines 397-453).

`core/Engine/bron/model.py`: delete lines 134-135 (`kb_labels`, `kb_doc_types`).

`core/Engine/bron/loader.py`: delete `MAX_DOC_TYPES` and `_doc_types` (lines 144-171); replace lines 222-238 with:

```python
    knowledge = doc.meta.get("knowledge") or {}
    if not isinstance(knowledge, dict):
        f.problem("field.type", "'knowledge' should hold model_pages and max_model_pages", level="warning")
        knowledge = {}
    model_pages = knowledge.get("model_pages", True)
    if isinstance(model_pages, bool):
        settings.kb_model_pages = model_pages
    else:
        f.problem("field.type", "'knowledge.model_pages' should be true or false", level="warning")
```

(the `max_model_pages` block after it stays).

`template/System/Settings.md`: the `knowledge:` block becomes

```yaml
knowledge:
  model_pages: true
  max_model_pages: 20
```

and line 31 becomes:

```markdown
- `knowledge`: when a page is a scan or too messy to read directly, Bron may ask a model to read it (`model_pages`), for at most `max_model_pages` pages per document. The wiki's rules, including your document types, are in `Knowledge/Schema.md` (see System/Core/Manual/knowledge.md).
```

- [ ] **Step 4: Run the tests**

Run: `uv run --project core/Engine pytest tests/test_kb_models.py tests/test_kb_ingest.py tests/test_kb_cli.py tests/test_kb_store.py tests/test_kb_search.py tests/test_kb_service.py -q`
Expected: PASS.

- [ ] **Step 5: Run everything and commit**

Run: `uv run --project core/Engine pytest tests -q` — Expected: PASS. Also `grep -rn "label_call\|kb_labels\|kb_doc_types\|FakeLabels\|models.labels(" core tests` prints nothing.

```bash
git add core/Engine/bron/kb/models.py core/Engine/bron/kb/ingest.py core/Engine/bron/kb/jobs.py core/Engine/bron/kb/cli.py core/Engine/bron/model.py core/Engine/bron/loader.py template/System/Settings.md tests/kbkit.py tests/test_kb_ingest.py tests/test_kb_cli.py tests/test_kb_models.py tests/test_kb_store.py tests/test_kb_speed.py
git commit -m "Stop sending document text to a model for labels; remove bron kb label

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The wiki's files — Schema.md, index.md, log.md, type folders — and the 0.8.0 migration (spec §4.1, §4.4, §8, §9)

**Files:**
- Create: `core/Engine/bron/kb/schema.py`
- Create: `core/Templates/Schema.md` and the identical `template/Knowledge/Schema.md`
- Create: `template/Knowledge/index.md`, `template/Knowledge/log.md`, `template/Knowledge/Documents/.gitkeep`, `template/Knowledge/Organisations/.gitkeep`, `template/Knowledge/People/.gitkeep`, `template/Knowledge/Topics/.gitkeep`
- Create: `core/Engine/bron/migrations/knowledge_wiki.py`
- Modify: `core/Engine/bron/migrations/__init__.py:32-41` (registry)
- Modify: `CHANGELOG.md:4` (new `## 0.8.0` section, first line only; Task 10 completes it)
- Test: `tests/test_kb_wiki_migration.py` (create); `tests/test_kb_store.py:148-150` (`test_template_has_inbox_and_files`)

**Interfaces:**
- Consumes: `fmedit.edit_meta(text, changes) -> str` / `fmedit.EditError` (`core/Engine/bron/fmedit.py:107-184`), `frontmatter.parse/read`, `setup.Change(summary, writes, folders, done)` (`core/Engine/bron/setup.py:31-38`), `migrations.Migration`, `store.all_docs`.
- Produces (`kb/schema.py`):
  - constants `SCHEMA = "Schema.md"`, `INDEX = "index.md"`, `LOG = "log.md"`, `PAGE_TYPES = ["Documents", "Organisations", "People", "Topics"]`, `INDEX_HEADER`, `EMPTY_INDEX`, `LOG_HEADER` (exact text below).
  - `schema_path(vault) -> Path`; `template_text(vault) -> str` (reads `vault.core_templates / "Schema.md"`); `clean_list(value, *, limit: int = 50) -> list[str]`; `page_types(vault) -> list[str]` (from Schema.md's `page_types` property; the default four when missing/invalid; never `Inbox`/`Files`); `with_doc_types(text: str, types: list[str]) -> str` (raises `fmedit.EditError`).
  - Migration `Migration(id="knowledge-wiki", version="0.8.0", summary=knowledge_wiki.SUMMARY, build=_knowledge_wiki)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kb_wiki_migration.py`:

```python
"""0.8.0: the wiki's files ship with new vaults and are added to existing ones; doc_types move to Schema.md."""
import shutil
from pathlib import Path

from bron import frontmatter as fm
from bron import migrations
from bron.kb import schema, store
from bron.migrations import apply_pending
from bron.migrations.knowledge_wiki import SUMMARY
from vaultkit import set_meta

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "template" / "Knowledge"


def migration():
    [found] = [m for m in migrations.MIGRATIONS if m.id == "knowledge-wiki"]
    return found


def as_071(vault, **knowledge):
    """A vault the way 0.7.1 left it: no wiki files, the 0.7 knowledge settings."""
    k = vault.knowledge_dir
    for name in (schema.SCHEMA, schema.INDEX, schema.LOG):
        (k / name).unlink()
    for name in schema.PAGE_TYPES:
        shutil.rmtree(k / name)
    set_meta(vault.settings_file, knowledge={"model_pages": True, "max_model_pages": 20, **knowledge})


def test_new_vaults_get_the_wiki_files():
    assert (TEMPLATE / "Schema.md").read_text(encoding="utf-8") == (REPO / "core" / "Templates" / "Schema.md").read_text(encoding="utf-8")
    assert (TEMPLATE / "index.md").read_text(encoding="utf-8") == schema.EMPTY_INDEX
    assert (TEMPLATE / "log.md").read_text(encoding="utf-8") == schema.LOG_HEADER
    for name in schema.PAGE_TYPES:
        assert (TEMPLATE / name).is_dir()


def test_the_schema_lists_the_page_types_and_the_general_document_types(vault):
    meta = fm.read(vault.knowledge_dir / "Schema.md").meta
    assert meta["page_types"] == ["Documents", "Organisations", "People", "Topics"]
    assert meta["doc_types"] == ["contract", "invoice", "receipt", "statement", "report", "financial statements", "budget",
                                 "presentation", "meeting minutes", "policy", "letter", "form", "spreadsheet", "other"]
    text = (vault.knowledge_dir / "Schema.md").read_text(encoding="utf-8")
    for rule in ("When a page is created", "Citations", "previously", "Your edits win", "two or more documents",
                 "(see [[", "index.md", "log.md"):
        assert rule in text, rule
    assert schema.page_types(vault) == schema.PAGE_TYPES


def test_your_own_page_types_come_first_in_your_order(vault):
    path = vault.knowledge_dir / "Schema.md"
    path.write_text(schema.with_doc_types(path.read_text(encoding="utf-8"), ["lease"])
                    .replace("page_types: [Documents, Organisations, People, Topics]",
                             "page_types: [Documents, Properties, Organisations, People, Topics, Inbox]"), encoding="utf-8")
    assert schema.page_types(vault) == ["Documents", "Properties", "Organisations", "People", "Topics"]
    assert fm.read(path).meta["doc_types"] == ["lease"]
    path.write_text("---\npage_types: nonsense: [\n---\n", encoding="utf-8")
    assert schema.page_types(vault) == schema.PAGE_TYPES


def test_clean_list():
    assert schema.clean_list([" Lease ", "utility  bill", "lease", "Bad [x] | y\x07", "", 2024, True, {"a": 1}]) == [
        "Lease", "utility bill", "Bad x y", "2024"]
    assert schema.clean_list("lease, invoice") == ["lease", "invoice"]
    assert schema.clean_list({"a": 1}) == [] and schema.clean_list(None) == []
    assert len(schema.clean_list([f"type {i}" for i in range(60)])) == 50


def test_the_migration_builds_the_wiki_and_moves_your_document_types(vault):
    as_071(vault, labels=False, doc_types=["Lease", "Utility bill"])
    doc = store.Doc(store.doc_id_for("a"), "a", "file", "/a.pdf", "a.pdf", "/a.pdf", status="read")
    store.save(vault, doc, ["text"], [])
    lines = apply_pending(vault, "0.7.1", "0.8.0")
    k = vault.knowledge_dir
    meta = fm.read(k / "Schema.md").meta
    assert meta["doc_types"] == ["Lease", "Utility bill", "other"] and meta["page_types"] == schema.PAGE_TYPES
    body = fm.read(k / "Schema.md").body
    assert body == fm.read(vault.core_templates / "Schema.md").body  # only the list changed
    assert (k / "index.md").read_text(encoding="utf-8") == schema.EMPTY_INDEX
    assert (k / "log.md").read_text(encoding="utf-8") == schema.LOG_HEADER
    assert all((k / name).is_dir() for name in schema.PAGE_TYPES)
    assert fm.read(vault.settings_file).meta["knowledge"] == {"model_pages": True, "max_model_pages": 20}
    text = "\n".join(lines)
    assert SUMMARY in text and "1 document you read before has no wiki page yet" in text and "finish the wiki pages" in text
    assert apply_pending(vault, "0.7.1", "0.8.0") == []  # once


def test_without_your_own_types_the_schema_is_the_template(vault):
    as_071(vault, labels=True)
    apply_pending(vault, "0.7.1", "0.8.0")
    assert (vault.knowledge_dir / "Schema.md").read_text(encoding="utf-8") == schema.template_text(vault)
    assert fm.read(vault.settings_file).meta["knowledge"] == {"model_pages": True, "max_model_pages": 20}


def test_an_existing_schema_keeps_its_text_and_gets_your_types(vault):
    as_071(vault, doc_types=["Lease"])
    own = "---\npage_types: [Documents, Topics]\ndoc_types: [contract]\n---\n# My rules\n\nKeep it short.\n"
    (vault.knowledge_dir / "Schema.md").write_text(own, encoding="utf-8")
    apply_pending(vault, "0.7.1", "0.8.0")
    after = fm.read(vault.knowledge_dir / "Schema.md")
    assert after.meta == {"page_types": ["Documents", "Topics"], "doc_types": ["Lease", "other"]}
    assert after.body == "# My rules\n\nKeep it short.\n"


def test_an_up_to_date_vault_has_nothing_to_migrate(vault):
    assert apply_pending(vault, "0.7.1", "0.8.0") == []


def test_the_migration_is_registered_for_0_8_0():
    m = migration()
    assert m.version == "0.8.0" and m.summary == SUMMARY
    assert SUMMARY in (REPO / "CHANGELOG.md").read_text(encoding="utf-8").split("## 0.7.1")[0]
```

In `tests/test_kb_store.py` replace `test_template_has_inbox_and_files` (lines 148-150) with:

```python
def test_template_has_inbox_files_and_the_wiki_folders():
    root = Path(__file__).resolve().parents[1] / "template" / "Knowledge"
    for name in ("Inbox", "Files", "Documents", "Organisations", "People", "Topics"):
        assert (root / name).is_dir(), name
    for name in ("Schema.md", "index.md", "log.md"):
        assert (root / name).is_file(), name
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki_migration.py tests/test_kb_store.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'bron.kb.schema'` / `bron.migrations.knowledge_wiki`.

- [ ] **Step 3: Implement**

Create `core/Engine/bron/kb/schema.py`:

```python
"""The wiki's rules file, Knowledge/Schema.md, and the headers of the two files Bron's code writes (index.md, log.md).

Schema.md's properties hold what code reads (`page_types`: the page folders, in index order; `doc_types`); its body is
plain English for the agents. It's the user's file: Bron only reads it (the 0.8.0 migration creates it once)."""
from __future__ import annotations

from pathlib import Path

from .. import frontmatter as fm
from ..vault import Vault

SCHEMA = "Schema.md"
INDEX = "index.md"
LOG = "log.md"
PAGE_TYPES = ["Documents", "Organisations", "People", "Topics"]
NOT_PAGE_FOLDERS = ("Inbox", "Files")
MAX_ITEMS = 50
INDEX_HEADER = "# Index\n\nEvery page in the wiki, by type. Bron writes this file; don't edit it.\n"
EMPTY_INDEX = INDEX_HEADER + "\nNo pages yet.\n"
LOG_HEADER = "# Log\n\nWhat happened in the wiki, newest last. Bron writes this file; don't edit it.\n"


def schema_path(vault: Vault) -> Path:
    return vault.knowledge_dir / SCHEMA


def template_text(vault: Vault) -> str:
    """The Schema.md Bron ships (System/Core/Templates/Schema.md, replaced on every update)."""
    return (vault.core_templates / SCHEMA).read_text(encoding="utf-8")


def _meta(vault: Vault) -> dict:
    try:
        return fm.read(schema_path(vault)).meta
    except (OSError, UnicodeDecodeError, fm.FrontmatterError):
        return {}


def clean_list(value, *, limit: int = MAX_ITEMS) -> list[str]:
    """A list of plain names (or one line split at commas): no brackets or pipes, no repeats, at most `limit`."""
    if value is None or value == "" or value == []:
        return []
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list):
        return []
    found: list[str] = []
    for item in value:
        if not isinstance(item, (str, int, float)) or isinstance(item, bool):
            continue
        name = " ".join("".join(" " if c in "[]|" or not c.isprintable() else c for c in str(item)).split())[:60]
        if name and name.lower() not in {t.lower() for t in found}:
            found.append(name)
    return found[:limit]


def page_types(vault: Vault) -> list[str]:
    """The page-type folders in the schema's order (the default four when Schema.md is missing or names none)."""
    chosen = [t.strip("/ ") for t in clean_list(_meta(vault).get("page_types"))]
    return [t for t in chosen if t and t not in NOT_PAGE_FOLDERS] or list(PAGE_TYPES)


def with_doc_types(text: str, types: list[str]) -> str:
    """Schema.md's text with its doc_types property replaced; every other line stays as written."""
    from ..fmedit import edit_meta

    return edit_meta(text, {"doc_types": list(types)})
```

Create `core/Templates/Schema.md` with exactly this content, and copy it byte for byte to `template/Knowledge/Schema.md`:

````markdown
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

Document pages also have `doc` (Bron's document id), `source` (the Drive link, web link or kept-copy path), `organisation` (the organisation the document is mainly about, as a link), `doc_type` (one of `doc_types` above) and `date` (YYYY-MM-DD, or empty). Search uses `organisation`, `doc_type` and `date` as its filters, so correcting them on the page corrects the search.

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
````

Create `template/Knowledge/index.md` (exactly `schema.EMPTY_INDEX`):

```markdown
# Index

Every page in the wiki, by type. Bron writes this file; don't edit it.

No pages yet.
```

Create `template/Knowledge/log.md` (exactly `schema.LOG_HEADER`):

```markdown
# Log

What happened in the wiki, newest last. Bron writes this file; don't edit it.
```

Create the empty files `template/Knowledge/Documents/.gitkeep`, `template/Knowledge/Organisations/.gitkeep`, `template/Knowledge/People/.gitkeep`, `template/Knowledge/Topics/.gitkeep`.

Create `core/Engine/bron/migrations/knowledge_wiki.py`:

```python
"""0.8.0: the knowledge base becomes a wiki.

Knowledge/ gets Schema.md (with the vault's own knowledge.doc_types, when it had some), index.md, log.md and the four
page-type folders, wherever they're missing; knowledge.labels and knowledge.doc_types leave System/Settings.md (a
document's labels now come from its wiki page). Nothing is deleted; documents already read show up as "read but no page
yet" until their pages are written."""
from __future__ import annotations

from .. import frontmatter as fm
from ..fmedit import EditError, edit_meta
from ..kb import schema, store
from ..loader import Config
from ..setup import Change

SUMMARY = ("Your knowledge base becomes a wiki: Knowledge/ gets Schema.md (its rules, with your document types), "
           "index.md, log.md and folders for documents, organisations, people and topics.")
OLD_KEYS = ("labels", "doc_types")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def build(cfg: Config) -> Change:
    vault = cfg.vault
    folder = vault.knowledge_dir
    writes: dict[str, str] = {}
    folders: list[str] = []
    try:
        settings_text = vault.settings_file.read_text(encoding="utf-8")
        knowledge = fm.parse(settings_text).meta.get("knowledge")
    except (OSError, UnicodeDecodeError, fm.FrontmatterError):
        settings_text, knowledge = "", None
    knowledge = knowledge if isinstance(knowledge, dict) else {}
    own = schema.clean_list(knowledge.get("doc_types"))
    if own and not any(t.lower() == "other" for t in own):
        own.append("other")
    keep_types = False  # Schema.md can't take the list: it stays in Settings rather than being lost
    target = schema.schema_path(vault)
    try:
        if not target.exists():
            text = schema.template_text(vault)
            writes[f"Knowledge/{schema.SCHEMA}"] = schema.with_doc_types(text, own) if own else text
        elif own:
            writes[f"Knowledge/{schema.SCHEMA}"] = schema.with_doc_types(target.read_text(encoding="utf-8"), own)
    except (OSError, UnicodeDecodeError, EditError):
        keep_types = True
    if not (folder / schema.INDEX).exists():
        writes[f"Knowledge/{schema.INDEX}"] = schema.EMPTY_INDEX
    if not (folder / schema.LOG).exists():
        writes[f"Knowledge/{schema.LOG}"] = schema.LOG_HEADER
    folders = [f"Knowledge/{name}" for name in schema.PAGE_TYPES if not (folder / name).is_dir()]
    drop = [key for key in OLD_KEYS if key in knowledge and not (key == "doc_types" and keep_types)]
    if drop and settings_text:
        try:
            writes["System/Settings.md"] = edit_meta(settings_text, {"knowledge": {k: v for k, v in knowledge.items()
                                                                                   if k not in drop}})
        except EditError:
            pass  # an unusual settings block stays as it is; Bron ignores the old keys
    if not writes and not folders:
        return Change(done="")  # nothing to say
    summary = ["Turn Knowledge/ into a wiki: add Schema.md, index.md, log.md and the page folders where they're missing."]
    if drop:
        summary.append("Move your document types into Knowledge/Schema.md and remove knowledge.labels and "
                       "knowledge.doc_types from System/Settings.md.")
    done = SUMMARY
    waiting = sum(1 for d in store.all_docs(vault) if d.status == "read")
    if waiting:
        done += (f" {_plural(waiting, 'document')} you read before {'has' if waiting == 1 else 'have'} no wiki page yet; "
                 "ask Bron to \"finish the wiki pages\" when you want them.")
    return Change(summary=summary, writes=writes, folders=folders, done=done)
```

In `core/Engine/bron/migrations/__init__.py` add after `_memory_saves` (line 35):

```python
def _knowledge_wiki(cfg: Config) -> Change:
    from .knowledge_wiki import build

    return build(cfg)
```

and append to `MIGRATIONS` (after the 0.6.0 entry, line 40):

```python
    Migration(id="knowledge-wiki", version="0.8.0",
              summary=("Your knowledge base becomes a wiki: Knowledge/ gets Schema.md (its rules, with your document "
                       "types), index.md, log.md and folders for documents, organisations, people and topics."),
              build=_knowledge_wiki),
```

In `CHANGELOG.md` insert above `## 0.7.1` (Task 10 adds the other lines of this section):

```markdown
## 0.8.0
- Your knowledge base becomes a wiki: Knowledge/ gets Schema.md (its rules, with your document types), index.md, log.md and folders for documents, organisations, people and topics.

```

- [ ] **Step 4: Run the tests**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki_migration.py tests/test_kb_store.py tests/test_migrations.py tests/test_install.py -q`
Expected: PASS.

- [ ] **Step 5: Run everything and commit**

Run: `uv run --project core/Engine pytest tests -q` — Expected: PASS.

```bash
git add core/Engine/bron/kb/schema.py core/Templates/Schema.md template/Knowledge core/Engine/bron/migrations/knowledge_wiki.py core/Engine/bron/migrations/__init__.py CHANGELOG.md tests/test_kb_wiki_migration.py tests/test_kb_store.py
git commit -m "Ship the wiki's Schema.md, index.md, log.md and folders; migrate 0.7 vaults

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The wiki's pages, the document ↔ page record, index.md and log.md (spec §4.1–4.3, §4.5, §5.3 step 2)

**Files:**
- Create: `core/Engine/bron/kb/wiki.py`
- Modify: `core/Engine/bron/kb/store.py:24-44` (`Doc`), `:99-125` (`save`, `save_meta`, `load`), `:187-191` (`effective_labels`); add `page_of`, `set_page`, `clear_page`
- Modify: `tests/kbkit.py` (add `write_page`, `later`, `stored_doc`)
- Test: `tests/test_kb_wiki.py` (create)

**Interfaces:**
- Consumes: `schema.SCHEMA/INDEX/LOG/INDEX_HEADER/EMPTY_INDEX/LOG_HEADER`, `schema.page_types(vault)` (Task 3); `frontmatter.parse`; `statefile.locked`; `store._write`.
- Produces:
  - `store.Doc` gains `page: str = ""` and `page_labels: dict = {}` (loaded from `.bron/kb/docs/<id>/page.json`, never written into `meta.json`); `store.page_of(vault, doc_id) -> dict` (`{"page": rel, "labels": {...}}` or `{}`); `store.set_page(vault, doc_id, page: str, labels: dict) -> None`; `store.clear_page(vault, doc_id) -> None`; `store.effective_labels(doc)` = labels from reading, then the page's labels on top when the document has a page, else the 0.7 user labels on top.
  - `wiki.OTHER = "Other"`, `wiki.LINK` (regex; group 1 = the link's target name), `wiki.LOG_KINDS = ("ingest", "update", "save", "check", "forget")`.
  - `wiki.Page` dataclass: `path: Path, rel: str (vault-relative posix), title: str (file stem), kind: str (first folder under Knowledge/, or "Other"), meta: dict, body: str, mtime: float, size: int, error: str ("" or a plain reason)`; properties `summary -> str`, `doc_id -> str`, `is_document -> bool` (has `doc` or lives in `Documents/`), `aliases -> list[str]`; method `links() -> list[str]`.
  - `wiki.property_text(value) -> str`; `wiki.name_of(target: str) -> str` (a link target or page title, folded for comparing: last path part, no `.md`, casefolded).
  - `wiki.page_paths(vault) -> list[Path]`; `wiki.read_page(vault, path) -> Page`; `wiki.all_pages(vault) -> list[Page]`.
  - `wiki.page_labels(page) -> dict` (`{"company", "doc_type", "date", "title"}`).
  - `wiki.link_documents(vault, pages: list[Page], removed=()) -> tuple[list[str], set[str]]` — records each document page as its document's page with its labels; returns (plain lines about pages whose `doc` Bron doesn't have, ids of documents whose record changed).
  - `wiki.index_text(vault, pages: list[Page] | None = None) -> str`; `wiki.write_index(vault, pages=None) -> bool` (True when it wrote).
  - `wiki.append_log(vault, entries: list[tuple[str, str]], *, now: str | None = None) -> None`; `wiki.parse_log_text(text: str) -> tuple[str, str]`.
  - kbkit: `write_page(vault, rel, body="", **meta) -> Path`, `later(path, seconds=5.0) -> None`, `stored_doc(vault, name, pages, *, folder="", index_it=False) -> Doc`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/kbkit.py` (below `make_pptx`):

```python
def write_page(vault, rel: str, body: str = "", **meta) -> Path:
    """A wiki page under Knowledge/ (rel like "Organisations/Acme Ltda.md") with these properties."""
    from bron import frontmatter as fm

    path = vault.knowledge_dir / rel
    fm.write(path, fm.Document(dict(meta), body))
    return path


def later(path: Path, seconds: float = 5.0) -> None:
    """Move a file's modification time forward, so a quick edit in a test always counts as a change."""
    st = path.stat()
    os.utime(path, (st.st_atime + seconds, st.st_mtime + seconds))


def stored_doc(vault, name: str, pages: list[str], *, folder: str = "", index_it: bool = False):
    """A document Bron has read (in the store; in the search index too with index_it), without any reader."""
    from bron.kb import index, store
    from bron.kb.models import labels_from_names
    from bron.kb.passages import split

    identity = f"file:/docs/{name}"
    doc = store.Doc(store.doc_id_for(identity), identity, "file", f"/docs/{name}", name, f"/docs/{name}",
                    labels=labels_from_names(name, folder), read_at="2026-10-04", pages=len(pages))
    passages = split([(i + 1, t) for i, t in enumerate(pages)], store.effective_labels(doc))
    store.save(vault, doc, pages, passages)
    if index_it:
        index.put(vault, doc, passages, fake_embed)
    return store.load(vault, doc.doc_id)
```

Create `tests/test_kb_wiki.py`:

```python
"""The wiki's pages, their links and properties, the record of each document's page, index.md and log.md."""
import time

from bron.cli import build_parser
from bron.kb import cli as kb_cli
from bron.kb import schema, store, wiki
from kbkit import stored_doc, write_page

LEASE = "Documents/Office lease (2025-03-01).md"


def test_pages_are_the_markdown_files_under_knowledge(vault):
    write_page(vault, "Organisations/Acme Ltda.md", "# Acme Ltda\n", type="organisation", summary="A supplier")
    write_page(vault, LEASE, type="document", summary="A lease")
    write_page(vault, "Notes.md", type="topic", summary="Loose notes")
    (vault.knowledge_dir / "Inbox" / "draft.md").write_text("x")
    kept = vault.knowledge_dir / "Files" / "2026-10"
    kept.mkdir(parents=True)
    (kept / "copy.md").write_text("x")
    (vault.knowledge_dir / "Topics" / ".hidden.md").write_text("x")
    pages = wiki.all_pages(vault)
    assert [(p.rel, p.kind, p.title) for p in pages] == [
        ("Knowledge/Documents/Office lease (2025-03-01).md", "Documents", "Office lease (2025-03-01)"),
        ("Knowledge/Notes.md", wiki.OTHER, "Notes"),
        ("Knowledge/Organisations/Acme Ltda.md", "Organisations", "Acme Ltda"),
    ]
    assert pages[2].summary == "A supplier" and pages[0].is_document and not pages[2].is_document


def test_links_come_from_the_body_and_the_properties(vault):
    path = write_page(vault, LEASE, "Tenant: [[Harbor Bakery|the bakery]]; see [[Office move#Dates]] and ![[plan.png]].\n",
                      type="document", summary="A lease", organisation="[[Northwind Properties Ltd]]", aliases=["Shop lease"])
    page = wiki.read_page(vault, path)
    assert sorted(page.links()) == ["Harbor Bakery", "Northwind Properties Ltd", "Office move", "plan.png"]
    assert page.aliases == ["Shop lease"]
    assert wiki.name_of("Knowledge/Organisations/Harbor Bakery.md") == wiki.name_of("harbor bakery") == "harbor bakery"


def test_an_unquoted_link_in_a_property_still_counts(vault):
    path = vault.knowledge_dir / "Documents" / "Invoice 1042 (2025-02-01).md"
    path.write_text("---\ntype: document\nsummary: Rent for February\ndoc: \"abc123\"\norganisation: [[Harbor Bakery]]\n"
                    "doc_type: invoice\ndate: 2025-02-01\n---\n# Invoice 1042\nFrom [[Northwind Properties Ltd]] (p. 1).\n",
                    encoding="utf-8")
    page = wiki.read_page(vault, path)
    assert page.error == "" and sorted(page.links()) == ["Harbor Bakery", "Northwind Properties Ltd"]
    assert wiki.page_labels(page) == {"company": "Harbor Bakery", "doc_type": "invoice", "date": "2025-02-01",
                                      "title": "Invoice 1042 (2025-02-01)"}
    assert page.doc_id == "abc123"


def test_a_page_with_broken_properties_says_why(vault):
    path = vault.knowledge_dir / "Topics" / "Broken.md"
    path.write_text("---\ntype: topic\nsummary: [unclosed\n---\nbody\n", encoding="utf-8")
    page = wiki.read_page(vault, path)
    assert page.error.startswith("the properties block is not valid YAML") and page.links() == [] and page.meta == {}


def test_a_document_page_names_its_document_and_gives_it_labels(vault):
    doc = stored_doc(vault, "lease.pdf", ["Lease text"])
    store.save_user_labels(vault, doc.doc_id, {"company": "Old Name"})  # a 0.7 correction: it counts until there's a page
    assert store.effective_labels(store.load(vault, doc.doc_id))["company"] == "Old Name"
    path = write_page(vault, LEASE, type="document", summary="A lease", doc=doc.doc_id, organisation="[[Harbor Bakery]]",
                      doc_type="contract", date="2025-03-01")
    unknown, touched = wiki.link_documents(vault, [wiki.read_page(vault, path)])
    assert unknown == [] and touched == {doc.doc_id}
    again = store.load(vault, doc.doc_id)
    assert again.page == "Knowledge/" + LEASE
    assert store.effective_labels(again) == {"company": "Harbor Bakery", "doc_type": "contract", "date": "2025-03-01",
                                             "title": "Office lease (2025-03-01)", "language": "other"}
    assert wiki.link_documents(vault, [wiki.read_page(vault, path)]) == ([], set())  # nothing new
    store.save(vault, again, ["Lease text, read again"], [])  # reading it again keeps its page
    assert store.load(vault, doc.doc_id).page == "Knowledge/" + LEASE
    assert "page" not in (store.kb_dir(vault) / "docs" / doc.doc_id / "meta.json").read_text()
    path.unlink()
    assert wiki.link_documents(vault, [], removed=["Knowledge/" + LEASE]) == ([], {doc.doc_id})
    gone = store.load(vault, doc.doc_id)
    assert gone.page == "" and store.effective_labels(gone)["company"] == "Old Name"


def test_a_page_naming_a_document_bron_does_not_have_is_reported(vault):
    path = write_page(vault, LEASE, type="document", summary="A lease", doc="0000000000000000")
    unknown, touched = wiki.link_documents(vault, [wiki.read_page(vault, path)])
    assert unknown == ["Office lease (2025-03-01): its doc 0000000000000000 isn't in the knowledge base "
                       "(forgotten, or never read)."]
    assert touched == set()


def test_kb_list_uses_the_page_labels(vault, capsys):
    doc = stored_doc(vault, "lease.pdf", ["Lease text"])
    path = write_page(vault, LEASE, type="document", summary="A lease", doc=doc.doc_id, organisation="[[Harbor Bakery]]",
                      doc_type="contract", date="2025-03-01")
    wiki.link_documents(vault, [wiki.read_page(vault, path)])
    kb_cli.handle(build_parser().parse_args(["kb", "list", "--company", "harbor"]), vault)
    assert "lease.pdf — Harbor Bakery · contract · 2025-03-01" in capsys.readouterr().out


def test_index_md_lists_every_page_by_type_with_its_sources(vault):
    write_page(vault, LEASE, "Tenant: [[Harbor Bakery]].\n", type="document", summary="Lease of the shop", date="2025-03-01")
    write_page(vault, "Documents/Rent letter (2026-01-10).md", "Rent goes up for [[Harbor Bakery]].\n", type="document",
               summary="Rent increase notice", organisation="[[Harbor Bakery]]", date="2026-01-10")
    write_page(vault, "Organisations/Harbor Bakery.md", "Rents a shop.\n", type="organisation", summary="A bakery")
    write_page(vault, "People/Jane Doe.md", "Signs for [[Harbor Bakery]].\n", type="person", summary="Owner of the bakery")
    write_page(vault, "Properties/Shop 4.md", "", type="property", summary="The shop")
    write_page(vault, "Loose.md", "", type="topic", summary="")
    (vault.knowledge_dir / "Topics" / "Broken.md").write_text("---\nsummary: [x\n---\n", encoding="utf-8")
    today = time.strftime("%Y-%m-%d")
    assert wiki.write_index(vault) is True
    text = (vault.knowledge_dir / "index.md").read_text(encoding="utf-8")
    assert text == (schema.INDEX_HEADER + "\n## Documents\n"
                    f"- [[Office lease (2025-03-01)]] — Lease of the shop (2025-03-01, updated {today})\n"
                    f"- [[Rent letter (2026-01-10)]] — Rent increase notice (2026-01-10, updated {today})\n"
                    "\n## Organisations\n"
                    f"- [[Harbor Bakery]] — A bakery (2 sources, updated {today})\n"
                    "\n## People\n"
                    f"- [[Jane Doe]] — Owner of the bakery (0 sources, updated {today})\n"
                    "\n## Properties\n"
                    f"- [[Shop 4]] — The shop (0 sources, updated {today})\n"
                    "\n## Other\n"
                    f"- [[Loose]] — no summary yet (0 sources, updated {today})\n")
    assert wiki.write_index(vault) is False  # unchanged: not written again


def test_index_md_follows_the_schema_order_and_is_empty_without_pages(vault):
    assert wiki.index_text(vault) == schema.EMPTY_INDEX
    write_page(vault, "Topics/Office move.md", "", type="topic", summary="Moving")
    write_page(vault, "Organisations/Acme Ltda.md", "", type="organisation", summary="Supplier")
    path = schema.schema_path(vault)
    path.write_text(path.read_text(encoding="utf-8").replace("[Documents, Organisations, People, Topics]",
                                                             "[Topics, Documents, Organisations, People]"), encoding="utf-8")
    text = wiki.index_text(vault)
    assert text.index("## Topics") < text.index("## Organisations")


def test_log_entries_are_appended_newest_last(vault):
    wiki.append_log(vault, [("ingest", "[[Office lease (2025-03-01)]]"), ("update", "[[Harbor Bakery]],\n [[Jane Doe]]")],
                    now="2026-10-04 14:03")
    wiki.append_log(vault, [wiki.parse_log_text("save | Rent history")], now="2026-10-04 14:10")
    text = (vault.knowledge_dir / "log.md").read_text(encoding="utf-8")
    assert text == (schema.LOG_HEADER + "\n## [2026-10-04 14:03] ingest | [[Office lease (2025-03-01)]]\n"
                    "\n## [2026-10-04 14:03] update | [[Harbor Bakery]], [[Jane Doe]]\n"
                    "\n## [2026-10-04 14:10] save | Rent history\n")
    assert not list(vault.knowledge_dir.glob("*.lock"))  # the lock lives in .bron/kb


def test_log_text_kinds():
    assert wiki.parse_log_text("check | 12 pages checked, 2 fixed") == ("check", "12 pages checked, 2 fixed")
    assert wiki.parse_log_text("SAVE| Rent history") == ("save", "Rent history")
    assert wiki.parse_log_text("wrote a note") == ("update", "wrote a note")
    assert wiki.parse_log_text("hello | there") == ("update", "hello | there")


def test_a_missing_log_is_started_with_its_header(vault):
    (vault.knowledge_dir / "log.md").unlink()
    wiki.append_log(vault, [("forget", "lease.pdf")], now="2026-10-04 09:00")
    assert (vault.knowledge_dir / "log.md").read_text(encoding="utf-8") == (
        schema.LOG_HEADER + "\n## [2026-10-04 09:00] forget | lease.pdf\n")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki.py -q`
Expected: FAIL — `ImportError: cannot import name 'wiki' from 'bron.kb'`.

- [ ] **Step 3: Implement**

`core/Engine/bron/kb/store.py`:
- in `Doc` after `reader_version` (line 44) add:

```python
    page: str = ""  # its wiki page (vault-relative), from page.json; never written into meta.json
    page_labels: dict = field(default_factory=dict)  # the labels its page's properties give it
```

- after `save_user_labels` (line 96) add:

```python
PAGE_FILE = "page.json"
_NOT_META = ("page", "page_labels")


def _meta_json(doc: Doc) -> str:
    data = asdict(doc)
    for key in _NOT_META:
        data.pop(key, None)
    return json.dumps(data, ensure_ascii=False, indent=2)


def page_of(vault: Vault, doc_id: str) -> dict:
    """{"page": <vault-relative path>, "labels": {...}} for a document that has a wiki page, else {}. Kept in its own
    file, like the user's labels, so reading the document again never loses it."""
    try:
        data = json.loads((_folder(vault, doc_id) / PAGE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and isinstance(data.get("page"), str) and data["page"] else {}


def set_page(vault: Vault, doc_id: str, page: str, labels: dict) -> None:
    _write(_folder(vault, doc_id) / PAGE_FILE, json.dumps({"page": page, "labels": labels}, ensure_ascii=False, indent=2))


def clear_page(vault: Vault, doc_id: str) -> None:
    try:
        (_folder(vault, doc_id) / PAGE_FILE).unlink()
    except FileNotFoundError:
        pass
```

- in `save` (line 108) and `save_meta` (line 114) replace `json.dumps(asdict(doc), ensure_ascii=False, indent=2)` with `_meta_json(doc)`.
- in `load`, after the user-labels lines (123-124) add:

```python
    linked = page_of(vault, doc_id)
    doc.page = str(linked.get("page") or "")
    doc.page_labels = linked["labels"] if isinstance(linked.get("labels"), dict) else {}
```

- replace `effective_labels` (lines 187-191) with:

```python
def effective_labels(doc: Doc) -> dict:
    """The labels worked out when it was read; once the document has a wiki page, that page's properties on top;
    before that, the user's 0.7 corrections on top."""
    base = doc.labels if isinstance(doc.labels, dict) else {}
    page = doc.page_labels if isinstance(doc.page_labels, dict) else {}
    if page:
        return fold_fund({**base, **{k: v for k, v in page.items() if v}})
    user = doc.user_labels if isinstance(doc.user_labels, dict) else {}
    return fold_fund({**base, **{k: v for k, v in user.items() if v}})
```

Create `core/Engine/bron/kb/wiki.py`:

```python
"""The wiki in Knowledge/: its pages, their links and properties, the document each document page stands for, and the
two files Bron's code writes (index.md, log.md). Agents write the pages; this module only reads them.

A page is any .md file under Knowledge/ except Schema.md, index.md, log.md and what's in Inbox/ and Files/; its type
is its first folder."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .. import frontmatter as fm
from .. import statefile
from ..vault import Vault
from . import schema, store

RESERVED = {schema.SCHEMA, schema.INDEX, schema.LOG}
OTHER = "Other"  # pages directly in Knowledge/, outside any type folder
LINK = re.compile(r"!?\[\[([^\[\]|#]*)(?:#[^\[\]|]*)?(?:\|[^\[\]]*)?\]\]")
LOG_KINDS = ("ingest", "update", "save", "check", "forget")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def property_text(value) -> str:
    """A property as plain text: "[[Acme Ltda|Acme]]" → "Acme Ltda", a YAML date → "2025-01-21", and [[Acme]] written
    without quotes (YAML reads it as a list in a list) → "Acme"."""
    while isinstance(value, list) and value:
        value = value[0]
    if value is None or isinstance(value, (list, dict)):
        return ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    text = " ".join(str(value).split())
    found = LINK.fullmatch(text)
    return found.group(1).strip() if found else text


def _property_links(value) -> list[str]:
    if isinstance(value, str):
        return [m.group(1).strip() for m in LINK.finditer(value)]
    if isinstance(value, list):
        if len(value) == 1 and isinstance(value[0], list) and len(value[0]) == 1 and isinstance(value[0][0], str):
            return [value[0][0].strip()]  # [[Name]] without quotes: YAML reads it as a list in a list
        return [name for item in value for name in _property_links(item)]
    if isinstance(value, dict):
        return [name for item in value.values() for name in _property_links(item)]
    return []


def name_of(target: str) -> str:
    """A link target or a page title, folded for comparing: "Knowledge/Organisations/Acme.md" and "acme" are the same."""
    return target.strip().rsplit("/", 1)[-1].removesuffix(".md").strip().casefold()


@dataclass
class Page:
    path: Path
    rel: str  # vault-relative, like "Knowledge/Organisations/Acme Ltda.md"
    title: str  # the file name without .md
    kind: str  # the type folder ("Organisations"), or OTHER
    meta: dict = field(default_factory=dict)
    body: str = ""
    mtime: float = 0.0
    size: int = 0
    error: str = ""  # why its properties can't be read ("" when they can)

    @property
    def summary(self) -> str:
        return property_text(self.meta.get("summary"))

    @property
    def doc_id(self) -> str:
        return property_text(self.meta.get("doc"))

    @property
    def is_document(self) -> bool:
        return bool(self.doc_id) or self.kind == "Documents"

    @property
    def aliases(self) -> list[str]:
        raw = self.meta.get("aliases")
        items = raw if isinstance(raw, list) else [raw] if raw else []
        return [t for t in (property_text(a) for a in items) if t]

    def links(self) -> list[str]:
        """The pages this one links to (body and properties), by name: no "#heading", no "|label"."""
        found = [m.group(1).strip() for m in LINK.finditer(self.body)] + _property_links(self.meta)
        return [name for name in found if name]


def page_paths(vault: Vault) -> list[Path]:
    root = vault.knowledge_dir
    if not root.is_dir():
        return []
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        top = here == root
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and not (top and d in schema.NOT_PAGE_FOLDERS))
        for name in filenames:
            if name.startswith(".") or not name.endswith(".md") or (top and name in RESERVED):
                continue
            out.append(here / name)
    return sorted(out)


def read_page(vault: Vault, path: Path) -> Page:
    rel = path.relative_to(vault.root).as_posix()
    parts = path.relative_to(vault.knowledge_dir).parts
    page = Page(path, rel, path.stem, parts[0] if len(parts) > 1 else OTHER)
    try:
        st = path.stat()
        page.mtime, page.size = st.st_mtime, st.st_size
        parsed = fm.parse(path.read_text(encoding="utf-8"))
        page.meta, page.body = parsed.meta, parsed.body
    except fm.FrontmatterError as exc:
        page.error = str(exc).replace("the settings block at the top", "the properties block")
    except (OSError, UnicodeDecodeError) as exc:
        page.error = f"it can't be opened ({exc.__class__.__name__})"
    return page


def all_pages(vault: Vault) -> list[Page]:
    return [read_page(vault, path) for path in page_paths(vault)]


def page_labels(page: Page) -> dict:
    """The search labels a document page gives its document."""
    when = property_text(page.meta.get("date"))
    return {"company": property_text(page.meta.get("organisation")), "doc_type": property_text(page.meta.get("doc_type")),
            "date": when if _DATE.fullmatch(when) else "", "title": page.title}


def link_documents(vault: Vault, pages: list[Page], removed=()) -> tuple[list[str], set[str]]:
    """Record each document page among `pages` as its document's page, with the labels its properties give; forget the
    record of pages that were removed or no longer name their document. Returns (plain lines about pages whose doc Bron
    doesn't have, ids of the documents whose record changed)."""
    unknown: list[str] = []
    touched: set[str] = set()
    claimed = {p.doc_id: p for p in pages if not p.error and p.doc_id}
    looked_at = set(removed) | {p.rel for p in pages if not p.error}
    for doc in store.all_docs(vault):
        if doc.page in looked_at and doc.doc_id not in claimed:
            store.clear_page(vault, doc.doc_id)
            touched.add(doc.doc_id)
    for doc_id, page in claimed.items():
        if not store.exists(vault, doc_id):
            unknown.append(f"{page.title}: its doc {doc_id} isn't in the knowledge base (forgotten, or never read).")
            continue
        wanted = {"page": page.rel, "labels": page_labels(page)}
        if store.page_of(vault, doc_id) != wanted:
            store.set_page(vault, doc_id, page.rel, wanted["labels"])
            touched.add(doc_id)
    return unknown, touched


# ---- index.md ----

def _kinds_in_order(kinds: set[str], order: list[str]) -> list[str]:
    def key(kind: str):
        if kind in order:
            return (0, order.index(kind), "")
        return (2 if kind == OTHER else 1, 0, kind.casefold())

    return sorted(kinds, key=key)


def _sources(pages: list[Page]) -> dict[str, set[str]]:
    """Page name → the titles of the document pages that link to it."""
    out: dict[str, set[str]] = {}
    for page in pages:
        if page.is_document:
            for target in page.links():
                name = name_of(target)
                if name != name_of(page.title):
                    out.setdefault(name, set()).add(page.title)
    return out


def index_text(vault: Vault, pages: list[Page] | None = None) -> str:
    """index.md: one section per page type (the schema's order, then others alphabetically, then Other), one line per
    page. Pages whose properties can't be read are left out (the check reports them)."""
    pages = [p for p in (all_pages(vault) if pages is None else pages) if not p.error]
    if not pages:
        return schema.EMPTY_INDEX
    sources = _sources(pages)
    lines = [schema.INDEX_HEADER.rstrip("\n")]
    for kind in _kinds_in_order({p.kind for p in pages}, schema.page_types(vault)):
        lines += ["", f"## {kind}"]
        for page in sorted((p for p in pages if p.kind == kind), key=lambda p: p.title.casefold()):
            updated = time.strftime("%Y-%m-%d", time.localtime(page.mtime))
            if page.is_document:
                when = page_labels(page)["date"]
                tail = f"({when}, updated {updated})" if when else f"(updated {updated})"
            else:
                n = len(sources.get(name_of(page.title), set()))
                tail = f"({n} source{'' if n == 1 else 's'}, updated {updated})"
            lines.append(f"- [[{page.title}]] — {page.summary or 'no summary yet'} {tail}")
    return "\n".join(lines) + "\n"


def write_index(vault: Vault, pages: list[Page] | None = None) -> bool:
    """Rewrite index.md when it would change; True when it did."""
    path = vault.knowledge_dir / schema.INDEX
    text = index_text(vault, pages)
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except (OSError, UnicodeDecodeError):
        pass
    store._write(path, text)
    return True


# ---- log.md ----

def parse_log_text(text: str) -> tuple[str, str]:
    """"check | 3 pages fixed" → ("check", "3 pages fixed"); text without a known kind is an update."""
    kind, sep, rest = text.partition("|")
    if sep and kind.strip().lower() in LOG_KINDS and rest.strip():
        return kind.strip().lower(), rest.strip()
    return "update", text.strip()


def append_log(vault: Vault, entries: list[tuple[str, str]], *, now: str | None = None) -> None:
    """Add `## [YYYY-MM-DD HH:MM] <kind> | <text>` entries to log.md (started with its header when missing)."""
    entries = [(kind, " ".join(text.split())) for kind, text in entries if text.strip()]
    if not entries:
        return
    path = vault.knowledge_dir / schema.LOG
    stamp = now or time.strftime("%Y-%m-%d %H:%M")
    with statefile.locked(store.kb_dir(vault) / "wiki-log"):  # the lock file lives in .bron/kb, not in the vault
        try:
            text = path.read_text(encoding="utf-8")
        except (FileNotFoundError, UnicodeDecodeError):
            text = schema.LOG_HEADER
        if not text.endswith("\n"):
            text += "\n"
        text += "".join(f"\n## [{stamp}] {kind} | {line}\n" for kind, line in entries)
        store._write(path, text)
```

- [ ] **Step 4: Run the tests**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki.py tests/test_kb_store.py tests/test_kb_ingest.py tests/test_kb_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Run everything and commit**

Run: `uv run --project core/Engine pytest tests -q` — Expected: PASS.

```bash
git add core/Engine/bron/kb/wiki.py core/Engine/bron/kb/store.py tests/kbkit.py tests/test_kb_wiki.py
git commit -m "Read the wiki's pages; write index.md and log.md; document pages label their documents

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Pages in the search database; one search for pages then passages (spec §6.1)

**Files:**
- Create: `core/Engine/bron/kb/wiki_index.py`
- Modify: `core/Engine/bron/kb/index.py:40-72` (page tables), add `set_labels`
- Modify: `core/Engine/bron/kb/search.py:28-37` (`Hit`), `:144-194` (`find`, `search`, rendering)
- Modify: `core/Engine/bron/kb/service.py:118-133` (`_answer`)
- Modify: `core/Engine/bron/kb/cli.py:33-39` (search parser), `:45-48` (list parser), `:124-144` (`_search`)
- Test: `tests/test_kb_wiki_search.py` (create), `tests/test_kb_service.py` (one test added)

**Interfaces:**
- Consumes: `wiki.page_paths/read_page/link_documents/write_index/LINK` (Task 4), `passages.windows`, `passages.normal_tokens`, `search._query_terms`, `index._FailFast`, `index._bump`.
- Produces:
  - `index._create_page_tables(con)` (tables `page_fts(path UNINDEXED, w UNINDEXED, excerpt UNINDEXED, body)`, `page_vectors(path, w, vec)`, `pages(path PRIMARY KEY, mtime, size, title, kind, summary, doc_id, vectors)`), created by `_create_schema` and, for an older index, on open.
  - `index.set_labels(con, doc) -> None` — updates the `docs` row's company/doc_type/date from `store.effective_labels(doc)` and bumps the counter.
  - `wiki_index.PageHit(path: str, title: str, kind: str, summary: str, excerpt: str, score: float)`.
  - `wiki_index.refresh(vault, con, embedder) -> bool` — indexes new/changed pages, drops removed ones, adds vectors still missing (`embedder=None`: words only, vectors later), records document pages and pushes their labels into `docs`, rewrites index.md when pages changed; True when anything changed.
  - `wiki_index.search_pages(vault, con, query, embedder, *, allowed: set[str] | None = None, limit: int = 3) -> list[PageHit]`.
  - `search.Hit` gains `wiki_page: str = ""`; `search.Results(pages: list[PageHit], hits: list[Hit])`; `search.find(vault, query, *, embedder, company="", doc_type="", after="", before="", limit=8, pages_only=False) -> Results`; `search.search(...)` unchanged signature, returns `find(...).hits`; `search.render_pages(pages) -> str`; `search.render_all(results) -> str`.
  - Helper reply: `{"hits": [...], "pages": [...], "keyword_only": bool}`; request key `"pages_only"`.
  - CLI: `bron kb search '<q>' [--organisation X | --company X] [--type T] [--after D] [--before D] [--limit N] [--pages-only]`; `bron kb list [--organisation X | --company X] [--type T] [--failed]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kb_wiki_search.py`:

```python
"""Wiki pages live in the search database beside the passages: one search returns pages, then passages."""
import pytest

from bron import cli as bron_cli
from bron.kb import cli as kb_cli
from bron.kb import embed, index, search, service, store, tools, wiki_index
from kbkit import fake_embed, later, stored_doc, write_page

LEASE_PAGE = "Documents/Office lease (2025-03-01).md"


def find(vault, query, **kw):
    return search.find(vault, query, embedder=fake_embed, **kw)


def lease(vault):
    doc = stored_doc(vault, "lease.pdf", ["Lease between Northwind Properties Ltd and Harbor Bakery LLC for shop 4. " * 3,
                                          "The monthly rent is USD 4,200.00 from March 1, 2025, paid on the first day. " * 3],
                     index_it=True)
    write_page(vault, LEASE_PAGE,
               "# Office lease\n\nThe monthly rent is USD 4,200.00 (p. 2).\n\n## Parties\n- [[Harbor Bakery]] — tenant\n",
               type="document", summary="Lease of the bakery's shop", doc=doc.doc_id, source="/docs/lease.pdf",
               organisation="[[Harbor Bakery]]", doc_type="contract", date="2025-03-01")
    write_page(vault, "Organisations/Harbor Bakery.md",
               "# Harbor Bakery\n\n## Key facts\n- Pays rent of USD 4,200.00 a month (see [[Office lease (2025-03-01)]], p. 2)\n",
               type="organisation", summary="A bakery that rents a shop", aliases=["Harbor"])
    return doc


def titles(found):
    return [p.title for p in found.pages]


def test_search_returns_pages_then_passages(vault):
    doc = lease(vault)
    found = find(vault, "monthly rent")
    assert set(titles(found)) == {"Office lease (2025-03-01)", "Harbor Bakery"}
    assert all(p.path.startswith("Knowledge/") and p.summary for p in found.pages)
    assert any("4,200.00" in p.excerpt for p in found.pages)
    assert found.hits and found.hits[0].doc_id == doc.doc_id and found.hits[0].wiki_page == "Office lease (2025-03-01)"
    out = search.render_all(found)
    assert out.startswith("Wiki pages:\n1. [[") and out.index("Wiki pages:") < out.index("Document passages:")
    assert "Page: [[Office lease (2025-03-01)]]" in out


def test_pages_only_skips_the_passages(vault):
    lease(vault)
    found = find(vault, "rent", pages_only=True)
    assert found.hits == [] and found.pages
    assert "Document passages:" not in search.render_all(found)


def test_an_edited_page_is_searched_again_and_a_removed_one_is_gone(vault):
    lease(vault)
    page = vault.knowledge_dir / "Organisations" / "Harbor Bakery.md"
    assert "Harbor Bakery" not in titles(find(vault, "sourdough", pages_only=True))
    page.write_text(page.read_text(encoding="utf-8") + "- Known for its sourdough (see [[Office lease (2025-03-01)]], p. 1)\n",
                    encoding="utf-8")
    later(page)
    assert titles(find(vault, "sourdough", pages_only=True))[0] == "Harbor Bakery"
    page.unlink()
    assert "Harbor Bakery" not in titles(find(vault, "sourdough", pages_only=True))
    assert "[[Harbor Bakery]]" not in (vault.knowledge_dir / "index.md").read_text(encoding="utf-8")


def test_a_page_with_broken_properties_is_not_indexed_and_the_rest_are(vault):
    lease(vault)
    (vault.knowledge_dir / "Topics" / "Rent history.md").write_text("---\nsummary: [rent\n---\nRent history\n", encoding="utf-8")
    found = find(vault, "rent history", pages_only=True)
    assert "Rent history" not in titles(found) and "Harbor Bakery" in titles(found)


def test_an_edited_document_page_changes_the_filters_on_the_next_search(vault):
    doc = lease(vault)
    assert [h.doc_id for h in search.search(vault, "rent", embedder=fake_embed, company="harbor")][:1] == [doc.doc_id]
    assert search.search(vault, "rent", embedder=fake_embed, doc_type="invoice") == []
    page = vault.knowledge_dir / LEASE_PAGE
    page.write_text(page.read_text(encoding="utf-8").replace("doc_type: contract", "doc_type: invoice"), encoding="utf-8")
    later(page)
    assert [h.doc_id for h in search.search(vault, "rent", embedder=fake_embed, doc_type="invoice")][:1] == [doc.doc_id]
    assert store.load(vault, doc.doc_id).page == "Knowledge/" + LEASE_PAGE


def test_filters_narrow_document_pages_but_not_other_pages(vault):
    lease(vault)
    found = find(vault, "rent", doc_type="invoice")
    assert found.hits == [] and "Office lease (2025-03-01)" not in titles(found) and "Harbor Bakery" in titles(found)


def test_a_new_page_rewrites_index_md_on_the_next_search(vault):
    lease(vault)
    find(vault, "rent")
    text = (vault.knowledge_dir / "index.md").read_text(encoding="utf-8")
    assert "- [[Harbor Bakery]] — A bakery that rents a shop (1 source, updated " in text


def test_an_index_from_0_7_gets_the_page_tables_without_a_rebuild(vault):
    stored_doc(vault, "a.pdf", ["alpha text for the index"], index_it=True)
    con = index.open(vault)
    for table in ("page_fts", "page_vectors", "pages"):
        con.execute(f"DROP TABLE {table}")
    con.commit()
    before = index.counter(con)
    con.close()
    con = index.open(vault)
    try:
        assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'pages'").fetchone()[0] == 1
        assert index.counter(con) == before and con.execute("SELECT COUNT(*) FROM docs").fetchone()[0] == 1
    finally:
        con.close()


def test_vectors_missing_after_words_only_indexing_are_added_by_the_next_search(vault):
    lease(vault)
    con = index.open(vault)
    try:
        assert wiki_index.refresh(vault, con, None) is True
        assert con.execute("SELECT COUNT(*) FROM page_vectors").fetchone()[0] == 0
    finally:
        con.close()
    find(vault, "rent")
    con = index.open(vault)
    try:
        assert con.execute("SELECT COUNT(*) FROM page_vectors").fetchone()[0] > 0
        assert con.execute("SELECT MIN(vectors) FROM pages").fetchone()[0] == 1
    finally:
        con.close()


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(tools, "ensure", lambda vault, say=print: None)
    monkeypatch.setattr(service, "query", lambda *a, **k: None)
    monkeypatch.setattr(embed, "get", lambda vault: fake_embed)


def run_cli(vault, capsys, *argv):
    code = kb_cli.handle(bron_cli.build_parser().parse_args(["kb", *argv]), vault)
    return code, capsys.readouterr().out


def test_organisation_and_company_are_the_same_filter(vault, offline, capsys):
    lease(vault)
    _, by_org = run_cli(vault, capsys, "search", "monthly rent", "--organisation", "harbor")
    _, by_company = run_cli(vault, capsys, "search", "monthly rent", "--company", "harbor")
    assert by_org == by_company and "Document passages:" in by_org and "lease.pdf" in by_org
    code, out = run_cli(vault, capsys, "search", "monthly rent", "--pages-only")
    assert code == 0 and out.startswith("Wiki pages:") and "Document passages:" not in out
    code, out = run_cli(vault, capsys, "list", "--organisation", "harbor")
    assert "lease.pdf — Harbor Bakery · contract · 2025-03-01" in out
```

Append to `tests/test_kb_service.py`:

```python
def test_the_helper_returns_pages_and_passages(vault, helper):
    from kbkit import write_page

    add(vault, "a", ["The monthly rent is USD 4,200.00."])
    write_page(vault, "Organisations/Harbor Bakery.md", "Pays a monthly rent of USD 4,200.00.\n", type="organisation",
               summary="A bakery")
    helper()
    reply = service.query(vault, {"query": "monthly rent", "pages_only": True}, start=False)
    assert reply["hits"] == [] and reply["pages"][0]["title"] == "Harbor Bakery"
    reply = service.query(vault, {"query": "monthly rent"}, start=False)
    assert reply["hits"] and reply["pages"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki_search.py tests/test_kb_service.py::test_the_helper_returns_pages_and_passages -q`
Expected: FAIL — `AttributeError: module 'bron.kb.search' has no attribute 'find'` / no `wiki_index`.

- [ ] **Step 3: Implement**

`core/Engine/bron/kb/index.py` — after `_create_schema` (line 52) add, and call `_create_page_tables(con)` at the end of `_create_schema` (before `con.commit()`):

```python
def _create_page_tables(con: sqlite3.Connection) -> None:
    """The wiki pages' tables (0.8.0), beside the documents' tables; an older index gets them when it's opened."""
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS page_fts USING fts5("
                "path UNINDEXED, w UNINDEXED, excerpt UNINDEXED, body, tokenize='unicode61 remove_diacritics 2')")
    con.execute("CREATE TABLE IF NOT EXISTS page_vectors (path TEXT, w INTEGER, vec BLOB)")
    con.execute("CREATE INDEX IF NOT EXISTS page_vectors_path ON page_vectors(path)")
    con.execute("CREATE TABLE IF NOT EXISTS pages (path TEXT PRIMARY KEY, mtime REAL, size INTEGER, title TEXT, "
                "kind TEXT, summary TEXT, doc_id TEXT, vectors INTEGER)")
    con.commit()
```

In `_connect`, after the version check (inside `if has_tables:` after line 66) add:

```python
            if not con.execute("SELECT 1 FROM sqlite_master WHERE name = 'pages'").fetchone():
                _create_page_tables(con)  # an index from 0.7: no rebuild, just the new tables
```

After `counter` (line 92) add:

```python
def set_labels(con: sqlite3.Connection, doc: Doc) -> None:
    """A document's search filters after its wiki page changed them (its passages stay as they are)."""
    labels = store.effective_labels(doc)
    with con:
        con.execute("UPDATE docs SET company = ?, fund = '', doc_type = ?, date = ? WHERE doc_id = ?",
                    (str(labels.get("company", "")), str(labels.get("doc_type", "")), str(labels.get("date", "")),
                     doc.doc_id))
        _bump(con)
```

Create `core/Engine/bron/kb/wiki_index.py`:

```python
"""Wiki pages in the search database: their words and meaning, refreshed from the files' modification times on every
search (a quick look at Knowledge/**/*.md) and by `bron wiki done`."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..vault import Vault
from . import index, store, wiki
from .embed import DIM
from .passages import normal_tokens, windows
from .store import KbError

PAGES = 3  # wiki pages a search shows
TOP = 50
EXCERPT = 400


@dataclass
class PageHit:
    path: str  # vault-relative
    title: str
    kind: str
    summary: str
    excerpt: str  # the best-matching part of the page
    score: float


def _stats(vault: Vault) -> dict[str, tuple[float, int, Path]]:
    out: dict[str, tuple[float, int, Path]] = {}
    for path in wiki.page_paths(vault):
        try:
            st = path.stat()
        except OSError:
            continue
        out[path.relative_to(vault.root).as_posix()] = (st.st_mtime, st.st_size, path)
    return out


def _pieces(page: wiki.Page) -> list[tuple[str, str]]:
    """(excerpt, searchable text) per ~100-word window; the title, other names and summary go with every window."""
    head = " ".join([page.title, *page.aliases, page.summary]).strip()
    body = wiki.LINK.sub(lambda m: m.group(1), page.body)  # [[Acme Ltda|Acme]] reads as Acme Ltda
    return [(w, f"{head} {w}".strip()) for w in (windows(body) or [""])]


def _delete(con: sqlite3.Connection, rel: str) -> None:
    for table in ("pages", "page_fts", "page_vectors"):
        con.execute(f"DELETE FROM {table} WHERE path = ?", (rel,))


def _put(con: sqlite3.Connection, page: wiki.Page, embedder, *, only_with_vectors: bool = False) -> None:
    """Index one page. Without the meaning model (or embedder None) its words go in now and its vectors later."""
    pieces = _pieces(page)
    matrix = None
    if embedder is not None:
        try:
            matrix = np.asarray(embedder.embed([t for _, t in pieces]), dtype=np.float32)
        except KbError:
            matrix = None
    if only_with_vectors and matrix is None:
        return
    with con:
        _delete(con, page.rel)
        con.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?)", (page.rel, page.mtime, page.size, page.title, page.kind,
                                                                   page.summary, page.doc_id, int(matrix is not None)))
        con.executemany("INSERT INTO page_fts(path, w, excerpt, body) VALUES (?,?,?,?)",
                        [(page.rel, w, excerpt, f"{text} {' '.join(normal_tokens(text))}")
                         for w, (excerpt, text) in enumerate(pieces)])
        if matrix is not None:
            con.executemany("INSERT INTO page_vectors VALUES (?,?,?)",
                            [(page.rel, w, matrix[w].tobytes()) for w in range(len(pieces))])


def _put_broken(con: sqlite3.Connection, page: wiki.Page) -> None:
    """A page whose properties can't be read: remembered (so it isn't read on every search) but never found."""
    with con:
        _delete(con, page.rel)
        con.execute("INSERT INTO pages VALUES (?,?,?,?,?,?,?,?)", (page.rel, page.mtime, page.size, page.title, "", "", "", 1))


def refresh(vault: Vault, con: sqlite3.Connection, embedder) -> bool:
    """Bring the pages in the index up to date: new and changed pages, removed ones, and vectors still missing. Document
    pages are recorded as their documents' pages and their labels go into the search filters; index.md is rewritten
    when pages changed. True when anything changed."""
    current = _stats(vault)
    known = {r[0]: (r[1], r[2], r[3]) for r in con.execute("SELECT path, mtime, size, vectors FROM pages")}
    removed = sorted(set(known) - set(current))
    changed = [rel for rel, (mtime, size, _) in current.items() if rel not in known or known[rel][:2] != (mtime, size)]
    waiting = [rel for rel, row in known.items() if rel in current and rel not in changed and not row[2]]
    if not removed and not changed and not (waiting and embedder is not None):
        return False
    embedder = index._FailFast(embedder) if embedder is not None else None
    for rel in removed:
        with con:
            _delete(con, rel)
    pages = [wiki.read_page(vault, current[rel][2]) for rel in changed]
    for page in pages:
        if page.error:
            _put_broken(con, page)
        else:
            _put(con, page, embedder)
    for rel in (waiting if embedder is not None else []):
        page = wiki.read_page(vault, current[rel][2])
        if not page.error:
            _put(con, page, embedder, only_with_vectors=True)
    good = [p for p in pages if not p.error]
    _, touched = wiki.link_documents(vault, good, removed)
    for doc_id in touched | {p.doc_id for p in good if p.doc_id}:
        doc = store.load(vault, doc_id)
        if doc is not None and doc.status == "read":
            index.set_labels(con, doc)
    if removed or changed:
        wiki.write_index(vault)
    return True


def _keyword(con: sqlite3.Connection, query: str) -> list[tuple[str, int]]:
    from .search import _query_terms

    terms = _query_terms(query)
    if not terms:
        return []
    sql = f"SELECT path, w FROM page_fts WHERE page_fts MATCH ? ORDER BY bm25(page_fts) LIMIT {TOP}"
    return [(path, int(w)) for path, w in con.execute(sql, [" OR ".join(terms)])]


def _meaning(con: sqlite3.Connection, query: str, embedder) -> list[tuple[str, int]]:
    if embedder is None:
        return []
    rows = con.execute("SELECT path, w, vec FROM page_vectors").fetchall()
    if not rows:
        return []
    try:
        q = embedder.embed([query])[0]
    except KbError:
        return []  # the model isn't available: keyword matches still work
    matrix = np.frombuffer(b"".join(r[2] for r in rows), dtype=np.float32).reshape(len(rows), DIM)
    scores = matrix @ q
    return [(rows[i][0], int(rows[i][1])) for i in np.argsort(-scores)[:TOP] if scores[i] > 0]


def search_pages(vault: Vault, con: sqlite3.Connection, query: str, embedder, *, allowed: set[str] | None = None,
                 limit: int = PAGES) -> list[PageHit]:
    """The best pages for the question. With filters (`allowed`: the documents they leave), a document page is shown
    only when its document is allowed; other pages are matched by the question alone."""
    from .search import _fuse

    if limit <= 0:
        return []
    rows = {r[0]: r for r in con.execute("SELECT path, title, kind, summary, doc_id FROM pages WHERE kind != ''")}
    if allowed is not None:
        rows = {path: r for path, r in rows.items() if not r[4] or r[4] in allowed}
    if not rows:
        return []
    best: dict[str, tuple[int, float]] = {}
    for (path, w), score in _fuse(_keyword(con, query), _meaning(con, query, embedder)):
        if path in rows and path not in best:
            best[path] = (w, score)
            if len(best) >= limit:
                break
    hits: list[PageHit] = []
    for path, (w, score) in best.items():
        found = con.execute("SELECT excerpt FROM page_fts WHERE path = ? AND w = ?", (path, w)).fetchone()
        text = found[0] if found else ""
        excerpt = text if len(text) <= EXCERPT else text[:EXCERPT].rstrip() + "…"
        _, title, kind, summary, _ = rows[path]
        hits.append(PageHit(path, title, kind, summary, excerpt, score))
    return hits
```

`core/Engine/bron/kb/search.py`:
- add `from pathlib import Path` to the imports.
- `Hit` (lines 28-37): add the last field `wiki_page: str = ""  # the title of the document's wiki page, when it has one`.
- replace `_search` and `search` (lines 144-179) with:

```python
@dataclass
class Results:
    pages: list  # wiki_index.PageHit, best first (at most 3)
    hits: list[Hit]  # document passages, best first


class _Once:
    """Works out the question's meaning once, for both the wiki pages and the passages."""

    def __init__(self, inner):
        self._inner = inner
        self._seen: dict = {}

    @property
    def model(self):
        return getattr(self._inner, "model", "")

    def embed(self, texts):
        key = tuple(texts)
        if key not in self._seen:
            self._seen[key] = self._inner.embed(texts)
        return self._seen[key]


def _find(vault, query, embedder, company, doc_type, after, before, limit, pages_only) -> Results:
    from . import wiki_index

    embedder = _Once(embedder)
    index.ensure(vault, embedder)
    con = index.open(vault)
    try:
        try:
            wiki_index.refresh(vault, con, embedder)
        except (OSError, UnicodeDecodeError) as exc:  # a page Bron can't open: the rest still works
            from .ingest import _log

            _log(vault, "refreshing the wiki pages", exc)
        filtering = any((company, doc_type, after, before))
        allowed = _filtered(con, company, doc_type, after, before) if filtering else None
        pages = wiki_index.search_pages(vault, con, query, embedder, allowed=allowed)
        if pages_only or limit <= 0 or (allowed is not None and not allowed):
            return Results(pages, [])
        keyword = _keyword(con, query, allowed)
        meaning = _meaning(vault, con, query, allowed, embedder)
    finally:
        con.close()
    hits: list[Hit] = []
    docs: dict[str, tuple] = {}
    for (doc_id, n), score in _fuse(keyword, meaning):
        if doc_id not in docs:
            doc = store.load(vault, doc_id)
            docs[doc_id] = (doc, store.passages(vault, doc_id)) if doc else (None, [])
        doc, passages = docs[doc_id]
        if doc is None or doc.status != "read" or n >= len(passages):
            continue  # the index is out of step with the store (or the last reading failed); skip
        p = passages[n]
        hits.append(Hit(doc_id, doc.name, store.effective_labels(doc), p.get("page") or 0, str(p.get("section") or ""),
                        doc.source, str(p.get("text", "")), score, Path(doc.page).stem if doc.page else ""))
        if len(hits) >= limit:
            break
    return Results(pages, hits)


def find(vault: Vault, query: str, *, embedder, company: str = "", doc_type: str = "", after: str = "",
         before: str = "", limit: int = 8, pages_only: bool = False) -> Results:
    """Wiki pages (at most 3), then document passages (at most `limit`)."""
    return index.with_recovery(
        vault, embedder, lambda: _find(vault, query, embedder, company, doc_type, after, before, limit, pages_only))


def search(vault: Vault, query: str, *, embedder, company: str = "", doc_type: str = "",
           after: str = "", before: str = "", limit: int = 8) -> list[Hit]:
    return find(vault, query, embedder=embedder, company=company, doc_type=doc_type, after=after, before=before,
                limit=limit).hits
```

- in `render` (lines 182-194) replace the `blocks.append(...)` line with:

```python
        page_line = f"\nPage: [[{h.wiki_page}]]" if h.wiki_page else ""
        blocks.append(f"{i}. {head}\n{h.source}{page_line}\n{text}")
```

- after `render` add:

```python
def render_pages(pages) -> str:
    blocks = []
    for i, p in enumerate(pages, start=1):
        head = f"{i}. [[{p.title}]]" + (f" — {p.summary}" if p.summary else "")
        blocks.append(f"{head}\n{p.path}\n{p.excerpt}")
    return "\n\n".join(blocks)


def render_all(results: Results) -> str:
    """Wiki pages first, then the document passages; only passages look exactly as before."""
    if results.pages and results.hits:
        return "Wiki pages:\n" + render_pages(results.pages) + "\n\nDocument passages:\n" + render(results.hits)
    if results.pages:
        return "Wiki pages:\n" + render_pages(results.pages)
    return render(results.hits)
```

`core/Engine/bron/kb/service.py` — replace `_answer`'s search block (lines 125-133) with:

```python
    probe = Probe(embedder)
    try:
        found = search.find(vault, str(request.get("query", "")), embedder=probe, limit=int(request.get("limit", 8)),
                            pages_only=bool(request.get("pages_only")),
                            **{k: str(request.get(k) or "") for k in FILTERS})
    except KbError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # the helper must stay up whatever one search does
        return {"error": f"The search failed ({type(exc).__name__})."}
    return {"hits": [dataclasses.asdict(h) for h in found.hits], "pages": [dataclasses.asdict(p) for p in found.pages],
            "keyword_only": probe.failed}
```

`core/Engine/bron/kb/cli.py`:
- search parser (lines 33-39): replace the `--company` line with

```python
    search.add_argument("--organisation", "--company", dest="company", default="",
                        help="the organisation a document is mainly about (--company works too)")
```

  and add `search.add_argument("--pages-only", action="store_true", help="only wiki pages, no document passages")`.
- list parser (line 46): `listing.add_argument("--organisation", "--company", dest="company", default="")`.
- replace `_search` (lines 124-144) with:

```python
def _search(args, vault) -> int:
    from . import embed, search, service, wiki_index

    request = {"query": args.query, "company": args.company, "doc_type": args.doc_type, "after": args.after,
               "before": args.before, "limit": args.limit, "pages_only": args.pages_only}
    reply = service.query(vault, request)
    if reply is not None and "error" in reply:
        print(reply["error"])
        return 1
    if reply is not None:
        found = search.Results([wiki_index.PageHit(**p) for p in reply.get("pages", [])],
                               [search.Hit(**h) for h in reply.get("hits", [])])
        note = bool(reply.get("keyword_only"))
    else:
        probe = service.Probe(embed.get(vault))
        found = search.find(vault, args.query, embedder=probe, company=args.company, doc_type=args.doc_type,
                            after=args.after, before=args.before, limit=args.limit, pages_only=args.pages_only)
        note = probe.failed
    if note:
        print(KEYWORD_NOTE)
    print(search.render_all(found) if (found.pages or found.hits) else NOTHING)
    return 0
```

- [ ] **Step 4: Run the tests**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki_search.py tests/test_kb_search.py tests/test_kb_service.py tests/test_kb_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Run everything and commit**

Run: `uv run --project core/Engine pytest tests -q` — Expected: PASS.

```bash
git add core/Engine/bron/kb/index.py core/Engine/bron/kb/wiki_index.py core/Engine/bron/kb/search.py core/Engine/bron/kb/service.py core/Engine/bron/kb/cli.py tests/test_kb_wiki_search.py tests/test_kb_service.py
git commit -m "Search wiki pages and passages together; --pages-only, --organisation

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Mechanical checks, `bron wiki done` and `bron wiki check`, and the health check (spec §5.3, §7.1, §10)

**Files:**
- Create: `core/Engine/bron/kb/wiki_check.py`, `core/Engine/bron/kb/wiki_done.py`, `core/Engine/bron/kb/wiki_cli.py`
- Modify: `core/Engine/bron/kb/health.py:29-39` (`issues`)
- Modify: `core/Engine/bron/cli.py:45-51` (register `wiki`), `:128-131` (dispatch)
- Test: `tests/test_kb_wiki_check.py`, `tests/test_kb_wiki_done.py` (create)

**Interfaces:**
- Consumes: `wiki.all_pages/page_paths/read_page/link_documents/write_index/append_log/parse_log_text/name_of/property_text` (Task 4), `wiki_index.refresh` (Task 5), `index.open/with_recovery/_Lazy`, `store.all_docs/exists/kb_dir`, `tools.missing`, `memory.facts.fold`, `model.Issue`.
- Produces:
  - `wiki_check.MAX_CHARS = 30_000`, `wiki_check.ORDER` (codes, in report order), `wiki_check.TITLES` (code → plain heading), `wiki_check.Problem(code: str, where: str, text: str)`.
  - `wiki_check.run(vault, *, only: set[str] | None = None, pages: list[wiki.Page] | None = None) -> list[Problem]` — `only`: limit page checks to these vault-relative paths and skip the store-wide "read but no page yet" check.
  - `wiki_check.render(problems, *, everything: bool) -> str`.
  - `wiki_done.STATE = "wiki-state.json"`; `wiki_done.done(vault, *, log_text: str = "") -> str` (the text to print; never raises for a bad page).
  - `wiki_cli.add_parser(sub)`, `wiki_cli.handle(args, vault) -> int`; commands `bron wiki done [--log '<kind> | <text>']`, `bron wiki check [--all]`.
  - Health check codes `wiki.<code>` (warnings), message `"<title> (<count>): <first three>; …and N more. Run `bron wiki check --all` for the list."`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kb_wiki_check.py`:

```python
"""The mechanical checks of the wiki: free, no model."""
from bron.check import run_checks
from bron.cli import build_parser
from bron.kb import wiki_check, wiki_cli
from bron.loader import load
from kbkit import stored_doc, write_page


def codes(vault, **kw):
    return [(p.code, p.where) for p in wiki_check.run(vault, **kw)]


def org(vault, name, body="", **meta):
    return write_page(vault, f"Organisations/{name}.md", body, **{"type": "organisation", "summary": f"About {name}", **meta})


def test_a_tidy_wiki_has_no_problems(vault):
    doc = stored_doc(vault, "lease.pdf", ["Lease text"])
    write_page(vault, "Documents/Lease (2025-03-01).md", "Tenant: [[Harbor Bakery]] (p. 1).\n", type="document",
               summary="A lease", doc=doc.doc_id, organisation="[[Harbor Bakery]]")
    org(vault, "Harbor Bakery", "Rents a shop (see [[Lease (2025-03-01)]], p. 1).\n")
    assert wiki_check.run(vault) == []
    assert wiki_check.render([], everything=False) == "The wiki has no problems Bron can find."


def test_links_to_pages_that_do_not_exist(vault):
    org(vault, "Acme Ltda", "Owns [[Nobody Inc]] and [[Projects/Unsorted/Plan]] and [[Settings]], see [[Acme Ltda]].\n")
    found = wiki_check.run(vault)
    broken = [p.text for p in found if p.code == "broken-link"]
    assert broken == ["Acme Ltda: links to [[Nobody Inc]], which doesn't exist.",
                      "Acme Ltda: links to [[Projects/Unsorted/Plan]], which doesn't exist."]  # System/Settings.md exists


def test_pages_nothing_links_to(vault):
    org(vault, "Acme Ltda", "See [[Beta Ltda]].\n")
    org(vault, "Beta Ltda", "See [[Beta Ltda]] itself.\n")
    index_md = vault.knowledge_dir / "index.md"
    index_md.write_text(index_md.read_text(encoding="utf-8") + "- [[Acme Ltda]]\n", encoding="utf-8")
    assert codes(vault) == [("orphan", "Knowledge/Organisations/Acme Ltda.md")]  # index.md and self-links don't count


def test_missing_type_or_summary_and_broken_properties(vault):
    write_page(vault, "Topics/Office move.md", "Moving in May.\n", summary="Moving")
    write_page(vault, "Topics/Budget.md", "See [[Office move]].\n")
    (vault.knowledge_dir / "Topics" / "Broken.md").write_text("---\ntype: [x\n---\nSee [[Budget]].\n", encoding="utf-8")
    texts = {p.code: [] for p in wiki_check.run(vault)}
    for p in wiki_check.run(vault):
        texts[p.code].append(p.text)
    assert texts["missing-properties"] == ["Budget: no type or summary in its properties.",
                                           "Office move: no type in its properties."]
    assert texts["bad-properties"][0].startswith("Broken: its properties can't be read (the properties block is not valid YAML")


def test_documents_without_a_page_and_pages_without_a_document(vault):
    stored_doc(vault, "invoice.pdf", ["Invoice text"])
    write_page(vault, "Documents/Old lease.md", "Gone.\n", type="document", summary="An old lease", doc="0000000000000000")
    found = {p.code: p.text for p in wiki_check.run(vault)}
    assert found["no-page-yet"].startswith("invoice.pdf (doc ") and found["no-page-yet"].endswith("): read but no page yet.")
    assert found["unknown-doc"] == ("Old lease: its doc 0000000000000000 isn't in the knowledge base "
                                    "(forgotten, or never read).")
    assert "no-page-yet" not in [p.code for p in wiki_check.run(vault, only={"Knowledge/Documents/Old lease.md"})]


def test_probable_duplicates_fold_case_accents_and_company_suffixes(vault):
    org(vault, "Ágora Ltda.", "See [[Agora]].\n")
    org(vault, "Agora", "See [[Ágora Ltda.]] and [[Acme Holdings]].\n")
    org(vault, "Acme Holdings", "See [[Agora]]; also [[Northwind]].\n", aliases=["Northwind S.A."])
    org(vault, "Northwind", "See [[Acme Holdings]].\n")
    write_page(vault, "Topics/Agora.md", "See [[Agora]].\n", type="topic", summary="A different kind of page")
    dups = [p.text for p in wiki_check.run(vault) if p.code == "duplicate"]
    assert dups == ["[[Acme Holdings]] and [[Northwind]] look like the same page.",
                    "[[Agora]] and [[Ágora Ltda.]] look like the same page."]


def test_pages_over_30000_characters(vault):
    org(vault, "Acme Ltda", "word " * 6001 + "[[Acme Ltda]]\n")
    write_page(vault, "Topics/Notes.md", "[[Acme Ltda]]\n", type="topic", summary="Notes")
    org(vault, "Beta", "[[Notes]]\n")
    found = [p.text for p in wiki_check.run(vault) if p.code == "too-long"]
    assert found == ["Acme Ltda: 30,019 characters; split it into smaller pages."]


def test_the_report_shows_three_of_each_unless_all(vault):
    for i in range(5):
        org(vault, f"Org {i}", f"Links to [[Missing {i}]].\n")
    short = wiki_check.render(wiki_check.run(vault), everything=False)
    assert "Links to pages that don't exist (5):" in short and short.count("which doesn't exist") == 3
    assert "…and 2 more; run `.bron/bin/bron wiki check --all`." in short
    full = wiki_check.render(wiki_check.run(vault), everything=True)
    assert full.count("which doesn't exist") == 5 and "…and" not in full


def test_wiki_check_command(vault, capsys):
    org(vault, "Acme Ltda", "See [[Nobody]].\n")
    assert wiki_cli.handle(build_parser().parse_args(["wiki", "check", "--all"]), vault) == 0
    assert "Acme Ltda: links to [[Nobody]], which doesn't exist." in capsys.readouterr().out


def test_the_health_check_shows_counts_and_the_first_three(vault):
    for i in range(4):
        org(vault, f"Org {i}", f"Links to [[Missing {i}]] and [[Org {(i + 1) % 4}]].\n")
    issue = next(i for i in run_checks(load(vault)) if i.code == "wiki.broken-link")
    assert issue.level == "warning" and issue.message.startswith("Links to pages that don't exist (4): Org 0: links to")
    assert "…and 1 more" in issue.message and "bron wiki check --all" in issue.message
```

Create `tests/test_kb_wiki_done.py`:

```python
"""`bron wiki done`: after an agent wrote pages."""
import json
import os
import time

from bron.cli import build_parser
from bron.kb import index, search, store, wiki_cli
from bron.kb.wiki_done import done
from kbkit import fake_embed, later, stored_doc, write_page

LEASE = "Documents/Office lease (2025-03-01).md"


def log(vault):
    return (vault.knowledge_dir / "log.md").read_text(encoding="utf-8")


def write_lease(vault, doc, extra=""):
    return write_page(vault, LEASE, f"Tenant: [[Harbor Bakery]]; rent USD 4,200.00 (p. 2).{extra}\n", type="document",
                      summary="Lease of the shop", doc=doc.doc_id, source="/docs/lease.pdf",
                      organisation="[[Harbor Bakery]]", doc_type="contract", date="2025-03-01")


def write_bakery(vault):
    return write_page(vault, "Organisations/Harbor Bakery.md", "Rents shop 4 (see [[Office lease (2025-03-01)]], p. 1).\n",
                      type="organisation", summary="A bakery")


def test_done_records_indexes_logs_and_rewrites_the_index(vault):
    doc = stored_doc(vault, "lease.pdf", ["Lease text", "The monthly rent is USD 4,200.00."], index_it=True)
    write_lease(vault, doc)
    write_bakery(vault)
    out = done(vault)
    assert out == "Wiki updated: 2 pages (2 new)."
    assert store.load(vault, doc.doc_id).page == "Knowledge/" + LEASE
    assert store.effective_labels(store.load(vault, doc.doc_id))["company"] == "Harbor Bakery"
    text = log(vault)
    assert "] ingest | [[Office lease (2025-03-01)]]\n" in text and "] update | [[Harbor Bakery]]\n" in text
    assert "- [[Harbor Bakery]] — A bakery (1 source, updated " in (vault.knowledge_dir / "index.md").read_text(encoding="utf-8")
    con = index.open(vault)
    try:
        assert con.execute("SELECT COUNT(*) FROM pages WHERE kind != ''").fetchone()[0] == 2
        assert con.execute("SELECT company FROM docs WHERE doc_id = ?", (doc.doc_id,)).fetchone()[0] == "Harbor Bakery"
    finally:
        con.close()
    assert json.loads((store.kb_dir(vault) / "wiki-state.json").read_text())["pages"]
    found = search.find(vault, "rent", embedder=fake_embed, company="harbor")
    assert found.pages and found.hits  # the next search adds the meaning vectors and finds both


def test_nothing_changed_and_log_lines(vault):
    assert done(vault) == "Nothing changed in the wiki."
    assert done(vault, log_text="save | Rent history") == "Nothing changed in the wiki."
    assert done(vault, log_text="checked everything") == "Nothing changed in the wiki."
    text = log(vault)
    assert "] save | Rent history\n" in text and "] update | checked everything\n" in text


def test_a_search_in_between_does_not_swallow_the_log(vault):
    doc = stored_doc(vault, "lease.pdf", ["Lease text"], index_it=True)
    write_lease(vault, doc)
    write_bakery(vault)
    search.find(vault, "lease", embedder=fake_embed)  # the search indexes the new pages first
    assert done(vault) == "Wiki updated: 2 pages (2 new)."
    assert "] ingest | [[Office lease (2025-03-01)]]\n" in log(vault)


def test_problems_in_what_changed_are_listed_and_fixing_them_clears_them(vault):
    doc = stored_doc(vault, "lease.pdf", ["Lease text"])
    write_lease(vault, doc)
    out = done(vault)
    assert out.splitlines()[0] == "Wiki updated: 1 page (1 new)."
    assert "- Office lease (2025-03-01): links to [[Harbor Bakery]], which doesn't exist." in out
    assert out.splitlines()[-1] == "Fix these, then run `.bron/bin/bron wiki done` again."
    write_bakery(vault)
    assert done(vault) == "Wiki updated: 1 page (1 new)."  # the lease page was checked again: its link works now


def test_a_page_naming_an_unknown_document_is_reported(vault):
    write_page(vault, "Documents/Old lease.md", "See [[Old lease]].\n", type="document", summary="An old lease",
               doc="0000000000000000")
    out = done(vault)
    assert "- Old lease: its doc 0000000000000000 isn't in the knowledge base (forgotten, or never read)." in out


def test_a_page_with_broken_properties_is_reported_and_the_rest_carry_on(vault):
    doc = stored_doc(vault, "lease.pdf", ["Lease text"], index_it=True)
    write_lease(vault, doc)
    write_bakery(vault)
    (vault.knowledge_dir / "Topics" / "Broken.md").write_text("---\ntype: [x\n---\nSee [[Harbor Bakery]].\n", encoding="utf-8")
    out = done(vault)
    assert out.startswith("Wiki updated: 3 pages (3 new).")
    assert "- Broken: its properties can't be read (the properties block is not valid YAML" in out
    assert "[[Broken]]" not in (vault.knowledge_dir / "index.md").read_text(encoding="utf-8")
    assert "] ingest | [[Office lease (2025-03-01)]]\n" in log(vault)
    assert store.load(vault, doc.doc_id).page == "Knowledge/" + LEASE


def test_a_document_read_again_is_logged_as_an_ingest(vault):
    doc = stored_doc(vault, "lease.pdf", ["Lease text"])
    path = write_lease(vault, doc)
    write_bakery(vault)
    done(vault)
    pages_file = store.kb_dir(vault) / "docs" / doc.doc_id / "pages.jsonl"
    store.save(vault, store.load(vault, doc.doc_id), ["Lease text, amended"], [])  # `bron kb add` read it again
    t = time.time() + 10
    os.utime(pages_file, (t, t))
    write_lease(vault, doc, " Previously USD 4,000.00.")
    later(path, 20)
    done(vault)
    assert "] ingest | [[Office lease (2025-03-01)]] (read again)\n" in log(vault)


def test_a_removed_page_is_logged_and_forgotten_by_its_document(vault):
    doc = stored_doc(vault, "lease.pdf", ["Lease text"])
    path = write_lease(vault, doc)
    write_bakery(vault)
    done(vault)
    path.unlink()
    out = done(vault)
    assert out.startswith("Wiki updated: 0 pages (0 new).") and "removed: Office lease (2025-03-01)" in log(vault)
    assert store.load(vault, doc.doc_id).page == ""


def test_the_wiki_done_command(vault, capsys):
    doc = stored_doc(vault, "lease.pdf", ["Lease text"])
    write_lease(vault, doc)
    write_bakery(vault)
    args = build_parser().parse_args(["wiki", "done", "--log", "check | 2 pages checked"])
    assert wiki_cli.handle(args, vault) == 0
    assert capsys.readouterr().out.strip() == "Wiki updated: 2 pages (2 new)."
    assert "] check | 2 pages checked\n" in log(vault)


def test_an_unexpected_error_is_one_plain_line(vault, capsys, monkeypatch):
    import bron.kb.wiki_done as wiki_done

    monkeypatch.setattr(wiki_done, "done", lambda vault, log_text="": (_ for _ in ()).throw(ValueError("deep inside")))
    assert wiki_cli.handle(build_parser().parse_args(["wiki", "done"]), vault) == 1
    assert capsys.readouterr().out.strip() == ("Something went wrong in the wiki (ValueError). "
                                               "Details are in .bron/logs/kb-errors.log.")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki_check.py tests/test_kb_wiki_done.py -q`
Expected: FAIL — `ImportError: cannot import name 'wiki_check'` / `'wiki_cli'`.

- [ ] **Step 3: Implement**

Create `core/Engine/bron/kb/wiki_check.py`:

```python
"""Mechanical checks of the wiki (free: no model). Links to pages that don't exist, pages nothing links to, pages
missing `type` or `summary`, documents read without a page, pages naming a document Bron doesn't have, probable
duplicates, pages too long to read in one go, and pages whose properties can't be read."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from ..memory.facts import fold
from ..vault import Vault
from . import store, wiki

MAX_CHARS = 30_000
SUFFIXES = {"ltda", "llc", "inc", "sa", "lp"}  # folded away when looking for duplicates ("Acme Ltda." = "Acme")
ORDER = ("bad-properties", "broken-link", "missing-properties", "unknown-doc", "no-page-yet", "duplicate", "orphan",
         "too-long")
TITLES = {
    "bad-properties": "Pages whose properties can't be read",
    "broken-link": "Links to pages that don't exist",
    "missing-properties": "Pages missing type or summary",
    "unknown-doc": "Document pages whose document Bron doesn't have",
    "no-page-yet": "Documents read but no page yet",
    "duplicate": "Pages that look like duplicates",
    "orphan": "Pages nothing links to",
    "too-long": "Pages over 30,000 characters",
}


@dataclass
class Problem:
    code: str
    where: str  # the page's vault-relative path, or the document's id
    text: str  # one plain sentence


def _targets(vault: Vault) -> set[str]:
    """Every name a link can point to: each file's name and vault-relative path, with and without .md, folded."""
    names: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(vault.root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        here = Path(dirpath).relative_to(vault.root)
        for name in filenames:
            if name.startswith("."):
                continue
            rel = (here / name).as_posix()
            names |= {name.casefold(), rel.casefold()}
            if name.endswith(".md"):
                names |= {name[:-3].casefold(), rel[:-3].casefold()}
    return names


def _exists(target: str, names: set[str]) -> bool:
    folded = target.strip().strip("/").casefold()
    return folded in names


def _key(name: str) -> str:
    """A name folded for spotting duplicates: no case, accents, punctuation or company suffix."""
    words = re.findall(r"\w+", fold(name).replace(".", ""))
    while words and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words)


def _duplicates(pages: list[wiki.Page], mine) -> list[Problem]:
    groups: dict[tuple[str, str], dict[str, wiki.Page]] = {}
    for page in pages:
        for name in {page.title, *page.aliases}:
            key = _key(name)
            if key:
                groups.setdefault((page.kind, key), {})[page.rel] = page
    out: list[Problem] = []
    seen: set[tuple[str, str]] = set()
    for group in groups.values():
        same = sorted(group.values(), key=lambda p: p.title.casefold())
        for i, a in enumerate(same):
            for b in same[i + 1:]:
                pair = (a.rel, b.rel)
                if pair in seen or not (mine(a) or mine(b)):
                    continue
                seen.add(pair)
                out.append(Problem("duplicate", a.rel, f"[[{a.title}]] and [[{b.title}]] look like the same page."))
    return out


def run(vault: Vault, *, only: set[str] | None = None, pages: list[wiki.Page] | None = None) -> list[Problem]:
    """Every problem, or (only=) those of these pages: `wiki done` checks the pages that changed and the pages linking
    to them, and leaves out the store-wide "read but no page yet" check."""
    pages = wiki.all_pages(vault) if pages is None else pages
    good = [p for p in pages if not p.error]

    def mine(page: wiki.Page) -> bool:
        return only is None or page.rel in only

    out: list[Problem] = [Problem("bad-properties", p.rel, f"{p.title}: its properties can't be read ({p.error}).")
                          for p in pages if p.error and mine(p)]
    names = _targets(vault)
    linked: dict[str, set[str]] = {}  # page name → the pages that link to it
    for page in good:
        for target in page.links():
            linked.setdefault(wiki.name_of(target), set()).add(page.rel)
            if mine(page) and not _exists(target, names):
                out.append(Problem("broken-link", page.rel, f"{page.title}: links to [[{target}]], which doesn't exist."))
    for page in good:
        if not mine(page):
            continue
        missing = [key for key in ("type", "summary") if not wiki.property_text(page.meta.get(key))]
        if missing:
            out.append(Problem("missing-properties", page.rel,
                               f"{page.title}: no {' or '.join(missing)} in its properties."))
        if page.doc_id and not store.exists(vault, page.doc_id):
            out.append(Problem("unknown-doc", page.rel, f"{page.title}: its doc {page.doc_id} isn't in the knowledge "
                                                        "base (forgotten, or never read)."))
        if len(page.body) > MAX_CHARS:
            out.append(Problem("too-long", page.rel,
                               f"{page.title}: {len(page.body):,} characters; split it into smaller pages."))
        if not (linked.get(wiki.name_of(page.title), set()) - {page.rel}):
            out.append(Problem("orphan", page.rel, f"{page.title}: no other page links to it."))
    out += _duplicates(good, mine)
    if only is None:
        with_pages = {p.doc_id for p in good if p.doc_id}
        for doc in store.all_docs(vault):
            if doc.status == "read" and doc.doc_id not in with_pages:
                out.append(Problem("no-page-yet", doc.doc_id, f"{doc.name} (doc {doc.doc_id}): read but no page yet."))
    return sorted(out, key=lambda p: (ORDER.index(p.code), p.where, p.text))


def render(problems: list[Problem], *, everything: bool) -> str:
    if not problems:
        return "The wiki has no problems Bron can find."
    lines: list[str] = []
    for code in ORDER:
        found = [p for p in problems if p.code == code]
        if not found:
            continue
        shown = found if everything else found[:3]
        lines.append(f"{TITLES[code]} ({len(found)}):")
        lines += [f"- {p.text}" for p in shown]
        if len(found) > len(shown):
            lines.append(f"- …and {len(found) - len(shown)} more; run `.bron/bin/bron wiki check --all`.")
    return "\n".join(lines)
```

Create `core/Engine/bron/kb/wiki_done.py`:

```python
"""`bron wiki done`: run by an agent after writing pages. It records document pages, indexes the changed pages, rewrites
index.md, logs what happened and checks what changed. One bad page never stops the rest."""
from __future__ import annotations

from pathlib import Path

from .. import statefile
from ..vault import Vault
from . import store, wiki, wiki_check

STATE = "wiki-state.json"  # what `wiki done` saw last time (searches keep their own record in index.db)


def _state_path(vault: Vault) -> Path:
    return store.kb_dir(vault) / STATE


def _read_stamp(vault: Vault, doc_id: str) -> float:
    """When the document's text was last saved (it changes only when it is read)."""
    try:
        return (store.kb_dir(vault) / "docs" / doc_id / "pages.jsonl").stat().st_mtime
    except OSError:
        return 0.0


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _index(vault: Vault) -> None:
    """The changed pages' words go into the search database now; the next search adds their meaning."""
    from . import tools

    if tools.missing():
        return  # the first search after setup indexes them
    from . import index, wiki_index
    from .store import KbError

    def run():
        con = index.open(vault)
        try:
            wiki_index.refresh(vault, con, None)
        finally:
            con.close()

    try:
        index.with_recovery(vault, index._Lazy(vault), run)
    except KbError:
        pass  # busy: the next search catches up


def done(vault: Vault, *, log_text: str = "") -> str:
    state = statefile.read_json(_state_path(vault), {})
    before = state.get("pages") if isinstance(state.get("pages"), dict) else {}
    reads = state.get("docs") if isinstance(state.get("docs"), dict) else {}
    pages = wiki.all_pages(vault)
    now = {p.rel: [p.mtime, p.size] for p in pages}
    changed = [p for p in pages if before.get(p.rel) != now[p.rel]]
    removed = sorted(set(before) - set(now))
    new = [p for p in changed if p.rel not in before]
    wiki.link_documents(vault, changed, removed)
    _index(vault)
    wiki.write_index(vault, pages)
    entries: list[tuple[str, str]] = []
    others: list[wiki.Page] = []
    for page in sorted(changed, key=lambda p: p.title.casefold()):
        if page.error:
            continue
        if page.is_document and page.rel not in before:
            entries.append(("ingest", f"[[{page.title}]]"))
        elif page.is_document and page.doc_id in reads and reads[page.doc_id] != _read_stamp(vault, page.doc_id):
            entries.append(("ingest", f"[[{page.title}]] (read again)"))
        else:
            others.append(page)
    if others or removed:
        text = ", ".join(f"[[{p.title}]]" for p in others)
        if removed:
            text += ("; " if text else "") + "removed: " + ", ".join(Path(rel).stem for rel in removed)
        entries.append(("update", text))
    if log_text.strip():
        entries.append(wiki.parse_log_text(log_text))
    wiki.append_log(vault, entries)
    scope = {p.rel for p in changed}
    names = {wiki.name_of(p.title) for p in changed} | {wiki.name_of(Path(rel).stem) for rel in removed}
    scope |= {p.rel for p in pages if not p.error and any(wiki.name_of(t) in names for t in p.links())}
    problems = wiki_check.run(vault, only=scope, pages=pages) if scope else []
    docs = {p.doc_id: _read_stamp(vault, p.doc_id) for p in pages
            if not p.error and p.doc_id and store.exists(vault, p.doc_id)}
    statefile.write_json(_state_path(vault), {"pages": now, "docs": docs})
    if not changed and not removed:
        head = "Nothing changed in the wiki."
    else:
        head = f"Wiki updated: {_plural(len(changed), 'page')} ({len(new)} new)."
    if not problems:
        return head
    return "\n".join([head, *[f"- {p.text}" for p in problems],
                      "Fix these, then run `.bron/bin/bron wiki done` again."])
```

Create `core/Engine/bron/kb/wiki_cli.py`:

```python
"""`bron wiki …`: what agents run after writing wiki pages, and the mechanical checks."""
from __future__ import annotations

import time
import traceback

CRASHED = "Something went wrong in the wiki ({}). Details are in .bron/logs/kb-errors.log."


def add_parser(sub) -> None:
    parser = sub.add_parser("wiki", help="the wiki in Knowledge/: finish after writing pages, and check it")
    commands = parser.add_subparsers(dest="wiki_command", required=True)
    done = commands.add_parser("done", help="after writing pages: index them, update index.md and log.md, check them")
    done.add_argument("--log", default="", help="a line for log.md, like 'save | <title>' or 'check | <what you found>'")
    check = commands.add_parser("check", help="links, orphans, missing properties, documents without a page, duplicates")
    check.add_argument("--all", action="store_true", help="list every problem, not just the first three of each kind")


def _log_crash(vault, args, exc: BaseException) -> None:
    try:
        path = vault.bron_dir / "logs" / "kb-errors.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} bron wiki {args.wiki_command}: "
                     f"{''.join(traceback.format_exception(exc))}\n")
    except OSError:
        pass


def handle(args, vault) -> int:
    from .store import KbError

    try:
        if args.wiki_command == "done":
            from . import wiki_done

            print(wiki_done.done(vault, log_text=args.log))
            return 0
        if args.wiki_command == "check":
            from . import wiki_check

            print(wiki_check.render(wiki_check.run(vault), everything=args.all))
            return 0
    except KbError as exc:
        print(exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - never a traceback for the user (Ctrl-C still stops it)
        _log_crash(vault, args, exc)
        print(CRASHED.format(exc.__class__.__name__))
        return 1
    print("Not available yet.")
    return 1
```

`core/Engine/bron/kb/health.py` — at the end of `issues` (before `return out`, line 39) add:

```python
    try:
        from . import wiki_check

        problems = wiki_check.run(vault)
    except Exception:  # noqa: BLE001 - the wiki never breaks the health check
        problems = []
    for code in (wiki_check.ORDER if problems else ()):
        found = [p for p in problems if p.code == code]
        if found:
            first = "; ".join(p.text.rstrip(".") for p in found[:3])
            more = f"; …and {len(found) - 3} more" if len(found) > 3 else ""
            out.append(Issue("warning", f"wiki.{code}", f"{wiki_check.TITLES[code]} ({len(found)}): {first}{more}. "
                                                         "Run `bron wiki check --all` for the list."))
```

`core/Engine/bron/cli.py`:
- line 46: `from .kb import cli as kb_cli, wiki_cli`; after `kb_cli.add_parser(sub)` (line 51) add `wiki_cli.add_parser(sub)`.
- after the `kb` dispatch (lines 128-131) add:

```python
    if args.command == "wiki":
        from .kb import wiki_cli

        return wiki_cli.handle(args, vault)
```

- [ ] **Step 4: Run the tests**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki_check.py tests/test_kb_wiki_done.py tests/test_kb_health.py tests/test_check.py tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Run everything and commit**

Run: `uv run --project core/Engine pytest tests -q` — Expected: PASS.

```bash
git add core/Engine/bron/kb/wiki_check.py core/Engine/bron/kb/wiki_done.py core/Engine/bron/kb/wiki_cli.py core/Engine/bron/kb/health.py core/Engine/bron/cli.py tests/test_kb_wiki_check.py tests/test_kb_wiki_done.py
git commit -m "Add bron wiki done and bron wiki check; wiki problems in the health check

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The background wiki run inside the kb job — one writer at a time, a queue, resume, cancel (spec §5.2, §10)

**Files:**
- Create: `core/Engine/bron/kb/wiki_run.py`
- Modify: `core/Engine/bron/kb/jobs.py:32-45` (`Job`), `:56-66` (paths), `:92-115` (`_prune`, `create`), `:120-143` (`_hold_lock`, `_beat`), `:172-198` (`runner_active`, `stalled`), `:236-257` (`_finish`, `cancel`), `:310-331` (`run`), `:371-394` (`status_lines`); add `create_wiki`, `wiki_pending`, `wiki_active`, `_needs_pages`, `_write_wiki`, `_write_one`, `_wiki_failed`
- Modify: `tests/kbkit.py` (add `FakeTicketRunner`)
- Modify: `tests/test_kb_ingest.py:312-319` (`test_status_lines` wording), `tests/test_kb_cli.py:285` and `:344` (idle wording)
- Test: `tests/test_kb_wiki_run.py` (create)

**Interfaces:**
- Consumes: `tickets.new_ticket(vault, *, title, assignee, request, requested_by="you")` (`core/Engine/bron/tickets.py:104-146`), `runner.run_ticket(vault, ticket_id) -> RunOutcome(ticket_id, status, cli, message)` (`core/Engine/bron/runner.py:314-428`), `cfg.default_agent` (`core/Engine/bron/loader.py:37-39`), `store.load` / `Doc.page` (Task 4), `notices.add`.
- Produces:
  - `wiki_run.SECONDS_PER_DOC = 60`; `wiki_run.title(label: str, count: int) -> str`; `wiki_run.request(vault, doc_ids: list[str], report: str = "") -> str`; `wiki_run.start_ticket(vault, cfg, job) -> str` (ticket id; raises `KbError` when there's no default agent).
  - `jobs.Job` new fields: `wiki: bool = False`, `wiki_status: str = ""` (`waiting|writing|done|failed|cancelled`), `wiki_docs: list[str]`, `wiki_since: str = ""`, `wiki_attempts: int = 0`, `ticket: str = ""`, `label: str = ""`, `report: str = ""`.
  - `jobs.create(vault, items, *, failed=(), again=False, wiki=False, label="") -> Job`; `jobs.create_wiki(vault, doc_ids: list[str], *, label="") -> Job`.
  - `jobs.wiki_pending(vault) -> list[Job]`; `jobs.runner_active(vault, *, wiki: bool = False) -> bool`; `jobs.wiki_active(vault) -> bool`.
  - `jobs.run(vault, job_id, *, embedder=None, readers_ocr=None, model_call=None, cfg=None, run_ticket=None) -> bool` — reads every waiting job (reader lock), lets go of the reader lock, then writes every waiting wiki run (wiki lock); `run_ticket=None` means `bron.runner.run_ticket`.
  - `jobs.IDLE = "Nothing is being read."`; `jobs.status_lines(vault)` gains wiki lines; `jobs.cancel(vault)` also cancels waiting wiki runs; `jobs.stalled(vault)` also returns wiki runs nobody is writing.
  - kbkit: `FakeTicketRunner(status="in-review", message="", write=None)` — callable like `run_ticket(vault, ticket_id, **kw)`; `.calls: list[str]`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/kbkit.py`:

```python
class FakeTicketRunner:
    """Stand-in for runner.run_ticket: records the tickets it runs, calls write(vault, ticket) first (to write pages,
    say), then settles the ticket like a real run: in-review with a summary, or `status` with `message`."""

    def __init__(self, status: str = "in-review", message: str = "", write=None):
        self.status, self.message, self.write = status, message, write
        self.calls: list[str] = []

    def __call__(self, vault, ticket_id, **kw):
        from bron.runner import RunOutcome
        from bron.tickets import editing, find_ticket, load_ticket, set_result, set_status

        self.calls.append(ticket_id)
        if self.write is not None:
            self.write(vault, load_ticket(find_ticket(vault, ticket_id)))
        with editing(vault, ticket_id) as ticket:
            if self.status == "in-review":
                set_result(ticket, "Learned: three leases. Pages: 3 documents, 1 organisation.", ticket.assignee)
            else:
                set_status(ticket, self.status, "runner", self.message or "stand-in")
        return RunOutcome(ticket_id, self.status, "claude", self.message or f"{ticket_id} is now {self.status}")
```

Create `tests/test_kb_wiki_run.py`:

```python
"""The background wiki run: after a folder is read, one agent run (a ticket through the ticket runner) writes its pages."""
import fcntl

import pytest

from bron.kb import jobs, notices, sources, store, wiki
from bron.tickets import find_ticket, load_ticket
from kbkit import FakeTicketRunner, fake_embed, make_text_pdf, stored_doc, write_page


def folder_of(tmp_path, n, name="Leases"):
    folder = tmp_path / name
    folder.mkdir(exist_ok=True)
    for i in range(n):
        make_text_pdf(folder / f"lease{i}.pdf", [f"Lease number {i}: Harbor Bakery rents shop {i} from Northwind Properties Ltd."])
    return folder


def read_folder(vault, tmp_path, n=3, name="Leases", runner=None):
    found = sources.resolve_targets(vault, [str(folder_of(tmp_path, n, name))])
    job = jobs.create(vault, found.items, wiki=True, label=f"the {found.folders[0]} folder")
    runner = runner or FakeTicketRunner()
    jobs.run(vault, job.job_id, embedder=fake_embed, run_ticket=runner)
    return jobs.load(vault, job.job_id), runner


def hold_the_wiki_lock(vault):
    path = store.kb_dir(vault) / "jobs" / "wiki.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    held = open(path, "a+")
    fcntl.flock(held, fcntl.LOCK_EX)  # another run is writing the wiki
    return held


def test_a_folder_is_read_then_written_into_the_wiki_by_one_ticket(vault, tmp_path):
    job, runner = read_folder(vault, tmp_path)
    assert job.status == "done" and job.wiki_status == "done" and len(job.wiki_docs) == 3
    assert runner.calls == [job.ticket]
    ticket = load_ticket(find_ticket(vault, job.ticket))
    assert ticket.title == "Read the Leases folder into the wiki"
    assert ticket.assignee == "bron" and ticket.requested_by == "you" and ticket.status == "in-review"
    assert "read-documents skill" in ticket.request and "wiki done --log 'check |" in ticket.request
    assert all(f"doc {doc_id}" in ticket.request for doc_id in job.wiki_docs)
    assert job.report.startswith("Read 3 documents")
    assert notices.take(vault) == []  # the ticket's update is the summary
    assert jobs.status_lines(vault)[0] == jobs.IDLE


def test_a_failed_wiki_run_tells_the_user_what_was_read(vault, tmp_path):
    job, _ = read_folder(vault, tmp_path, runner=FakeTicketRunner(status="blocked", message="T-0001 is blocked: the run failed"))
    assert job.wiki_status == "failed"
    told = notices.take(vault)
    assert len(told) == 1 and told[0].startswith("Read 3 documents")
    assert "couldn't write all their wiki pages (T-0001 is blocked: the run failed)" in told[0]
    assert told[0].endswith('Say "finish the wiki pages" to write the rest.')


def test_what_could_not_be_read_goes_into_the_request(vault, tmp_path):
    (folder_of(tmp_path, 2) / "broken.zip").write_bytes(b"x")
    job, _ = read_folder(vault, tmp_path, n=0)
    request = load_ticket(find_ticket(vault, job.ticket)).request
    assert "From the reading: Couldn't read: broken.zip (Bron can't read .zip files yet)." in request


def test_one_wiki_writer_at_a_time(vault, tmp_path):
    runner = FakeTicketRunner()
    held = hold_the_wiki_lock(vault)
    try:
        job, _ = read_folder(vault, tmp_path, runner=runner)
        assert job.status == "done" and job.wiki_status == "waiting" and runner.calls == []
        assert any(line.startswith("Waiting to write the Leases folder into the wiki (since ")
                   for line in jobs.status_lines(vault))
    finally:
        held.close()
    jobs.run(vault, job.job_id, embedder=fake_embed, run_ticket=runner)
    assert jobs.load(vault, job.job_id).wiki_status == "done" and len(runner.calls) == 1


def test_documents_read_in_a_conversation_wait_behind_the_folder_being_written(vault, tmp_path):
    order = []

    def write(vault_, ticket):
        order.append(ticket.title)
        if len(order) == 1:  # while the folder is written, a conversation reads two more documents
            assert jobs.wiki_active(vault) and not jobs.runner_active(vault)  # the reader is free meanwhile
            a, b = stored_doc(vault, "a.pdf", ["A"]), stored_doc(vault, "b.pdf", ["B"])
            jobs.create_wiki(vault, [a.doc_id, b.doc_id])

    read_folder(vault, tmp_path, runner=FakeTicketRunner(write=write))
    assert order == ["Read the Leases folder into the wiki", "Read 2 documents into the wiki"]
    assert jobs.wiki_pending(vault) == []


def test_an_interrupted_wiki_run_resumes_then_gives_up_plainly(vault, tmp_path):
    class LidCloses(FakeTicketRunner):
        def __call__(self, vault, ticket_id, **kw):
            self.calls.append(ticket_id)
            raise KeyboardInterrupt

    runner = LidCloses()
    with pytest.raises(KeyboardInterrupt):
        read_folder(vault, tmp_path, runner=runner)
    job = jobs.all_jobs(vault)[-1]
    assert job.wiki_status == "writing" and job.wiki_attempts == 1 and not jobs.wiki_active(vault)
    assert [j.job_id for j in jobs.stalled(vault)] == [job.job_id]  # a new session starts a runner for it
    assert any("stopped part-way" in line for line in jobs.status_lines(vault))
    with pytest.raises(KeyboardInterrupt):
        jobs.run(vault, job.job_id, embedder=fake_embed, run_ticket=runner)
    assert len(runner.calls) == 2 and runner.calls[0] == runner.calls[1]  # the same ticket, run again
    jobs.run(vault, job.job_id, embedder=fake_embed, run_ticket=runner)
    final = jobs.load(vault, job.job_id)
    assert final.wiki_status == "failed" and len(runner.calls) == 2  # never a third time
    told = notices.take(vault)[0]
    assert "it stopped twice before finishing" in told and "finish the wiki pages" in told
    assert len(store.all_docs(vault)) == 3  # what was read stays searchable


def test_documents_that_already_have_pages_are_not_written_again(vault, tmp_path):
    job, runner = read_folder(vault, tmp_path, n=2)
    first, second = job.wiki_docs
    write_page(vault, "Documents/Lease 0.md", type="document", summary="Lease 0", doc=first)
    wiki.link_documents(vault, wiki.all_pages(vault))
    again = jobs.create(vault, sources.resolve_targets(vault, [str(tmp_path / "Leases")]).items, wiki=True)
    jobs.run(vault, again.job_id, embedder=fake_embed, run_ticket=runner)
    done = jobs.load(vault, again.job_id)
    assert done.read == [] and sorted(done.unchanged) == sorted([first, second]) and done.wiki_docs == [second]
    write_page(vault, "Documents/Lease 1.md", type="document", summary="Lease 1", doc=second)
    wiki.link_documents(vault, wiki.all_pages(vault))
    last = jobs.create(vault, sources.resolve_targets(vault, [str(tmp_path / "Leases")]).items, wiki=True)
    jobs.run(vault, last.job_id, embedder=fake_embed, run_ticket=runner)
    assert jobs.load(vault, last.job_id).wiki_status == "" and len(runner.calls) == 2
    assert notices.take(vault)[-1].startswith("Already read, unchanged: lease0.pdf, lease1.pdf")


def test_cancel_stops_wiki_runs_that_are_waiting(vault, tmp_path):
    held = hold_the_wiki_lock(vault)
    try:
        job, _ = read_folder(vault, tmp_path)
        texts = jobs.cancel(vault)
    finally:
        held.close()
    assert jobs.load(vault, job.job_id).wiki_status == "cancelled" and jobs.wiki_pending(vault) == []
    assert any(t.startswith("Read 3 documents") and "the wiki pages for 3 documents weren't written" in t
               and "finish the wiki pages" in t for t in texts)


def test_jobs_waiting_for_the_wiki_are_never_pruned(vault):
    waiting = jobs.create_wiki(vault, ["0000000000000000"])
    for _ in range(jobs.KEEP_FINISHED + 2):
        finished = jobs.create(vault, [])
        finished.status = "done"
        jobs.save(vault, finished)
    jobs.create(vault, [])  # creating a job prunes the old finished ones
    assert jobs.load(vault, waiting.job_id) is not None


def test_without_a_default_agent_the_run_fails_plainly(vault, tmp_path):
    from vaultkit import set_meta

    set_meta(vault.settings_file, default_agent="Nobody")
    job, runner = read_folder(vault, tmp_path)
    assert job.wiki_status == "failed" and runner.calls == []
    assert "There's no default agent to write the wiki pages" in notices.take(vault)[0]
```

In `tests/test_kb_ingest.py` `test_status_lines` (lines 312-319) replace the two idle assertions:

```python
def test_status_lines(kb, tmp_path):
    assert jobs.status_lines(kb.vault) == [jobs.IDLE]
    job = jobs.create(kb.vault, items_in(kb, tmp_path, 2))
    assert jobs.status_lines(kb.vault)[0].startswith("Waiting to read 2 documents")
    jobs.run(kb.vault, job.job_id, **kb.deps)
    lines = jobs.status_lines(kb.vault)
    assert lines[0] == "Nothing is being read."
    assert lines[1].startswith("Last batch finished ") and lines[1].endswith(": 2 documents read, 0 couldn't be read.")
```

In `tests/test_kb_cli.py` replace `"No documents are being read right now."` with `"Nothing is being read."` on lines 285 (`test_status_shows_documents_and_jobs`) and 344 (`test_status_cancel`).

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki_run.py tests/test_kb_ingest.py::test_status_lines -q`
Expected: FAIL — `TypeError: create() got an unexpected keyword argument 'wiki'`, `jobs` has no `IDLE`.

- [ ] **Step 3: Implement**

Create `core/Engine/bron/kb/wiki_run.py`:

```python
"""The background wiki run: once a folder (or more than three documents) is read, one agent run writes their wiki pages.
It is a ticket for the default agent, run through the ticket runner like any other, so its final reply (the summary)
reaches the user like any ticket update."""
from __future__ import annotations

from ..vault import Vault
from . import store
from .store import KbError

SECONDS_PER_DOC = 60  # writing one document's pages (the reading is estimated on its own)

REQUEST = """Read these documents into the wiki, one after another. Load the read-documents skill first and follow it; \
write the pages in Knowledge/ (not in Projects/).
{docs}

Then run the skill's judgement checkup over the pages you touched, and finish with
.bron/bin/bron wiki done --log 'check | <one line: what the checkup found and fixed>'

Nobody is waiting on this run, so don't ask questions: note real conflicts and open questions in your reply instead of \
deciding them. Your final reply is what the user reads: in a few lines, what you learned, what changed or contradicted \
earlier pages, the pages you created and updated, and the documents that couldn't be read."""


def title(label: str, count: int) -> str:
    what = label or ("1 document" if count == 1 else f"{count} documents")
    return f"Read {what} into the wiki"


def request(vault: Vault, doc_ids: list[str], report: str = "") -> str:
    lines = []
    for doc_id in doc_ids:
        doc = store.load(vault, doc_id)
        if doc is not None:
            lines.append(f"- {doc.name} — doc {doc.doc_id}")
    text = REQUEST.format(docs="\n".join(lines))
    failed = [line for line in report.splitlines() if line.startswith("Couldn't")]
    if failed:
        text += "\n\nFrom the reading: " + " ".join(failed)
    return text


def start_ticket(vault: Vault, cfg, job) -> str:
    """The run's ticket, assigned to the default agent and asked for by the user (made once per job)."""
    from ..tickets import new_ticket

    agent = cfg.default_agent
    if agent is None:
        raise KbError("There's no default agent to write the wiki pages (System/Settings.md, default_agent).")
    ticket = new_ticket(vault, title=title(job.label, len(job.wiki_docs)), assignee=agent.key,
                        request=request(vault, job.wiki_docs, job.report), requested_by="you")
    return ticket.id
```

`core/Engine/bron/kb/jobs.py`:
- module docstring: add a second paragraph: `Once a job is read, its documents' wiki pages are written by one background agent run (kb/wiki_run.py). One wiki run at a time: others wait. The reader and the wiki writer have their own locks, so documents can be read while a folder is being written.`
- `Job` (after `unchanged`, line 45) add:

```python
    wiki: bool = False  # write the wiki pages in the background once read
    wiki_status: str = ""  # "" (no wiki run) | waiting | writing | done | failed | cancelled
    wiki_docs: list[str] = field(default_factory=list)  # ids of the documents whose pages the run writes
    wiki_since: str = ""  # when it began waiting to be written
    wiki_attempts: int = 0  # wiki runs started (a third is never tried)
    ticket: str = ""  # the wiki run's ticket
    label: str = ""  # "the Leases folder" (empty: "N documents"), for the ticket's title
    report: str = ""  # the reading report: handed to the wiki run, and told to the user if the run fails
```

- after `MAX_ATTEMPTS = 2` (line 28) add `IDLE = "Nothing is being read."`.
- after `_runner_path` (line 61) add:

```python
def _wiki_lock_path(vault: Vault) -> Path:
    return _dir(vault) / "wiki.lock"


def _writer_path(vault: Vault) -> Path:
    return _dir(vault) / "wiki.status"
```

- `_prune` (lines 92-99): `finished = [j for j in all_jobs(vault) if j.status in ("done", "cancelled") and j.wiki_status not in ("waiting", "writing")]`.
- after `pending` (line 89) add:

```python
def wiki_pending(vault: Vault) -> list[Job]:
    """Jobs whose wiki pages are waiting to be written, or being written."""
    return [j for j in all_jobs(vault) if j.wiki_status in ("waiting", "writing")]
```

- `create` (lines 102-115): signature `def create(vault: Vault, items: list, *, failed: list[str] | tuple = (), again: bool = False, wiki: bool = False, label: str = "") -> Job:`, docstring adds `` `wiki`: write their wiki pages in the background once read; `label`: "the Leases folder", for the run's title.`` and the `Job(...)` call gains `wiki=wiki, label=label`. After it add:

```python
def create_wiki(vault: Vault, doc_ids: list[str], *, label: str = "") -> Job:
    """Documents read in a conversation while a background wiki run is writing: their pages are written after it."""
    _prune(vault)
    stamp = datetime.now().isoformat(timespec="microseconds")
    job = Job(job_id=time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2), created=stamp, items=[], done=[],
              failed=[], status="done", finished=time.strftime("%Y-%m-%d %H:%M"), wiki=True, wiki_status="waiting",
              wiki_docs=list(doc_ids), wiki_since=stamp, label=label)
    save(vault, job)
    return job
```

- replace `_hold_lock`, `_beat` (lines 120-143) with:

```python
@contextlib.contextmanager
def _hold_lock(vault: Vault, *, wiki: bool = False):
    path = _wiki_lock_path(vault) if wiki else _lock_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            _beat(vault, wiki=wiki)
            yield True
        finally:
            try:
                (_writer_path(vault) if wiki else _runner_path(vault)).unlink()
            except OSError:
                pass
            fcntl.flock(handle, fcntl.LOCK_UN)


def _beat(vault: Vault, *, wiki: bool = False) -> None:
    """Who is reading (or writing the wiki), for `runner_active` (which must never touch the locks)."""
    statefile.write_json(_writer_path(vault) if wiki else _runner_path(vault), {"pid": os.getpid(), "beat": time.time()})
```

- `runner_active` (lines 172-182): signature `def runner_active(vault: Vault, *, wiki: bool = False) -> bool:`, docstring adds `` `wiki`: the wiki writer instead of the reader.``, and read `(_writer_path(vault) if wiki else _runner_path(vault))`. After it add:

```python
def wiki_active(vault: Vault) -> bool:
    """A background wiki run is writing pages right now."""
    return runner_active(vault, wiki=True)
```

- replace `stalled` (lines 185-198) with:

```python
def _age(stamp: str, now: datetime) -> float:
    try:
        return (now - datetime.fromisoformat(stamp)).total_seconds()
    except ValueError:
        return STALE_QUEUED_SECONDS


def stalled(vault: Vault) -> list[Job]:
    """Jobs nobody is working on: interrupted ones, queued ones whose runner never started, and wiki runs nobody is
    writing (a reader at work writes them once it's done)."""
    reading = runner_active(vault)
    now = datetime.now()
    out: list[Job] = []
    if not reading:
        out += [j for j in pending(vault) if j.status == "running" or _age(j.created, now) >= STALE_QUEUED_SECONDS]
        if not runner_active(vault, wiki=True):
            out += [j for j in wiki_pending(vault)
                    if j.wiki_status == "writing" or _age(j.wiki_since, now) >= STALE_QUEUED_SECONDS]
    return out
```

- replace `_finish` and `cancel` (lines 236-257) with:

```python
def _needs_pages(vault: Vault, job: Job) -> list[str]:
    """The documents a wiki run writes pages for: those just read (a page is updated when its document is read again)
    and those skipped as unchanged that have no page yet."""
    out: list[str] = []
    for doc_id in [*job.read, *job.unchanged]:
        doc = store.load(vault, doc_id)
        if doc is not None and doc.status == "read" and (doc_id in job.read or not doc.page) and doc_id not in out:
            out.append(doc_id)
    return out


def _finish(vault: Vault, job: Job, status: str, *, shown: bool = False) -> str:
    """Report first, then mark the job finished: an interruption in between gives the report once, never zero times.
    A wiki job keeps its report for its wiki run, whose ticket update becomes what the user is told."""
    if status == "cancelled":
        job.cancelled = [str(raw.get("name", "")) if isinstance(raw, dict) else str(raw) for raw in _remaining(job)]
    text = report(vault, job)
    pages = _needs_pages(vault, job) if job.wiki and status == "done" else []
    if pages:
        job.report, job.wiki_docs, job.wiki_status = text, pages, "waiting"
        job.wiki_since = datetime.now().isoformat(timespec="microseconds")
    else:
        notices.add(vault, text, job_id=job.job_id, shown=shown)
    job.status = status
    job.finished = time.strftime("%Y-%m-%d %H:%M")
    save(vault, job)  # the cancel flag stays until the job is pruned: a runner that already picked it up stops too
    return text


def cancel(vault: Vault) -> list[str]:
    """Stop every waiting or running job, and every wiki run that is waiting. Jobs nobody is working on stop now (their
    reports are returned, for the caller to print); the one being read stops after its current document and reports as
    usual; a wiki run already writing finishes."""
    texts: list[str] = []
    active = runner_active(vault)
    for job in pending(vault):
        _cancel_path(vault, job.job_id).touch()
        if job.status == "queued" or not active:
            texts.append(_finish(vault, job, "cancelled", shown=True))
    for job in wiki_pending(vault):
        if job.wiki_status == "waiting":
            job.wiki_status, job.finished = "cancelled", time.strftime("%Y-%m-%d %H:%M")
            save(vault, job)
            note = (f"Cancelled: the wiki pages for {_plural(len(job.wiki_docs), 'document')} weren't written; "
                    "say \"finish the wiki pages\" when you want them.")
            texts.append(f"{job.report}\n{note}" if job.report else note)
    return texts
```

- replace `run` (lines 310-331) with the version below, and add the wiki writer after it:

```python
def run(vault: Vault, job_id: str, *, embedder=None, readers_ocr=None, model_call=None, cfg=None, run_ticket=None) -> bool:
    """Run this job and any others waiting, oldest first; then let go of the reader and write the wiki pages of what was
    read. False when another runner is already reading (it picks up every waiting job, this one included)."""
    if cfg is None:
        from ..loader import load as load_cfg

        cfg = load_cfg(vault)
    embedder = embedder or _default_embedder(vault)
    deps = dict(embedder=embedder, readers_ocr=readers_ocr, model_call=model_call)
    while True:
        with _hold_lock(vault) as got:
            if not got:
                return False
            _finish_indexing(vault, embedder)
            while True:
                waiting = pending(vault)
                if not waiting:
                    break
                _work(vault, cfg, waiting[0], **deps)
        # A job queued while this runner was finishing found the lock taken: look once more after letting go.
        if not pending(vault):
            break
    _write_wiki(vault, cfg, run_ticket=run_ticket)
    return True


def _write_wiki(vault: Vault, cfg, *, run_ticket=None) -> None:
    """Write every waiting wiki run, oldest first: one writer at a time (another one already at work writes them)."""
    while True:
        with _hold_lock(vault, wiki=True) as got:
            if not got:
                return
            while True:
                waiting = wiki_pending(vault)
                if not waiting:
                    break
                _write_one(vault, cfg, waiting[0], run_ticket=run_ticket)
        # One queued while this writer was finishing found the lock taken: look once more after letting go.
        if not wiki_pending(vault):
            return


def _wiki_failed(vault: Vault, job: Job, why: str) -> None:
    note = (f"Bron read the documents but couldn't write all their wiki pages ({why.rstrip('.')}). "
            "Say \"finish the wiki pages\" to write the rest.")
    notices.add(vault, f"{job.report}\n{note}" if job.report else note, job_id=f"{job.job_id}-wiki")
    job.wiki_status, job.finished = "failed", time.strftime("%Y-%m-%d %H:%M")
    save(vault, job)


def _write_one(vault: Vault, cfg, job: Job, *, run_ticket=None) -> None:
    from . import wiki_run

    fresh = load(vault, job.job_id)
    if fresh is None or fresh.wiki_status not in ("waiting", "writing"):
        return  # cancelled or written since it was picked
    job = fresh
    if job.wiki_attempts >= MAX_ATTEMPTS:  # it stopped the writer twice: never a third time
        _wiki_failed(vault, job, "it stopped twice before finishing")
        return
    job.wiki_status, job.wiki_attempts = "writing", job.wiki_attempts + 1
    save(vault, job)  # written down first, so an interruption counts
    _beat(vault, wiki=True)
    try:
        if not job.ticket:
            job.ticket = wiki_run.start_ticket(vault, cfg, job)
            save(vault, job)
        if run_ticket is None:
            from ..runner import run_ticket
        outcome = run_ticket(vault, job.ticket)
        ok = outcome.status == "in-review"  # a ticket already in review (finished before a crash) counts as written
        why = "" if ok else (outcome.message or f"its ticket is {outcome.status or 'not finished'}")
    except Exception as exc:  # noqa: BLE001 - one failed run never stops the queue (Ctrl-C still stops it)
        ok, why = False, str(exc) if isinstance(exc, store.KbError) else f"{exc.__class__.__name__}: {exc}"
    if ok:
        job.wiki_status, job.finished = "done", time.strftime("%Y-%m-%d %H:%M")
        save(vault, job)
    else:
        _wiki_failed(vault, job, why)
```

- replace `status_lines` (lines 371-394) with:

```python
def status_lines(vault: Vault) -> list[str]:
    """What `bron kb status` says. Idle, nothing in it contains "reading" (an agent once waited for that word)."""
    lines: list[str] = []
    active = runner_active(vault)
    for job in pending(vault):
        total = len(job.items)
        failed = sum(1 for f in job.failed if f.get("identity"))
        left = total - len(job.done) - failed
        if job.status == "running" and active:
            lines.append(f"Reading {_plural(total, 'document')}: {len(job.done)} read, {failed} couldn't be read, "
                         f"{left} to go (started {_when(job.created)}).")
        elif job.status == "running":
            lines.append(f"Reading {_plural(total, 'document')} stopped part-way: {len(job.done)} read, {left} to go.")
        else:
            lines.append(f"Waiting to read {_plural(total, 'document')} (since {_when(job.created)}).")
    writer = runner_active(vault, wiki=True)
    for job in wiki_pending(vault):
        what = job.label or _plural(len(job.wiki_docs), "document")
        if job.wiki_status == "writing" and writer:
            lines.append(f"Writing {what} into the wiki ({job.ticket or 'starting'}, since {_when(job.wiki_since)}).")
        elif job.wiki_status == "writing":
            lines.append(f"Writing {what} into the wiki stopped part-way; Bron picks it up again.")
        else:
            lines.append(f"Waiting to write {what} into the wiki (since {_when(job.wiki_since)}).")
    if not lines:
        lines.append(IDLE)
    finished = [j for j in all_jobs(vault) if j.status in ("done", "cancelled") and j.items]
    if finished:
        last = finished[-1]
        failed = sum(1 for f in last.failed if f.get("name"))
        how = "was cancelled" if last.status == "cancelled" else "finished"
        lines.append(f"Last batch {how} {last.finished}: {_plural(len(last.read), 'document')} read, "
                     f"{failed} couldn't be read.")
    return lines
```

- [ ] **Step 4: Run the tests**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki_run.py tests/test_kb_ingest.py tests/test_kb_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Run everything and commit**

Run: `uv run --project core/Engine pytest tests -q` — Expected: PASS.

```bash
git add core/Engine/bron/kb/wiki_run.py core/Engine/bron/kb/jobs.py tests/kbkit.py tests/test_kb_wiki_run.py tests/test_kb_ingest.py tests/test_kb_cli.py
git commit -m "Write a read folder into the wiki in the background, one run at a time

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `bron kb add` — up to 3 documents in the conversation, a folder or more in the background; forget, show and status (spec §3 item 1, §5.1, §5.2 output, §8)

**Files:**
- Modify: `core/Engine/bron/kb/cli.py:1-17` (imports, constants), `:172-238` (`_queue`, `_add_export`, `_add`; new `_sizes`, `_report`), `:296-325` (`_show`), `:379-394` (`_forget`), `:458-492` (`_status`)
- Modify: `core/Engine/bron/kb/ingest.py` (add `lines` after `summary`, line 482)
- Modify: `tests/test_kb_cli.py` (fixture and the tests listed below)
- Test: `tests/test_kb_add.py` (create)

**Interfaces:**
- Consumes: `sources.resolve_targets` (Task 1), `tools.ensure`, `ingest.page_count/looks_scanned/guess_pages/read_item/add_export/export_item`, `jobs.create(..., wiki=True, label=...)`, `jobs.create_wiki`, `jobs.wiki_pending`, `jobs.wiki_active`, `jobs.runner_active`, `jobs.spawn`, `jobs.IDLE` (Task 7), `wiki_run.SECONDS_PER_DOC` (Task 7), `wiki.append_log` (Task 4), `Doc.page` (Task 4).
- Produces:
  - `kb_cli.FOREGROUND = 3`, `kb_cli.FOREGROUND_SECONDS = 300`, `kb_cli.TEXT_SECONDS_PER_PAGE = 0.05`, `kb_cli.SCAN_SECONDS_PER_PAGE = 1.0`, `kb_cli.BACKGROUND`, `kb_cli.BEHIND`, `kb_cli.NEXT` (exact texts below). `FOREGROUND_PAGES` and `SETTING_UP` are removed.
  - `ingest.lines(docs: list[Doc], notes=()) -> str` — `Read <name> (<N> pages, <S> scanned) — doc <id>`, `Already read <name> — doc <id> (page: [[<page>]])` or `(no page yet)`, `Couldn't read <name>: <reason>`, then the notes.
  - `bron kb forget` prints `… Its page [[<page>]] is still there; delete it or keep it.` and logs `forget | <name> (doc <id>)[; its page [[…]] was kept]`; `bron kb show` prints `Page: [[<page>]]`; `bron kb status` idle prints `Nothing is being read.`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_kb_cli.py`:
- imports: add `from bron import runner` and `FakeTicketRunner` to the `kbkit` import.
- `env` fixture: replace `monkeypatch.setattr(tools, "ensure", lambda vault, say=print: None)` with

```python
    ensured = []
    monkeypatch.setattr(tools, "ensure", lambda vault, say=print: ensured.append(vault))
    monkeypatch.setattr(runner, "run_ticket", FakeTicketRunner())
```

  and set `e.ensured = ensured` next to `e.vault, e.root, e.spawned = …`.
- replace `add_all`:

```python
def add_all(env, capsys):
    """A folder is read in the background and then written into the wiki; the test runs that job here and returns its
    reading report (the wiki run's ticket carries it)."""
    code, out = run(env, capsys, "add", acme_folder(env))
    assert code == 0 and out.strip() == ("Reading 3 documents into the wiki in the background (about 3 minutes); "
                                         "I'll report when it's done."), out
    jobs.run(env.vault, env.spawned[-1], embedder=fake_embed)  # what the detached `bron kb run-job` does
    return jobs.load(env.vault, env.spawned[-1]).report
```

- replace `test_more_than_five_documents_read_in_the_background_and_report_in_the_briefing_once` with:

```python
def test_a_folder_is_read_and_written_in_the_background_and_a_failure_is_told_once(env, capsys, tmp_path, monkeypatch):
    folder = tmp_path / "pile"
    folder.mkdir()
    for i in range(6):
        make_text_pdf(folder / f"report{i}.pdf", [f"Quarterly report number {i}, with revenue and costs."])
    code, out = run(env, capsys, "add", str(folder))
    assert code == 0 and out.strip() == ("Reading 6 documents into the wiki in the background (about 6 minutes); "
                                         "I'll report when it's done.")
    assert len(env.spawned) == 1 and store.all_docs(env.vault) == []
    code, out = run(env, capsys, "status")
    assert "Waiting to read 6 documents" in out
    monkeypatch.setattr(runner, "run_ticket", FakeTicketRunner(status="blocked", message="the run failed"))
    jobs.run(env.vault, env.spawned[0], embedder=fake_embed)  # what the detached `bron kb run-job` does
    first = build_briefing(env.vault, cli="claude")
    assert "## Knowledge base" in first and "Read 6 documents" in first and "finish the wiki pages" in first
    assert "## Knowledge base" not in build_briefing(env.vault, cli="claude")
```

- `test_failures_are_reported_and_never_stop_the_batch`: name the files instead of the folder (a folder now goes to the background):

```python
def test_failures_are_reported_and_never_stop_the_batch(env, capsys, tmp_path):
    good = make_text_pdf(tmp_path / "good.pdf", [SPA_TEXT])
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    song = tmp_path / "song.mp3"
    song.write_bytes(b"x")
    code, out = run(env, capsys, "add", str(good), str(bad), str(song), "https://drive.google.com/file/d/NOPE/view")
    assert code == 0 and out.startswith("Read good.pdf (1 page, 0 scanned) — doc ")
    assert "Couldn't read bad.pdf: This file is damaged or isn't really a PDF" in out
    assert "Couldn't read song.mp3: Bron can't read .mp3 files yet." in out
    assert "Couldn't find https://drive.google.com/file/d/NOPE/view in Google Drive on this Mac" in out
    assert out.strip().endswith(kb_cli.NEXT)
```

- `test_add_an_exported_google_doc`: `assert code == 0 and out.startswith("Read IC memo (1 page, 0 scanned) — doc ")`.
- `test_a_small_request_waits_behind_a_running_job`:

```python
def test_a_small_request_waits_behind_a_running_job(env, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "runner_active", lambda vault, wiki=False: not wiki)
    one = make_text_pdf(tmp_path / "one.pdf", [SPA_TEXT])
    code, out = run(env, capsys, "add", str(one))
    assert code == 0 and out.strip() == ("Reading 1 document into the wiki in the background (about 1 minute); "
                                         "I'll report when it's done.")
    assert len(env.spawned) == 1 and store.all_docs(env.vault) == []
```

- `test_an_unreadable_inbox_file_is_reported_and_the_rest_is_read`: `assert code == 0 and out.startswith("Read good.pdf (") and "Traceback" not in out` and `assert "Couldn't read locked.pdf: Bron couldn't open this file (Permission denied)." in out`.
- `test_reading_the_same_file_again_is_skipped_unless_asked`:

```python
def test_reading_the_same_file_again_is_skipped_unless_asked(env, capsys, tmp_path):
    spa = make_text_pdf(tmp_path / "spa.pdf", [SPA_TEXT])
    code, out = run(env, capsys, "add", str(spa))
    assert code == 0 and out.startswith("Read spa.pdf (1 page, 0 scanned) — doc ")
    doc_id = out.split("— doc ", 1)[1].split()[0]
    code, out = run(env, capsys, "add", str(spa))
    assert code == 0 and out.splitlines()[0] == f"Already read spa.pdf — doc {doc_id} (no page yet)"
    code, out = run(env, capsys, "add", str(spa), "--again")
    assert code == 0 and out.startswith("Read spa.pdf (")
```

- replace `SETUP_BACKGROUND` and the three setup tests (`test_first_add_without_the_tools_sets_up_and_reads_in_the_background`, `test_a_failed_setup_in_the_background_is_reported`, `test_a_failed_setup_leaves_jobs_alone_while_another_runner_reads_them`) with:

```python
def test_the_first_add_sets_the_tools_up_and_reads_in_the_conversation(env, capsys, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(tools, "ensure", lambda vault, say=print: calls.append("ensure") or say(tools.SETUP))
    one = make_text_pdf(tmp_path / "one.pdf", [SPA_TEXT])
    code, out = run(env, capsys, "add", str(one))
    assert code == 0 and calls == ["ensure"] and env.spawned == []
    assert out.splitlines()[0] == tools.SETUP and out.splitlines()[1].startswith("Read one.pdf (")
    text = tmp_path / "memo.txt"
    text.write_text("The committee approved a budget of BRL 750.000,00 for the office move.")
    code, out = run(env, capsys, "add", "--file", str(text), "--source", "https://docs.google.com/document/d/GDOC1/edit",
                    "--name", "IC memo")
    assert code == 0 and calls == ["ensure", "ensure"] and out.splitlines()[1].startswith("Read IC memo (")


def test_a_setup_that_fails_in_the_conversation_is_one_plain_line(env, capsys, tmp_path, monkeypatch):
    from bron.kb.store import KbError

    def refuse(vault, say=print):
        raise KbError("The knowledge base tools couldn't be installed (No route to host). Check the internet connection and try again.")

    monkeypatch.setattr(tools, "ensure", refuse)
    code, out = run(env, capsys, "add", str(make_text_pdf(tmp_path / "one.pdf", [SPA_TEXT])))
    assert code == 1 and out.strip() == ("The knowledge base tools couldn't be installed (No route to host). "
                                         "Check the internet connection and try again.")


def test_a_failed_setup_in_the_background_is_reported(env, capsys, tmp_path, monkeypatch):
    from bron.kb import notices
    from bron.kb.store import KbError

    folder = tmp_path / "F"
    folder.mkdir()
    make_text_pdf(folder / "one.pdf", [SPA_TEXT])
    run(env, capsys, "add", str(folder))

    def refuse(vault, say=print):
        raise KbError("The knowledge base tools couldn't be installed (No route to host).")

    monkeypatch.setattr(tools, "missing", lambda: ["fastembed"])
    monkeypatch.setattr(tools, "ensure", refuse)
    code, out = run(env, capsys, "run-job", env.spawned[0])
    assert code == 1
    assert jobs.load(env.vault, env.spawned[0]).status == "done" and jobs.pending(env.vault) == []
    told = notices.take(env.vault)
    assert len(told) == 1 and "couldn't be installed (No route to host)" in told[0] and "one.pdf" in told[0]


def test_a_failed_setup_leaves_jobs_alone_while_another_runner_reads_them(env, capsys, tmp_path):
    import fcntl

    from bron.kb import notices

    folder = tmp_path / "F"
    folder.mkdir()
    make_text_pdf(folder / "one.pdf", [SPA_TEXT])
    run(env, capsys, "add", str(folder))
    lock = jobs._lock_path(env.vault)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)  # a runner whose setup worked is reading
        jobs.give_up(env.vault, "The knowledge base tools couldn't be installed (No route to host).")
    assert [j.job_id for j in jobs.pending(env.vault)] == env.spawned[:1] and notices.take(env.vault) == []
```

- replace `test_more_than_fifty_pages_read_in_the_background` and `test_images_and_scans_read_in_the_background` with:

```python
def test_a_long_read_goes_to_the_background(env, capsys, tmp_path, monkeypatch):
    one = make_text_pdf(tmp_path / "one.pdf", [SPA_TEXT])
    monkeypatch.setattr(ingest, "page_count", lambda item: 301)
    monkeypatch.setattr(ingest, "looks_scanned", lambda item: True)
    code, out = run(env, capsys, "add", str(one))
    assert out.strip() == ("Reading 1 document into the wiki in the background (about 2 minutes); "
                           "I'll report when it's done.")
    monkeypatch.setattr(ingest, "page_count", lambda item: 300)  # 300 scanned pages: about 5 minutes, still here
    code, out = run(env, capsys, "add", str(one))
    assert out.startswith("Read one.pdf (") and len(env.spawned) == 1


def test_a_scan_is_read_in_the_conversation(env, capsys, tmp_path):
    path = make_scanned_pdf(tmp_path / "scan.pdf", ["scanned page"])
    code, out = run(env, capsys, "add", str(path))
    assert code == 0 and out.startswith("Read scan.pdf (1 page, 1 scanned) — doc ") and env.spawned == []
```

- `test_schemeless_drive_links_are_links`: `assert code == 0 and out.startswith("Read spa.pdf (")`.

Create `tests/test_kb_add.py`:

```python
"""`bron kb add` in 0.8.0: up to 3 documents in the conversation, a folder or more in the background with a wiki run."""
import pytest

from bron.kb import cli as kb_cli
from bron.kb import jobs, store, tools, wiki
from kbkit import fake_embed, make_text_pdf, stored_doc, write_page
from test_kb_cli import SPA_TEXT, env, run  # noqa: F401 - env is a fixture

PAGE = "Documents/Purchase agreement (2025-01-21).md"


def pdfs(tmp_path, n, prefix="doc"):
    return [make_text_pdf(tmp_path / f"{prefix}{i}.pdf", [f"{SPA_TEXT} Copy {i}."]) for i in range(n)]


def with_page(env, doc):
    path = write_page(env.vault, PAGE, type="document", summary="A purchase agreement", doc=doc.doc_id)
    wiki.link_documents(env.vault, [wiki.read_page(env.vault, path)])
    return path


def test_up_to_three_documents_are_read_in_the_conversation(env, capsys, tmp_path):
    code, out = run(env, capsys, "add", *map(str, pdfs(tmp_path, 3)))
    lines = out.strip().splitlines()
    assert code == 0 and env.spawned == [] and len(env.ensured) == 1
    assert [line.split(" — doc ")[0] for line in lines[:3]] == [f"Read doc{i}.pdf (1 page, 0 scanned)" for i in range(3)]
    assert {line.split(" — doc ")[1] for line in lines[:3]} == {d.doc_id for d in store.all_docs(env.vault)}
    assert lines[3] == kb_cli.NEXT


def test_four_documents_or_a_folder_go_to_the_background_with_a_wiki_run(env, capsys, tmp_path):
    code, out = run(env, capsys, "add", *map(str, pdfs(tmp_path, 4)))
    assert out.strip() == ("Reading 4 documents into the wiki in the background (about 4 minutes); "
                           "I'll report when it's done.")
    assert jobs.load(env.vault, env.spawned[0]).wiki is True and env.ensured == []
    folder = tmp_path / "Receipts"
    folder.mkdir()
    make_text_pdf(folder / "r.pdf", [SPA_TEXT])
    code, out = run(env, capsys, "add", str(folder))
    assert out.strip() == ("Reading 1 document into the wiki in the background (about 1 minute); "
                           "I'll report when it's done.")
    job = jobs.load(env.vault, env.spawned[1])
    assert job.wiki is True and job.label == "the Receipts folder"


def test_the_inbox_counts_its_documents_not_as_a_folder(env, capsys):
    inbox = env.vault.root / "Knowledge" / "Inbox"
    make_text_pdf(inbox / "a.pdf", [SPA_TEXT])
    make_text_pdf(inbox / "b.pdf", [SPA_TEXT + " Two."])
    code, out = run(env, capsys, "add", "--inbox")
    assert code == 0 and out.startswith("Read a.pdf (1 page, 0 scanned) — doc ") and env.spawned == []


def test_documents_read_while_a_folder_is_written_wait_behind_it(env, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "wiki_active", lambda vault: True)
    code, out = run(env, capsys, "add", *map(str, pdfs(tmp_path, 2)))
    lines = out.strip().splitlines()
    assert code == 0 and lines[0].startswith("Read doc0.pdf") and kb_cli.NEXT not in out
    assert lines[-1] == "A folder is being written into the wiki; I'll add these after it (about 2 minutes)."
    job = jobs.load(env.vault, env.spawned[0])
    assert job.wiki_status == "waiting" and sorted(job.wiki_docs) == sorted(d.doc_id for d in store.all_docs(env.vault))


def test_a_document_already_read_names_its_page(env, capsys, tmp_path):
    spa = pdfs(tmp_path, 1)[0]
    run(env, capsys, "add", str(spa))
    doc = store.all_docs(env.vault)[0]
    with_page(env, doc)
    code, out = run(env, capsys, "add", str(spa))
    assert code == 0 and out.strip() == f"Already read doc0.pdf — doc {doc.doc_id} (page: [[Purchase agreement (2025-01-21)]])"


def test_show_names_the_page_and_forget_keeps_it_and_says_so(env, capsys, tmp_path):
    run(env, capsys, "add", str(pdfs(tmp_path, 1)[0]))
    doc = store.all_docs(env.vault)[0]
    path = with_page(env, doc)
    code, out = run(env, capsys, "show", doc.doc_id, "--pages", "1")
    assert "Page: [[Purchase agreement (2025-01-21)]]" in out
    code, out = run(env, capsys, "forget", doc.doc_id)
    assert code == 0 and out.strip().endswith(
        "Its page [[Purchase agreement (2025-01-21)]] is still there; delete it or keep it.")
    assert path.exists()
    log = (env.vault.knowledge_dir / "log.md").read_text(encoding="utf-8")
    assert f"] forget | doc0.pdf (doc {doc.doc_id}); its page [[Purchase agreement (2025-01-21)]] was kept\n" in log


@pytest.mark.parametrize("state", ["fresh", "after a batch", "tools missing"])
def test_idle_status_never_says_reading(env, capsys, tmp_path, monkeypatch, state):
    if state == "after a batch":
        folder = tmp_path / "F"
        folder.mkdir()
        make_text_pdf(folder / "a.pdf", [SPA_TEXT])
        run(env, capsys, "add", str(folder))
        jobs.run(env.vault, env.spawned[0], embedder=fake_embed)
    if state == "tools missing":
        monkeypatch.setattr(tools, "missing", lambda: ["fastembed"])
    code, out = run(env, capsys, "status")
    assert code == 0 and jobs.IDLE in out and "reading" not in out.lower()
    if state == "after a batch":
        assert "Last batch finished " in out and ": 1 document read, 0 couldn't be read." in out


def test_status_shows_a_waiting_wiki_run_and_cancel_stops_it(env, capsys):
    doc = stored_doc(env.vault, "a.pdf", ["A"])
    job = jobs.create_wiki(env.vault, [doc.doc_id], label="the Leases folder")
    code, out = run(env, capsys, "status")
    assert "Waiting to write the Leases folder into the wiki (since " in out
    code, out = run(env, capsys, "status", "--cancel")
    assert "weren't written" in out and jobs.load(env.vault, job.job_id).wiki_status == "cancelled"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_kb_add.py tests/test_kb_cli.py -q`
Expected: FAIL — old output ("Read 1 document (…") and `kb_cli` has no `NEXT`.

- [ ] **Step 3: Implement**

`core/Engine/bron/kb/ingest.py` — after `summary` (line 482) add:

```python
def lines(docs: list[Doc], notes: list[str] | tuple = ()) -> str:
    """What `bron kb add` prints in a conversation: one line per document, with its id for `bron kb show`, then the
    links that weren't found."""
    out: list[str] = []
    for d in docs:
        if d.status == "read":
            out.append(f"Read {d.name} ({plural(d.pages, 'page')}, {d.scanned} scanned) — doc {d.doc_id}")
        elif d.status == "unchanged":
            page = f"page: [[{Path(d.page).stem}]]" if d.page else "no page yet"
            out.append(f"Already read {d.name} — doc {d.doc_id} ({page})")
        else:
            out.append(f"Couldn't read {d.name}: {d.error}")
    out += [str(n) for n in notes]
    return "\n".join(out) if out else "There was nothing to read."
```

`core/Engine/bron/kb/cli.py`:
- imports (line 4): `import re` and `from pathlib import Path`.
- replace the constants `FOREGROUND = 5`, `FOREGROUND_PAGES = 50`, `SECONDS_PER_PAGE …` and `SETTING_UP = …` (lines 11-13 and 16) with:

```python
FOREGROUND = 3  # up to 3 documents are read in the conversation; a folder, or more, in the background
FOREGROUND_SECONDS = 300  # …and only while they read in about 5 minutes, so a command never outlasts its 10-minute limit
TEXT_SECONDS_PER_PAGE = 0.05
SCAN_SECONDS_PER_PAGE = 1.0  # Mac text recognition
SECONDS_PER_PAGE = 0.2  # a mix of text and scanned pages, for estimates of what isn't opened
BACKGROUND = "Reading {count} into the wiki in the background ({duration}); I'll report when it's done."
BEHIND = "A folder is being written into the wiki; I'll add these after it ({duration})."
NEXT = "Next: load the read-documents skill, write their wiki pages, then run `.bron/bin/bron wiki done`."
```

- replace `_queue`, `_add_export` and `_add` (lines 172-238) with:

```python
def _queue(vault, items, failed, *, again: bool, label: str, pages: int) -> int:
    """Read in the background, then write the wiki pages in the same background job."""
    from . import jobs, wiki_run

    ahead = sum(len(j.wiki_docs) for j in jobs.wiki_pending(vault))
    behind = bool(ahead) or jobs.wiki_active(vault)
    job = jobs.create(vault, items, failed=failed, again=again, wiki=True, label=label)
    if not jobs.spawn(vault, job.job_id):
        print("Bron couldn't start reading in the background (.bron/bin/bron is missing). Run `.bron/bin/bron check`.")
        return 1
    duration = _duration(pages * SECONDS_PER_PAGE + (ahead + len(items)) * wiki_run.SECONDS_PER_DOC)
    print(BEHIND.format(duration=duration) if behind
          else BACKGROUND.format(count=_plural(len(items), "document"), duration=duration))
    return 0


def _report(vault, docs, notes) -> int:
    """What was read in the conversation; then either "write their pages now" or, while a background wiki run is
    writing, queue them behind it (one wiki writer at a time)."""
    from . import ingest, jobs, wiki_run

    print(ingest.lines(docs, notes))
    todo = [d.doc_id for d in docs if d.status == "read" or (d.status == "unchanged" and not d.page)]
    if todo:
        ahead = jobs.wiki_pending(vault)
        if ahead or jobs.wiki_active(vault):
            job = jobs.create_wiki(vault, todo)
            jobs.spawn(vault, job.job_id)  # if it can't start now, the next session or `bron kb status` starts it
            count = sum(len(j.wiki_docs) for j in ahead) + len(todo)
            print(BEHIND.format(duration=_duration(count * wiki_run.SECONDS_PER_DOC)))
        else:
            print(NEXT)
    return 0 if any(d.status in ("read", "unchanged") for d in docs) else 1


def _add_export(args, vault) -> int:
    from ..loader import load
    from . import ingest, tools

    if args.targets or args.inbox:
        print("--file reads one exported Google file on its own. Run it separately from other links, paths or --inbox.")
        return 1
    if not (args.file and args.source and args.name):
        print("To add an exported Google Doc, give all three: --file <text file> --source <Drive link> --name '<title>'.")
        return 1
    ingest.export_item(args.file, args.source, args.name)  # a plain error now: the link, the file, or not text
    tools.ensure(vault)  # the first time, the tools are set up right here
    doc = ingest.add_export(vault, load(vault), args.file, args.source, args.name, embedder=_embedder(vault))
    return _report(vault, [doc], [])


def _sizes(items) -> tuple[int, float]:
    """Pages and estimated reading seconds of a few documents (PDFs on this Mac are opened to count them)."""
    from . import ingest

    pages, seconds = 0, 0.0
    for item in items:
        n = ingest.page_count(item)
        pages += n
        seconds += n * (SCAN_SECONDS_PER_PAGE if ingest.looks_scanned(item) else TEXT_SECONDS_PER_PAGE)
    return pages, seconds


def _add(args, vault) -> int:
    from ..loader import load
    from . import ingest, jobs, sources, tools

    if args.file or args.source or args.name:
        return _add_export(args, vault)
    if not args.targets and not args.inbox:
        print("Tell me what to read: a Google Drive link, a file or folder path, a web link, or --inbox.")
        return 1
    found = sources.resolve_targets(vault, args.targets, inbox=args.inbox)
    items, seen = [], set()
    for item in found.items:  # the same file named twice is read once
        if item.identity not in seen:
            seen.add(item.identity)
            items.append(item)
    if not items:
        if found.failed:
            print("\n".join(found.failed))
            return 1
        print("The inbox (Knowledge/Inbox) is empty." if args.inbox and not args.targets else "There's nothing to read there.")
        return 0
    few = len(items) <= FOREGROUND and not found.folders
    if few:
        tools.ensure(vault)  # the first time, the tools are set up right here (a few minutes; one line says so)
        pages, seconds = _sizes(items)
    else:
        # Many files are estimated from their size, so nothing is downloaded from Drive before the user says yes.
        pages, seconds = (0 if args.yes else sum(ingest.guess_pages(item) for item in items)), 0.0
    if not args.yes and (len(items) > MAX_DOCS or pages > MAX_PAGES):
        print(_ask_first(vault, len(items), pages))
        return 0
    if not few or seconds > FOREGROUND_SECONDS or jobs.runner_active(vault):  # never two readers at once
        label = f"the {found.folders[0]} folder" if len(found.folders) == 1 else ""
        return _queue(vault, items, found.failed, again=args.again, label=label, pages=pages)
    cfg, embedder = load(vault), _embedder(vault)
    docs = [ingest.read_item(vault, cfg, item, embedder=embedder, again=args.again) for item in items]
    return _report(vault, docs, found.failed)
```

- `_show`: after the `Title:` lines (305-306) add `if doc.page: print(f"Page: [[{Path(doc.page).stem}]]")`.
- replace `_forget` (lines 379-394) with:

```python
def _forget(args, vault) -> int:
    from . import store, wiki

    doc = _find(vault, args.doc)
    if doc is None:
        return 1
    if _tools_ready():
        from . import index

        index.drop(vault, doc.doc_id)
    else:
        _drop_index_files(vault)
    store.forget(vault, doc.doc_id)
    kept = " Its copy in Knowledge/Files is still there." if doc.kind == "file" else ""
    text = f"Forgot {doc.name}; searches won't find it any more. The original wasn't touched.{kept}"
    note = f"{doc.name} (doc {doc.doc_id})"
    if doc.page:  # the page isn't deleted: the check flags it until the user decides
        title = Path(doc.page).stem
        text += f" Its page [[{title}]] is still there; delete it or keep it."
        note += f"; its page [[{title}]] was kept"
    print(text)
    wiki.append_log(vault, [("forget", note)])
    return 0
```

- `_status` (lines 458-492): the cancel branch becomes

```python
    if args.cancel:
        if not jobs.pending(vault) and not jobs.wiki_pending(vault):
            print("Nothing is being read, so there's nothing to cancel.")
            return 0
        reports = jobs.cancel(vault)
        for text in reports:
            print(text)
        if jobs.runner_active(vault):
            print("Bron stops after the document it's reading now and reports what it read.")
        if jobs.wiki_active(vault):
            print("Bron finishes the wiki pages it's writing now.")
        return 0
```

  the missing-tools line becomes `print("The knowledge base tools aren't installed yet; Bron sets them up the first time you add or search.")`, and the stalled line becomes `print("Bron stopped before it finished; it's picking it up again in the background.")`.

- [ ] **Step 4: Run the tests**

Run: `uv run --project core/Engine pytest tests/test_kb_add.py tests/test_kb_cli.py tests/test_kb_ingest.py tests/test_kb_wiki_run.py -q`
Expected: PASS.

- [ ] **Step 5: Run everything and commit**

Run: `uv run --project core/Engine pytest tests -q` — Expected: PASS.

```bash
git add core/Engine/bron/kb/cli.py core/Engine/bron/kb/ingest.py tests/test_kb_cli.py tests/test_kb_add.py
git commit -m "kb add: up to 3 documents in the conversation, folders into the wiki in the background

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The `read-documents` skill and the AGENTS.md rules (spec §5.1 steps 2–4, §6.2, §7.2, §8)

**Files:**
- Create: `core/Skills/read-documents/SKILL.md`
- Modify: `core/Templates/AGENTS.md.tmpl:51-57` (Knowledge base section)
- Modify: `tests/test_kb_health.py:79-96` (`test_agents_md_has_the_knowledge_section_and_its_commands_parse`)
- Test: `tests/test_kb_wiki_skill.py` (create)

**Interfaces:**
- Consumes: every command the text names must exist and parse: `kb add` (incl. `--file/--source/--name`, `--inbox`), `kb show <doc> --pages`, `kb search '<q>' [--organisation X] [--type T] [--pages-only]`, `kb forget`, `wiki done [--log]`, `wiki check [--all]` (Tasks 5, 6, 8).
- Produces: core skill `read-documents` (auto-discovered by `loader._skills`, synced to both CLIs); the AGENTS.md Knowledge base section (≤ 1,600 characters).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kb_wiki_skill.py`:

```python
"""The read-documents skill (the wiki maintainer's procedure) and the short rules in AGENTS.md."""
import re
import shlex
from pathlib import Path

from bron import frontmatter as fm
from bron.agents_md import render_agents_md
from bron.cli import build_parser
from bron.loader import load

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "core" / "Skills" / "read-documents" / "SKILL.md"


def commands(text):
    return re.findall(r"\.bron/bin/bron\s+[^\n`]+", text)


def parse(cmd):
    norm = cmd.replace(".bron/bin/bron", "").strip()
    norm = re.sub(r"\s*\[.*?\]\s*", " ", norm)
    norm = re.sub(r"<[^>]*>", "x", norm).replace("…", "x").replace("N-M", "1-2")
    build_parser().parse_args(shlex.split(" ".join(norm.split())))


def knowledge_section(vault):
    return render_agents_md(load(vault)).split("## Knowledge base", 1)[1].split("\n## ", 1)[0]


def test_the_skill_is_a_core_skill_with_the_whole_procedure(vault):
    assert "read-documents" in load(vault).skills
    meta = fm.read(SKILL).meta
    assert meta["name"] == "read-documents" and "Knowledge/" in meta["description"]
    text = SKILL.read_text(encoding="utf-8")
    for must in ("Knowledge/Schema.md", "kb show", "--pages-only", "wiki done", "(see [[", "previously", "**Conflict:**",
                 "two or more documents", "Your edits win", "## Judgement checkup", "Check the wiki", "wiki check --all",
                 "Save this as a page?", "finish the wiki pages", "Never poll", "index.md", "log.md",
                 "never go and fetch", "doc_type", "organisation:", "Background runs"):
        assert must in text, must
    found = commands(text)
    assert len(found) >= 6
    for cmd in found:
        parse(cmd)


def test_agents_md_points_to_the_skill_and_the_drive_rules(vault):
    section = knowledge_section(vault)
    assert len(section) <= 1600
    for must in ("read-documents", "Drive link", "Google Doc, Sheet or Slides", "Never download or copy a Drive file",
                 "Never poll", "Save this as a page?", "--organisation", "Knowledge/Schema.md", "wiki done"):
        assert must in section, must
    assert "kb label" not in section
```

In `tests/test_kb_health.py` replace `test_agents_md_has_the_knowledge_section_and_its_commands_parse` (lines 79-96) with:

```python
def test_agents_md_has_the_knowledge_section_and_its_commands_parse(vault):
    text = render_agents_md(load(vault))
    assert "## Knowledge base" in text
    section = text.split("## Knowledge base", 1)[1].split("\n## ", 1)[0]
    assert len(section) <= 1600
    commands = re.findall(r"\.bron/bin/bron\s+[^\n`]+", section)
    assert len(commands) >= 6
    parser = build_parser()
    for cmd in commands:
        for keep in (False, True):
            norm = cmd.replace(".bron/bin/bron", "").strip()
            norm = re.sub(r"\[(.*?)\]", r"\1", norm) if keep else re.sub(r"\s*\[.*?\]\s*", " ", norm)
            norm = re.sub(r"<[^>]*>", "x", norm).replace("N-M", "1-2").replace("...", "")
            parser.parse_args(shlex.split(" ".join(norm.split())))
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki_skill.py tests/test_kb_health.py -q`
Expected: FAIL — the skill file doesn't exist; the AGENTS section has no `read-documents`.

- [ ] **Step 3: Write the skill and the rules**

Create `core/Skills/read-documents/SKILL.md` with exactly this content:

````markdown
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

When all the documents are done, run `.bron/bin/bron wiki done`. It records the document pages, updates the search database, `index.md` and `log.md`, and checks what changed. Fix every problem it lists (a broken link, a missing `summary`…) and run it again until it lists none.

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

Put links and the doc id in properties in quotes (`"[[Name]]"`, `"3f2a…"`) so they're read correctly.

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
- **Forgotten** (`bron kb forget` said its page is still there): ask the user whether to delete the page. If they keep it, remove its `doc` property so the check stops flagging it, and say in its summary that the document was removed.

## Never

- download or copy a Drive file, or put a document into `Knowledge/` yourself (only `bron kb add` keeps copies, in `Knowledge/Files/`);
- edit `index.md` or `log.md`;
- poll `bron kb status`;
- invent a fact, a number or a citation;
- decide a real conflict for the user.
````

In `core/Templates/AGENTS.md.tmpl` replace the Knowledge base section (lines 51-57: the heading stays, its four bullet lines and intro line go) with:

```markdown
## Knowledge base

`Knowledge/` is a wiki you keep: a page per document, plus organisation, person and topic pages (rules: `Knowledge/Schema.md`). The documents themselves stay where they are.
- Read: `.bron/bin/bron kb add '<link or path>' [...]` (`--inbox` for the inbox). A Drive link always goes to `kb add` first. Only a Google Doc, Sheet or Slides file is exported through the Drive connection, then `.bron/bin/bron kb add --file <file> --source '<link>' --name '<title>'`. Never download or copy a Drive file; if Bron can't find one, ask the user to check that Google Drive for desktop shows it. The first `bron kb` command in a vault can take a few minutes; use a long command timeout (10 minutes). Never poll `kb status`.
- Then load the read-documents skill, write the pages, and run `.bron/bin/bron wiki done`. A folder is read and written in the background and reported when done.
- Answer: `.bron/bin/bron kb search '<question>' [--organisation X] [--type T]` (wiki pages, then passages). Open a page if the excerpt isn't enough, check numbers against the passages, cite the document page, page number and link, and say so when nothing answers it. More text: `.bron/bin/bron kb show '<document>' --pages N-M`.
- After an answer that combined several documents, ask "Save this as a page?"; on yes, follow the read-documents skill.
- Remove: `.bron/bin/bron kb forget '<document>'`; problems: `.bron/bin/bron wiki check`.
```

(The section measures about 1,415 characters; the test allows 1,600.)

- [ ] **Step 4: Run the tests**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki_skill.py tests/test_kb_health.py tests/test_gen_claude.py tests/test_gen_codex.py tests/test_sync.py tests/test_loader.py -q`
Expected: PASS (the new core skill is synced like the others).

- [ ] **Step 5: Run everything and commit**

Run: `uv run --project core/Engine pytest tests -q` — Expected: PASS.

```bash
git add core/Skills/read-documents/SKILL.md core/Templates/AGENTS.md.tmpl tests/test_kb_wiki_skill.py tests/test_kb_health.py
git commit -m "Add the read-documents skill; AGENTS.md knowledge rules for the wiki

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Manual, CHANGELOG 0.8.0, wording check and the live test per CLI (spec §8 manual, §11, §12)

**Files:**
- Modify: `core/Manual/knowledge.md` (rewrite), `core/Manual/index.md` (the knowledge row), `CHANGELOG.md` (complete the `## 0.8.0` section from Task 3)
- Modify: `tests/live/test_knowledge.py` (rewrite)
- Test: `tests/test_kb_wiki_wording.py` (create); `tests/test_kb_health.py:107-112` (manual sentence test stays as is)

**Interfaces:**
- Consumes: everything above. The live test uses `scripts/dev-vault.sh <folder>` (as today), `kbkit.make_text_pdf`, `kbkit.set_drive_id`, `vaultkit.set_meta`, and the real `claude` / `codex` CLIs.
- Produces: no code.

- [ ] **Step 1: Write the failing test**

Create `tests/test_kb_wiki_wording.py`:

```python
"""Bron is a general framework: the wiki text it ships is domain-neutral and carries no personal data."""
import re
from pathlib import Path

import pytest

from bron.agents_md import render_agents_md
from bron.loader import load

REPO = Path(__file__).resolve().parents[1]
DOMAIN = re.compile(r"\b(funds?|fundo|venture|VC|portfolio|investors?|investments?|LPA|capital calls?|cap tables?|"
                    r"term sheets?|side letters?|K-1)\b", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
SHIPPED = ["core/Skills/read-documents/SKILL.md", "core/Templates/Schema.md", "template/Knowledge/Schema.md",
           "template/Knowledge/index.md", "template/Knowledge/log.md", "core/Manual/knowledge.md"]


@pytest.mark.parametrize("rel", SHIPPED)
def test_shipped_wiki_text_is_domain_neutral(rel):
    text = (REPO / rel).read_text(encoding="utf-8")
    assert DOMAIN.findall(text) == [] and EMAIL.findall(text) == []


def test_the_0_8_0_release_notes_and_the_agents_rules_are_domain_neutral(vault):
    notes = (REPO / "CHANGELOG.md").read_text(encoding="utf-8").split("## 0.8.0", 1)[1].split("\n## ", 1)[0]
    section = render_agents_md(load(vault)).split("## Knowledge base", 1)[1].split("\n## ", 1)[0]
    for text in (notes, section):
        assert DOMAIN.findall(text) == [] and EMAIL.findall(text) == []
    for must in ("wiki", "Schema.md", "bron wiki check", "--organisation", "bron kb label", "Nothing is being read."):
        assert must in notes, must


def test_the_manual_explains_the_wiki():
    text = (REPO / "core" / "Manual" / "knowledge.md").read_text(encoding="utf-8")
    for must in ("Knowledge/Schema.md", "index.md", "log.md", "read-documents", "bron wiki check", "--pages-only",
                 "--organisation", "finish the wiki pages", "Online-only files are downloaded as they're read",
                 "never copies", "two or more documents", "previously", "Karpathy"):
        assert must in text, must
    assert "kb label" not in text and "labels: false" not in text
```

- [ ] **Step 2: Run it to see it fail**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki_wording.py -q`
Expected: FAIL — the manual still has the 0.7 text (`kb label`, `labels: false`, no `Schema.md`); the CHANGELOG section has only its first line.

- [ ] **Step 3: Write the manual, the release notes and the live test**

Replace `core/Manual/knowledge.md` with exactly:

````markdown
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
- **A folder, or more than three documents,** is read and written into the wiki in the background; you keep working. One agent works through the documents one after another and checks the pages it touched; its summary reaches you like any ticket update, in your next message or briefing. One folder is written at a time: anything you add meanwhile waits its turn ("A folder is being written into the wiki; I'll add these after it").
- The very first reading sets up the reading and search tools (about 300 MB, a few minutes).
- A document Bron already read is skipped when it hasn't changed (`--again` reads it anyway). Reading a document again replaces its text, and the agent updates its page.
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

- The health check counts wiki problems: links to pages that don't exist, pages nothing links to, pages missing `type` or `summary`, documents read without a page, pages whose document was forgotten, probable duplicates (Acme, Acme Ltda.) and pages over 30,000 characters. `.bron/bin/bron wiki check` shows them; `--all` lists every one.
- After each folder, the agent rereads the pages it touched: it settles changes a newer document clearly makes, flags real conflicts to you, creates pages for names that now appear in two or more documents, and lists gaps (a document that's referred to but wasn't read) as suggestions.
- Say "check the wiki" for a full checkup, or "finish the wiki pages" to write the pages of documents that were read without one (an interrupted run, or documents read before the wiki existed).

## Looking after it

- `.bron/bin/bron kb list` shows what was read (`--failed` only what couldn't be, `--organisation` and `--type` narrow it).
- `.bron/bin/bron kb forget '<document>'` removes a document from the knowledge base; the original is never touched. Its wiki page stays until you delete it or keep it (the check reminds you).
- `.bron/bin/bron kb status` shows what's being read or written; `--cancel` stops it. When nothing is happening it says "Nothing is being read."

## Privacy

- Everything stays in your vault: the text and search database in `.bron/kb/`, the wiki in `Knowledge/`. Scanned pages are read on your Mac; search runs on your Mac.
- Your agents read the documents' text and write the pages with your Claude or Codex plan (the same login you use to talk to Bron). A folder in the background is one agent run.
- A page too messy for Mac text recognition (a bad scan, a photo) is sent as an image to your plan's model. Turn it off with `knowledge: model_pages: false` in `System/Settings.md`; `max_model_pages` (default 20) limits the pages per document. Each one is logged in `.bron/kb/model-log.jsonl`.
- No document text is sent to a model just to label it: a document's organisation, type and date come from its wiki page (before it has one, from its file and folder names).

## Limits

- A short page (under 50 words, like a cover or signature page) is joined to the next page in search results; the text then shows `[p. N]` where each page starts, and the agent cites that page.
- A badly scanned page can still contain misread characters, so check the numbers that matter against the original.
- Charts and pictures inside documents are not described.
- A background run stops after the time limit in `System/Settings.md` (`runner: max_minutes`, 30 by default); a very large folder may not finish. What was read stays searchable, the documents without a page show up in the check, and "finish the wiki pages" picks them up.
- If the meaning-search model can't be downloaded (no internet, say), documents are still read and found by their words; meaning search starts once the model downloads.
````

In `core/Manual/index.md` replace the knowledge row with:

```markdown
| [knowledge.md](knowledge.md) | The knowledge wiki: reading documents into it (Drive, files, inbox), asking questions with citations, checkups and privacy |
```

Complete the `## 0.8.0` section of `CHANGELOG.md` (keep the migration line Task 3 added as the last bullet):

```markdown
## 0.8.0
- Reading a document now builds a wiki in Knowledge/: a page per document, plus pages for the organisations, people and topics in it, linked to each other and citing the document and page. After reading, Bron tells you in a few lines what it learned, what changed or contradicted earlier pages, and which pages it touched.
- A folder, or more than three documents, is read and written into the wiki in the background while you keep working; the summary arrives when it's done. Up to three documents are read right away, scans and the first-time setup included.
- Search shows wiki pages first, then the exact passages in the documents. `--organisation` narrows it (`--company` still works) and `--pages-only` shows only pages. After an answer that combined several documents, Bron offers to save it as a page.
- Knowledge/Schema.md holds the wiki's rules: page types, document types and naming. Edit it to fit your work; the document types you set in System/Settings.md move there.
- `bron wiki check` and the health check find broken links, pages nothing links to, documents without a page and probable duplicates. Say "check the wiki" for a full checkup.
- No document text is sent to a model just to label it any more: a document's organisation, type and date come from its wiki page. `bron kb label` and the `knowledge: labels` setting are gone; edit the page's properties instead.
- Fixes: folders shared with you in Google Drive are found; `bron kb add --file` takes only exported text; `bron kb status` says "Nothing is being read." when nothing is.
- Your knowledge base becomes a wiki: Knowledge/ gets Schema.md (its rules, with your document types), index.md, log.md and folders for documents, organisations, people and topics.
```

Replace `tests/live/test_knowledge.py` with:

```python
"""Live knowledge wiki, in each CLI: a session reads a Drive file shared with the user into the wiki, a folder is
written into the wiki in the background, and a question is answered from the pages with a citation.
Downloads the meaning model (about 220 MB) and installs the reading tools into each temporary vault on first use.
The vaults, the fake Google Drive folder and the search helper's socket folder are temporary, and the helper is stopped
at the end. The CLI sessions themselves log to the real home (~/.claude/projects, ~/.codex/sessions), because both apps
need their real login.
Run with: BRON_LIVE=1 uv run --project core/Engine pytest tests/live/test_knowledge.py -q -s"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("BRON_LIVE") != "1", reason="live CLI test: set BRON_LIVE=1")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests"))

LEASE = ["Lease agreement between Northwind Properties Ltd (landlord) and Harbor Bakery LLC (tenant) for shop 4, "
         "12 Example Street. Signed on March 1, 2025.",
         "Clause 3. The monthly rent is USD 4,200.00, due on the first day of each month. The lease runs for three "
         "years from March 1, 2025."]
FOLDER = {
    "invoice-2025-04.pdf": ["Invoice 1042 from Northwind Properties Ltd to Harbor Bakery LLC, dated April 1, 2025.",
                            "Rent for April 2025 for shop 4: USD 4,200.00. Payment due April 10, 2025."],
    "rent-increase-2026.pdf": ["Letter from Northwind Properties Ltd to Harbor Bakery LLC, dated January 10, 2026.",
                               "From March 1, 2026 the monthly rent for shop 4 is USD 4,450.00, as clause 3 of the "
                               "lease allows."],
    "insurance-2025.pdf": ["Insurance policy for Harbor Bakery LLC, shop 4, 12 Example Street, from May 1, 2025.",
                           "Cover: fire and water damage up to USD 250,000.00. Yearly premium: USD 1,180.00."],
}


def bron(vault: Path, *args: str, timeout: int = 1800) -> str:
    done = subprocess.run([str(vault / ".bron" / "bin" / "bron"), *args], cwd=vault, capture_output=True, text=True,
                          timeout=timeout)
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def stop_helper(vault: Path) -> None:
    """Stop the warm search helper this vault started (the one whose working folder is the vault)."""
    found = subprocess.run(["pgrep", "-f", "kb serve"], capture_output=True, text=True).stdout.split()
    for pid in found:
        where = subprocess.run(["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"], capture_output=True, text=True).stdout
        if f"n{vault}" in where.splitlines():
            subprocess.run(["kill", pid])


def fake_drive(account: Path) -> Path:
    """Google Drive for desktop's layout: My Drive with a folder, and a file in a folder shared with the user."""
    from kbkit import make_text_pdf, set_drive_id

    my_drive = account / "My Drive"
    shared = account / ".shortcut-targets-by-id" / "SHAREDLEASE" / "Shared with me"
    shared.mkdir(parents=True)
    my_drive.mkdir(parents=True)
    set_drive_id(make_text_pdf(shared / "lease.pdf", LEASE), "LEASE1")
    folder = my_drive / "Shop 4"
    folder.mkdir()
    set_drive_id(folder, "SHOP4")
    for i, (name, pages) in enumerate(FOLDER.items()):
        set_drive_id(make_text_pdf(folder / name, pages), f"SHOPFILE{i}")
    return my_drive


@pytest.fixture(scope="module", params=["claude", "codex"])
def vault(request, tmp_path_factory):
    from vaultkit import set_meta

    cli = request.param
    if not shutil.which(cli):
        pytest.skip(f"{cli} is not installed")
    socket_dir = tempfile.mkdtemp(prefix="bk", dir="/tmp")  # private, short: socket paths are limited in length
    os.chmod(socket_dir, 0o700)
    before = {key: os.environ.get(key) for key in ("BRON_KB_SOCKET_DIR", "BRON_DRIVE_ROOT")}
    base = tmp_path_factory.mktemp(f"wiki-{cli}")
    root = base / "Wiki Vault"
    try:
        os.environ["BRON_KB_SOCKET_DIR"] = socket_dir
        os.environ["BRON_DRIVE_ROOT"] = str(fake_drive(base / "GoogleDrive-test"))
        subprocess.run([str(REPO / "scripts" / "dev-vault.sh"), str(root)], check=True)
        root = root.resolve()
        set_meta(root / "System" / "Settings.md", default_cli=cli)  # the background run uses this CLI
        bron(root, "sync")
        started = time.time()
        bron(root, "kb", "search", "warm up")  # installs the tools and loads the model, outside the timings
        print(f"\n[{cli} setup] {time.time() - started:.0f}s")
        yield cli, root
    finally:
        stop_helper(root)
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(socket_dir, ignore_errors=True)


def ask(cli: str, vault: Path, prompt: str) -> str:
    if cli == "claude":
        done = subprocess.run(["claude", "-p", prompt, "--permission-mode", "acceptEdits",
                               "--allowedTools", "Bash(.bron/bin/bron *)"],
                              cwd=vault, capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout
    last = vault.parent / "last-answer.txt"
    last.unlink(missing_ok=True)
    done = subprocess.run(["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", "-o", str(last), prompt],
                          cwd=vault, capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    assert done.returncode == 0, done.stdout + done.stderr
    return last.read_text(encoding="utf-8") if last.exists() else done.stdout


def wait_until_idle(vault: Path, started: float, limit: float = 1800) -> str:
    while True:
        status = bron(vault, "kb", "status")
        if "Nothing is being read." in status and "Last batch" in status:
            return status
        assert time.time() - started < limit, status
        time.sleep(10)


def pages(vault: Path, folder: str) -> list[Path]:
    return sorted((vault / "Knowledge" / folder).glob("*.md"))


def test_reading_a_shared_drive_file_takes_seconds(vault):
    cli, root = vault
    started = time.time()
    out = bron(root, "kb", "add", "https://drive.google.com/file/d/LEASE1/view")
    seconds = time.time() - started
    print(f"\n[{cli} extract] {seconds:.1f}s\n{out}")
    assert out.startswith("Read lease.pdf (2 pages, 0 scanned) — doc ") and seconds < 5


def test_one_document_is_read_into_the_wiki_in_a_conversation(vault):
    cli, root = vault
    started = time.time()
    answer = ask(cli, root, "Read this document into the wiki: https://drive.google.com/file/d/LEASE1/view")
    seconds = time.time() - started
    print(f"\n[{cli} one document] {seconds:.1f}s\n{answer}")
    found = pages(root, "Documents")
    assert found, "no document page was written"
    text = found[0].read_text(encoding="utf-8")
    assert "doc:" in text and re.search(r"p\. ?2", text) and "[[" in text
    assert "] ingest | [[" in (root / "Knowledge" / "log.md").read_text(encoding="utf-8")
    assert f"[[{found[0].stem}]]" in (root / "Knowledge" / "index.md").read_text(encoding="utf-8")
    assert seconds < 60


def test_a_folder_is_written_into_the_wiki_in_the_background(vault):
    cli, root = vault
    started = time.time()
    out = bron(root, "kb", "add", "https://drive.google.com/drive/folders/SHOP4")
    print(f"\n[{cli} folder] {out}")
    assert out.startswith("Reading 3 documents into the wiki in the background")
    status = wait_until_idle(root, started)
    print(f"[{cli} folder done] {time.time() - started:.0f}s\n{status}")
    assert len(pages(root, "Documents")) >= 4 and pages(root, "Organisations")
    assert "Read the Shop 4 folder into the wiki" in bron(root, "ticket", "list")
    assert "] check | " in (root / "Knowledge" / "log.md").read_text(encoding="utf-8")
    print(bron(root, "wiki", "check"))


def test_nothing_from_drive_was_copied_into_the_vault(vault):
    _, root = vault
    assert [p for p in root.rglob("*.pdf") if ".bron" not in p.parts] == []


def test_a_question_is_answered_from_the_wiki_with_a_citation(vault):
    cli, root = vault
    started = time.time()
    answer = ask(cli, root, "What is the monthly rent for shop 4 now, and what was it before? Cite your sources.")
    print(f"\n[{cli} question] {time.time() - started:.1f}s\n{answer}")
    assert "4,450" in answer and "4,200" in answer
    assert re.search(r"(p\.|page|p[aá]gina)\s*2\b", answer, re.I), answer
```

- [ ] **Step 4: Run the tests**

Run: `uv run --project core/Engine pytest tests/test_kb_wiki_wording.py tests/test_kb_health.py -q` — Expected: PASS.
Run: `uv run --project core/Engine pytest tests -q` — Expected: PASS (the live test is skipped without `BRON_LIVE=1`).
Run the live test once per CLI and keep the printed timings for the controller (needs both CLIs logged in; ~10–30 minutes): `BRON_LIVE=1 uv run --project core/Engine pytest tests/live/test_knowledge.py -q -s`. Expected: PASS for each installed CLI; extract < 5 s; one document < 60 s. If a timing target is missed but everything else passes, report the numbers instead of loosening the assertion.

- [ ] **Step 5: Commit**

```bash
git add core/Manual/knowledge.md core/Manual/index.md CHANGELOG.md tests/test_kb_wiki_wording.py tests/live/test_knowledge.py
git commit -m "Manual and release notes for the knowledge wiki; live test per CLI

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the last task (controller)

- Release with `scripts/release.sh 0.8.0` (not a task in this plan).
- Then offer the user (spec §12): remove the kept copy left by the 2026-10-04 test in their test vault, read that document again from its Drive link, and write their own version of `Knowledge/Schema.md` for their work.

## Spec coverage (self-review)

| Spec | Task |
|---|---|
| §3.1 idle status wording, never poll, foreground singles | 7 (status lines), 8 (kb add/status), 9 (AGENTS, skill) |
| §3.2 `.shortcut-targets-by-id` walk, direct folder-id path | 1 |
| §3.3 `--file` text only; Drive links first; never download/copy | 1 (code), 9 (AGENTS, skill), 10 (manual, live check) |
| §4.1 layout, page = any .md except the three and Inbox/Files, type = first folder | 3 (files), 4 (`page_paths`, `read_page`) |
| §4.2 properties, citations, "previously", names | 3 (Schema.md), 4 (`page_labels`), 9 (skill) |
| §4.3 page-creation rule | 3 (Schema.md), 9 (skill) |
| §4.4 Schema.md template, doc types, "your edits win" | 3 |
| §4.5 index.md (order, sources, dates), log.md (kinds) | 4 |
| §5.1 foreground ≤ 3, output lines, no label call, skill, `wiki done`, summary | 2, 8, 9 |
| §5.2 folder → background reading + wiki ticket via `run_ticket`, summary as ticket update, queue, status | 7, 8 |
| §5.3 `wiki done` steps 1–5 | 6 (uses 4, 5) |
| §5.4 sources unchanged except stated | 1 |
| §6.1 pages + passages, `--pages-only`, `--organisation`/`--company`, refresh from mtimes, helper serves both | 5 |
| §6.2 answering rules, "Save this as a page?" | 9 |
| §7.1 mechanical checks, `wiki check [--all]`, health check counts + first three | 6 |
| §7.2 judgement checkup after folders and on "check the wiki" | 7 (request), 9 (skill) |
| §8 label call, `kb label`, `knowledge.labels` removed; doc_types → Schema.md; forget reports page; thresholds; status; AGENTS ≤ 1,600; manual; CHANGELOG | 2, 3, 8, 9, 10 |
| §9 migration | 3 |
| §10 plain failures, `wiki done` never fails on one page, failed run → report + "finish the wiki pages" | 6, 7 |
| §11 unit tests listed; live per CLI with timings | 1–10 |
| §12 release notes; after-release offer | 10, controller |

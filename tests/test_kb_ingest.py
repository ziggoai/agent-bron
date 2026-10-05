import fcntl
import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from bron.kb import index, ingest, jobs, notices, search, sources, store
from bron.kb.sources import Item
from bron.kb.store import KbError
from bron.loader import load
from kbkit import (FakeModel, FakeOcr, fake_drive, fake_embed, hook_reads, make_scanned_pdf, make_text_pdf, set_drive_id)

SPA_TEXT = ("Share Purchase Agreement between Acme Ltda and the Fund. The purchase price is USD 2,000,000.00 "
            "payable at closing on January 21, 2025.")
JUMBLED = "\n".join(["Ano Receita (R$ mil) EBITDA", "2024 12.345", "1.234", "2025", "15.678", "2.001"])


@pytest.fixture
def kb(vault, tmp_path, monkeypatch):
    class Env:
        pass

    env = Env()
    env.vault = vault
    env.cfg = load(vault)
    env.ocr = FakeOcr()
    env.model = FakeModel("| Ano | Receita |\n| --- | --- |\n| 2024 | 12.345 |")
    env.deps = dict(readers_ocr=env.ocr, model_call=env.model, embedder=fake_embed)
    env.root = fake_drive(tmp_path)
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(env.root))

    def read(item):
        return ingest.read_item(vault, env.cfg, item, **env.deps)

    env.read = read
    return env


def drive_pdf(kb, name="spa.pdf", text=SPA_TEXT, item_id="SPA1"):
    folder = kb.root / "Acme"
    folder.mkdir(exist_ok=True)
    path = make_text_pdf(folder / name, [text])
    set_drive_id(path, item_id)
    items, failed = sources.resolve(kb.vault, [f"https://drive.google.com/file/d/{item_id}/view"])
    assert failed == []
    return path, items[0]


def find(vault, query, **kw):
    return search.search(vault, query, embedder=fake_embed, **kw)


# ---- reading one item ----

def test_drive_file_is_read_in_place_labelled_from_names_and_searchable(kb):
    path, item = drive_pdf(kb)
    doc = kb.read(item)
    assert doc.status == "read" and doc.identity == "drive:SPA1" and doc.path == str(path)
    assert doc.source == "https://drive.google.com/open?id=SPA1"
    assert doc.labels == {"company": "Acme", "doc_type": "other", "date": "", "title": "", "language": "other"}
    assert store.load(kb.vault, doc.doc_id) == doc
    assert not (kb.vault.root / "Knowledge" / "Files").exists() or not any((kb.vault.root / "Knowledge" / "Files").rglob("*.pdf"))
    hits = find(kb.vault, "purchase price")
    assert hits[0].doc_id == doc.doc_id and hits[0].page == 1 and hits[0].source == doc.source


def test_inbox_file_with_a_drive_id_is_kept_as_a_copy_and_removed_from_the_inbox(kb):
    inbox = kb.vault.root / "Knowledge" / "Inbox"
    original = make_text_pdf(inbox / "spa.pdf", [SPA_TEXT])
    set_drive_id(original, "DRAGGED1")  # dragged out of the Drive folder: keeps its attribute
    items, _ = sources.resolve(kb.vault, [], inbox=True)
    assert [i.kind for i in items] == ["file"]
    doc = kb.read(items[0])
    kept = kb.vault.root / "Knowledge" / "Files" / time.strftime("%Y-%m") / "spa.pdf"
    assert doc.status == "read" and kept.is_file() and not original.exists()
    assert doc.identity == f"file:{kept}" and doc.source == str(kept) and doc.path == str(kept)
    assert find(kb.vault, "purchase price")[0].source == str(kept)


def test_an_inbox_file_removed_just_before_an_interruption_is_read_from_its_copy(kb):
    inbox = kb.vault.root / "Knowledge" / "Inbox"
    make_text_pdf(inbox / "spa.pdf", [SPA_TEXT])
    item = sources.resolve(kb.vault, [], inbox=True)[0][0]
    first = kb.read(item)
    again = kb.read(item)  # the job hadn't written it down as done when it stopped
    assert again.status == "unchanged" and again.doc_id == first.doc_id  # the copy is the same file: not read again
    forced = ingest.read_item(kb.vault, kb.cfg, item, again=True, **kb.deps)
    assert forced.status == "read" and forced.doc_id == first.doc_id


def test_inbox_file_that_cannot_be_read_stays_in_the_inbox(kb):
    inbox = kb.vault.root / "Knowledge" / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    bad = inbox / "archive.zip"
    bad.write_bytes(b"PK")
    items, _ = sources.resolve(kb.vault, [], inbox=True)
    doc = kb.read(items[0])
    assert doc.status == "failed" and doc.error == "Bron can't read .zip files yet."
    assert bad.exists()
    assert not any((kb.vault.root / "Knowledge" / "Files").rglob("archive*"))
    assert store.load(kb.vault, doc.doc_id).status == "failed"
    assert store.passages(kb.vault, doc.doc_id) == []


def test_a_path_is_copied_once_and_reading_it_again_replaces_the_same_document(kb, tmp_path):
    (tmp_path / "notes").mkdir()
    original = make_text_pdf(tmp_path / "notes" / "memo.pdf", [SPA_TEXT])
    first = kb.read(sources.resolve(kb.vault, [str(original)])[0][0])
    make_text_pdf(original, ["Revised memo: the board approved the budget of BRL 3,000,000.00 for the next year."])
    second = kb.read(sources.resolve(kb.vault, [str(original)])[0][0])
    month = kb.vault.root / "Knowledge" / "Files" / time.strftime("%Y-%m")
    assert first.doc_id == second.doc_id and original.exists()
    assert sorted(p.name for p in month.iterdir()) == ["memo.pdf"]
    assert "Revised memo" in store.pages(kb.vault, second.doc_id)[0]
    other = tmp_path / "other"
    other.mkdir()
    third = kb.read(sources.resolve(kb.vault, [str(make_text_pdf(other / "memo.pdf", [SPA_TEXT]))])[0][0])
    assert third.doc_id != first.doc_id and Path(third.path).name == "memo (2).pdf"


def test_reread_keeps_user_labels(kb):
    path, item = drive_pdf(kb)
    doc = kb.read(item)
    doc.user_labels = {"company": "Acme Holdings", "doc_type": "SHA"}
    store.save(kb.vault, doc, store.pages(kb.vault, doc.doc_id), store.passages(kb.vault, doc.doc_id))
    make_text_pdf(path, ["Amended agreement: the purchase price is now USD 2,500,000.00 with an earn-out clause."])
    again = kb.read(item)
    assert again.doc_id == doc.doc_id
    assert again.user_labels == {"company": "Acme Holdings", "doc_type": "SHA"}
    assert store.effective_labels(again)["company"] == "Acme Holdings"
    assert "earn-out" in store.pages(kb.vault, doc.doc_id)[0]
    assert all("Acme Holdings" in p["header"] for p in store.passages(kb.vault, doc.doc_id))
    hits = find(kb.vault, "earn-out", company="holdings")
    assert hits and hits[0].doc_id == doc.doc_id
    assert not find(kb.vault, "closing")  # the old text is gone from the index


def test_a_failed_reread_keeps_the_previous_text(kb):
    path, item = drive_pdf(kb)
    doc = kb.read(item)
    path.write_bytes(b"this is not a pdf any more")
    again = kb.read(item)
    assert again.status == "failed" and "damaged" in again.error
    assert store.load(kb.vault, doc.doc_id).status == "read"
    assert find(kb.vault, "purchase price")[0].doc_id == doc.doc_id


def test_each_document_gets_its_own_work_folder(kb, tmp_path):
    a = make_scanned_pdf(tmp_path / "a.pdf", ["first scan"])
    b = make_scanned_pdf(tmp_path / "b.pdf", ["second scan"])
    items, _ = sources.resolve(kb.vault, [str(a), str(b)])
    texts = iter(["Scanned lease of shop one.", "Scanned lease of shop two."])  # two different documents, not copies
    docs = []
    for item in items:
        kb.ocr.text = next(texts)
        docs.append(kb.read(item))
    assert [d.status for d in docs] == ["read", "read"] and [d.scanned for d in docs] == [1, 1]
    assert [p.name for p in kb.ocr.images] == ["p1.png", "p1.png"]
    assert kb.ocr.images[0].parent != kb.ocr.images[1].parent
    assert not any(p.exists() or p.parent.exists() for p in kb.ocr.images)


def test_hard_pages_go_to_the_model_and_are_counted(kb, tmp_path):
    kb.ocr.text = JUMBLED
    item = sources.resolve(kb.vault, [str(make_scanned_pdf(tmp_path / "table.pdf", ["x"]))])[0][0]
    doc = kb.read(item)
    assert doc.scanned == 1 and doc.model_pages == 1 and len(kb.model.calls) == 1
    assert "| Ano | Receita |" in store.pages(kb.vault, doc.doc_id)[0]


def test_web_page_is_fetched_with_curl(kb, monkeypatch):
    seen = []

    def run(argv, **kw):
        seen.append(argv)
        html = "<html><body><h1>Fund news</h1><p>" + "The fund closed its second vehicle at USD 50 million. " * 5 + "</p></body></html>"
        return subprocess.CompletedProcess(argv, 0, html.encode(), b"")

    monkeypatch.setattr(ingest.subprocess, "run", run)
    item = sources.resolve(kb.vault, ["https://example.com/news#top"])[0][0]
    doc = kb.read(item)
    assert seen[0] == ["curl", "-fsSL", "--max-time", "30", "-A", "Mozilla/5.0 (Bron)", "https://example.com/news"]
    assert doc.status == "read" and doc.identity == "web:https://example.com/news" and doc.source == "https://example.com/news"
    assert "second vehicle" in store.pages(kb.vault, doc.doc_id)[0]


def test_unreachable_web_page_is_a_plain_failure(kb, monkeypatch):
    monkeypatch.setattr(ingest.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(
        argv, 6, b"", b"curl: (6) Could not resolve host: nope.example\n"))
    doc = kb.read(Item("web", "web:https://nope.example/x", "https://nope.example/x", "https://nope.example/x", "", "https://nope.example/x"))
    assert doc.status == "failed"
    assert doc.error == "Couldn't open https://nope.example/x (Could not resolve host: nope.example)."


def test_google_native_items_give_the_export_instruction(kb):
    stub = kb.root / "Board memo.gdoc"
    stub.write_text("{}")
    set_drive_id(stub, "DOC1")
    item = sources.resolve(kb.vault, [str(stub)])[0][0]
    doc = kb.read(item)
    assert item.kind == "native" and doc.status == "failed"
    assert doc.error.startswith("Export this Google Doc through the Drive connection, then run: bron kb add --file <text file> "
                                "--source https://drive.google.com/open?id=DOC1 --name 'Board memo'")


def test_export_is_read_as_that_document(kb, tmp_path):
    stub = kb.root / "Board memo.gdoc"
    stub.write_text("{}")
    set_drive_id(stub, "DOC1")
    native = kb.read(sources.resolve(kb.vault, [str(stub)])[0][0])
    text = tmp_path / "export.txt"
    text.write_text("\n\n".join(f"Paragraph {i}: the board discussed the follow-on investment in Acme. " * 4 for i in range(25)))
    doc = ingest.add_export(kb.vault, kb.cfg, text, "https://docs.google.com/document/d/DOC1/edit", "Board memo",
                            embedder=fake_embed)
    assert doc.doc_id == native.doc_id and doc.status == "read" and doc.identity == "drive:DOC1"
    assert doc.name == "Board memo" and doc.source == "https://docs.google.com/document/d/DOC1/edit"
    pages = store.pages(kb.vault, doc.doc_id)
    assert len(pages) >= 2 and all(len(p) <= 3200 for p in pages)
    assert find(kb.vault, "follow-on")[0].doc_id == doc.doc_id


def test_export_needs_a_drive_link(kb, tmp_path):
    text = tmp_path / "export.txt"
    text.write_text("hello")
    with pytest.raises(KbError, match="Google Drive link"):
        ingest.add_export(kb.vault, kb.cfg, text, "https://example.com/doc", "Memo", embedder=fake_embed)


def test_summary_lists_labels_and_reasons(kb):
    _, item = drive_pdf(kb)
    good = kb.read(item)
    bad = store.Doc("x", "file:/x.zip", "file", "/x.zip", "x.zip", "/x.zip", status="failed", error="Bron can't read .zip files yet.")
    text = ingest.summary([good, bad], ["Couldn't find https://drive.google.com/file/d/NOPE/view in Google Drive on this Mac."])
    assert text.startswith("Read 1 document (0 scanned pages, 0 pages read by the model).")
    assert "- spa.pdf — Acme · other" in text
    assert "Couldn't read: x.zip (Bron can't read .zip files yet)" in text
    assert "Couldn't find https://drive.google.com/file/d/NOPE/view" in text


def test_summary_caps_the_label_lines(kb):
    docs = [store.Doc(f"d{i}", f"file:/d{i}", "file", "", f"doc{i}.pdf", "", labels={"company": "Acme"}) for i in range(14)]
    text = ingest.summary(docs, [])
    assert text.count("\n- ") == 10 and "…and 4 more; see `bron kb list`" in text


# ---- background jobs ----

def items_in(kb, tmp_path, n, prefix="doc"):
    folder = tmp_path / f"batch-{prefix}"
    folder.mkdir()
    for i in range(n):
        make_text_pdf(folder / f"{prefix}{i}.pdf", [f"Document {prefix} number {i}: the fund invested in company {prefix}{i} in 2024."])
    return sources.resolve(kb.vault, [str(folder)])[0]


def test_job_reads_everything_and_reports_once(kb, tmp_path):
    items_in(kb, tmp_path, 3)
    (tmp_path / "batch-doc" / "broken.zip").write_bytes(b"x")
    items = sources.resolve(kb.vault, [str(tmp_path / "batch-doc")])[0]
    job = jobs.create(kb.vault, items, failed=["Couldn't find https://drive.google.com/file/d/NOPE/view in Google Drive on this Mac."])
    assert job.status == "queued" and (store.kb_dir(kb.vault) / "jobs" / f"{job.job_id}.json").is_file()
    jobs.run(kb.vault, job.job_id, **kb.deps)
    done = jobs.load(kb.vault, job.job_id)
    assert done.status == "done" and len(done.done) == 3 and len(done.failed) == 2
    told = notices.take(kb.vault)
    assert len(told) == 1 and told[0].startswith("Read 3 documents")
    assert "Couldn't read: broken.zip (Bron can't read .zip files yet)" in told[0] and "NOPE" in told[0]
    assert notices.take(kb.vault) == []


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


def test_a_second_job_waits_and_runs_after_the_first(kb, tmp_path):
    first = jobs.create(kb.vault, items_in(kb, tmp_path, 2, "a"))
    second = jobs.create(kb.vault, items_in(kb, tmp_path, 2, "b"))
    lock = store.kb_dir(kb.vault) / "jobs" / "runner.lock"
    with open(lock, "a+") as held:  # another runner is busy
        fcntl.flock(held, fcntl.LOCK_EX)
        jobs.run(kb.vault, second.job_id, **kb.deps)
        assert jobs.load(kb.vault, second.job_id).status == "queued"
        fcntl.flock(held, fcntl.LOCK_UN)
    jobs.run(kb.vault, first.job_id, **kb.deps)
    assert jobs.load(kb.vault, first.job_id).status == "done"
    assert jobs.load(kb.vault, second.job_id).status == "done"
    told = notices.take(kb.vault)
    assert len(told) == 2 and "a0.pdf" in told[0] and "b0.pdf" in told[1]


def test_status_lines(kb, tmp_path):
    assert jobs.status_lines(kb.vault) == ["Nothing is being read."]
    job = jobs.create(kb.vault, items_in(kb, tmp_path, 2))
    assert jobs.status_lines(kb.vault)[0].startswith("Waiting to read 2 documents")
    jobs.run(kb.vault, job.job_id, **kb.deps)
    lines = jobs.status_lines(kb.vault)
    assert lines[0] == "Nothing is being read."
    assert re.fullmatch(r"Last batch finished .+: 2 documents read in \d+ s, 0 couldn't be read\.", lines[1])


def test_spawn_starts_a_detached_run_job(kb):
    (kb.vault.bron_dir / "bin").mkdir(parents=True, exist_ok=True)
    (kb.vault.bron_dir / "bin" / "bron").write_text("#!/bin/sh\n")
    calls = []
    assert jobs.spawn(kb.vault, "J1", popen=lambda argv, **kw: calls.append((argv, kw)))
    assert calls[0][0][1:] == ["kb", "run-job", "J1"] and calls[0][1]["start_new_session"] is True


# ---- notices ----

def test_notices_are_taken_once(vault):
    notices.add(vault, "Read 2 documents.")
    notices.add(vault, "Read 1 document.")
    assert notices.take(vault) == ["Read 2 documents.", "Read 1 document."]
    assert notices.take(vault) == []
    notices.add(vault, "Read 4 documents.")
    assert notices.take(vault) == ["Read 4 documents."]
    assert json.loads((store.kb_dir(vault) / "notices.jsonl").read_text().splitlines()[0])["text"] == "Read 2 documents."


# ---- fix round 1 ----

LPA_TEXT = "Limited Partnership Agreement of Fund II. The management fee is 2% of commitments during the investment period."
MINUTES_TEXT = "Minutes of the board meeting of Beta Pagamentos. The board approved the hiring of a new CFO in March."


def test_a_new_inbox_file_with_an_old_name_is_a_new_document(kb, tmp_path):
    inbox = kb.vault.root / "Knowledge" / "Inbox"
    make_text_pdf(inbox / "scan.pdf", [LPA_TEXT])
    lpa = kb.read(sources.resolve(kb.vault, [], inbox=True)[0][0])
    make_text_pdf(inbox / "scan.pdf", [MINUTES_TEXT])  # a different file, dropped under the same name
    minutes = kb.read(sources.resolve(kb.vault, [], inbox=True)[0][0])
    month = kb.vault.root / "Knowledge" / "Files" / time.strftime("%Y-%m")
    assert lpa.doc_id != minutes.doc_id
    assert sorted(p.name for p in month.iterdir()) == ["scan (2).pdf", "scan.pdf"]
    assert "management fee" in store.pages(kb.vault, lpa.doc_id)[0]  # the LPA's only copy and its text survive
    assert "management fee" in ingest_text(month / "scan.pdf")
    assert {d.doc_id for d in store.all_docs(kb.vault)} == {lpa.doc_id, minutes.doc_id}
    make_text_pdf(inbox / "scan.pdf", [MINUTES_TEXT])  # the same bytes again (an interrupted read, resumed)
    again = kb.read(sources.resolve(kb.vault, [], inbox=True)[0][0])
    assert again.doc_id == minutes.doc_id and len(list(month.iterdir())) == 2


def ingest_text(path):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(path)
    try:
        return doc[0].get_textpage().get_text_range()
    finally:
        doc.close()


def test_page_count_never_opens_an_online_only_file(kb, monkeypatch):
    import os as real_os

    path = make_text_pdf(kb.root / "big.pdf", ["x" * 60])
    item = Item("drive", "drive:BIG", "https://drive.google.com/open?id=BIG", "big.pdf", str(path))
    real_stat = real_os.stat

    class Dataless:
        def __init__(self, st):
            self.st = st

        def __getattr__(self, name):
            return getattr(self.st, name)

        st_flags = ingest.SF_DATALESS
        st_size = 5_000_000
        st_blocks = 0

    monkeypatch.setattr(ingest.os, "stat", lambda p, *a, **k: Dataless(real_stat(p, *a, **k)) if str(p) == str(path) else real_stat(p, *a, **k))
    import pypdfium2

    monkeypatch.setattr(pypdfium2, "PdfDocument", lambda *a, **k: pytest.fail("an online-only file was opened"))
    assert ingest.page_count(item) == 100  # estimated from its size, nothing downloaded


def test_an_interrupted_index_step_leaves_the_document_indexing(kb, monkeypatch):
    path, item = drive_pdf(kb)
    doc = kb.read(item)
    make_text_pdf(path, ["Amended agreement: the purchase price now includes an earn-out of USD 500,000.00."])
    real_put = index._put
    calls = []

    def stop_once(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise KeyboardInterrupt
        return real_put(*a, **k)

    monkeypatch.setattr(index, "_put", stop_once)
    with pytest.raises(KeyboardInterrupt):
        kb.read(item)
    assert store.load(kb.vault, doc.doc_id).status == "indexing"
    real_ensure = index.ensure
    monkeypatch.setattr(index, "ensure", lambda vault, embedder: None)
    assert find(kb.vault, "closing") == [] and find(kb.vault, "earn-out") == []  # stale rows are never cited
    monkeypatch.setattr(index, "ensure", real_ensure)
    hits = find(kb.vault, "earn-out")  # the next search finishes indexing it
    assert hits and hits[0].doc_id == doc.doc_id and "earn-out" in hits[0].text
    assert store.load(kb.vault, doc.doc_id).status == "read"
    assert not find(kb.vault, "closing")


def test_a_runner_finishes_documents_left_indexing(kb, monkeypatch):
    path, item = drive_pdf(kb)
    real_put = index._put
    monkeypatch.setattr(index, "_put", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        kb.read(item)
    monkeypatch.setattr(index, "_put", real_put)
    assert store.load(kb.vault, store.doc_id_for("drive:SPA1")).status == "indexing"
    job = jobs.create(kb.vault, [])
    jobs.run(kb.vault, job.job_id, **kb.deps)
    assert store.load(kb.vault, store.doc_id_for("drive:SPA1")).status == "read"


def test_a_failed_save_still_leaves_a_record(kb, monkeypatch):
    path, item = drive_pdf(kb)
    doc = kb.read(item)
    real = store._write
    monkeypatch.setattr(store, "_write", lambda p, t: (_ for _ in ()).throw(OSError(28, "No space left on device"))
                        if p.name == "passages.jsonl" else real(p, t))
    failed = ingest.read_item(kb.vault, kb.cfg, item, again=True, **kb.deps)
    assert failed.status == "failed" and store.load(kb.vault, doc.doc_id).status == "failed"


def test_user_labels_survive_a_crash_while_saving(kb, monkeypatch):
    path, item = drive_pdf(kb)
    doc = kb.read(item)
    store.save_user_labels(kb.vault, doc.doc_id, {"company": "Acme Holdings"})
    assert store.load(kb.vault, doc.doc_id).user_labels == {"company": "Acme Holdings"}
    real = store._write

    def crash(p, t):
        if p.name == "passages.jsonl":
            raise KeyboardInterrupt  # the process dies half-way through saving
        real(p, t)

    monkeypatch.setattr(store, "_write", crash)
    with pytest.raises(KeyboardInterrupt):
        ingest.read_item(kb.vault, kb.cfg, item, again=True, **kb.deps)
    assert store.load(kb.vault, doc.doc_id) is None  # the meta was removed first
    monkeypatch.setattr(store, "_write", real)
    again = kb.read(item)
    assert again.user_labels == {"company": "Acme Holdings"}
    assert store.effective_labels(store.load(kb.vault, doc.doc_id))["company"] == "Acme Holdings"


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


def test_cancel_stops_waiting_jobs_and_reports_them(kb, tmp_path):
    job = jobs.create(kb.vault, items_in(kb, tmp_path, 3))
    texts = jobs.cancel(kb.vault)
    cancelled = jobs.load(kb.vault, job.job_id)
    assert cancelled.status == "cancelled" and len(cancelled.cancelled) == 3
    assert len(texts) == 1 and "Cancelled: 3 documents weren't read" in texts[0]
    jobs.run(kb.vault, job.job_id, **kb.deps)
    assert store.all_docs(kb.vault) == [] and notices.take(kb.vault) == []  # reported by the command, not again


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


def test_a_report_is_never_lost_or_doubled_around_a_crash(kb, tmp_path, monkeypatch):
    job = jobs.create(kb.vault, items_in(kb, tmp_path, 1))
    real_save = jobs.save

    def crash_when_done(vault, j):
        if j.status == "done":
            raise KeyboardInterrupt
        real_save(vault, j)

    monkeypatch.setattr(jobs, "save", crash_when_done)
    with pytest.raises(KeyboardInterrupt):
        jobs.run(kb.vault, job.job_id, **kb.deps)
    monkeypatch.setattr(jobs, "save", real_save)
    jobs.run(kb.vault, job.job_id, **kb.deps)
    assert jobs.load(kb.vault, job.job_id).status == "done"
    assert len(notices.take(kb.vault)) == 1
    second = jobs.create(kb.vault, items_in(kb, tmp_path, 1, "late"))
    real_add = notices.add
    monkeypatch.setattr(notices, "add", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        jobs.run(kb.vault, second.job_id, **kb.deps)  # stopped while writing the report
    monkeypatch.setattr(notices, "add", real_add)
    jobs.run(kb.vault, second.job_id, **kb.deps)
    assert jobs.load(kb.vault, second.job_id).status == "done"
    assert len(notices.take(kb.vault)) == 1  # the report still arrives


def test_notices_for_the_same_job_are_kept_once(vault):
    notices.add(vault, "Read 2 documents.", job_id="J1")
    notices.add(vault, "Read 2 documents.", job_id="J1")
    notices.add(vault, "Shown already.", job_id="J2", shown=True)
    notices.add(vault, "Shown already.", job_id="J2")
    assert notices.take(vault) == ["Read 2 documents."]


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


def test_status_lines_use_the_singular(kb, tmp_path):
    jobs.create(kb.vault, items_in(kb, tmp_path, 1))
    assert jobs.status_lines(kb.vault)[0].startswith("Waiting to read 1 document (")


# ---- final fixes ----

def test_an_unreadable_inbox_file_fails_alone_and_the_batch_goes_on(kb):
    inbox = kb.vault.root / "Knowledge" / "Inbox"
    good = make_text_pdf(inbox / "good.pdf", [SPA_TEXT])
    locked = make_text_pdf(inbox / "locked.pdf", [LPA_TEXT])
    locked.chmod(0)
    try:
        items = sources.resolve(kb.vault, [], inbox=True)[0]
        job = jobs.create(kb.vault, items)
        jobs.run(kb.vault, job.job_id, **kb.deps)  # never a traceback: the unreadable file is one failure
        done = jobs.load(kb.vault, job.job_id)
        assert done.status == "done" and len(done.done) == 1
        assert done.failed == [{"identity": f"file:{locked}", "name": "locked.pdf",
                                "error": "Bron couldn't open this file (Permission denied)."}]
        assert "locked.pdf (Bron couldn't open this file (Permission denied))" in notices.take(kb.vault)[0]
        assert not good.exists() and locked.exists()  # the readable one was kept and left the inbox
        assert "locked.pdf" in (kb.vault.bron_dir / "logs" / "kb-errors.log").read_text()
    finally:
        locked.chmod(0o644)


@pytest.mark.parametrize("damage", ["empty vectors.npy", "vectors.json holds a list", "vectors.json is not JSON"])
def test_damaged_vector_files_are_worked_out_again(kb, damage):
    import numpy as np

    _, item = drive_pdf(kb)
    doc = kb.read(item)
    folder = store.kb_dir(kb.vault) / "docs" / doc.doc_id
    if damage == "empty vectors.npy":
        (folder / "vectors.npy").write_bytes(b"")
    elif damage == "vectors.json holds a list":
        (folder / "vectors.json").write_text("[1, 2, 3]")
    else:
        (folder / "vectors.json").write_text("{nope")
    index.delete_files(kb.vault)  # the next search rebuilds the index from the saved vectors
    hits = find(kb.vault, "purchase price")
    assert hits and hits[0].doc_id == doc.doc_id
    assert np.load(folder / "vectors.npy").shape[1] == 384  # the bad files were replaced
    assert isinstance(json.loads((folder / "vectors.json").read_text()), dict)


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


def test_web_pages_are_always_read_again(kb, monkeypatch):
    fetched = []

    def run(argv, **kw):
        fetched.append(argv)
        html = "<html><body><h1>Fund news</h1><p>" + "The fund closed its second vehicle at USD 50 million. " * 5 + "</p></body></html>"
        return subprocess.CompletedProcess(argv, 0, html.encode(), b"")

    monkeypatch.setattr(ingest.subprocess, "run", run)
    item = sources.resolve(kb.vault, ["https://example.com/news"])[0][0]
    assert kb.read(item).status == "read" and kb.read(item).status == "read"
    assert len(fetched) == 2


def test_a_job_reports_unchanged_documents(kb, tmp_path):
    items = items_in(kb, tmp_path, 2)
    jobs.run(kb.vault, jobs.create(kb.vault, items).job_id, **kb.deps)
    notices.take(kb.vault)
    job = jobs.create(kb.vault, items)
    jobs.run(kb.vault, job.job_id, **kb.deps)
    done = jobs.load(kb.vault, job.job_id)
    assert done.status == "done" and len(done.done) == 2 and done.read == [] and len(done.unchanged) == 2
    told = notices.take(kb.vault)[0]
    assert told == "Already read, unchanged: doc0.pdf, doc1.pdf (2 unchanged, skipped; add --again to read them again)."
    forced = jobs.create(kb.vault, items, again=True)
    jobs.run(kb.vault, forced.job_id, **kb.deps)
    assert len(jobs.load(kb.vault, forced.job_id).read) == 2


def test_a_marker_stays_while_the_meta_is_being_saved(kb):
    _, item = drive_pdf(kb)
    doc = kb.read(item)
    meta = store.kb_dir(kb.vault) / "docs" / doc.doc_id / "meta.json"
    saved = meta.read_text()
    meta.unlink()  # another process is half-way through store.save
    store.mark_indexing(kb.vault, doc.doc_id)
    index.ensure(kb.vault, fake_embed)
    assert store.indexing_ids(kb.vault) == [doc.doc_id]
    meta.write_text(saved)
    store.forget(kb.vault, doc.doc_id)
    store.mark_indexing(kb.vault, doc.doc_id)
    index.ensure(kb.vault, fake_embed)
    assert store.indexing_ids(kb.vault) == []  # the document folder is gone: nothing to finish


def test_a_reused_pid_is_not_a_runner(kb, monkeypatch):
    status = store.kb_dir(kb.vault) / "jobs" / "runner.status"
    status.parent.mkdir(parents=True, exist_ok=True)
    other = subprocess.Popen(["sleep", "30"])
    try:
        status.write_text(json.dumps({"pid": other.pid, "beat": 0}))
        seen = []
        monkeypatch.setattr(jobs, "_command_of", lambda pid: seen.append(pid) or "/bin/sleep 30")
        assert not jobs.runner_active(kb.vault) and seen == [other.pid]
        monkeypatch.setattr(jobs, "_command_of", lambda pid: "/x/.bron/venv/bin/python /x/.bron/bin/bron kb run-job J1")
        assert jobs.runner_active(kb.vault)
        monkeypatch.setattr(jobs, "_command_of", lambda pid: "")  # ps couldn't tell
        assert not jobs.runner_active(kb.vault)
    finally:
        other.kill()
        other.wait()


def test_the_real_ps_names_the_command(kb):
    assert "pytest" in jobs._command_of(os.getpid())
    assert jobs._command_of(999999) == ""


class NoModel:
    """The meaning model can't be downloaded."""

    model = "fake-embedder"

    def embed(self, texts):
        raise KbError("The meaning-search model couldn't be loaded (offline). Keyword search still works.")


def test_without_the_meaning_model_documents_are_read_for_keyword_search(kb):
    path, item = drive_pdf(kb)
    doc = ingest.read_item(kb.vault, kb.cfg, item, **{**kb.deps, "embedder": NoModel()})
    assert doc.status == "read" and doc.vectors_pending
    assert store.load(kb.vault, doc.doc_id).vectors_pending
    assert store.indexing_ids(kb.vault) == [doc.doc_id]  # tried again later
    con = index.open(kb.vault)
    try:
        assert con.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM fts").fetchone()[0] > 0
    finally:
        con.close()
    assert search.search(kb.vault, "purchase price", embedder=NoModel())[0].doc_id == doc.doc_id
    text = ingest.summary([doc])
    assert text.startswith("Read 1 document (0 scanned pages, 0 pages read by the model); "
                           "meaning search for it will be ready once the model downloads.")
    hits = find(kb.vault, "purchase price")  # the model is back: the next search finishes the job
    assert hits and hits[0].doc_id == doc.doc_id
    again = store.load(kb.vault, doc.doc_id)
    assert again.status == "read" and not again.vectors_pending and store.indexing_ids(kb.vault) == []
    con = index.open(kb.vault)
    try:
        assert con.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] > 0
    finally:
        con.close()


def test_a_rebuild_without_the_meaning_model_keeps_keyword_search(kb):
    _, item = drive_pdf(kb)
    doc = kb.read(item)
    for f in (store.kb_dir(kb.vault) / "docs" / doc.doc_id).glob("vectors.*"):
        f.unlink()
    index.delete_files(kb.vault)
    assert search.search(kb.vault, "purchase price", embedder=NoModel())[0].doc_id == doc.doc_id
    assert store.load(kb.vault, doc.doc_id).vectors_pending and store.indexing_ids(kb.vault) == [doc.doc_id]
    find(kb.vault, "purchase price")
    assert not store.load(kb.vault, doc.doc_id).vectors_pending


def test_some_documents_waiting_for_the_model_are_counted(kb):
    docs = [store.Doc(f"d{i}", f"file:/d{i}", "file", "", f"doc{i}.pdf", "", vectors_pending=i < 2) for i in range(3)]
    assert ingest.summary(docs).startswith("Read 3 documents (0 scanned pages, 0 pages read by the model); "
                                           "meaning search for 2 of them will be ready once the model downloads.")


def test_the_folder_hint_never_names_anything_above_home_drive_or_vault(kb, monkeypatch):
    from pathlib import Path as P

    home = P.home()

    def hint(path):
        return ingest._folder_hint(kb.vault, Item("file", f"file:{path}", str(path), P(path).name, str(path)))

    assert hint(home / "Downloads" / "spa.pdf") == "Downloads"
    assert hint(home / "Downloads" / "Portfolio" / "Acme" / "spa.pdf") == "Portfolio/Acme"
    assert hint("/Users/someone/Downloads/spa.pdf") == "Downloads"
    assert hint("/Users/someone/spa.pdf") == ""
    assert hint(kb.root / "Portfolio" / "Acme" / "Deals" / "spa.pdf") == "Acme/Deals"
    assert hint(kb.root / "spa.pdf") == ""
    assert hint(kb.vault.root / "Knowledge" / "Inbox" / "spa.pdf") == "Knowledge/Inbox"
    assert hint("/Volumes/Backup/Funds/Acme/spa.pdf") == "Funds/Acme"
    for path in (home / "Downloads" / "x.pdf", "/Users/someone/Downloads/x.pdf"):
        assert P.home().name not in hint(path) and "someone" not in hint(path) and "Users" not in hint(path)


def test_the_folder_hint_never_names_a_drive_account_or_computer(kb, tmp_path, monkeypatch):
    from pathlib import Path as P

    home = tmp_path / "Users" / "carla"
    account = home / "Library" / "CloudStorage" / "GoogleDrive-carla@fund.example"
    for sub in ("Meu Drive/Acme/Deals", "My Drive/Funds", "Shared drives/Fund I/Legal", "Other computers/Carla's MacBook/Docs"):
        (account / sub).mkdir(parents=True)
    monkeypatch.setattr(P, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("BRON_DRIVE_ROOT", raising=False)

    def hint(path):
        return ingest._folder_hint(kb.vault, Item("file", f"file:{path}", str(path), P(path).name, str(path)))

    assert hint(account / "Meu Drive" / "Acme" / "Deals" / "spa.pdf") == "Acme/Deals"
    assert hint(account / "My Drive" / "Funds" / "lpa.pdf") == "Funds"
    assert hint(account / "Shared drives" / "Fund I" / "Legal" / "lpa.pdf") == "Fund I/Legal"
    assert hint(account / "Other computers" / "Carla's MacBook" / "Docs" / "x.pdf") == "Docs"
    assert hint(account / "x.pdf") == ""
    assert account / "Meu Drive" in sources.drive_roots()


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


def test_meta_records_the_reader_and_passage_versions(kb):
    _, item = drive_pdf(kb)
    doc = kb.read(item)
    meta = json.loads((store.kb_dir(kb.vault) / "docs" / doc.doc_id / "meta.json").read_text())
    assert meta["passages_version"] == 1 and meta["reader_version"] == 1


def test_an_export_can_wait_in_a_job(kb, tmp_path):
    text = tmp_path / "export.txt"
    text.write_text("The investment committee approved a follow-on of BRL 750.000,00 in Acme.")
    item = Item("export", "drive:GDOC1", "https://docs.google.com/document/d/GDOC1/edit", "IC memo", str(text),
                "https://docs.google.com/document/d/GDOC1/edit")
    missing = Item("export", "drive:GDOC2", "https://docs.google.com/document/d/GDOC2/edit", "Gone", str(tmp_path / "gone.txt"),
                   "https://docs.google.com/document/d/GDOC2/edit")
    job = jobs.create(kb.vault, [item, missing])
    jobs.run(kb.vault, job.job_id, **kb.deps)
    done = jobs.load(kb.vault, job.job_id)
    assert len(done.read) == 1 and store.load(kb.vault, done.read[0]).name == "IC memo"
    assert done.failed[0]["name"] == "Gone" and "no readable file" in done.failed[0]["error"]


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


# ---- copies ----

def test_a_copy_of_a_document_already_read_is_skipped(kb):
    _, first = drive_pdf(kb, "lease.pdf", item_id="L1")
    _, copy = drive_pdf(kb, "lease (1).pdf", item_id="L2")
    original = kb.read(first)
    skipped = kb.read(copy)
    assert original.status == "read" and original.text_hash
    assert skipped.status == "duplicate" and skipped.duplicate_of == original.doc_id
    assert not store.exists(kb.vault, skipped.doc_id)  # nothing stored, nothing indexed, no page to write
    assert ingest.lines([skipped]) == f"Skipped lease (1).pdf: same text as lease.pdf — doc {original.doc_id}"
    assert ingest.summary([original, skipped]).endswith(
        "Skipped 1 copy of a document already read: lease (1).pdf (same text as lease.pdf).")


def test_reading_the_same_document_again_is_never_called_a_copy(kb):
    _, item = drive_pdf(kb, "lease.pdf", item_id="L1")
    kb.read(item)
    assert ingest.read_item(kb.vault, kb.cfg, item, again=True, **kb.deps).status == "read"


def test_a_document_read_before_copies_were_checked_still_catches_its_copies(kb):
    _, first = drive_pdf(kb, "lease.pdf", item_id="L1")
    original = kb.read(first)
    meta = store._folder(kb.vault, original.doc_id) / "meta.json"
    data = json.loads(meta.read_text())
    del data["text_hash"]
    meta.write_text(json.dumps(data))  # as 0.8.0 before this check
    _, copy = drive_pdf(kb, "lease copy.pdf", item_id="L2")
    assert kb.read(copy).status == "duplicate"
    assert store.load(kb.vault, original.doc_id).text_hash == original.text_hash  # filled in on the way


def test_a_folder_with_copies_reads_each_text_once(kb, tmp_path, desktop_notices):
    folder = tmp_path / "Agreements"
    folder.mkdir()
    for name in ("lpa.pdf", "lpa (1).pdf", "lpa (2).pdf"):
        make_text_pdf(folder / name, ["Limited partnership agreement of Northwind Properties Ltd, signed in 2024."])
    make_text_pdf(folder / "side.pdf", ["A different document about Harbor Bakery LLC."])
    items = sources.resolve(kb.vault, [str(folder)])[0]
    job = jobs.create(kb.vault, items)
    jobs.run(kb.vault, job.job_id, **kb.deps)
    job = jobs.load(kb.vault, job.job_id)
    assert len(job.read) == 2 and len(job.copies) == 2 and job.failed == []
    told = notices.take(kb.vault)[0]
    # read in name order: "lpa (1).pdf" comes first, so it's the one kept
    assert "Skipped 2 copies of documents already read: lpa (2).pdf (same text as lpa (1).pdf), " \
           "lpa.pdf (same text as lpa (1).pdf)." in told
    assert re.fullmatch(r"Bron read 2 documents, skipped 2 copies \(\d+ s\)\.", desktop_notices[0])

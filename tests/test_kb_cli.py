import io
import json

import pytest

from bron import cli as bron_cli
from bron.briefing import build_briefing
from bron.hooks import main as hook
from bron.kb import cli as kb_cli, embed, ingest, jobs, models, readers, service, store, tools
from bron.memory import summaries
from kbkit import FakeLabels, FakeModel, FakeOcr, fake_drive, fake_embed, make_docx, make_scanned_pdf, make_text_pdf, set_drive_id

SPA_TEXT = ("Share Purchase Agreement between Acme Ltda and the Fund. The purchase price is USD 2,000,000.00 "
            "payable at closing on January 21, 2025.")
LABELS = {
    "spa.pdf": {"company": "Acme", "type": "SPA", "date": "2025-01-21", "title": "Acme share purchase"},
    "scan.pdf": {"company": "Acme", "type": "term sheet", "date": "2025-01-10", "title": "Acme term sheet", "language": "pt"},
    "memo.docx": {"company": "Beta Pagamentos", "type": "board minutes", "date": "2024-11-05", "title": "Beta board minutes"},
}


@pytest.fixture
def env(vault, tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "ensure", lambda vault, say=print: None)
    monkeypatch.setattr(service, "query", lambda *a, **k: None)
    monkeypatch.setattr(embed, "get", lambda vault: fake_embed)
    monkeypatch.setattr(readers, "ocr_page", FakeOcr())
    monkeypatch.setattr(models, "call_image", FakeModel())
    monkeypatch.setattr(summaries, "call_model", FakeLabels(LABELS))
    spawned = []
    monkeypatch.setattr(jobs, "spawn", lambda vault, job_id, **kw: spawned.append(job_id) or True)
    root = fake_drive(tmp_path)
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(root))
    monkeypatch.setenv("BRON_VAULT", str(vault.root))

    class Env:
        pass

    e = Env()
    e.vault, e.root, e.spawned = vault, root, spawned
    return e


def run(env, capsys, *argv):
    args = bron_cli.build_parser().parse_args(["kb", *argv])
    code = kb_cli.handle(args, env.vault)
    return code, capsys.readouterr().out


def acme_folder(env):
    folder = env.root / "Portfolio" / "Acme"
    folder.mkdir(parents=True)
    spa = make_text_pdf(folder / "spa.pdf", [SPA_TEXT, "Schedule 1: the sellers and their shares, listed in full for the record."])
    scan = make_scanned_pdf(folder / "scan.pdf", ["scanned term sheet"])
    scan.with_suffix(".scan.png").unlink()
    memo = make_docx(folder / "memo.docx", [("h1", "Board minutes"), ("p", "The board of Beta Pagamentos approved the budget for 2025 and a new CFO hire.")])
    for path, item_id in ((folder, "FOLDER1"), (spa, "SPA1"), (scan, "SCAN1"), (memo, "MEMO1")):
        set_drive_id(path, item_id)
    return "https://drive.google.com/drive/folders/FOLDER1"


def add_all(env, capsys):
    """The folder holds a scan, so it is read in the background; the test runs that job here and returns its report."""
    from bron.kb import notices

    code, out = run(env, capsys, "add", acme_folder(env))
    assert code == 0 and out.strip() == "Reading 3 documents in the background; I'll report when it's done.", out
    jobs.run(env.vault, env.spawned[-1], embedder=fake_embed)  # what the detached `bron kb run-job` does
    return notices.take(env.vault)[0]


def test_add_a_drive_folder_then_search_with_citations(env, capsys):
    out = add_all(env, capsys)
    assert out.startswith("Read 3 documents (1 scanned page, 0 pages read by the model).")
    assert "- spa.pdf — Acme · SPA · 2025-01-21" in out
    assert "- memo.docx — Beta Pagamentos · board minutes · 2024-11-05" in out
    assert len(env.spawned) == 1
    code, out = run(env, capsys, "search", "purchase price")
    assert code == 0 and "Acme share purchase · Acme · SPA · 2025-01-21 · p. 1" in out
    assert "https://drive.google.com/open?id=SPA1" in out
    code, out = run(env, capsys, "search", "1,500,000.00", "--company", "acme")
    assert "Acme term sheet" in out and "https://drive.google.com/open?id=SCAN1" in out
    code, out = run(env, capsys, "search", "budget", "--type", "board minutes")
    assert "Beta board minutes" in out and "Acme" not in out


def test_more_than_five_documents_read_in_the_background_and_report_in_the_briefing_once(env, capsys, tmp_path):
    folder = tmp_path / "pile"
    folder.mkdir()
    for i in range(6):
        make_text_pdf(folder / f"report{i}.pdf", [f"Quarterly report number {i} for the portfolio, with revenue and burn."])
    code, out = run(env, capsys, "add", str(folder))
    assert code == 0 and out.strip() == "Reading 6 documents in the background; I'll report when it's done."
    assert len(env.spawned) == 1 and store.all_docs(env.vault) == []
    code, out = run(env, capsys, "status")
    assert "Waiting to read 6 documents" in out
    jobs.run(env.vault, env.spawned[0], embedder=fake_embed)  # what the detached `bron kb run-job` does
    first = build_briefing(env.vault, cli="claude")
    assert "## Knowledge base" in first and "Read 6 documents" in first
    assert "## Knowledge base" not in build_briefing(env.vault, cli="claude")


def prompt():
    out = io.StringIO()
    assert hook("user-prompt", "claude", stdin=io.StringIO(json.dumps({"prompt": "hi"})), stdout=out) == 0
    return out.getvalue()


def test_the_message_trigger_reports_a_finished_job_once(env):
    from bron.kb import notices

    notices.add(env.vault, "Read 2 documents (0 scanned pages, 0 pages read by the model).")
    first = prompt()
    assert "Knowledge base reading finished:" in first and "Read 2 documents" in first
    assert prompt() == ""


def test_ticket_runs_leave_the_report_for_the_user(env, monkeypatch):
    from bron.kb import notices

    notices.add(env.vault, "Read 2 documents.")
    monkeypatch.setenv("BRON_TICKET", "T-0001")
    assert prompt() == ""
    assert "## Knowledge base" not in build_briefing(env.vault, cli="claude")
    monkeypatch.delenv("BRON_TICKET")
    assert "Read 2 documents." in prompt()


def test_big_requests_ask_first(env, capsys, tmp_path, monkeypatch):
    folder = tmp_path / "big"
    folder.mkdir()
    for i in range(6):
        (folder / f"f{i}.txt").write_text("x")
    monkeypatch.setattr(ingest, "page_count", lambda item: pytest.fail("more than 5 documents: pages are estimated, never opened"))
    monkeypatch.setattr(ingest, "guess_pages", lambda item: 600)
    code, out = run(env, capsys, "add", str(folder))
    assert code == 0
    assert out.strip() == ("This is 6 documents (about 3,600 pages). The first reading takes about 12 minutes in the background; "
                           "up to 20 pages per document may be read by your Claude or Codex model. "
                           "Run the same command with --yes to go ahead.")
    assert env.spawned == [] and not (store.kb_dir(env.vault) / "jobs").exists()
    code, out = run(env, capsys, "add", str(folder), "--yes")
    assert code == 0 and "in the background" in out and len(env.spawned) == 1


def test_a_few_huge_pdfs_ask_first_too(env, capsys, tmp_path, monkeypatch):
    a = make_text_pdf(tmp_path / "a.pdf", [SPA_TEXT])
    b = make_text_pdf(tmp_path / "b.pdf", [SPA_TEXT])
    monkeypatch.setattr(ingest, "page_count", lambda item: 2000)
    code, out = run(env, capsys, "add", str(a), str(b))
    assert code == 0 and out.startswith("This is 2 documents (about 4,000 pages).") and store.all_docs(env.vault) == []


def test_many_documents_ask_first_without_opening_them(env, capsys, tmp_path, monkeypatch):
    folder = tmp_path / "many"
    folder.mkdir()
    for i in range(301):
        (folder / f"f{i}.txt").write_text("x")
    monkeypatch.setattr(ingest, "page_count", lambda item: pytest.fail("pages are only counted for up to 300 documents"))
    code, out = run(env, capsys, "add", str(folder))
    assert out.startswith("This is 301 documents (about 301 pages).")


def test_failures_are_reported_and_never_stop_the_batch(env, capsys, tmp_path):
    folder = tmp_path / "mixed"
    folder.mkdir()
    make_text_pdf(folder / "good.pdf", [SPA_TEXT])
    (folder / "bad.pdf").write_bytes(b"not a pdf")
    (folder / "song.mp3").write_bytes(b"x")
    code, out = run(env, capsys, "add", str(folder), "https://drive.google.com/file/d/NOPE/view")
    assert code == 0 and out.startswith("Read 1 document (")
    assert "Couldn't read: bad.pdf (This file is damaged or isn't really a PDF)" in out
    assert "song.mp3 (Bron can't read .mp3 files yet)" in out
    assert "Couldn't find https://drive.google.com/file/d/NOPE/view in Google Drive on this Mac" in out


def test_nothing_readable_is_exit_one(env, capsys, tmp_path):
    code, out = run(env, capsys, "add", str(tmp_path / "missing.pdf"))
    assert code == 1 and "There's no file at" in out
    code, out = run(env, capsys, "add")
    assert code == 1 and "Tell me what to read" in out
    code, out = run(env, capsys, "add", "--inbox")
    assert code == 0 and out.strip() == "The inbox (Knowledge/Inbox) is empty."


def test_add_an_exported_google_doc(env, capsys, tmp_path):
    text = tmp_path / "memo.txt"
    text.write_text("The investment committee approved a follow-on of BRL 750.000,00 in Acme.")
    code, out = run(env, capsys, "add", "--file", str(text), "--source", "https://docs.google.com/document/d/GDOC1/edit",
                    "--name", "IC memo")
    assert code == 0 and out.startswith("Read 1 document")
    doc = store.load(env.vault, store.doc_id_for("drive:GDOC1"))
    assert doc.name == "IC memo" and doc.status == "read"
    code, out = run(env, capsys, "add", "--file", str(text))
    assert code == 1 and "--source" in out and "--name" in out


def test_show_list_forget(env, capsys):
    add_all(env, capsys)
    code, out = run(env, capsys, "list")
    assert code == 0 and len(out.strip().splitlines()) == 3 and "spa.pdf — Acme · SPA · 2025-01-21" in out
    code, out = run(env, capsys, "list", "--company", "beta")
    assert "memo.docx" in out and "spa.pdf" not in out
    code, out = run(env, capsys, "list", "--type", "SPA")
    assert out.strip().splitlines()[-1].endswith("spa.pdf — Acme · SPA · 2025-01-21")
    code, out = run(env, capsys, "show", "spa.pdf", "--pages", "2")
    assert code == 0 and "Schedule 1" in out and "purchase price" not in out and "https://drive.google.com/open?id=SPA1" in out
    code, out = run(env, capsys, "show", "spa", "--pages", "1-2")
    assert "--- p. 1 ---" in out and "--- p. 2 ---" in out
    code, out = run(env, capsys, "show", "spa.pdf", "--pages", "9")
    assert code == 1 and "spa.pdf has 2 pages." in out
    code, out = run(env, capsys, "forget", "SPA.PDF")
    assert code == 0 and "Forgot spa.pdf" in out
    code, out = run(env, capsys, "search", "purchase price")
    assert "spa.pdf" not in out and "Acme share purchase" not in out
    assert len(store.all_docs(env.vault)) == 2


def test_label_corrections_are_reindexed(env, capsys):
    add_all(env, capsys)
    code, out = run(env, capsys, "label", "spa.pdf", "--company", "Acme Holdings", "--type", "sha", "--date", "2025-02-01")
    assert code == 0 and "Acme Holdings · SHA · 2025-02-01" in out
    doc = next(d for d in store.all_docs(env.vault) if d.name == "spa.pdf")
    assert doc.user_labels == {"company": "Acme Holdings", "doc_type": "SHA", "date": "2025-02-01"}
    assert store.passages(env.vault, doc.doc_id)[0]["header"].startswith("[Acme Holdings | SHA | 2025-02-01")
    code, out = run(env, capsys, "search", "purchase price", "--company", "holdings", "--type", "SHA")
    assert "Acme Holdings" in out and "p. 1" in out
    code, out = run(env, capsys, "label", "spa.pdf", "--date", "1st of May")
    assert code == 1 and "YYYY-MM-DD" in out
    code, out = run(env, capsys, "label", "spa.pdf", "--type", "napkin")
    assert code == 1 and "LPA" in out


def test_an_ambiguous_document_changes_nothing(env, capsys):
    add_all(env, capsys)
    code, out = run(env, capsys, "forget", "acme")  # matches two titles
    assert code == 1 and "Several documents match 'acme'" in out and "spa.pdf" in out and "scan.pdf" in out
    assert len(store.all_docs(env.vault)) == 3
    code, out = run(env, capsys, "forget", " ")
    assert code == 1 and "Name a document" in out and len(store.all_docs(env.vault)) == 3
    code, out = run(env, capsys, "show", "nothing-like-this")
    assert code == 1 and "No document matches 'nothing-like-this'" in out
    doc = next(d for d in store.all_docs(env.vault) if d.name == "scan.pdf")
    code, out = run(env, capsys, "forget", doc.doc_id)
    assert code == 0 and "Forgot scan.pdf" in out


def test_status_shows_documents_and_jobs(env, capsys, monkeypatch):
    add_all(env, capsys)
    monkeypatch.setattr(tools, "missing", lambda: [])
    code, out = run(env, capsys, "status")
    assert code == 0 and "The knowledge base has 3 documents." in out and "No documents are being read right now." in out


def test_status_resumes_an_interrupted_job(env, capsys, tmp_path):
    job = jobs.create(env.vault, [])
    jobs.save(env.vault, jobs.Job(job.job_id, job.created, [], [], [], "running"))
    code, out = run(env, capsys, "status")
    assert env.spawned == [job.job_id] and "picking it up again" in out


def test_a_new_session_resumes_an_interrupted_job(env, monkeypatch):
    from bron import hooks

    job = jobs.create(env.vault, [])
    jobs.save(env.vault, jobs.Job(job.job_id, job.created, [], [], [], "running"))
    monkeypatch.setenv("BRON_TICKET", "T-0001")
    hooks._resume_reading("claude", env.vault)
    assert env.spawned == []  # ticket runs leave it to the user's sessions
    monkeypatch.delenv("BRON_TICKET")
    hooks._resume_reading("claude", env.vault)
    assert env.spawned == [job.job_id]
    jobs.run(env.vault, job.job_id, embedder=fake_embed)
    hooks._resume_reading("claude", env.vault)
    assert env.spawned == [job.job_id]  # nothing left to resume


def test_status_mentions_missing_tools(env, capsys, monkeypatch):
    monkeypatch.setattr(tools, "missing", lambda: ["fastembed"])
    code, out = run(env, capsys, "status")
    assert "aren't installed yet" in out


def test_internal_commands_are_hidden():
    parser = bron_cli.build_parser()
    assert parser.parse_args(["kb", "run-job", "J1"]).kb_command == "run-job"
    kb = parser._subparsers._group_actions[0].choices["kb"]
    usage = kb.format_usage()
    assert "serve" not in usage and "run-job" not in usage
    for name in ("add", "search", "show", "list", "forget", "label", "status"):
        assert name in usage


def test_a_small_request_waits_behind_a_running_job(env, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "runner_active", lambda vault: True)
    one = make_text_pdf(tmp_path / "one.pdf", [SPA_TEXT])
    code, out = run(env, capsys, "add", str(one))
    assert code == 0 and out.strip() == "Reading 1 document in the background; I'll report when it's done."
    assert len(env.spawned) == 1 and store.all_docs(env.vault) == []


def test_status_cancel(env, capsys, tmp_path):
    folder = tmp_path / "pile"
    folder.mkdir()
    for i in range(7):
        make_text_pdf(folder / f"r{i}.pdf", [f"Quarterly report number {i} for the portfolio, with revenue and burn."])
    run(env, capsys, "add", str(folder))
    code, out = run(env, capsys, "status", "--cancel")
    assert code == 0 and "Cancelled: 7 documents weren't read" in out
    code, out = run(env, capsys, "status")
    assert "No documents are being read right now." in out and env.spawned and len(env.spawned) == 1
    code, out = run(env, capsys, "status", "--cancel")
    assert out.strip() == "Nothing is being read, so there's nothing to cancel."


def test_status_finishes_documents_left_indexing(env, capsys, monkeypatch):
    add_all(env, capsys)
    doc = next(d for d in store.all_docs(env.vault) if d.name == "spa.pdf")
    doc.status = "indexing"
    store.save_meta(env.vault, doc)
    store.mark_indexing(env.vault, doc.doc_id)
    monkeypatch.setattr(tools, "missing", lambda: [])
    run(env, capsys, "status")
    assert store.load(env.vault, doc.doc_id).status == "read"


# ---- final fixes ----

def test_an_unreadable_inbox_file_is_reported_and_the_rest_is_read(env, capsys):
    inbox = env.vault.root / "Knowledge" / "Inbox"
    make_text_pdf(inbox / "good.pdf", [SPA_TEXT])
    locked = make_text_pdf(inbox / "locked.pdf", [SPA_TEXT + " Second copy."])
    locked.chmod(0)
    try:
        code, out = run(env, capsys, "add", "--inbox")
    finally:
        locked.chmod(0o644)
    assert code == 0 and out.startswith("Read 1 document (") and "Traceback" not in out
    assert "Couldn't read: locked.pdf (Bron couldn't open this file (Permission denied))." in out


def test_reading_the_same_file_again_is_skipped_unless_asked(env, capsys, tmp_path):
    spa = make_text_pdf(tmp_path / "spa.pdf", [SPA_TEXT])
    code, out = run(env, capsys, "add", str(spa))
    assert code == 0 and out.startswith("Read 1 document (")
    code, out = run(env, capsys, "add", str(spa))
    assert code == 0
    assert out.strip() == "Already read, unchanged: spa.pdf (1 unchanged, skipped; add --again to read it again)."
    code, out = run(env, capsys, "add", str(spa), "--again")
    assert code == 0 and out.startswith("Read 1 document (")


def test_again_reaches_a_background_job(env, capsys, tmp_path):
    folder = tmp_path / "pile"
    folder.mkdir()
    for i in range(6):
        make_text_pdf(folder / f"report{i}.pdf", [f"Quarterly report number {i} for the portfolio, with revenue and burn."])
    run(env, capsys, "add", str(folder), "--again")
    assert jobs.load(env.vault, env.spawned[0]).again is True


def test_an_unexpected_error_is_logged_not_shown_as_a_traceback(env, capsys, monkeypatch):
    def broken(args, vault):
        raise ValueError("something deep inside")

    monkeypatch.setattr(kb_cli, "_list", broken)
    code, out = run(env, capsys, "list")
    assert code == 1
    assert out.strip() == ("Something went wrong in the knowledge base (ValueError). "
                           "Details are in .bron/logs/kb-errors.log.")
    log = (env.vault.bron_dir / "logs" / "kb-errors.log").read_text()
    assert "Traceback" in log and "ValueError: something deep inside" in log


def test_ctrl_c_is_not_swallowed(env, capsys, monkeypatch):
    def stop(args, vault):
        raise KeyboardInterrupt

    monkeypatch.setattr(kb_cli, "_list", stop)
    with pytest.raises(KeyboardInterrupt):
        run(env, capsys, "list")


SETUP_BACKGROUND = "Setting up the knowledge base tools and reading in the background; I'll report when it's done."


def test_first_add_without_the_tools_sets_up_and_reads_in_the_background(env, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "missing", lambda: ["fastembed"])
    monkeypatch.setattr(tools, "ensure", lambda vault, say=print: pytest.fail("never installed in the foreground"))
    one = make_text_pdf(tmp_path / "one.pdf", [SPA_TEXT])
    code, out = run(env, capsys, "add", str(one))
    assert code == 0 and out.strip() == SETUP_BACKGROUND
    assert len(env.spawned) == 1 and store.all_docs(env.vault) == []
    text = tmp_path / "memo.txt"
    text.write_text("The investment committee approved a follow-on of BRL 750.000,00 in Acme.")
    code, out = run(env, capsys, "add", "--file", str(text), "--source", "https://docs.google.com/document/d/GDOC1/edit",
                    "--name", "IC memo")
    assert code == 0 and out.strip() == SETUP_BACKGROUND and len(env.spawned) == 2
    queued = jobs.load(env.vault, env.spawned[1])
    assert queued.items[0]["kind"] == "export" and queued.items[0]["path"] == str(text.resolve())
    monkeypatch.setattr(tools, "missing", lambda: [])
    for job_id in env.spawned:
        jobs.run(env.vault, job_id, embedder=fake_embed)
    assert {d.name for d in store.all_docs(env.vault)} == {"one.pdf", "IC memo"}


def test_a_failed_setup_in_the_background_is_reported(env, capsys, tmp_path, monkeypatch):
    from bron.kb import notices
    from bron.kb.store import KbError

    monkeypatch.setattr(tools, "missing", lambda: ["fastembed"])
    one = make_text_pdf(tmp_path / "one.pdf", [SPA_TEXT])
    run(env, capsys, "add", str(one))

    def refuse(vault, say=print):
        raise KbError("The knowledge base tools couldn't be installed (No route to host).")

    monkeypatch.setattr(tools, "ensure", refuse)
    code, out = run(env, capsys, "run-job", env.spawned[0])
    assert code == 1
    assert jobs.load(env.vault, env.spawned[0]).status == "done" and jobs.pending(env.vault) == []
    told = notices.take(env.vault)
    assert len(told) == 1 and "couldn't be installed (No route to host)" in told[0] and "one.pdf" in told[0]


def test_a_failed_setup_leaves_jobs_alone_while_another_runner_reads_them(env, capsys, tmp_path, monkeypatch):
    import fcntl

    from bron.kb import notices

    monkeypatch.setattr(tools, "missing", lambda: ["fastembed"])
    run(env, capsys, "add", str(make_text_pdf(tmp_path / "one.pdf", [SPA_TEXT])))
    lock = jobs._lock_path(env.vault)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a+") as held:
        fcntl.flock(held, fcntl.LOCK_EX)  # a runner whose setup worked is reading
        jobs.give_up(env.vault, "The knowledge base tools couldn't be installed (No route to host).")
    assert [j.job_id for j in jobs.pending(env.vault)] == env.spawned[:1] and notices.take(env.vault) == []


def test_more_than_fifty_pages_read_in_the_background(env, capsys, tmp_path, monkeypatch):
    one = make_text_pdf(tmp_path / "one.pdf", [SPA_TEXT])
    monkeypatch.setattr(ingest, "page_count", lambda item: 51)
    code, out = run(env, capsys, "add", str(one))
    assert code == 0 and out.strip() == "Reading 1 document in the background; I'll report when it's done."
    monkeypatch.setattr(ingest, "page_count", lambda item: 50)
    code, out = run(env, capsys, "add", str(one))
    assert out.startswith("Read 1 document (") and len(env.spawned) == 1


@pytest.mark.parametrize("name", ["photo.png", "receipt.HEIC", "scan.pdf"])
def test_images_and_scans_read_in_the_background(env, capsys, tmp_path, name):
    path = tmp_path / name
    if name == "scan.pdf":
        make_scanned_pdf(path, ["scanned term sheet"])
    else:
        path.write_bytes(b"not really an image")
    code, out = run(env, capsys, "add", str(path))
    assert code == 0 and out.strip() == "Reading 1 document in the background; I'll report when it's done."


def test_the_scan_check_never_opens_online_only_files(env, monkeypatch, tmp_path):
    import pypdfium2

    from bron.kb.sources import Item

    pdf = make_text_pdf(tmp_path / "big.pdf", ["x"])
    item = Item("drive", "drive:BIG", "https://drive.google.com/open?id=BIG", "big.pdf", str(pdf))
    monkeypatch.setattr(ingest, "online_only", lambda path: True)
    monkeypatch.setattr(pypdfium2, "PdfDocument", lambda *a, **k: pytest.fail("an online-only file was opened"))
    assert ingest.looks_scanned(item) is False
    monkeypatch.undo()
    assert ingest.looks_scanned(item) is True  # one "x": fewer than 40 characters of text on page 1
    text = make_text_pdf(tmp_path / "text.pdf", [SPA_TEXT])
    assert ingest.looks_scanned(Item("file", "file:t", str(text), "text.pdf", str(text))) is False


def test_file_with_other_targets_is_refused(env, capsys, tmp_path):
    text = tmp_path / "memo.txt"
    text.write_text("x")
    code, out = run(env, capsys, "add", str(text), "--file", str(text), "--source",
                    "https://docs.google.com/document/d/GDOC1/edit", "--name", "IC memo")
    assert code == 1 and out.strip() == ("--file reads one exported Google file on its own. "
                                         "Run it separately from other links, paths or --inbox.")
    code, out = run(env, capsys, "add", "--inbox", "--file", str(text), "--source",
                    "https://docs.google.com/document/d/GDOC1/edit", "--name", "IC memo")
    assert code == 1 and "separately" in out and store.all_docs(env.vault) == []


def test_asking_first_mentions_the_model_pages(env, capsys, tmp_path, monkeypatch):
    from vaultkit import set_meta

    folder = tmp_path / "big"
    folder.mkdir()
    for i in range(6):
        (folder / f"f{i}.txt").write_text("x")
    monkeypatch.setattr(ingest, "guess_pages", lambda item: 600)
    code, out = run(env, capsys, "add", str(folder))
    assert "up to 20 pages per document may be read by your Claude or Codex model" in out
    set_meta(env.vault.settings_file, knowledge={"model_pages": False})
    code, out = run(env, capsys, "add", str(folder))
    assert "Claude or Codex" not in out


def test_schemeless_drive_links_are_links(env, capsys):
    folder = env.root / "Acme"
    folder.mkdir()
    spa = make_text_pdf(folder / "spa.pdf", [SPA_TEXT])
    set_drive_id(spa, "SPA9")
    code, out = run(env, capsys, "add", "drive.google.com/file/d/SPA9/view")
    assert code == 0 and out.startswith("Read 1 document (")
    code, out = run(env, capsys, "add", "docs.google.com/document/d/NOPE/edit")
    assert "Couldn't find https://docs.google.com/document/d/NOPE/edit in Google Drive" in out

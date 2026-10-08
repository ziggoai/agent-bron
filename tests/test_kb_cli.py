import io
import json

import pytest

from bron import cli as bron_cli
from bron import notifications, runner
from bron.briefing import build_briefing
from bron.hooks import main as hook
from bron.kb import cli as kb_cli, embed, ingest, jobs, models, readers, service, store, tools
from bron.memory import summaries
from bron.tickets import find_ticket, load_ticket
from kbkit import FakeModel, FakeOcr, FakeTicketRunner, fake_drive, fake_embed, make_docx, make_scanned_pdf, make_text_pdf, set_drive_id, stored_doc

SPA_TEXT = ("Share Purchase Agreement between Acme Ltda and the Fund. The purchase price is USD 2,000,000.00 "
            "payable at closing on January 21, 2025.")


@pytest.fixture
def env(vault, tmp_path, monkeypatch):
    ensured = []
    monkeypatch.setattr(tools, "ensure", lambda vault, say=print: ensured.append(vault))
    monkeypatch.setattr(runner, "run_ticket", FakeTicketRunner())
    monkeypatch.setattr(service, "query", lambda *a, **k: None)
    monkeypatch.setattr(embed, "get", lambda vault: fake_embed)
    monkeypatch.setattr(readers, "ocr_page", FakeOcr())
    monkeypatch.setattr(models, "call_image", FakeModel())
    monkeypatch.setattr(summaries, "call_model", lambda *a, **k: pytest.fail("no text is sent to a model to label documents"))
    spawned = []
    monkeypatch.setattr(jobs, "spawn", lambda vault, job_id, **kw: spawned.append(job_id) or True)
    root = fake_drive(tmp_path)
    monkeypatch.setenv("BRON_DRIVE_ROOT", str(root))
    monkeypatch.setenv("BRON_VAULT", str(vault.root))

    class Env:
        pass

    e = Env()
    e.vault, e.root, e.spawned = vault, root, spawned
    e.ensured = ensured
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
    """A folder is read in the background and then written into the wiki; the test runs that job here and returns its
    reading report (the wiki run's ticket carries it)."""
    code, out = run(env, capsys, "add", acme_folder(env))
    assert code == 0 and out.strip() == ("Reading 3 documents into the wiki in the background (about 3 minutes); "
                                         "a Mac notification will say when it's done, "
                                         "and I'll tell you in your next message."), out
    jobs.run(env.vault, env.spawned[-1], embedder=fake_embed)  # what the detached `bron kb run-job` does
    return jobs.load(env.vault, env.spawned[-1]).report


def test_add_a_drive_folder_then_search_with_citations(env, capsys):
    out = add_all(env, capsys)
    assert out.startswith("Read 3 documents (1 scanned page, 0 pages read by the model).")
    assert out.splitlines()[1:4] == ["- memo.docx", "- scan.pdf", "- spa.pdf"]  # no labels guessed from folder names
    assert len(env.spawned) == 1
    code, out = run(env, capsys, "search", "purchase price")
    assert code == 0 and "spa.pdf · Acme · other · p. 1" in out
    assert "https://drive.google.com/open?id=SPA1" in out
    code, out = run(env, capsys, "search", "1,500,000.00", "--company", "acme")
    assert "scan.pdf" in out and "https://drive.google.com/open?id=SCAN1" in out
    code, out = run(env, capsys, "search", "budget", "--type", "contract")
    assert out.strip() == kb_cli.NOTHING


def test_a_folder_is_read_and_written_in_the_background_and_a_failure_is_told_once(env, capsys, tmp_path, monkeypatch):
    folder = tmp_path / "pile"
    folder.mkdir()
    for i in range(6):
        make_text_pdf(folder / f"report{i}.pdf", [f"Quarterly report number {i}, with revenue and costs."])
    code, out = run(env, capsys, "add", str(folder))
    assert code == 0 and out.strip() == ("Reading 6 documents into the wiki in the background (about 6 minutes); "
                                         "a Mac notification will say when it's done, "
                                         "and I'll tell you in your next message.")
    assert len(env.spawned) == 1 and store.all_docs(env.vault) == []
    code, out = run(env, capsys, "status")
    assert "Waiting to read 6 documents" in out
    monkeypatch.setattr(runner, "run_ticket", FakeTicketRunner(status="blocked", message="the run failed"))
    jobs.run(env.vault, env.spawned[0], embedder=fake_embed)  # what the detached `bron kb run-job` does
    first = build_briefing(env.vault, cli="claude")
    assert "## Knowledge base" in first and "Read 6 documents" in first and "finish the wiki pages" in first
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
    assert code == 0 and out.startswith("Read IC memo (1 page, 0 scanned) — doc ")
    doc = store.load(env.vault, store.doc_id_for("drive:GDOC1"))
    assert doc.name == "IC memo" and doc.status == "read"
    code, out = run(env, capsys, "add", "--file", str(text))
    assert code == 1 and "--source" in out and "--name" in out


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


def test_show_stops_before_the_output_gets_too_long(env, capsys, monkeypatch):
    monkeypatch.setattr(kb_cli, "SHOW_CHARS", 100)
    stored_doc(env.vault, "long.pdf", ["a" * 40 + "\r\nline two", "b" * 40, "c" * 40, "d" * 250, "e" * 10])
    code, out = run(env, capsys, "show", "long.pdf")
    assert code == 0 and "--- p. 2 ---" in out and "--- p. 3 ---" not in out
    assert "\r" not in out and "a" * 40 + "\nline two" in out
    assert out.rstrip().endswith("…3 more pages; continue with --pages 3-5.")
    code, out = run(env, capsys, "show", "long.pdf", "--pages", "3-5")
    assert "--- p. 3 ---" in out and "--- p. 4" not in out and out.rstrip().endswith("…2 more pages; continue with --pages 4-5.")
    code, out = run(env, capsys, "show", "long.pdf", "--pages", "1-2")
    assert "--- p. 2 ---" in out and "more page" not in out  # the whole range fit
    code, out = run(env, capsys, "show", "long.pdf", "--pages", "4")  # one page longer than a whole show: in parts
    assert "--- p. 4 (part 1 of 3) ---\n" + "d" * 100 + "\n" in out
    assert out.rstrip().endswith("…p. 4 goes on; continue with --pages 4 --part 2.")
    code, out = run(env, capsys, "show", "long.pdf", "--pages", "4", "--part", "3")
    assert "d" * 50 in out and "d" * 51 not in out and out.rstrip().endswith("…1 more page; continue with --pages 5.")
    code, out = run(env, capsys, "show", "long.pdf", "--pages", "4", "--part", "4")
    assert code == 1 and "p. 4 of long.pdf has 3 parts." in out


def test_show_cut_short_by_a_closed_pipe_is_not_an_error(env, capsys, monkeypatch):
    stored_doc(env.vault, "long.pdf", ["text"])
    monkeypatch.setattr(kb_cli, "_show", lambda args, vault: (_ for _ in ()).throw(BrokenPipeError()))
    monkeypatch.setattr(kb_cli, "_quiet_stdout", lambda: None)
    code, _ = run(env, capsys, "show", "long.pdf")
    assert code == 0 and not (env.vault.bron_dir / "logs" / "kb-errors.log").exists()


def test_in_claude_code_a_background_read_says_to_wait_for_it(env, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out = run(env, capsys, "add", acme_folder(env))
    assert code == 0 and out.strip().splitlines()[-1] == kb_cli.WAIT_HINT.format(job=env.spawned[-1])
    monkeypatch.setenv("BRON_TICKET", "T-0001")  # a background ticket run has nobody to tell
    kb_cli._wait_hint("j1")
    monkeypatch.delenv("BRON_TICKET")
    monkeypatch.delenv("CLAUDECODE")  # Codex: the Mac notification and the next message's notice tell the user
    kb_cli._wait_hint("j1")
    assert capsys.readouterr().out == ""
    monkeypatch.setattr(kb_cli, "_who_hears", lambda: "claude")  # one rule for who hears the end
    kb_cli._wait_hint("j1")
    assert capsys.readouterr().out.strip() == kb_cli.WAIT_HINT.format(job="j1")


def test_wait_reports_once_the_reading_and_the_wiki_are_done(env, capsys):
    run(env, capsys, "add", acme_folder(env))
    checks = []

    def sleep(seconds):
        checks.append(seconds)
        jobs.run(env.vault, env.spawned[-1], embedder=fake_embed)  # the background job finishes meanwhile
        ticket = load_ticket(find_ticket(env.vault, jobs.load(env.vault, env.spawned[-1]).ticket))
        notifications.record(env.vault, ticket)  # as the real runner does when the run ends

    args = bron_cli.build_parser().parse_args(["kb", "wait"])
    assert kb_cli._wait(args, env.vault, sleep=sleep) == 0
    out = capsys.readouterr().out
    assert checks == [10] and "Ticket updates since your last message:" in out and "is now done" in out
    assert kb_cli._wait(args, env.vault, sleep=sleep) == 0  # told once: the next message won't repeat it
    assert capsys.readouterr().out.strip() == "Everything is read and written; it was already reported."


def test_a_wait_for_one_job_reports_only_it_even_after_another_conversation_was_told(env, capsys):
    from bron import hooks

    run(env, capsys, "add", acme_folder(env))
    mine = env.spawned[-1]

    def sleep(seconds):
        jobs.run(env.vault, mine, embedder=fake_embed)
        ticket = load_ticket(find_ticket(env.vault, jobs.load(env.vault, mine).ticket))
        notifications.record(env.vault, ticket)
        hooks.updates_text("claude")  # another conversation's next message takes the updates first

    args = bron_cli.build_parser().parse_args(["kb", "wait", "--job", mine])
    assert kb_cli._wait(args, env.vault, sleep=sleep) == 0
    out = capsys.readouterr().out
    ticket = jobs.load(env.vault, mine).wiki_tickets[0]
    assert f"- {ticket} " in out and "is done" in out and "ticket show <id>" in out
    assert hooks.updates_text("claude") == ""  # and it isn't told again
    bad = bron_cli.build_parser().parse_args(["kb", "wait", "--job", "nope"])
    assert kb_cli._wait(bad, env.vault, sleep=sleep) == 1 and "There's no reading nope" in capsys.readouterr().out


def test_wait_stops_when_nobody_is_reading(env, capsys, monkeypatch):
    run(env, capsys, "add", acme_folder(env))
    monkeypatch.setattr(jobs, "stalled", lambda vault: jobs.pending(vault))
    args = bron_cli.build_parser().parse_args(["kb", "wait"])
    assert kb_cli._wait(args, env.vault, sleep=lambda s: None) == 1
    assert "Reading stopped before it finished" in capsys.readouterr().out


def test_forget_with_an_unreadable_log_still_forgets(env, capsys):
    add_all(env, capsys)
    (env.vault.knowledge_dir / "log.md").write_bytes(b"\xff\xfe\x00bad")
    code, out = run(env, capsys, "forget", "spa.pdf")
    assert code == 0 and out.splitlines() == [
        "Forgot spa.pdf; searches won't find it any more. The original wasn't touched.",
        "log.md can't be read (it isn't plain text), so Bron left it as it is."]
    assert len(store.all_docs(env.vault)) == 2


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


def test_an_ambiguous_document_changes_nothing(env, capsys):
    add_all(env, capsys)
    code, out = run(env, capsys, "forget", "pdf")  # matches two names
    assert code == 1 and "Several documents match 'pdf'" in out and "spa.pdf" in out and "scan.pdf" in out
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
    assert code == 0 and "The knowledge base has 3 documents." in out and "Nothing is being read." in out


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
    for name in ("add", "search", "show", "list", "forget", "status"):
        assert name in usage
    assert "label" not in kb.format_usage().split("{", 1)[1]


def test_a_small_request_waits_behind_a_running_job(env, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "runner_active", lambda vault, wiki=False: not wiki)
    one = make_text_pdf(tmp_path / "one.pdf", [SPA_TEXT])
    code, out = run(env, capsys, "add", str(one))
    assert code == 0 and out.strip() == ("Reading 1 document into the wiki in the background (about 1 minute); "
                                         "a Mac notification will say when it's done, "
                                         "and I'll tell you in your next message.")
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
    assert "Nothing is being read." in out and env.spawned and len(env.spawned) == 1
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
    assert code == 0 and out.startswith("Read good.pdf (") and "Traceback" not in out
    assert "Couldn't read locked.pdf: Bron couldn't open this file (Permission denied)." in out


def test_reading_the_same_file_again_is_skipped_unless_asked(env, capsys, tmp_path):
    spa = make_text_pdf(tmp_path / "spa.pdf", [SPA_TEXT])
    code, out = run(env, capsys, "add", str(spa))
    assert code == 0 and out.startswith("Read spa.pdf (1 page, 0 scanned) — doc ")
    doc_id = out.split("— doc ", 1)[1].split()[0]
    code, out = run(env, capsys, "add", str(spa))
    assert code == 0 and out.splitlines()[0] == f"Already read spa.pdf — doc {doc_id} (no page yet)"
    code, out = run(env, capsys, "add", str(spa), "--again")
    assert code == 0 and out.startswith("Read spa.pdf (")


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


def test_a_long_read_goes_to_the_background(env, capsys, tmp_path, monkeypatch):
    one = make_text_pdf(tmp_path / "one.pdf", [SPA_TEXT])
    monkeypatch.setattr(ingest, "page_count", lambda item: 301)
    monkeypatch.setattr(ingest, "looks_scanned", lambda item: True)
    code, out = run(env, capsys, "add", str(one))
    assert out.strip() == ("Reading 1 document into the wiki in the background (about 2 minutes); "
                           "a Mac notification will say when it's done, "
                           "and I'll tell you in your next message.")
    jobs.cancel(env.vault)  # the first one is out of the way
    monkeypatch.setattr(ingest, "page_count", lambda item: 300)  # 300 scanned pages: about 5 minutes, still here
    code, out = run(env, capsys, "add", str(one))
    assert out.startswith("Read one.pdf (") and len(env.spawned) == 1


def test_an_online_only_pdf_is_timed_like_a_scan(env, capsys, tmp_path, monkeypatch):
    from bron.kb.sources import Item

    big = make_text_pdf(tmp_path / "big.pdf", [SPA_TEXT])
    monkeypatch.setattr(ingest, "online_only", lambda path: True)  # streamed from Drive: whether it's scanned is unknown
    monkeypatch.setattr(ingest, "page_count", lambda item: 600)  # guessed from its size
    assert kb_cli._sizes([Item("drive", "drive:BIG", "https://drive.google.com/open?id=BIG", "big.pdf", str(big))]) == (
        600, 600 * kb_cli.SCAN_SECONDS_PER_PAGE)
    note = tmp_path / "note.txt"
    note.write_text("A short note.")
    assert kb_cli._sizes([Item("file", f"file:{note}", str(note), "note.txt", str(note))])[1] == kb_cli.TEXT_SECONDS_PER_PAGE * 600
    code, out = run(env, capsys, "add", str(big))
    assert out.startswith("Reading 1 document into the wiki in the background (") and len(env.spawned) == 1


def test_a_scan_is_read_in_the_conversation(env, capsys, tmp_path):
    path = make_scanned_pdf(tmp_path / "scan.pdf", ["scanned page"])
    code, out = run(env, capsys, "add", str(path))
    assert code == 0 and out.startswith("Read scan.pdf (1 page, 1 scanned) — doc ") and env.spawned == []


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
    assert code == 0 and out.startswith("Read spa.pdf (")
    code, out = run(env, capsys, "add", "docs.google.com/document/d/NOPE/edit")
    assert "Couldn't find https://docs.google.com/document/d/NOPE/edit in Google Drive" in out


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

"""`bron kb add` in 0.8.0: up to 3 documents in the conversation, a folder or more in the background with a wiki run."""
import re

import pytest

from bron.kb import cli as kb_cli
from bron.kb import jobs, store, tools, wiki, wiki_run
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
                           "a Mac notification will say when it's done, and I'll tell you in your next message.")
    assert jobs.load(env.vault, env.spawned[0]).wiki is True and env.ensured == []
    jobs.cancel(env.vault)  # the first one is out of the way
    folder = tmp_path / "Receipts"
    folder.mkdir()
    make_text_pdf(folder / "r.pdf", [SPA_TEXT])
    code, out = run(env, capsys, "add", str(folder))
    assert out.strip() == ("Reading 1 document into the wiki in the background (about 1 minute); "
                           "a Mac notification will say when it's done, and I'll tell you in your next message.")
    job = jobs.load(env.vault, env.spawned[1])
    assert job.wiki is True and job.label == f"the {tmp_path.name}/Receipts folder"


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
    assert lines[-1] == "A folder is already being written into the wiki; these start right after it and should be done in about 2 minutes."
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
        assert re.search(r"Last batch finished .+: 1 document read in \d+ s, 0 couldn't be read; "
                         r"wiki pages written in \d+ s\.", out)


def test_status_shows_a_waiting_wiki_run_and_cancel_stops_it(env, capsys):
    doc = stored_doc(env.vault, "a.pdf", ["A"])
    job = jobs.create_wiki(env.vault, [doc.doc_id], label="the Leases folder")
    code, out = run(env, capsys, "status")
    assert "Waiting to write the Leases folder into the wiki (since " in out
    code, out = run(env, capsys, "status", "--cancel")
    assert "weren't written" in out and jobs.load(env.vault, job.job_id).wiki_status == "cancelled"


def test_a_file_added_while_a_folder_is_being_read_waits_behind_it(env, capsys, tmp_path):
    folder = tmp_path / "F"
    folder.mkdir()
    make_text_pdf(folder / "a.pdf", [SPA_TEXT])
    run(env, capsys, "add", str(folder))  # queued, still reading: its wiki_status is still empty
    text = tmp_path / "memo.txt"
    text.write_text("The committee approved a budget of BRL 750.000,00 for the office move.")
    code, out = run(env, capsys, "add", "--file", str(text), "--source", "https://docs.google.com/document/d/GDOC1/edit",
                    "--name", "IC memo")
    lines = out.strip().splitlines()
    assert code == 0 and lines[0].startswith("Read IC memo (") and kb_cli.NEXT not in out
    assert lines[-1] == "A folder is already being written into the wiki; these start right after it and should be done in about 2 minutes."
    assert jobs.load(env.vault, env.spawned[1]).wiki_status == "waiting"


def test_a_second_background_add_waits_behind_the_first_folder(env, capsys, tmp_path):
    first = tmp_path / "First"
    first.mkdir()
    make_text_pdf(first / "a.pdf", [SPA_TEXT])
    run(env, capsys, "add", str(first))
    second = tmp_path / "Second"
    second.mkdir()
    make_text_pdf(second / "b.pdf", [SPA_TEXT + " Other."])
    code, out = run(env, capsys, "add", str(second))
    assert out.strip() == "A folder is already being written into the wiki; these start right after it and should be done in about 2 minutes."


def test_codex_is_told_a_notification_will_come(monkeypatch):
    monkeypatch.delenv("CLAUDECODE", raising=False)
    line = kb_cli._background_line("12 documents", "about 9 min")
    assert "notification" in line and "I'll report" not in line


def test_claude_code_still_reports(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    assert kb_cli._background_line("12 documents", "about 9 min").endswith("I'll report when it's done.")


def test_behind_says_it_starts_right_after(monkeypatch):
    monkeypatch.delenv("CLAUDECODE", raising=False)
    line = kb_cli._behind_line("about 12 min")
    assert "right after" in line and "done in about 12 min" in line


def test_ticket_titles_name_the_parent_folder(env, capsys, tmp_path):
    from bron.kb import sources

    client = tmp_path / "Acme Ltda"
    for sub in ("Contracts", "Invoices"):
        (client / sub).mkdir(parents=True)
        make_text_pdf(client / sub / f"{sub}.pdf", [SPA_TEXT])
    run(env, capsys, "add", str(client / "Contracts"))
    assert jobs.load(env.vault, env.spawned[-1]).label == "the Acme Ltda/Contracts folder"
    both = sources.resolve_targets(env.vault, [str(client / "Contracts"), str(client / "Invoices")])
    assert sources.folder_label(both, both.items) == "the Acme Ltda folder"
    loose = sources.resolve_targets(env.vault, [str(client / "Contracts" / "Contracts.pdf"),
                                                str(client / "Invoices" / "Invoices.pdf")])
    assert sources.folder_label(loose, loose.items) == "the Acme Ltda folder"
    web = sources.resolve_targets(env.vault, [str(client / "Contracts" / "Contracts.pdf"), "https://example.com/a"])
    assert sources.folder_label(web, web.items) == ""
    assert wiki_run.title("the Acme Ltda/Contracts folder", 3, 2, 4) == \
        "Read the Acme Ltda/Contracts folder into the wiki (part 2 of 4)"

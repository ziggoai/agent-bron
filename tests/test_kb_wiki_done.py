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
    assert done(vault, log_text="save | Rent history") == "Nothing changed in the wiki; the log line is recorded."
    assert done(vault, log_text="checked everything") == "Nothing changed in the wiki; the log line is recorded."
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


def test_done_does_not_create_the_search_database(vault):
    doc = stored_doc(vault, "lease.pdf", ["Lease text"])
    write_lease(vault, doc)
    write_bakery(vault)
    assert not index.db_path(vault).exists()
    assert done(vault) == "Wiki updated: 2 pages (2 new)."
    assert not index.db_path(vault).exists()
    assert search.find(vault, "lease", embedder=fake_embed).pages  # the next search builds it and finds the pages


def test_an_unreadable_log_is_one_line_and_the_rest_carries_on(vault):
    doc = stored_doc(vault, "lease.pdf", ["Lease text"])
    write_lease(vault, doc)
    write_bakery(vault)
    (vault.knowledge_dir / "log.md").write_bytes(b"\xff\xfe\x00bad")
    out = done(vault)
    lines = out.splitlines()
    assert lines[0] == "Wiki updated: 2 pages (2 new)."
    assert lines[1] == "log.md can't be read (it isn't plain text), so Bron left it as it is."
    assert store.load(vault, doc.doc_id).page == "Knowledge/" + LEASE
    assert "[[Harbor Bakery]]" in (vault.knowledge_dir / "index.md").read_text(encoding="utf-8")


def test_two_wiki_done_runs_take_turns(vault):
    import threading

    from bron import statefile

    doc = stored_doc(vault, "lease.pdf", ["Lease text"])
    write_lease(vault, doc)
    write_bakery(vault)
    held, release, result = threading.Event(), threading.Event(), []

    def other_run():
        with statefile.locked(store.kb_dir(vault) / "wiki-done"):
            held.set()
            release.wait(10)

    other = threading.Thread(target=other_run)
    other.start()
    assert held.wait(10)
    mine = threading.Thread(target=lambda: result.append(done(vault)))
    mine.start()
    mine.join(1.0)
    try:
        assert mine.is_alive() and result == []  # it waits for the other run instead of logging the same pages twice
    finally:
        release.set()
        mine.join(20)
        other.join(20)
    assert result[0] == "Wiki updated: 2 pages (2 new)."
    assert done(vault) == "Nothing changed in the wiki."
    assert log(vault).count("ingest | [[Office lease (2025-03-01)]]") == 1


def test_done_shows_what_is_worth_a_look_without_asking_for_another_run(vault):
    write_page(vault, "Organisations/Harbor Bakery.md", "Total 12192630 (p. 1); [[Corner Shop]]\n",
               type="organisation", summary="A bakery")
    write_page(vault, "Organisations/Corner Shop.md", "See [[Harbor Bakery]].\n", type="organisation", summary="A shop")
    out = done(vault)
    assert "Worth a look (fix what's real; these don't block `wiki done`):" in out
    assert "Numbers in spreadsheet form" in out
    assert "run `.bron/bin/bron wiki done` again" not in out

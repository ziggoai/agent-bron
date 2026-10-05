"""The wiki's pages, their links and properties, the record of each document's page, index.md and log.md."""
import json
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
    meta_text = (store.kb_dir(vault) / "docs" / doc.doc_id / "meta.json").read_text()
    assert not {"page", "page_labels"} & json.loads(meta_text).keys()
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

def test_a_page_with_an_impossible_date_is_reported_not_a_crash(vault):
    path = vault.knowledge_dir / "Documents" / "Bad date.md"
    path.write_text("---\ntype: document\nsummary: x\ndate: 2025-02-30\n---\nbody\n", encoding="utf-8")
    page = wiki.read_page(vault, path)
    assert page.error and page.meta == {} and page.links() == []
    write_page(vault, "Topics/Fine.md", "", type="topic", summary="ok")
    text = wiki.index_text(vault)
    assert "Fine" in text and "Bad date" not in text


def test_page_labels_survive_reading_a_document_again(vault):
    from bron.kb import ingest
    from kbkit import fake_embed

    link = "https://docs.google.com/document/d/abc123/edit"
    note = vault.root / "note.txt"
    note.write_text("Lease text.\n", encoding="utf-8")
    first = ingest.add_export(vault, None, note, link, "Lease", embedder=fake_embed)
    path = write_page(vault, LEASE, type="document", summary="A lease", doc=first.doc_id, organisation="[[Harbor Bakery]]")
    wiki.link_documents(vault, [wiki.read_page(vault, path)])
    note.write_text("Lease text, with more words.\n", encoding="utf-8")
    again = ingest.add_export(vault, None, note, link, "Lease", embedder=fake_embed)
    assert again.page == "Knowledge/" + LEASE and store.effective_labels(again)["company"] == "Harbor Bakery"
    assert all("Harbor Bakery" in p["header"] for p in store.passages(vault, first.doc_id))  # the passages were cut with the page's labels


def test_a_hand_edited_page_type_outside_knowledge_is_ignored(vault):
    path = schema.schema_path(vault)
    path.write_text(path.read_text(encoding="utf-8").replace("[Documents, Organisations, People, Topics]",
                                                             "[../x, a/b, Topics, Documents]"), encoding="utf-8")
    assert wiki.type_folders(vault) == ["Topics", "Documents"]



def test_a_page_that_is_not_utf8_cannot_be_opened(vault):
    path = vault.knowledge_dir / "Topics" / "Latin.md"
    path.write_bytes(b"---\ntype: topic\n---\ncaf\xe9\n")
    assert wiki.read_page(vault, path).error == "it can't be opened (UnicodeDecodeError)"


def test_an_unreadable_log_is_left_alone(vault):
    import pytest

    log = vault.knowledge_dir / "log.md"
    log.write_bytes(b"# Log\ncaf\xe9\n")
    with pytest.raises(store.KbError, match="log.md can't be read"):
        wiki.append_log(vault, [("update", "x")])
    assert log.read_bytes() == b"# Log\ncaf\xe9\n"

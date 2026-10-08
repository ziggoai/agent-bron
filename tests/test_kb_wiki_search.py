"""Wiki pages live in the search database beside the passages: one search returns pages, then passages."""
import pytest

from bron import cli as bron_cli
from bron.kb import cli as kb_cli
from bron.kb import embed, index, search, service, store, tools, wiki_done, wiki_index
from bron.kb.store import KbError
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


def test_a_new_page_goes_into_index_md_with_wiki_done(vault):
    lease(vault)
    wiki_done.done(vault)
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


class NoModel:
    """A meaning model that isn't available: every call fails, and is counted."""

    model = "fake-embedder"

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        raise KbError("The meaning model isn't available.")


class OtherModel:
    """Like the fake model, but another model by name."""

    model = "another-model"

    def embed(self, texts):
        return fake_embed.embed(texts)


def test_without_the_model_one_search_tries_it_once_and_still_finds_by_words(vault):
    lease(vault)
    broken = NoModel()
    found = search.find(vault, "monthly rent", embedder=broken)
    assert broken.calls == 1
    assert "Harbor Bakery" in titles(found) and found.hits


def test_page_vectors_from_another_model_are_made_again(vault):
    lease(vault)
    find(vault, "rent")
    other = OtherModel()
    search.find(vault, "rent", embedder=other)
    con = index.open(vault)
    try:
        assert {r[0] for r in con.execute("SELECT model FROM pages WHERE kind != ''")} == {"another-model"}
        assert con.execute("SELECT COUNT(*) FROM page_vectors").fetchone()[0] > 0
    finally:
        con.close()
    assert titles(search.find(vault, "monthly rent", embedder=other, pages_only=True))


def test_page_vectors_of_the_wrong_size_are_ignored_not_fatal(vault):
    lease(vault)
    find(vault, "rent")
    con = index.open(vault)
    try:
        with con:
            con.execute("UPDATE page_vectors SET vec = x'0000'")
            con.execute("UPDATE meta SET val = val + 1 WHERE key = 'pages_counter'")
    finally:
        con.close()
    assert "Harbor Bakery" in titles(find(vault, "monthly rent", pages_only=True))


def cached(vault):
    return wiki_index._MATRIX[str(index.db_path(vault))][1][0]


def test_the_page_matrix_is_kept_until_the_pages_change(vault):
    lease(vault)
    find(vault, "rent")
    first = cached(vault)
    find(vault, "rent")
    assert cached(vault) is first
    page = vault.knowledge_dir / "Organisations" / "Harbor Bakery.md"
    page.write_text(page.read_text(encoding="utf-8") + "- Opens at six\n", encoding="utf-8")
    later(page)
    find(vault, "rent")
    assert cached(vault) is not first


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


def test_an_edited_document_page_keeps_the_passage_vectors_cached(vault, monkeypatch):
    doc = lease(vault)
    loads = []
    real = search._read_vectors
    monkeypatch.setattr(search, "_read_vectors", lambda con: loads.append(1) or real(con))
    assert [h.doc_id for h in search.search(vault, "rent", embedder=fake_embed, doc_type="contract")][:1] == [doc.doc_id]
    assert len(loads) == 1
    page = vault.knowledge_dir / LEASE_PAGE
    page.write_text(page.read_text(encoding="utf-8").replace("doc_type: contract", "doc_type: invoice"), encoding="utf-8")
    later(page)
    assert [h.doc_id for h in search.search(vault, "rent", embedder=fake_embed, doc_type="invoice")][:1] == [doc.doc_id]
    assert search.search(vault, "rent", embedder=fake_embed, doc_type="contract") == []  # the new filter applies
    assert len(loads) == 1  # only the labels changed: the passage vectors weren't read again


def test_a_page_for_several_documents_is_shown_when_one_of_them_is_allowed(vault):
    a = stored_doc(vault, "form-a.pdf", ["Signed supplier form for Acme, delivery within ten days. " * 3], index_it=True)
    b = stored_doc(vault, "form-b.pdf", ["Signed supplier form for Zeta, delivery within ten days. " * 3], index_it=True)
    write_page(vault, "Documents/Supplier forms.md", "Signed delivery forms (p. 1).\n", type="document",
               summary="Signed supplier forms", doc=[a.doc_id, b.doc_id], organisation="[[Acme]]")
    found = find(vault, "delivery within ten days", company="acme")
    assert titles(found) == ["Supplier forms"]
    assert found.hits and found.hits[0].wiki_page == "Supplier forms"
    assert find(vault, "delivery", company="nobody").pages == []


def test_a_page_for_several_documents_is_found_through_its_second_document(vault):
    a = stored_doc(vault, "form-a.pdf", ["Signed supplier form, delivery within ten days. " * 3], folder="Acme",
                   index_it=True)
    b = stored_doc(vault, "form-b.pdf", ["Signed supplier form, delivery within ten days. " * 3], folder="Zeta",
                   index_it=True)
    write_page(vault, "Documents/Supplier forms.md", "Signed delivery forms (p. 1).\n", type="document",
               summary="Signed supplier forms", doc=[a.doc_id, b.doc_id])
    found = find(vault, "delivery within ten days", company="zeta")
    assert [h.doc_id for h in found.hits] == [b.doc_id]  # the filter leaves only the second document
    assert titles(found) == ["Supplier forms"]
    assert "Page: [[Supplier forms]]" in search.render_all(found)


def org(vault, name, body):
    return write_page(vault, f"Organisations/{name}.md", body, type="organisation", summary=f"{name} summary")


def test_search_sees_an_edit_without_wiki_done(vault):
    org(vault, "Acme Ltda", "Rents a shop.\n")
    find(vault, "shop")
    path = vault.knowledge_dir / "Organisations/Acme Ltda.md"
    later(path)
    path.write_text(path.read_text(encoding="utf-8").replace("Rents a shop", "Owns a bakery"), encoding="utf-8")
    assert titles(find(vault, "bakery", pages_only=True))[:1] == ["Acme Ltda"]


def test_a_search_does_not_rewrite_index_md(vault):
    org(vault, "Acme Ltda", "Rents a shop.\n")
    wiki_done.done(vault)
    index_md = vault.knowledge_dir / "index.md"
    before = index_md.read_text(encoding="utf-8")
    org(vault, "Beta Ltda", "Sells bread.\n")
    assert titles(find(vault, "bread", pages_only=True))[:1] == ["Beta Ltda"]
    assert index_md.read_text(encoding="utf-8") == before  # `wiki done` writes it
    wiki_done.done(vault)
    assert "Beta Ltda" in index_md.read_text(encoding="utf-8")


def test_an_edit_that_keeps_the_same_documents_still_updates_their_labels(vault):
    doc = lease(vault)
    find(vault, "rent")
    page = vault.knowledge_dir / LEASE_PAGE
    later(page)
    page.write_text(page.read_text(encoding="utf-8").replace("doc_type: contract", "doc_type: invoice"), encoding="utf-8")
    assert [h.doc_id for h in find(vault, "rent", doc_type="invoice").hits] == [doc.doc_id]

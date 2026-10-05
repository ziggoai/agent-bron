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


def test_a_broken_link_in_the_body_and_a_property_counts_once(vault):
    org(vault, "Acme Ltda", "See [[Nobody Inc]].\n", partner="[[Nobody Inc]]")
    broken = [p for p in wiki_check.run(vault) if p.code == "broken-link"]
    assert [p.text for p in broken] == ["Acme Ltda: links to [[Nobody Inc]], which doesn't exist."]


def test_a_partial_path_link_resolves_like_obsidian_does(vault):
    org(vault, "Acme Ltda", "Part of [[Knowledge/Organisations/Acme Ltda]].\n")
    org(vault, "Beta Ltda", "Sister of [[Organisations/Acme Ltda]] and [[organisations/acme ltda.md]].\n")
    assert [p for p in wiki_check.run(vault) if p.code == "broken-link"] == []


def test_a_partial_path_link_keeps_the_page_from_being_an_orphan(vault):
    org(vault, "Acme Ltda", "See [[Organisations/Beta Ltda]].\n")
    org(vault, "Beta Ltda", "See [[Organisations/Acme Ltda]].\n")
    assert [p for p in wiki_check.run(vault) if p.code == "orphan"] == []


def test_a_wrong_partial_path_is_still_broken(vault):
    org(vault, "Acme Ltda", "See [[Wrongfolder/Acme Ltda]].\n")
    broken = [p.text for p in wiki_check.run(vault) if p.code == "broken-link"]
    assert broken == ["Acme Ltda: links to [[Wrongfolder/Acme Ltda]], which doesn't exist."]


def test_a_wiki_that_cannot_be_checked_is_one_health_warning(vault, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(wiki_check, "run", boom)
    found = [i for i in run_checks(load(vault)) if i.code.startswith("wiki.")]
    assert [(i.level, i.code, i.message) for i in found] == [
        ("warning", "wiki.unchecked", "The wiki couldn't be checked; run `bron wiki check` for details.")]


def test_a_document_page_with_broken_properties_still_counts_as_its_page(vault):
    from bron.kb import store, wiki

    doc = stored_doc(vault, "lease.pdf", ["Lease text"])
    page = write_page(vault, "Documents/Lease.md", "See [[Harbor Bakery]].\n", type="document", summary="A lease",
                      doc=doc.doc_id)
    org(vault, "Harbor Bakery", "Rents a shop (see [[Lease]]).\n")
    wiki.link_documents(vault, wiki.all_pages(vault))
    page.write_text("---\ntype: [document\n---\nSee [[Harbor Bakery]].\n", encoding="utf-8")  # a YAML typo
    found = codes(vault)
    assert ("bad-properties", "Knowledge/Documents/Lease.md") in found
    assert ("no-page-yet", doc.doc_id) not in found  # no agent is sent to write a second page for it
    assert store.load(vault, doc.doc_id).page == "Knowledge/Documents/Lease.md"
    page.unlink()  # the page is gone: now the document has no page
    assert ("no-page-yet", doc.doc_id) in codes(vault)


def test_an_escaped_pipe_in_a_table_link_is_still_a_link(vault):
    org(vault, "Acme Ltda", "| Who | Role |\n|---|---|\n| [[Beta Ltda\\|Beta]] | buyer |\n")
    org(vault, "Beta Ltda", "| Who | Role |\n|---|---|\n| [[Acme Ltda\\|Acme]] | seller |\n")
    assert wiki_check.run(vault) == []  # no broken link to "Acme Ltda\", no orphan

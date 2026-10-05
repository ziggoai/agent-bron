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

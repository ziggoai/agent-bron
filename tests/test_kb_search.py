import os
import time

import pytest

from bron.kb import embed, index, search, store
from bron.kb.passages import split
from bron.kb.store import Doc, KbError
from kbkit import fake_embed


def add(vault, ident, texts, *, company="Acme", doc_type="contract", date="2025-01-10", fund="", name=None, embedder=fake_embed,
        user_labels=None):
    labels = {"company": company, "doc_type": doc_type, "date": date, "title": name or ident, "fund": fund}
    doc = Doc(store.doc_id_for(ident), ident, "pdf", f"/drive/{ident}.pdf", name or f"{ident}.pdf", "", labels=labels,
              user_labels=user_labels or {})
    passages = [{"text": t, "page": i + 1, "section": "", "header": f"[{company} | {doc_type} | p. {i + 1}]"} for i, t in enumerate(texts)]
    store.save(vault, doc, [], passages)
    index.put(vault, doc, passages, embedder)
    return doc


def ids(hits):
    return [(h.doc_id, h.page) for h in hits]


def test_index_then_search_finds_passage_by_word(vault):
    d = add(vault, "a", ["The liquidation preference is one times.", "Board seats are two."])
    hits = search.search(vault, "liquidation", embedder=fake_embed)
    assert hits[0].doc_id == d.doc_id and hits[0].page == 1
    assert "liquidation preference" in hits[0].text and hits[0].source == "/drive/a.pdf"
    assert hits[0].labels["company"] == "Acme"


def test_filters_exclude_other_companies_types_dates(vault):
    a = add(vault, "a", ["share price clause"], company="Ágora Capital", doc_type="contract", date="2025-01-10")
    b = add(vault, "b", ["share price clause"], company="Beta", doc_type="report", date="2024-03-01")
    q = dict(embedder=fake_embed)
    assert {h.doc_id for h in search.search(vault, "share price", **q)} == {a.doc_id, b.doc_id}
    assert [h.doc_id for h in search.search(vault, "share price", company="agora", **q)] == [a.doc_id]
    assert [h.doc_id for h in search.search(vault, "share price", doc_type="report", **q)] == [b.doc_id]
    assert [h.doc_id for h in search.search(vault, "share price", after="2025-01-01", **q)] == [a.doc_id]
    assert [h.doc_id for h in search.search(vault, "share price", before="2024-12-31", **q)] == [b.doc_id]
    assert search.search(vault, "share price", company="nobody", **q) == []


def test_user_labels_filter(vault):
    a = add(vault, "a", ["fee schedule"], user_labels={"company": "Override Ltda"})
    add(vault, "b", ["fee schedule"])
    q = dict(embedder=fake_embed)
    assert [h.doc_id for h in search.search(vault, "fee", company="override", **q)] == [a.doc_id]
    assert search.search(vault, "fee", company="Acme", **q)[0].labels["company"] == "Acme"


def test_a_stored_fund_label_counts_as_the_company(vault):
    """Documents read by Bron 0.7.0 may carry a "fund" label: it is found and shown as the company when there is none."""
    a = add(vault, "a", ["fee schedule"], company="", fund="Fund I")
    add(vault, "b", ["fee schedule"], fund="Fund II")  # has a company: that one stands
    c = add(vault, "c", ["fee schedule"], company="", user_labels={"fund": "Fund Three"})
    q = dict(embedder=fake_embed)
    hits = search.search(vault, "fee", company="fund i ", **q)
    assert [h.doc_id for h in hits] == [a.doc_id]
    assert hits[0].labels["company"] == "Fund I" and "fund" not in hits[0].labels
    assert search.search(vault, "fee", company="fund ii", **q) == []
    assert [h.doc_id for h in search.search(vault, "fee", company="fund three", **q)] == [c.doc_id]
    with pytest.raises(TypeError):
        search.search(vault, "fee", fund="Fund I", **q)  # the separate fund filter is gone


def test_a_070_index_keeps_working_without_a_rebuild(vault):
    """An index.db written by 0.7.0 (same schema, the fund in its own column) is searched as it is."""
    d = add(vault, "a", ["fee schedule"], company="", fund="Fund I")
    con = index.open(vault)
    with con:
        con.execute("UPDATE docs SET company = '', fund = 'Fund I' WHERE doc_id = ?", (d.doc_id,))  # as 0.7.0 wrote it
    before = (index.counter(con), con.execute("PRAGMA user_version").fetchone()[0])
    con.close()
    inode = index.db_path(vault).stat().st_ino
    q = dict(embedder=fake_embed)
    assert [h.doc_id for h in search.search(vault, "fee", company="fund i", **q)] == [d.doc_id]
    assert [h.doc_id for h in search.search(vault, "fee", **q)] == [d.doc_id]
    con = index.open(vault)
    assert (index.counter(con), con.execute("PRAGMA user_version").fetchone()[0]) == before
    con.close()
    assert index.db_path(vault).stat().st_ino == inode  # not rebuilt
    index.put(vault, d, store.passages(vault, d.doc_id), fake_embed)  # written again: the company column holds it now
    con = index.open(vault)
    assert con.execute("SELECT company, fund FROM docs").fetchall() == [("Fund I", "")]
    con.close()


def test_search_finds_amount_in_other_format(vault):
    d = add(vault, "a", ["O investimento foi de R$ 1.500.000,00 na rodada.", "Other text about nothing."])
    add(vault, "b", ["Unrelated content about governance."])
    hits = search.search(vault, "USD 1,500,000.00", embedder=fake_embed)
    assert hits and hits[0].doc_id == d.doc_id and hits[0].page == 1


def test_meaning_path_ranks_when_keyword_finds_nothing(vault):
    # no FTS word shared with the query, but plenty of fake-embedding collisions would be needed: use a hash collision
    import zlib
    from kbkit import FakeEmbedder

    emb = FakeEmbedder()
    target = "zebra"
    twin = next(w for w in (f"w{i}" for i in range(5000)) if zlib.crc32(w.encode()) % 384 == zlib.crc32(target.encode()) % 384)
    d = add(vault, "a", [f"{twin} alone"], embedder=emb)
    add(vault, "b", ["completely different"], embedder=emb)
    # keyword finds nothing for the query word
    con = index.open(vault)
    assert search._keyword(con, target, None) == []
    con.close()
    hits = search.search(vault, target, embedder=emb)
    assert hits and hits[0].doc_id == d.doc_id


def test_rrf_passage_found_by_both_ranks_first(vault):
    fused = search._fuse([("a", 0), ("b", 0), ("c", 0)], [("c", 0), ("d", 0)])
    assert fused[0][0] == ("c", 0)
    assert abs(fused[0][1] - (1 / 63 + 1 / 61)) < 1e-9
    d = add(vault, "x", ["apple banana cherry", "apple only here", "nothing relevant"])
    hits = search.search(vault, "apple banana cherry", embedder=fake_embed)
    assert hits[0].page == 1 and len({(h.doc_id, h.page) for h in hits}) == len(hits)


def test_replacing_a_document_removes_old_passages(vault):
    add(vault, "a", ["old unique phrase here"])
    assert search.search(vault, "unique", embedder=fake_embed)
    add(vault, "a", ["brand new text"])
    assert search.search(vault, "unique", embedder=fake_embed) == []
    assert search.search(vault, "brand", embedder=fake_embed)
    con = index.open(vault)
    assert con.execute("SELECT COUNT(*) FROM docs").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM fts").fetchone()[0] == 1
    con.close()


def test_forget_and_drop(vault):
    d = add(vault, "a", ["findable word"])
    store.forget(vault, d.doc_id)
    index.drop(vault, d.doc_id, fake_embed)
    assert search.search(vault, "findable", embedder=fake_embed) == []
    con = index.open(vault)
    assert con.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == 0
    con.close()


def test_corrupt_index_is_rebuilt_from_store(vault):
    d = add(vault, "a", ["recoverable passage text"])
    path = index.db_path(vault)
    path.write_bytes(b"this is not a database" * 100)
    hits = search.search(vault, "recoverable", embedder=fake_embed)
    assert hits and hits[0].doc_id == d.doc_id


def test_unrecoverable_index_gives_plain_error(vault, monkeypatch):
    add(vault, "a", ["text"])
    import sqlite3

    def boom(v):
        raise sqlite3.DatabaseError("still broken")

    monkeypatch.setattr(index, "open", boom)
    with pytest.raises(KbError) as err:
        search.search(vault, "text", embedder=fake_embed)
    assert "Traceback" not in str(err.value) and "safe" in str(err.value)


def test_old_schema_version_is_rebuilt(vault):
    d = add(vault, "a", ["versioned text"])
    import sqlite3

    con = sqlite3.connect(index.db_path(vault))
    con.execute("PRAGMA user_version = 99")
    con.commit()
    con.close()
    assert search.search(vault, "versioned", embedder=fake_embed)[0].doc_id == d.doc_id


def test_search_is_fast_for_3000_passages(vault):
    for i in range(30):
        add(vault, f"d{i}", [f"clause {i}-{j} alpha{j} beta{i} gamma text of the agreement" for j in range(100)])
    start = time.perf_counter()
    hits = search.search(vault, "alpha7 beta3", embedder=fake_embed)
    cold = time.perf_counter() - start
    start = time.perf_counter()
    search.search(vault, "alpha7 beta3 gamma", embedder=fake_embed, company="acme")
    warm = time.perf_counter() - start
    assert hits and cold < 0.2 and warm < 0.2, (cold, warm)


def test_render(vault):
    add(vault, "a", ["x" * 2000], name="Term sheet")
    out = search.render(search.search(vault, "x" * 2000, embedder=fake_embed))
    lines = out.splitlines()
    assert lines[0] == "1. Term sheet · Acme · contract · 2025-01-10 · p. 1"
    assert lines[1] == "/drive/a.pdf" and len(lines[2]) <= 1201


def test_embedder_is_lazy_and_constants(tmp_path):
    assert embed.DIM == 384 and embed.MODEL.endswith("paraphrase-multilingual-MiniLM-L12-v2")
    e = embed.Embedder(tmp_path / "m")
    assert e._model is None and e.embed([]).shape == (0, 384)


@pytest.mark.slow
def test_real_model_english_question_finds_portuguese_passage(vault):
    emb = embed.get(vault)
    add(vault, "sha", ["CLÁUSULA 4.2 – Preferência na Liquidação. Em caso de liquidação, os investidores recebem 1x o valor investido antes dos fundadores."],
        embedder=emb)
    add(vault, "fees", ["Management fee de 2% ao ano sobre o capital comprometido, pago trimestralmente."], embedder=emb)
    add(vault, "board", ["O conselho de administração terá três membros, sendo um indicado pelo investidor."], embedder=emb)
    hits = search.search(vault, "what happens to investors in a liquidation preference?", embedder=emb)
    assert hits[0].doc_id == store.doc_id_for("sha")


# ---- fix round 1 ----

import sqlite3

from kbkit import FakeEmbedder


def save_only(vault, ident, texts, company="Acme"):
    """A document in the store but not in the index (and with no saved vectors)."""
    labels = {"company": company, "doc_type": "contract", "date": "2025-01-10", "title": ident}
    doc = Doc(store.doc_id_for(ident), ident, "pdf", f"/drive/{ident}.pdf", f"{ident}.pdf", "", labels=labels)
    passages = [{"text": t, "page": i + 1, "section": "", "header": f"[{company} | p. {i + 1}]"} for i, t in enumerate(texts)]
    store.save(vault, doc, [], passages)
    return doc


def test_locked_index_is_busy_not_corrupt(vault, monkeypatch):
    d = add(vault, "a", ["locked passage"])
    monkeypatch.setattr(index, "BUSY_MS", 100)
    other = sqlite3.connect(index.db_path(vault))
    other.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(KbError) as err:
            add(vault, "b", ["second doc"])
        assert "busy" in str(err.value)
        assert index.db_path(vault).exists()
        assert search.search(vault, "locked", embedder=fake_embed)[0].doc_id == d.doc_id  # readers are not blocked
    finally:
        other.rollback()
        other.close()
    assert search.search(vault, "locked", embedder=fake_embed)[0].doc_id == d.doc_id


def test_other_operational_errors_are_plain_and_keep_the_index(vault, monkeypatch):
    add(vault, "a", ["some text"])

    def boom(v, embedder, *a, **k):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(search, "_search", boom)
    with pytest.raises(KbError) as err:
        search.search(vault, "text", embedder=fake_embed)
    assert "disk I/O error" in str(err.value) and index.db_path(vault).exists()


class FailsOnSecond(FakeEmbedder):
    def embed(self, texts):
        if self.calls >= 1:
            raise KbError("model went away")
        return super().embed(texts)


class StopsOnSecond(FakeEmbedder):
    def embed(self, texts):
        if self.calls >= 1:
            raise RuntimeError("interrupted")  # a missing model is not an interruption: see the next test
        return super().embed(texts)


def test_interrupted_rebuild_leaves_no_partial_index(vault):
    save_only(vault, "a", ["alpha text"])
    save_only(vault, "b", ["beta text"])
    with pytest.raises(RuntimeError):
        index.rebuild(vault, StopsOnSecond())
    assert not index.db_path(vault).exists()
    assert not list(index.db_path(vault).parent.glob("index.db*"))
    assert len(search.search(vault, "text", embedder=FakeEmbedder())) == 2  # next search rebuilds fully


def test_a_rebuild_while_the_model_is_away_keeps_every_document_for_keywords(vault):
    save_only(vault, "a", ["alpha text"])
    save_only(vault, "b", ["beta text"])
    index.rebuild(vault, FailsOnSecond())
    assert sorted(d.vectors_pending for d in store.all_docs(vault)) == [False, True]
    assert len(store.indexing_ids(vault)) == 1  # its vectors are added by a later search

    class Away(FakeEmbedder):
        def embed(self, texts):
            raise KbError("The meaning-search model couldn't be loaded (offline). Keyword search still works.")

    assert len(search.search(vault, "text", embedder=Away())) == 2


def test_missing_index_is_rebuilt_from_store(vault):
    a = save_only(vault, "a", ["findable passage"])
    assert not index.db_path(vault).exists()
    hits = search.search(vault, "findable", embedder=fake_embed)
    assert hits and hits[0].doc_id == a.doc_id


def test_put_on_missing_index_keeps_other_documents(vault):
    save_only(vault, "a", ["older document text"])
    add(vault, "b", ["newer document text"])
    assert len(search.search(vault, "document", embedder=fake_embed)) == 2


def test_vectors_are_saved_with_the_document(vault):
    import json

    import numpy as np

    d = add(vault, "a", ["word " * 150])  # 2 windows
    folder = store.kb_dir(vault) / "docs" / d.doc_id
    vecs = np.load(folder / "vectors.npy")
    meta = json.loads((folder / "vectors.json").read_text())
    assert vecs.shape == (2, 384) and vecs.dtype == np.float32
    assert meta["count"] == 2 and meta["model"] == "fake-embedder" and len(meta["hash"]) == 64
    store.forget(vault, d.doc_id)
    assert not folder.exists()


def test_rebuild_reuses_saved_vectors(vault):
    add(vault, "a", ["first doc text"])
    add(vault, "b", ["second doc text"])
    emb = FakeEmbedder()
    index.rebuild(vault, emb)
    assert emb.calls == 0
    assert len(search.search(vault, "doc", embedder=emb)) == 2


def test_changed_header_reembeds_only_that_document(vault):
    a = add(vault, "a", ["first doc text"])
    add(vault, "b", ["second doc text"])
    passages = store.passages(vault, a.doc_id)
    passages[0]["header"] = "[Renamed Co | p. 1]"
    store.save(vault, a, [], passages)
    emb = FakeEmbedder()
    index.rebuild(vault, emb)
    assert emb.seen and all("Renamed Co" in t for t in emb.seen)


def test_vector_matrix_is_cached_between_searches(vault, monkeypatch):
    add(vault, "a", ["cached text"])
    loads = []
    real = search._read_vectors
    monkeypatch.setattr(search, "_read_vectors", lambda con: loads.append(1) or real(con))
    search.search(vault, "cached", embedder=fake_embed)
    search.search(vault, "text", embedder=fake_embed)
    assert len(loads) == 1
    add(vault, "b", ["more text"])
    search.search(vault, "text", embedder=fake_embed)
    assert len(loads) == 2


def test_number_runs_stay_together(vault):
    right = add(vault, "right", ["Cláusula 4.2 Preferência na liquidação"], name="right")
    add(vault, "wrong", ["Cláusula sobre 4 pessoas e 2 sócios"], name="wrong")
    con = index.open(vault)
    got = search._keyword(con, "cláusula 4.2", None)
    con.close()
    assert got[0][0] == right.doc_id
    terms = search._query_terms("valor 1.500.000,00 e 4.2")
    assert '"1 500 000 00"' in terms and '"4 2"' in terms and '"valor"' in terms and '"4"' not in terms


def test_replace_updates_vector_rows_and_limit_zero(vault):
    add(vault, "a", ["word " * 150])
    add(vault, "a", ["short text"])
    con = index.open(vault)
    assert con.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == 1
    con.close()
    assert search.search(vault, "short", embedder=fake_embed, limit=0) == []
    assert search.search(vault, "short", embedder=fake_embed, limit=-3) == []


def test_render_shows_a_stored_fund_as_the_company(vault):
    add(vault, "a", ["fund text"], company="", fund="Fund I", name="Report")
    out = search.render(search.search(vault, "fund", embedder=fake_embed))
    assert out.splitlines()[0].startswith("1. Report · Fund I · ")


def test_model_failure_degrades_to_keyword_search(vault):
    d = add(vault, "a", ["keyword survives"])

    class Down:
        def embed(self, texts):
            raise KbError("The meaning-search model couldn't be loaded (offline). Keyword search still works.")

    assert search.search(vault, "keyword", embedder=Down())[0].doc_id == d.doc_id


def test_embedder_load_failure_message(tmp_path, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "fastembed", None)
    with pytest.raises(KbError) as err:
        embed.Embedder(tmp_path / "m").embed(["x"])
    assert "meaning-search model couldn't be loaded" in str(err.value) and "Keyword search still works" in str(err.value)

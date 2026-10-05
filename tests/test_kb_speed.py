"""Speed: 1,000 generated text pages read and indexed with the real meaning model; a warm search is quick.
Run with: BRON_SLOW=1 uv run --project core/Engine pytest tests/test_kb_speed.py -q -s"""
import random
import time

import pytest

from bron.kb import embed, ingest, search, sources
from bron.loader import load
from kbkit import make_text_pdf

pytestmark = pytest.mark.slow

WORDS = ("capital fund investor valuation round share option vesting board director revenue margin runway cash "
         "contract clause payment closing escrow warrant liquidation preference dividend audit tax report").split()


def page_text(rng, n):
    return f"Page {n}. " + " ".join(rng.choice(WORDS) for _ in range(90)) + f" reference code Z{n:04d}."


def test_a_thousand_pages_read_and_a_warm_search_is_fast(vault, tmp_path, monkeypatch):
    monkeypatch.setenv("BRON_VAULT", str(vault.root))
    rng = random.Random(7)
    cfg = load(vault)
    embedder = embed.get(vault)
    embedder.embed(["warm up the model"])  # the download (first run only) is not part of the timing
    folder = tmp_path / "docs"
    folder.mkdir()
    files = [make_text_pdf(folder / f"report-{d}.pdf", [page_text(rng, d * 100 + p) for p in range(100)]) for d in range(10)]
    started = time.time()
    for path in files:
        item = sources.Item("file", f"file:{path}", str(path), path.name, str(path), "")
        doc = ingest.read_item(vault, cfg, item, embedder=embedder)
        assert doc.status == "read", doc.error
    reading = time.time() - started
    query = "reference code Z0742"
    search.search(vault, query, embedder=embedder)  # first search loads the index
    timings = []
    for _ in range(5):
        t = time.time()
        hits = search.search(vault, query, embedder=embedder)
        timings.append(time.time() - t)
    print(f"\n1,000 pages read and indexed in {reading:.1f}s; warm search {min(timings):.3f}s best, {max(timings):.3f}s worst")
    print([(h.name, h.page, "Z0742" in h.text) for h in hits])
    assert hits and any("Z0742" in h.text for h in hits)
    assert min(timings) < 0.2

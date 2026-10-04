import subprocess
from pathlib import Path

import pytest

from bron.kb import readers
from bron.kb.store import KbError
from kbkit import make_docx, make_pptx, make_png, make_scanned_pdf, make_text_pdf, make_xlsx


def fake_ocr(image):
    return "TEXTO RECONHECIDO", 0.9


def test_text_pdf_pages(tmp_path):
    pdf = make_text_pdf(tmp_path / "a.pdf", ["Clausula 4.2 Preferencia na Liquidacao. " * 3, "Section 5 Management fee of 2% per year. " * 3])
    out = readers.read(pdf, ocr=fake_ocr, work=tmp_path)
    assert out.kind == "pdf" and len(out.pages) == 2
    assert "Preferencia" in out.pages[0].text and not out.pages[0].ocr


def test_scanned_pdf_uses_ocr(tmp_path):
    pdf = make_scanned_pdf(tmp_path / "s.pdf", ["CLÁUSULA 4.2"])
    out = readers.read(pdf, ocr=fake_ocr, work=tmp_path)
    assert out.pages[0].ocr and out.pages[0].text == "TEXTO RECONHECIDO" and out.pages[0].image.exists()


def test_mixed_pdf_keeps_page_numbers(tmp_path):
    first = make_text_pdf(tmp_path / "t.pdf", ["Page one text that is long enough to count as real text."])
    # concatenate a text page and a scanned page with pypdfium2
    import pypdfium2 as pdfium
    scanned = make_scanned_pdf(tmp_path / "s.pdf", ["scan"])
    doc = pdfium.PdfDocument(first)
    doc.import_pages(pdfium.PdfDocument(scanned))
    mixed = tmp_path / "mixed.pdf"
    doc.save(mixed)
    out = readers.read(mixed, ocr=fake_ocr, work=tmp_path)
    assert [p.number for p in out.pages] == [1, 2] and [p.ocr for p in out.pages] == [False, True]


def test_password_protected_pdf_is_a_plain_error(tmp_path, monkeypatch):
    import pypdfium2 as pdfium
    def locked(*a, **k):
        raise pdfium.PdfiumError("Failed to load document (PDFium: Incorrect password error).")
    monkeypatch.setattr(pdfium, "PdfDocument", locked)
    with pytest.raises(KbError, match="password-protected"):
        readers.read(make_text_pdf(tmp_path / "p.pdf", ["x"]), ocr=fake_ocr, work=tmp_path)


def test_damaged_file(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(KbError, match="damaged"):
        readers.read(bad, ocr=fake_ocr, work=tmp_path)


def test_xlsx_sheets_become_tables(tmp_path):
    x = make_xlsx(tmp_path / "f.xlsx", {"P&L": [["Ano", "Receita"], [2024, 12345], [2025, 15678]], "Empty": [], "Cash": [["Mes", "Caixa"], ["Jan", 3.2]]})
    out = readers.read(x, ocr=fake_ocr, work=tmp_path)
    assert out.kind == "sheet" and len(out.pages) == 2
    assert out.pages[0].text.startswith("Sheet: P&L") and "| Ano | Receita |" in out.pages[0].text and "15678" in out.pages[0].text


def test_big_sheet_repeats_header(tmp_path):
    rows = [["Company", "FMV"]] + [[f"Co {i}", i] for i in range(120)]
    out = readers.read(make_xlsx(tmp_path / "b.xlsx", {"Portfolio": rows}), ocr=fake_ocr, work=tmp_path)
    assert len(out.pages) == 3 and all("| Company | FMV |" in p.text for p in out.pages)


def test_docx_headings_and_tables(tmp_path):
    d = make_docx(tmp_path / "m.docx", [("h1", "Investment Memo"), ("p", "Acme raised a Series B."), ("table", [["Round", "Amount"], ["B", "1,500,000.00"]])])
    out = readers.read(d, ocr=fake_ocr, work=tmp_path)
    assert "# Investment Memo" in out.pages[0].text and "| B | 1,500,000.00 |" in out.pages[0].text


def test_pptx_one_page_per_slide(tmp_path):
    p = make_pptx(tmp_path / "deck.pptx", [("Q3 Update", "Revenue grew 20%"), ("Runway", "18 months")])
    out = readers.read(p, ocr=fake_ocr, work=tmp_path)
    assert out.kind == "slides" and len(out.pages) == 2 and "Runway" in out.pages[1].text


def test_image_and_html(tmp_path):
    out = readers.read(make_png(tmp_path / "i.png", ["hello"]), ocr=fake_ocr, work=tmp_path)
    assert out.pages[0].ocr
    web = readers.read_html("<html><body><nav>Menu</nav><article><h1>Fund news</h1><p>" + "The fund closed. " * 30 + "</p></article></body></html>", "https://e.com")
    assert "The fund closed." in web.pages[0].text


def test_unsupported_type(tmp_path):
    f = tmp_path / "x.zip"
    f.write_bytes(b"PK")
    with pytest.raises(KbError, match="can't read .zip files yet"):
        readers.read(f, ocr=fake_ocr, work=tmp_path)


@pytest.mark.slow
def test_real_mac_text_recognition_reads_portuguese(tmp_path):
    img = make_png(tmp_path / "pt.png", ["CLÁUSULA 4.2 – Preferência na Liquidação", "R$ 1.500.000,00"])
    text, confidence = readers.ocr_page(img)
    assert "Preferência" in text and "1.500.000,00" in text and confidence > 0.5


# ---- fix round 1 ----

LONG = "Clausula 4.2 Preferencia na Liquidacao e Management fee of 2% per year. "


def test_garbled_cid_text_layer_goes_to_ocr(tmp_path):
    pdf = make_text_pdf(tmp_path / "c.pdf", ["(cid:12)(cid:45)(cid:7) " * 8])
    out = readers.read(pdf, ocr=fake_ocr, work=tmp_path)
    assert out.pages[0].ocr


def test_symbol_soup_text_layer_goes_to_ocr(tmp_path):
    pdf = make_text_pdf(tmp_path / "g.pdf", ["@#$%^&*~ <>?/ |{} +=_ " * 6])
    assert readers.read(pdf, ocr=fake_ocr, work=tmp_path).pages[0].ocr


def test_private_use_characters_need_ocr():
    assert readers._needs_ocr(" abcdefgh " * 6)
    assert not readers._needs_ocr(LONG)


def test_thin_header_over_full_page_scan_goes_to_ocr(tmp_path):
    pdf = make_text_pdf(tmp_path / "h.pdf", ["CONFIDENTIAL - Fund II - Page header text here, long."], full_page_image=True)
    assert readers.read(pdf, ocr=fake_ocr, work=tmp_path).pages[0].ocr


def test_long_text_over_an_image_stays_text(tmp_path):
    pdf = make_text_pdf(tmp_path / "t.pdf", [LONG * 4], full_page_image=True)
    assert not readers.read(pdf, ocr=fake_ocr, work=tmp_path).pages[0].ocr


def test_normal_text_page_stays_text(tmp_path):
    pdf = make_text_pdf(tmp_path / "n.pdf", [LONG])
    assert not readers.read(pdf, ocr=fake_ocr, work=tmp_path).pages[0].ocr


@pytest.mark.parametrize("name", ["a.xlsx", "a.xlsm", "a.docx", "a.pptx"])
def test_password_protected_office_files(tmp_path, name):
    f = tmp_path / name
    f.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"\0" * 100)
    with pytest.raises(KbError, match="password-protected"):
        readers.read(f, ocr=fake_ocr, work=tmp_path)


def test_old_xls_with_ole2_header_is_not_called_password_protected(tmp_path):
    f = tmp_path / "old.xls"
    f.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"\0" * 100)
    with pytest.raises(KbError, match="damaged"):
        readers.read(f, ocr=fake_ocr, work=tmp_path)


@pytest.mark.parametrize("name,kind", [("b.xlsx", "spreadsheet"), ("b.docx", "Word document"), ("b.pptx", "PowerPoint file")])
def test_damaged_office_files(tmp_path, name, kind):
    f = tmp_path / name
    f.write_bytes(b"not an office file")
    with pytest.raises(KbError, match=f"damaged or isn't really a {kind}"):
        readers.read(f, ocr=fake_ocr, work=tmp_path)


def test_damaged_image_uses_the_right_article(tmp_path):
    f = tmp_path / "b.png"
    f.write_bytes(b"nope")
    with pytest.raises(KbError, match="isn't really an image"):
        readers.read(f, ocr=fake_ocr, work=tmp_path)


def test_heic_is_converted_with_sips_then_read(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        Path(argv[argv.index("--out") + 1]).write_bytes(b"png")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(readers.subprocess, "run", fake_run)
    seen = []
    heic = tmp_path / "photo.heic"
    heic.write_bytes(b"x")
    out = readers.read(heic, ocr=lambda i: (seen.append(i) or ("TEXT", 0.8)), work=tmp_path / "w")
    assert calls[0][:5] == ["sips", "-s", "format", "png", str(heic)]
    assert seen == [out.pages[0].image] and out.pages[0].image.suffix == ".png" and out.pages[0].ocr


def test_heic_output_names_do_not_collide(tmp_path, monkeypatch):
    def fake_run(argv, **kw):
        Path(argv[argv.index("--out") + 1]).write_bytes(b"png")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(readers.subprocess, "run", fake_run)
    a, b = tmp_path / "x" / "p.heic", tmp_path / "y" / "p.heic"
    for f in (a, b):
        f.parent.mkdir()
        f.write_bytes(b"x")
    one = readers.read(a, ocr=fake_ocr, work=tmp_path / "w").pages[0].image
    two = readers.read(b, ocr=fake_ocr, work=tmp_path / "w").pages[0].image
    assert one != two


def test_html_fallback_when_extractor_finds_nothing(tmp_path, monkeypatch):
    import trafilatura
    monkeypatch.setattr(trafilatura, "extract", lambda *a, **k: None)
    web = readers.read_html("<html><head><style>x{}</style></head><body><p>Fund &amp; news</p><script>bad()</script></body></html>", "https://e.com")
    assert web.pages[0].text == "Fund & news"


def test_cell_formatting():
    import datetime as dt
    cell = readers._cell
    assert cell(2024.0) == "2024" and cell(3.2) == "3.2" and cell(1e16) == "10000000000000000"
    assert cell(dt.date(2025, 1, 21)) == "2025-01-21" and cell(dt.datetime(2025, 1, 21, 0, 0)) == "2025-01-21"
    assert cell(dt.datetime(2025, 1, 21, 9, 30)) == "2025-01-21 09:30:00"
    assert cell(True) == "TRUE" and cell(None) == "" and cell("a|b") == "a\\|b"


def test_csv_with_embedded_newline_and_semicolons(tmp_path):
    f = tmp_path / "c.csv"
    f.write_text('Nome;Nota\n"Ana";"linha 1\nlinha 2"\nBia;ok\n', encoding="utf-8")
    text = readers.read(f, ocr=fake_ocr, work=tmp_path).pages[0].text
    assert "| Ana | linha 1 linha 2 |" in text and "| Bia | ok |" in text


def test_ocr_failure_is_a_plain_error(tmp_path):
    def boom(image):
        raise RuntimeError("vision exploded")
    with pytest.raises(KbError, match="couldn't read the text in this scan"):
        readers.read(make_png(tmp_path / "i.png", ["x"]), ocr=boom, work=tmp_path)


@pytest.mark.slow
def test_real_sips_converts_heic(tmp_path):
    from PIL import Image
    src = make_png(tmp_path / "s.png", ["hello"])
    heic = tmp_path / "s.heic"
    done = subprocess.run(["sips", "-s", "format", "heic", str(src), "--out", str(heic)], capture_output=True)
    if done.returncode != 0 or not heic.exists():
        pytest.skip("sips can't write HEIC here")
    out = readers.read(heic, ocr=fake_ocr, work=tmp_path / "w")
    assert out.pages[0].image.exists() and Image.open(out.pages[0].image).size[0] > 0


# ---- fix round 2 ----

def test_dot_leader_contents_page_stays_text(tmp_path):
    lines = ["1 Definicoes " + "." * 30 + " 3", "2 Termos e Condicoes Gerais " + "." * 20 + " 5",
             "3 Preferencia na Liquidacao " + "·" * 20 + " 9", "4 Taxa de Gestao " + "…" * 10 + " 12",
             "5 Direitos de Voto " + "-" * 25 + " 15", "6 Anexos " + "." * 40 + " 20"]
    assert not readers._needs_ocr("\n".join(lines))
    pdf = make_text_pdf(tmp_path / "toc.pdf", [" ".join(lines).replace("·", ".").replace("…", ".")])
    assert not readers.read(pdf, ocr=fake_ocr, work=tmp_path).pages[0].ocr


def test_signature_lines_stay_text():
    assert not readers._needs_ocr("Assinatura: ______________________  Data: ______________  Nome completo do signatario ________")


def test_heavy_mojibake_still_needs_ocr():
    assert readers._needs_ocr("§¤¶•ªº¬÷× ab §¤¶•ªº¬÷× cd §¤¶•ªº¬÷× ef §¤¶•ªº¬÷×")


def test_huge_integral_float_keeps_repr():
    assert readers._cell(1e20) == repr(1e20)

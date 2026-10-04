import pytest

from bron.kb import passages
from bron.kb.readers import Page

LABELS = {"company": "Acme", "doc_type": "LPA", "date": "2025-01-21", "title": "Fund LPA", "language": "en"}


def words(n, word="alpha"):
    return " ".join([word] * n)


def wc(text):
    return len(text.split())


def test_clause_boundaries_portuguese():
    text = (
        f"Cláusula 1.1 Objeto\n{words(320)}\n\n"
        f"Cláusula 2.1 Prazo\n{words(320, 'beta')}\n"
    )
    out = passages.split([Page(1, text)], LABELS)
    assert len(out) == 2
    assert out[0]["text"].startswith("Cláusula 1.1")
    assert out[1]["text"].startswith("Cláusula 2.1")
    assert out[0]["section"].startswith("Cláusula 1.1")
    assert out[1]["section"].startswith("Cláusula 2.1")
    assert all(300 <= wc(p["text"]) <= 500 for p in out)


def test_clause_boundaries_english_and_numbered():
    text = (
        f"Section 4.2 Fees\n{words(320)}\n\n"
        f"4.3 Expenses\n{words(320, 'beta')}\n\n"
        f"ARTICLE TWO\n{words(320, 'gamma')}\n"
    )
    out = passages.split([(1, text)], LABELS)
    assert [p["section"].split()[0] for p in out] == ["Section", "4.3", "ARTICLE"]
    assert all(p["page"] == 1 for p in out)


def test_small_blocks_are_merged_up_to_500_words():
    text = "\n\n".join(f"Cláusula {i}.1 x\n{words(150)}" for i in range(1, 7))
    out = passages.split([(1, text)], LABELS)
    assert len(out) >= 2
    assert all(wc(p["text"]) <= 500 for p in out[:-1])
    assert sum(wc(p["text"]) for p in out) == wc(text)


def test_long_paragraph_is_cut_at_500_words():
    out = passages.split([(1, words(1100))], LABELS)
    assert all(wc(p["text"]) <= 500 for p in out)
    assert sum(wc(p["text"]) for p in out) == 1100


def table(rows):
    lines = ["| Name | Amount | Note |", "| --- | --- | --- |"]
    lines += [f"| row{i} | {i * 10} | {words(4, 'note')} |" for i in range(rows)]
    return "\n".join(lines)


def test_big_table_never_split_mid_row_and_header_repeated():
    tbl = table(200)
    assert wc(tbl) > 500
    text = f"Sheet: Cap table\n{tbl}"
    out = passages.split([(3, text)], LABELS)
    assert len(out) >= 2
    seen_rows = []
    for p in out:
        lines = p["text"].splitlines()
        assert "| Name | Amount | Note |" in lines
        assert "| --- | --- | --- |" in lines
        for line in lines:
            if line.startswith("| row"):
                assert line.count("|") == 4  # whole row, never cut
                seen_rows.append(line)
        assert wc(p["text"]) <= 500
        assert p["section"] == "Sheet: Cap table"
    assert seen_rows == [f"| row{i} | {i * 10} | {words(4, 'note')} |" for i in range(200)]
    assert out[0]["text"].startswith("Sheet: Cap table")  # sheet name not stranded alone


def test_small_table_kept_whole_with_text():
    text = f"Intro paragraph.\n\n{table(5)}\n\nTail."
    out = passages.split([(1, text)], LABELS)
    assert len(out) == 1
    assert table(5) in out[0]["text"]


def test_tiny_pages_joined_to_next_keeping_first_number():
    pages = [Page(1, words(10)), Page(2, words(10, "beta")), Page(3, words(120, "gamma")), Page(4, words(200, "delta"))]
    out = passages.split(pages, LABELS)
    assert [p["page"] for p in out] == [1, 4]
    assert "alpha" in out[0]["text"] and "beta" in out[0]["text"] and "gamma" in out[0]["text"]
    assert "[p. 2]" in out[0]["text"] and "[p. 3]" in out[0]["text"] and "[p. 1]" not in out[0]["text"]


def test_passage_never_spans_full_pages():
    out = passages.split([(1, words(100)), (2, words(100, "beta"))], LABELS)
    assert [p["page"] for p in out] == [1, 2]


def test_empty_pages_skipped_numbering_kept():
    pages = [Page(1, words(120)), Page(2, ""), Page(3, "  \n "), Page(4, words(120, "beta"))]
    out = passages.split(pages, LABELS)
    assert [p["page"] for p in out] == [1, 4]


def test_trailing_tiny_page_still_emitted():
    out = passages.split([(1, words(120)), (2, "Signature page")], LABELS)
    assert [p["page"] for p in out] == [1, 2]


def test_header_contents_and_section_carry_over():
    pages = [(1, f"# Fees\n{words(120)}"), (2, words(120, "beta"))]
    out = passages.split(pages, LABELS)
    assert out[0]["header"] == "[Acme | LPA | 2025-01-21 | Fund LPA | p. 1 | Fees]"
    assert out[1]["section"] == "Fees"
    assert out[1]["header"].endswith("| p. 2 | Fees]")


def test_header_drops_empty_parts_and_page_word():
    out = passages.split([(7, words(120))], {"company": "Acme", "doc_type": "", "title": "Deck"}, page_word="pág.")
    assert out[0]["header"] == "[Acme | Deck | pág. 7]"
    assert out[0]["section"] == ""


def test_all_caps_line_is_heading():
    out = passages.split([(1, f"GENERAL PROVISIONS\n{words(120)}")], LABELS)
    assert out[0]["section"] == "GENERAL PROVISIONS"


@pytest.mark.parametrize(
    "a,b",
    [
        ("1.500.000,00", "1,500,000.00"),
        ("R$ 1,5 mi", "1.500.000"),
        ("US$ 2.3 million", "2,300,000"),
        ("21/01/2025", "2025-01-21"),
        ("21 de janeiro de 2025", "January 21, 2025"),
        ("5 de março de 2024", "2024-03-05"),
    ],
)
def test_amounts_and_dates_match_both_ways(a, b):
    ta, tb = passages.normal_tokens(a), passages.normal_tokens(b)
    assert set(ta) & set(tb), (ta, tb)


def test_amount_token_forms():
    assert "amt1500000_00" in passages.normal_tokens("1.500.000,00")
    assert "amt1500000_00" in passages.normal_tokens("1,500,000.00")
    assert "amt1500000" in passages.normal_tokens("1,500,000.00")
    for text in ["R$ 1,5 mi", "1.5M", "1,5 milhão", "1,5 milhões"]:
        assert "amt1500000" in passages.normal_tokens(text), text
    assert "amt2300000" in passages.normal_tokens("US$ 2.3 million")


def test_thousands_versus_decimals_both_ways():
    assert "amt1234" in passages.normal_tokens("1.234")
    assert "amt1234" in passages.normal_tokens("1,234")
    assert "amt1_50" in passages.normal_tokens("R$ 1,50")
    assert "amt1234" not in passages.normal_tokens("1,5")


def test_date_forms_and_ambiguous_day_first():
    for text in ["21/01/2025", "2025-01-21", "21 de janeiro de 2025", "January 21, 2025", "Jan 21 2025"]:
        assert "date20250121" in passages.normal_tokens(text), text
    assert "date20250201" in passages.normal_tokens("01/02/2025")
    assert "date20250201" in passages.normal_tokens("February 1, 2025")


def test_dates_do_not_leak_amount_tokens():
    toks = passages.normal_tokens("signed on 21/01/2025")
    assert toks == ["date20250121"]


def test_windows_overlap_and_cover():
    text = " ".join(f"w{i}" for i in range(250))
    ws = passages.windows(text)
    assert all(wc(w) <= 100 for w in ws)
    assert ws[1].split()[0] == "w80"
    assert set(" ".join(ws).split()) == set(text.split())
    assert ws[-1].split()[-1] == "w249"


def test_windows_short_and_empty():
    assert passages.windows("a b c") == ["a b c"]
    assert passages.windows("") == []


def amts(text):
    return [t for t in passages.normal_tokens(text) if t.startswith("amt")]


@pytest.mark.parametrize(
    "text",
    [
        "2024",
        "Q3 2025",
        "Section 4.2",
        "Cláusula 4.2",
        "Clause 12",
        "Art. 5",
        "1.5x MOIC",
        "3×",
        "8%",
        "12:30",
        "+55 11 99999-9999",
        "(11) 99999 9999",
        "12.345.678/0001-90",
        "123.456.789-00",
        "$0.0001",
        "9" * 400,
        "5 m",
        "4.2",
        "1,5",
        "31/02/2025",
    ],
)
def test_not_money_gives_no_amount_tokens(text):
    assert amts(text) == []


def test_invalid_date_gives_no_tokens_at_all():
    assert passages.normal_tokens("31/02/2025") == []
    assert passages.normal_tokens("31 de fevereiro de 2025") == []


@pytest.mark.parametrize(
    "text,token",
    [
        ("R$ 2.024", "amt2024"),
        ("2,024 units", "amt2024"),
        ("R$ 2024", "amt2024"),
        ("12.345", "amt12345"),
        ("1500000", "amt1500000"),
        ("1.500", "amt1500"),
        ("1,500", "amt1500"),
        ("1,5 mi", "amt1500000"),
        ("5 mil reais", "amt5000"),
        ("2 MM", "amt2000000"),
        ("3,5 bi", "amt3500000000"),
        ("100 USD", "amt100"),
        ("€ 40", "amt40"),
        ("10k", "amt10000"),
        ("US$ 2.3 million", "amt2300000"),
    ],
)
def test_money_cues_give_amount_tokens(text, token):
    assert token in amts(text)


def test_chunks_after_a_page_join_cite_the_page_they_start_on():
    out = passages.split([Page(1, words(10)), Page(2, words(1000, "beta"))], LABELS)
    assert len(out) >= 2
    assert out[0]["page"] == 1 and "alpha" in out[0]["text"] and "beta" not in out[0]["text"]
    for chunk in out[1:]:
        assert chunk["page"] == 2 and "p. 2" in chunk["header"]
    # a short page and the start of the next one in one chunk: cited at the first page, with a marker at the join
    joined = passages.split([Page(1, words(10)), Page(2, words(60, "beta"))], LABELS)
    assert [c["page"] for c in joined] == [1] and "[p. 2]" in joined[0]["text"]

import pytest

from bron.memory import facts
from bron.memory.secrets import looks_secret


def lines(text):
    return text.splitlines()


def test_add_creates_headings_in_order_and_formats_the_line():
    out = facts.add([], "Reports only include active companies", "decisions", "2026-10-03", "CFO")
    out = facts.add(out, "Prefers short answers, number first", "about-you", "2026-10-03", "Bron")
    text = "\n".join(out)
    assert text.index("## About you") < text.index("## Decisions")
    assert "- Reports only include active companies. (2026-10-03, CFO)" in out
    assert "- Prefers short answers, number first. (2026-10-03, Bron)" in out


def test_parse_reads_dates_and_authors_and_bare_lines():
    found = facts.parse(lines("## Decisions\n- Use Carta as source of truth. (2026-10-02, Bron)\n- A fact I typed myself\n"))
    assert [(f.text, f.date, f.by, f.section) for f in found] == [
        ("Use Carta as source of truth.", "2026-10-02", "Bron", "decisions"),
        ("A fact I typed myself", "", "", "decisions"),
    ]


def test_user_edits_survive_add_and_forget():
    start = lines("# My memory\nSome notes I wrote.\n\n## Decisions\n- Old rule. (2026-01-01, Bron)\n\n## My own heading\n- Custom fact\n")
    out = facts.add(start, "New rule", "decisions", "2026-10-03", "Bron")
    assert out[:2] == ["# My memory", "Some notes I wrote."]
    assert "- Custom fact" in out and "## My own heading" in out
    assert out.index("- New rule. (2026-10-03, Bron)") == out.index("- Old rule. (2026-01-01, Bron)") + 1
    custom = facts.matches(out, "custom")
    assert len(custom) == 1 and custom[0].section == "other"
    out = facts.remove(out, custom[0])
    assert "- Custom fact" not in out and "Some notes I wrote." in out


def test_matches_ignores_case_and_accents():
    found = facts.matches(lines("## Your firm\n- Relatório trimestral sai no dia 15. (2026-10-03, CFO)\n"), "RELATORIO")
    assert len(found) == 1


def test_replace_keeps_the_position():
    start = lines("## Decisions\n- A. (2026-01-01, Bron)\n- Cutoff is FMV > 0. (2026-01-01, Bron)\n- C. (2026-01-01, Bron)\n")
    old = facts.matches(start, "cutoff")[0]
    out = facts.replace(start, old, "Cutoff is FMV > 0 and not written off", "2026-10-03", "CFO")
    assert out[2] == "- Cutoff is FMV > 0 and not written off. (2026-10-03, CFO)"


def test_clean():
    assert facts.clean("  uses   two\nlines ") == "uses two lines."
    assert facts.clean("Ends with a question?") == "Ends with a question?"
    with pytest.raises(ValueError, match="nothing to remember"):
        facts.clean("   ")
    with pytest.raises(ValueError, match="one or two sentences"):
        facts.clean("x" * 301)


def test_size_counts_fact_text_only():
    assert facts.size(lines("# Title\nfree text\n## Decisions\n- Abc. (2026-01-01, Bron)\n")) == 4


@pytest.mark.parametrize("text", [
    "my key is sk-abc123def456ghi789",
    "token ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "AKIAABCDEFGHIJKLMNOP is the AWS key",
    "-----BEGIN PRIVATE KEY-----",
    "password: hunter2",
    "senha do portal: abc123",
    "card 4111 1111 1111 1111",
    "IBAN GB82 WEST 1234 5698 7654 32",
    "use x9Kq2LmP7vT4bN8cR1sW6yZ3 to log in",
    "4111111111111111",
    "api_key=sk-abc123def456",
    "api key: secret123abc",
    "token: ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "secret: abc123abc",
    "client_secret=mysecret",
    "card 4111-1111-1111-1111",
    "pay with 4111111111111111 now",
    "api key is 3f9a8b7c2d1e4f5a6b7c8d9e0f1a2b3c",
    "the webhook secret 9c1e7a2b4d6f8e0a1b3c5d7e9f2a4b6c",
    "log in with k2m9x7q1w5e6r4t0y8u2a3b5",
])
def test_secrets_are_spotted(text):
    assert looks_secret(text)


@pytest.mark.parametrize("text", [
    "Reports only include companies with FMV > 0.",
    "Fund II closed on 2024-03-15 at 1.500.000,00 BRL.",
    "The CNPJ format is 12.345.678/0001-90.",
    "Keep passwords out of Bron.",
    "Call 4111 when the board meets.",
    "CNPJ 36075983867565 ok",
    "CNPJ: 36075983867565.",
    "36075983867565,",
    "36075983867565",
    "12345678901",
    "Quarterly-Report-Q3-2026-Final-Version-v2",
    "Fund-II-2024-Q3-Final-v2-2025",
    "The token budget is 10k per run",
    "Save it as quarterly_report_2026_final_version_2.xlsx",
    "abcdefghijklmnopqrstuvwxyz is the alphabet",
    "Order 123456789012345678901234 shipped",
    "fund-ii-2024-q3-board-pack-final-v2.pdf",
])
def test_ordinary_facts_are_not_secrets(text):
    assert not looks_secret(text)


def test_cnpj_test_number_is_luhn_valid():
    """Verify the CNPJ test number is Luhn-valid so the test doesn't go vacuous."""
    from bron.memory.secrets import _luhn
    assert _luhn("36075983867565"), "Test CNPJ must be Luhn-valid to test the bug"

"""Cut pages into passages for search, and write amounts and dates in one canonical form so
`1.500.000,00` finds `1,500,000.00` and `21/01/2025` finds `January 21, 2025`."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from decimal import Decimal, InvalidOperation

MIN_WORDS = 300
MAX_WORDS = 500
TINY_PAGE_WORDS = 50
CAPS_HEADING_WORDS = 12
SECTION_CHARS = 80

CLAUSE_RE = re.compile(
    r"^(Cláusula|Clausula|CLÁUSULA|Section|SECTION|Art\.|Artigo)\s+[\dIVX]+(\.\d+)*|^\d+(\.\d+)+\s"
)
MARK_RE = re.compile(r"\[p\. (\d+)\]")
MD_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
SHEET_RE = re.compile(r"^Sheet:\s*\S")
SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _words(text: str) -> int:
    return len(text.split())


def _is_table_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _heading_kind(line: str) -> bool:
    s = line.strip()
    if MD_HEADING_RE.match(s) or SHEET_RE.match(s):
        return True
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 3 and s.isupper() and len(s.split()) <= CAPS_HEADING_WORDS and not _is_table_line(s)


def _section_name(line: str) -> str:
    s = line.strip().lstrip("#").strip()
    return s[:SECTION_CHARS]


# A block is (kind, text, section) where kind is "heading", "clause", "text" or "table"; section is the
# heading/clause line that opened the block ("" for the others).
def _blocks(text: str) -> list[tuple[str, str, str]]:
    blocks: list[tuple[str, str, str]] = []
    para: list[str] = []
    para_kind = "text"
    para_section = ""
    table: list[str] = []

    def flush_para() -> None:
        nonlocal para, para_kind, para_section
        if para:
            blocks.append((para_kind, "\n".join(para), para_section))
        para, para_kind, para_section = [], "text", ""

    def flush_table() -> None:
        nonlocal table
        if table:
            blocks.append(("table", "\n".join(table), ""))
        table = []

    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            flush_para()
            flush_table()
        elif _is_table_line(line):
            flush_para()
            table.append(line)
        elif _heading_kind(line):
            flush_para()
            flush_table()
            blocks.append(("heading", line.strip(), _section_name(line)))
        elif CLAUSE_RE.match(line.strip()):
            flush_para()
            flush_table()
            para, para_kind, para_section = [line.strip()], "clause", _section_name(line)
        else:
            flush_table()
            para.append(line.strip())
    flush_para()
    flush_table()
    return blocks


def _cut_words(text: str) -> list[str]:
    """Cut a long run of text into near-equal pieces of at most MAX_WORDS words."""
    words = text.split()
    pieces = -(-len(words) // MAX_WORDS)
    size = -(-len(words) // pieces)
    return [" ".join(words[i : i + size]) for i in range(0, len(words), size)]


def _cut_table(text: str, prefix: str) -> list[str]:
    """Split a long table between rows only, repeating the header (and its divider) in every piece."""
    lines = text.splitlines()
    head = lines[:1]
    if len(lines) > 1 and SEPARATOR_RE.match(lines[1].strip()):
        head = lines[:2]
    rows = lines[len(head) :]
    head_words = _words("\n".join(head))
    pieces: list[list[str]] = []
    current: list[str] = []
    used = head_words + _words(prefix)
    for row in rows:
        w = _words(row)
        if current and used + w > MAX_WORDS:
            pieces.append(current)
            current, used = [], head_words
        current.append(row)
        used += w
    if current:
        pieces.append(current)
    out = []
    for i, rows_part in enumerate(pieces):
        body = "\n".join(head + rows_part)
        out.append(f"{prefix}\n{body}" if i == 0 and prefix else body)
    return out


def _page_units(pages) -> list[tuple[int, str]]:
    """Normalise to (number, text); skip empty pages; join pages under 50 words onto the next one (marking where each later page starts)."""
    units: list[tuple[int, str]] = []
    carry_no: int | None = None
    carry_text = ""
    for page in pages:
        number, text = (page.number, page.text) if hasattr(page, "number") else (page[0], page[1])
        text = (text or "").strip()
        if not text:
            continue
        if carry_no is not None:
            # A later page's text keeps its own page marker, so a citation can name the right page.
            number, text = carry_no, f"{carry_text}\n\n[p. {number}]\n\n{text}"
            carry_no, carry_text = None, ""
        if _words(text) < TINY_PAGE_WORDS:
            carry_no, carry_text = number, text
            continue
        units.append((number, text))
    if carry_no is not None:
        units.append((carry_no, carry_text))
    return units


def _header(labels: dict, page: int, page_word: str, section: str) -> str:
    parts = [
        labels.get("company"),
        labels.get("doc_type"),
        labels.get("date"),
        labels.get("title"),
        f"{page_word} {page}",
        section,
    ]
    return "[" + " | ".join(str(p).strip() for p in parts if p and str(p).strip()) + "]"


def split(pages, labels: dict, *, page_word: str = "p.") -> list[dict]:
    out: list[dict] = []
    section = ""
    labels = labels or {}

    for number, text in _page_units(pages):
        current: list[tuple[str, str]] = []  # (kind, text); kind "mark" is a page marker from a merged short page
        words = 0
        page_now = number  # the page the block being handled is on
        chunk_page = number  # the page the chunk being built starts on
        current_section = section  # section in force at the end of what's in `current`

        def emit(chunks: list[str], sec: str, at: int) -> None:
            for chunk in chunks:
                out.append({"text": chunk, "page": at, "section": sec, "header": _header(labels, at, page_word, sec)})

        def flush() -> None:
            nonlocal current, words, chunk_page
            if current:
                tail = []
                while current and current[-1][0] == "mark":  # a marker belongs with the page it announces
                    tail.insert(0, current.pop())
                if current:
                    emit(["\n\n".join(t for _, t in current)], current_section, chunk_page)
                else:
                    tail = tail[:]  # only markers: nothing to emit
                current = []
                words = sum(_words(t) for _, t in tail)
                current += tail
                if tail:
                    chunk_page = int(MARK_RE.fullmatch(tail[0][1]).group(1))
                else:
                    chunk_page = page_now

        for kind, block, sec in _blocks(text):
            mark = MARK_RE.fullmatch(block.strip())
            if mark:
                kind, page_now = "mark", int(mark.group(1))
                if not current:
                    chunk_page = page_now
                current.append((kind, block.strip()))
                words += _words(block)
                continue
            boundary = kind in ("heading", "clause")
            w = _words(block)
            if boundary:
                if words >= MIN_WORDS:
                    flush()
                section = sec
            if kind == "table" and w > MAX_WORDS:
                prefix = ""
                if current and all(k in ("heading", "mark") for k, _ in current):
                    prefix = "\n\n".join(t for _, t in current)
                    current, words = [], 0
                flush()
                emit(_cut_table(block, prefix), section, page_now)
                chunk_page = page_now
                continue
            pieces = _cut_words(block) if w > MAX_WORDS else [block]
            for piece in pieces:
                pw = _words(piece)
                if current and words + pw > MAX_WORDS:
                    flush()
                if not current:
                    chunk_page = page_now
                current.append((kind, piece))
                words += pw
                current_section = section
        current_section = section
        flush()
    return out


# ---------------------------------------------------------------- amounts and dates

MONTHS = {
    # Portuguese and English, accents removed; abbreviations included.
    "janeiro": 1, "jan": 1, "january": 1,
    "fevereiro": 2, "fev": 2, "february": 2, "feb": 2,
    "marco": 3, "mar": 3, "march": 3,
    "abril": 4, "abr": 4, "april": 4, "apr": 4,
    "maio": 5, "mai": 5, "may": 5,
    "junho": 6, "jun": 6, "june": 6,
    "julho": 7, "jul": 7, "july": 7,
    "agosto": 8, "ago": 8, "august": 8, "aug": 8,
    "setembro": 9, "set": 9, "september": 9, "sep": 9, "sept": 9,
    "outubro": 10, "out": 10, "october": 10, "oct": 10,
    "novembro": 11, "nov": 11, "november": 11,
    "dezembro": 12, "dez": 12, "december": 12, "dec": 12,
}
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
# Accented spellings (março) are matched on the accent-stripped text, so no accents appear in the pattern.
_MONTH = rf"(?P<month>{_MONTH_ALT})\.?"

DATE_PATTERNS = [
    # 2025-01-21, 2025/01/21
    (re.compile(r"(?<!\d)(?P<y>\d{4})[-/](?P<m>\d{1,2})[-/](?P<d>\d{1,2})(?!\d)"), "ymd"),
    # 21/01/2025, 21-01-2025, 21.01.2025: day first
    (re.compile(r"(?<!\d)(?P<d>\d{1,2})[/.-](?P<m>\d{1,2})[/.-](?P<y>\d{4})(?!\d)"), "dmy"),
    # 21 de janeiro de 2025, 21 January 2025, 21st Jan. 2025
    (re.compile(
        rf"(?<!\d)(?P<d>\d{{1,2}})(?:º|°|st|nd|rd|th)?\s+(?:de\s+)?{_MONTH}\s*,?\s*(?:de\s+)?(?P<y>\d{{4}})(?!\d)",
        re.I,
    ), "name"),
    # January 21, 2025 / Jan 21 2025
    (re.compile(
        rf"(?<![A-Za-z]){_MONTH}\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(?P<y>\d{{4}})(?!\d)", re.I
    ), "name"),
]

_SCALES = {
    "mil": 10**3, "thousand": 10**3, "k": 10**3,
    "mi": 10**6, "milhao": 10**6, "milhoes": 10**6, "million": 10**6, "millions": 10**6, "mn": 10**6, "mm": 10**6, "m": 10**6,
    "bi": 10**9, "bilhao": 10**9, "bilhoes": 10**9, "billion": 10**9, "billions": 10**9, "bn": 10**9, "b": 10**9,
}
_SCALE_WORDS = (
    "bilhoes|bilhao|billions|billion|milhoes|milhao|millions|million|thousand|mil|mi|bi|mn|bn"
)
# Words in any case; the letters M, MM and B must be capitals (so `5 m` is not millions), k may be either.
SCALE_RE = re.compile(rf"(?:\s*(?P<word>(?i:{_SCALE_WORDS}))|\s*(?P<letter>MM|M|B|[kK]))(?![A-Za-z])")
CURRENCY_BEFORE_RE = re.compile(r"(?:R\$|US\$|U\$|\$|€|£|\b(?i:BRL|USD|EUR))\s*$")
CURRENCY_AFTER_RE = re.compile(r"\s*(?:(?i:reais|real|dolares|dolar|dollars|dollar|euros|euro|BRL|USD|EUR))(?![A-Za-z])")
CLAUSE_BEFORE_RE = re.compile(r"(?:section|secao|clausula|clause|art\.?|artigo|§|item)\s*$", re.I)
NOT_MONEY_AFTER_RE = re.compile(r"\s*(?:%|[x×](?![A-Za-z]))")
NUMBER_RE = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*")
THOUSANDS_FORM_RE = re.compile(r"\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?")
# Things that look like numbers but are not amounts: IDs (CNPJ, CPF, ranges), times, phone numbers.
ID_RE = re.compile(r"\d[\d.]*[/-]\d[\d./-]*")
TIME_RE = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?::\d{2})?(?!\d)")
PLUS_PHONE_RE = re.compile(r"\+\d[\d ()-]*")
SPACED_PHONE_RE = re.compile(r"(?<![\w.,])\(?\d{2,}\)?(?: \d{2,})+(?![\w.,])")
MAX_INTEGER_DIGITS = 15


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _parse_number(raw: str) -> Decimal | None:
    """Read `1.500.000,00`, `1,500,000.00`, `1,5`, `1.234` and so on.

    Separator rule: with both `.` and `,` present the last one is the decimal point. A separator
    repeated several times is thousands. A single separator followed by exactly 3 digits is
    thousands (`1.234` and `1,234` are both 1234); followed by 1-2 digits it is decimals (`1,5`
    is 1.5, `2,50` is 2.5). Anything else (clause numbers like `5.1.2`) is not an amount.
    """
    seps = [c for c in raw if c in ".,"]
    if not seps:
        return Decimal(raw)
    last = raw.rfind(seps[-1])
    after = raw[last + 1 :]
    if len(set(seps)) == 2:
        decimal_sep = raw[last]
        thousands = raw[:last].replace(decimal_sep, "")
        # the other separator must be a clean thousands separator
        groups = re.split(r"[.,]", thousands)
        if any(len(g) != 3 for g in groups[1:]) or len(after) > 2:
            return None
        return Decimal(re.sub(r"[.,]", "", thousands) + "." + after)
    if len(seps) > 1:
        groups = re.split(r"[.,]", raw)
        if any(len(g) != 3 for g in groups[1:]):
            return None
        return Decimal("".join(groups))
    if len(after) == 3:
        return Decimal(raw.replace(seps[0], ""))
    return Decimal(raw[:last] + "." + after)


def _dates(text: str) -> tuple[list[str], str]:
    found: list[str] = []
    for pattern, _kind in DATE_PATTERNS:
        def take(m: re.Match) -> str:
            gd = m.groupdict()
            month = MONTHS[gd["month"].lower()] if gd.get("month") else int(gd["m"])
            day, year = int(gd["d"]), int(gd["y"])
            if _kind == "dmy" and month > 12 >= day:  # 01/21/2025 can only be month-first
                day, month = month, day
            try:
                value = dt.date(year, month, day)
            except ValueError:  # an invalid date (31/02/2025) gives no tokens at all, not even amounts
                return " "
            found.append(f"date{value:%Y%m%d}")
            return " "

        text = pattern.sub(take, text)
    return found, text


def _blank_phones(text: str) -> str:
    def spaced(m: re.Match) -> str:
        return " " if sum(c.isdigit() for c in m.group(0)) >= 8 else m.group(0)

    for pattern in (ID_RE, TIME_RE, PLUS_PHONE_RE):
        text = pattern.sub(" ", text)
    return SPACED_PHONE_RE.sub(spaced, text)


def normal_tokens(text: str) -> list[str]:
    """Canonical tokens for every date (`date20250121`) and money amount (`amt1500000`, `amt1500000_00`).

    Only numbers that look like money become amounts: a currency marker, a scale word (mi, M, million...),
    thousands separators (`1.500.000`, `12.345`) or a plain integer of 5+ digits. Years, clause numbers,
    percentages, multiples, times, phone numbers and IDs never do.
    """
    tokens: list[str] = []
    dates, rest = _dates(_strip_accents(text))
    tokens.extend(dates)
    rest = _blank_phones(rest)
    for m in NUMBER_RE.finditer(rest):
        raw, before, after = m.group(0), rest[: m.start()], rest[m.end() :]
        if CLAUSE_BEFORE_RE.search(before) or NOT_MONEY_AFTER_RE.match(after):
            continue
        scale = SCALE_RE.match(after)
        money_cue = bool(CURRENCY_BEFORE_RE.search(before) or CURRENCY_AFTER_RE.match(after) or scale)
        if not (money_cue or THOUSANDS_FORM_RE.fullmatch(raw) or re.fullmatch(r"\d{5,}", raw)):
            continue
        try:
            value = _parse_number(raw)
        except InvalidOperation:
            continue
        if value is None:
            continue
        if scale:
            value *= _SCALES[(scale.group("word") or scale.group("letter")).lower()]
        if value < Decimal("0.01") or len(str(int(value))) > MAX_INTEGER_DIGITS:
            continue
        whole = int(value)
        tokens.append(f"amt{whole}")
        written_with_cents = not scale and re.search(r"[.,]\d{1,2}$", raw)
        if written_with_cents or value != whole:
            tokens.append(f"amt{whole}_{int((value - whole) * 100):02d}")
    seen: set[str] = set()
    return [t for t in tokens if not (t in seen or seen.add(t))]


def windows(text: str, size: int = 100, step: int = 80) -> list[str]:
    """Overlapping word windows for meaning search."""
    words = text.split()
    if not words:
        return []
    out = []
    for i in range(0, len(words), step):
        out.append(" ".join(words[i : i + size]))
        if i + size >= len(words):
            break
    return out

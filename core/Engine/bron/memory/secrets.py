"""Text that looks like a password, key or account number is never saved to memory."""
from __future__ import annotations

import re

_PREFIXES = re.compile(r"(?<![\w-])(sk-[\w-]{8,}|ghp_\w{20,}|gho_\w{20,}|xox[abpr]-[\w-]{8,}|AKIA[0-9A-Z]{16})")
_PEM = re.compile(r"-----BEGIN [A-Z ]*(KEY|CERTIFICATE)-----")
_LABELLED = re.compile(r"\b(password|passwd|senha|passcode|pin)\b[^:=]{0,30}[:=]\s*\S+", re.I)
_RANDOM = re.compile(r"\b(?=[A-Za-z0-9_\-]*[A-Za-z])(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9_\-]{24,}\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,4})?\b")
_DIGITS = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")


def _luhn(number: str) -> bool:
    digits = [int(d) for d in number if d.isdigit()]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return len(digits) >= 13 and total % 10 == 0


def looks_secret(text: str) -> bool:
    if _PREFIXES.search(text) or _PEM.search(text) or _LABELLED.search(text):
        return True
    if any(_luhn(m.group(0)) for m in _DIGITS.finditer(text)):
        return True
    if _IBAN.search(text):
        return True
    for match in _RANDOM.finditer(text):
        token = match.group(0)
        if sum(c.isupper() for c in token) and sum(c.islower() for c in token) and sum(c.isdigit() for c in token) >= 3:
            return True
    return False

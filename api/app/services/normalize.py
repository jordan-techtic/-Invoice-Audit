"""Turn raw model strings into clean, typed values. Pure functions, unit tested."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

VIN_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
_TRANSLIT = {
    **{str(i): i for i in range(10)},
    **dict(zip("ABCDEFGH", range(1, 9))),
    **dict(zip("JKLMN", range(1, 6))),
    "P": 7, "R": 9,
    **dict(zip("STUVWXYZ", range(2, 10))),
}
_VIN_OCR_FIXES = {"O": "0", "Q": "0", "I": "1"}  # I, O, Q never appear in real VINs


def parse_money(v) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v)).quantize(Decimal("0.01"))
    s = str(v).strip()
    neg = s.startswith("(") and s.endswith(")") or s.startswith("-")
    s = re.sub(r"[^0-9.,]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        # "1,234" thousands vs "12,50" decimal comma
        s = s.replace(",", "") if re.fullmatch(r"\d{1,3}(,\d{3})+", s) else s.replace(",", ".")
    try:
        d = Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return -d if neg else d


def parse_number(v) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = re.sub(r"[^0-9.\-]", "", str(v).replace(",", ""))
    try:
        return Decimal(s) if s not in ("", "-", ".") else None
    except InvalidOperation:
        return None


_DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%b %d %Y", "%m.%d.%Y"]


def parse_date(v) -> date | None:
    if v is None:
        return None
    s = str(v).strip()
    for f in _DATE_FORMATS:
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    return None


def parse_odometer(v) -> int | None:
    n = parse_number(v)
    if n is None:
        return None
    n = int(n)
    return n if 0 <= n <= 5_000_000 else None


def vin_check_digit_ok(vin: str) -> bool:
    if len(vin) != 17 or any(c not in _TRANSLIT for c in vin):
        return False
    total = sum(_TRANSLIT[c] * w for c, w in zip(vin, VIN_WEIGHTS))
    r = total % 11
    return vin[8] == ("X" if r == 10 else str(r))


def normalize_vin(v) -> tuple[str | None, str]:
    """Return (vin, status) where status is 'ok', 'fixed', 'bad_length', 'bad_check', or 'missing'.

    Uppercases, strips spaces/dashes, and tries the classic OCR confusions (O/Q->0, I->1) before giving up.
    A VIN with a failing check digit is still returned (so an analyst can fix it) but flagged.
    """
    if v is None or str(v).strip() == "":
        return None, "missing"
    raw = re.sub(r"[^A-Za-z0-9]", "", str(v)).upper()
    if len(raw) != 17:
        return (raw or None), "bad_length"
    if vin_check_digit_ok(raw):
        return raw, "ok"
    fixed = "".join(_VIN_OCR_FIXES.get(c, c) for c in raw)
    if fixed != raw and vin_check_digit_ok(fixed):
        return fixed, "fixed"
    return raw, "bad_check"


def clean_text(v, max_len: int = 300) -> str | None:
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s[:max_len] or None


def clean_id(v, max_len: int = 80) -> str | None:
    s = clean_text(v, max_len)
    return s


def normalize_description(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9/& ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()[:300]


def normalize_shop_name(s: str) -> str:
    s = re.sub(r"\b(inc|llc|co|corp|ltd|the)\b\.?", " ", s.lower())
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

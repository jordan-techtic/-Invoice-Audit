"""Read exact text from a PDF that carries it, so a value does not have to be read from pixels.

A model reading a picture mixes up look-alike characters (S/5, Z/2, B/8) even on a perfectly clean PDF, and a VIN has no room for that: the check digit
catches most such slips and the invoice is sent to review every time. A clean PDF already contains the VIN as text. Scans and photos have no text and
keep going to the model as before. Only a VIN that passes its own check digit is ever taken from the text.
"""

from __future__ import annotations

import re

from .normalize import vin_check_digit_ok

_VIN = re.compile(r"(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])")   # I, O and Q never appear in a VIN


def page_texts(data: bytes) -> list[str]:
    """The text of each page of a PDF ("" for a page with none, e.g. a scan). [] if the file cannot be opened as a PDF."""
    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(data)
        out = []
        for page in pdf:
            try:
                out.append(page.get_textpage().get_text_bounded() or "")
            except Exception:  # noqa: BLE001  (one unreadable page must not lose the others)
                out.append("")
        return out
    except Exception:  # noqa: BLE001
        return []


def valid_vins(text: str) -> list[str]:
    """Distinct 17-character VINs in the text that stand alone and pass the check digit, in order of appearance."""
    seen: list[str] = []
    for m in _VIN.findall((text or "").upper()):
        if vin_check_digit_ok(m) and m not in seen:
            seen.append(m)
    return seen


def apply_text_vin(page, text: str) -> bool:
    """Put the VIN printed on the page into the extraction when the text names exactly one valid VIN and the model's differs or is missing.
    Two different VINs in the text (two vehicles) are left alone, as is a model VIN that is one of them. Returns True if the VIN was set."""
    found = valid_vins(text)
    if len(found) != 1:
        return False
    vin = found[0]
    current = (str(page.header.vin.value) if page.header.vin.value is not None else "").upper().replace(" ", "").replace("-", "")
    if current == vin:
        return False
    page.header.vin.value, page.header.vin.confidence = vin, 0.99
    return True

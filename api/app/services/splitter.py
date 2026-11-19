"""Group consecutive pages into invoices, then merge each group into one record.

Boundary rules (applied page by page, in order):
- A page that says it is not an invoice is dropped.
- A page whose invoice number differs from the current invoice's starts a new invoice.
- A page with the same invoice number continues the current invoice.
- A page with no invoice number is a continuation when it says "Page N of M" with N > 1,
  or when the shop is unchanged; otherwise it starts a new invoice.
- A page that says "Page 1 of M" while the current invoice already has pages starts a new invoice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .extraction.schema import HEADER_FIELDS, PageExtraction
from .normalize import normalize_shop_name


@dataclass
class MergedInvoice:
    page_start: int  # 1-based, inclusive
    page_end: int
    header: dict[str, dict]  # field -> {"value", "confidence"}
    lines: list[dict[str, dict]]
    line_meta: list[dict] = None  # parallel to lines: {page, y}


def _inv_no(p: PageExtraction) -> str | None:
    v = p.header.invoice_number.value
    if v is None or str(v).strip() == "":
        return None
    return re.sub(r"[^A-Za-z0-9]", "", str(v)).upper()


def _shop(p: PageExtraction) -> str | None:
    v = p.header.shop_name.value
    return normalize_shop_name(str(v)) if v else None


def split_pages(pages: list[PageExtraction]) -> list[list[int]]:
    """Return groups of 0-based page indexes, one group per invoice."""
    groups: list[list[int]] = []
    cur_no: str | None = None
    cur_shop: str | None = None
    for i, p in enumerate(pages):
        if not p.is_invoice:
            continue
        no, shop = _inv_no(p), _shop(p)
        if not groups:
            new = True
        elif no is not None and cur_no is not None:
            new = no != cur_no
        elif no is not None and cur_no is None:
            new = False  # first page lacked a number (e.g. cut off); adopt it
        elif p.page_number and p.page_number > 1:
            new = False
        elif p.page_number == 1 and groups[-1]:
            new = True
        else:
            new = bool(shop and cur_shop and shop != cur_shop)
        if new:
            groups.append([i])
            cur_no, cur_shop = no, shop
        else:
            groups[-1].append(i)
            cur_no = cur_no or no
            cur_shop = cur_shop or shop
    return groups


_LAST_PAGE_FIELDS = {"subtotal", "tax", "total"}


def merge_group(pages: list[PageExtraction], idxs: list[int]) -> MergedInvoice:
    header: dict[str, dict] = {}
    for f in HEADER_FIELDS:
        cands = [(getattr(pages[i].header, f), i) for i in idxs if getattr(pages[i].header, f).value is not None]
        if not cands:
            header[f] = {"value": None, "confidence": 0.0}
            continue
        if f in _LAST_PAGE_FIELDS:
            s, _ = cands[-1]
        else:
            s, _ = max(cands, key=lambda c: c[0].confidence)
        header[f] = {"value": s.value, "confidence": s.confidence}
    lines = [{k: {"value": v["value"], "confidence": v["confidence"]} for k, v in ln.model_dump().items() if k != "y_center"} for i in idxs for ln in pages[i].lines]
    meta = [{"page": i + 1, "y": ln.y_center} for i in idxs for ln in pages[i].lines]
    return MergedInvoice(page_start=idxs[0] + 1, page_end=idxs[-1] + 1, header=header, lines=lines, line_meta=meta)

"""Mark flags whose inputs are fields the extraction was unsure about (still 'needs review').

A flag built on a misread number is the main source of false positives, so the analyst is told to check the image first.
"""

from .types import FlagDraft

LINE_FIELDS = {
    "labour_over_benchmark": ["labour_hours", "labour_rate", "vmrs_code"],
    "parts_price_outlier": ["parts_price", "qty", "part_number", "line_total"],
    "repeat_repair": ["vmrs_code", "line_total"],
    "warranty_eligible": ["vmrs_code", "line_total"],
    "math_error": ["qty", "parts_price", "labour_hours", "labour_rate", "line_total"],
    "duplicate": ["line_total", "description"],
}
INVOICE_FIELDS = {
    "repeat_repair": ["invoice_date", "odometer", "unit_number"],
    "warranty_eligible": ["invoice_date", "odometer", "unit_number"],
    "duplicate": ["invoice_number", "shop_name", "total", "invoice_date", "unit_number"],
    "math_error": ["subtotal", "tax", "total"],
}


def uncertain_fields(d: FlagDraft, needs_review: set[tuple[str, str]], lines_of: dict[str, list[str]]) -> list[str]:
    out = []
    whole_invoice = d.type in ("math_error", "duplicate", "repeat_repair", "warranty_eligible")   # these rest on more than the one line the flag points at
    if d.line_id and not whole_invoice:
        line_ids = [d.line_id]
    else:
        line_ids = list(lines_of.get(d.invoice_id, []))
        if d.related_invoice_id and d.type in ("repeat_repair", "warranty_eligible"):
            line_ids += lines_of.get(d.related_invoice_id, [])                                   # the earlier repair's job code matters too
    for lid in line_ids:
        out += [f for f in LINE_FIELDS.get(d.type, []) if (lid, f) in needs_review]
    inv_ids = [d.invoice_id] + ([d.related_invoice_id] if d.related_invoice_id and d.type in ("repeat_repair", "warranty_eligible") else [])
    for iid in inv_ids:
        out += [f for f in INVOICE_FIELDS.get(d.type, []) if (iid, f) in needs_review]
    return sorted(set(out))

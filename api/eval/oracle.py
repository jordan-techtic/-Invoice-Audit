"""Offline stand-in for the model: replays answer-key data with injected read errors.

It NEVER looks at pixels, so accuracy measured with it says nothing about real model quality. It exists to prove the
pipeline, metrics and review-queue plumbing work end to end at scale without an API key. Error rate depends on how
hard the synthetic file is (kind), and the confidence it reports is a made-up calibration: wrong values usually get
low confidence, right values usually high.
"""

from __future__ import annotations

import json
import random

ERR_RATE = {"clean_pdf": 0.02, "skewed_scan": 0.06, "phone_photo": 0.10, "handwritten": 0.22, "multi_pdf": 0.03}


def corrupt(v, rng: random.Random):
    s = str(v)
    if not s:
        return v
    i = rng.randrange(len(s))
    if s[i].isdigit():
        return s[:i] + str((int(s[i]) + rng.randint(1, 9)) % 10) + s[i + 1:]
    return s[:i] + s[i + 1:]


def _scored(v, kind: str, rng: random.Random):
    if v is None:
        return {"value": None, "confidence": 0.0}
    if rng.random() < ERR_RATE[kind]:
        conf = rng.uniform(0.35, 0.78) if rng.random() < 0.7 else rng.uniform(0.82, 0.97)
        return {"value": corrupt(v, rng), "confidence": round(conf, 2)}
    conf = rng.uniform(0.6, 0.78) if rng.random() < 0.03 else rng.uniform(0.88, 0.99)
    return {"value": v, "confidence": round(conf, 2)}


def pages_for_file(entry: dict, rng: random.Random) -> list[str]:
    """One raw JSON page response per page in the file, in order."""
    out: list[tuple[int, str]] = []
    kind = entry["kind"]
    for inv in entry["invoices"]:
        h, lines = inv["header"], inv["lines"]
        n_pages = inv["page_end"] - inv["page_start"] + 1
        chunks = [lines] if n_pages == 1 else [lines[: len(lines) // 2 or 1], lines[len(lines) // 2 or 1:]]
        for p in range(n_pages):
            last = p == n_pages - 1
            header = {k: _scored(h.get(k), kind, rng) for k in ("shop_name", "shop_address", "invoice_number", "invoice_date", "unit_number", "vin", "odometer")}
            for k in ("subtotal", "tax", "total"):
                header[k] = _scored(h.get(k), kind, rng) if last else {"value": None, "confidence": 0.0}
            lns = [{k: _scored(ln.get(k), kind, rng) for k in ("description", "part_number", "qty", "parts_price", "labour_hours", "labour_rate", "line_total")} for ln in chunks[p]]
            out.append((inv["page_start"] + p, json.dumps({
                "is_invoice": True, "page_number": p + 1 if n_pages > 1 else None, "page_count": n_pages if n_pages > 1 else None,
                "rotation_degrees": 0, "header": header, "lines": lns})))
    return [t for _, t in sorted(out)]

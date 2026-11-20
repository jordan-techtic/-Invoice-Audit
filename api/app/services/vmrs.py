"""Line -> VMRS code. Order: client cache, keyword lookup, then AI for whatever is left."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import VmrsCache, VmrsCode
from .normalize import normalize_description


FEE_LINE = re.compile(r"\b(shop supplies|supplies|environmental|enviro|disposal|haz[- ]?mat|surcharge|freight|sundry|fees?|waste|tax)\b", re.I)


def is_fee_line(description: str | None) -> bool:
    """Shop supplies, environmental and similar charges have no VMRS job code, by design: do not ask the AI or an analyst for one."""
    return bool(description and FEE_LINE.search(description))


@dataclass
class Classification:
    code: str | None
    confidence: float
    source: str  # cache | lookup | ai | none


def _kw_pattern(kw: str) -> re.Pattern:
    # Keywords are cleaned the same way as descriptions, so "pm-a" or "u-joint" can match "PM-A service" / "R&R U-joint".
    return re.compile(r"(?<![a-z0-9])" + re.escape(normalize_description(kw)) + r"(?:s|es)?(?![a-z0-9])")  # tolerate plurals


def load_codes(db: Session) -> list[VmrsCode]:
    return list(db.scalars(select(VmrsCode).order_by(VmrsCode.code)))


def codes_prompt(codes: list[VmrsCode]) -> str:
    return "\n".join(f"{c.code} | {c.system} | {c.component}" for c in codes)


def lookup(norm_desc: str, codes: list[VmrsCode]) -> Classification | None:
    """Keyword match. Longest keyword wins; two different codes tied on the longest keyword => ambiguous => None."""
    best_len, best = 0, set()
    for c in codes:
        for kw in filter(None, (normalize_description(k) for k in c.keywords.split(";"))):
            if len(kw) >= best_len and _kw_pattern(kw).search(norm_desc):
                if len(kw) > best_len:
                    best_len, best = len(kw), set()
                best.add(c.code)
    if not best or best_len < 3:
        return None
    if len(best) > 1:
        return None
    return Classification(next(iter(best)), 0.9 if best_len >= 6 else 0.82, "lookup")


def classify_lines(db: Session, descriptions: list[str], provider, upload_id=None, record_run=None) -> list[Classification]:
    """Classify descriptions in one pass. ``db`` must be bound to the client (cache is per client)."""
    codes = load_codes(db)
    valid = {c.code for c in codes}
    results: list[Classification | None] = [None] * len(descriptions)
    norms = [normalize_description(d) for d in descriptions]
    pending: dict[str, list[int]] = {}
    for i, n in enumerate(norms):
        if not n:
            results[i] = Classification(None, 0.0, "none")
            continue
        if is_fee_line(descriptions[i]):
            results[i] = Classification(None, 1.0, "fee")      # certain: there is no job code for a fee line
            continue
        cached = db.scalar(select(VmrsCache).where(VmrsCache.norm_description == n))
        if cached:
            results[i] = Classification(cached.vmrs_code, cached.confidence, "cache")
            continue
        hit = lookup(n, codes)
        if hit:
            results[i] = hit
            db.add(VmrsCache(norm_description=n, vmrs_code=hit.code, confidence=hit.confidence, source="lookup"))
            continue
        pending.setdefault(n, []).append(i)

    if pending:
        texts = list(pending)
        try:
            out = provider.classify(texts, codes_prompt(codes))
            if record_run:
                record_run(out, "classification")
            by_idx = {it.index: it for it in out.items}
        except Exception:
            by_idx = {}
        for j, n in enumerate(texts):
            it = by_idx.get(j)
            if it and it.vmrs_code in valid:
                cls = Classification(it.vmrs_code, max(0.0, min(1.0, it.confidence)), "ai")
                db.add(VmrsCache(norm_description=n, vmrs_code=cls.code, confidence=cls.confidence, source="ai"))
            else:
                cls = Classification(None, 0.0, "none")  # not cached: retry on the next upload
            for i in pending[n]:
                results[i] = cls
    db.flush()
    return [r or Classification(None, 0.0, "none") for r in results]

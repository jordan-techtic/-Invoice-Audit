"""Build the frozen report snapshot from analyst-accepted flags. Nothing here reads flags again after the report is saved."""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..flags.explain import BANNED, HEDGE
from ..flags.types import money
from ..models import Client, Flag, FlagRun, FlagStatus, Invoice, InvoiceLine

log = logging.getLogger("audit.report")  # ids and counts only

TYPE_LABELS = {
    "labour_over_benchmark": "Labour hours above typical", "repeat_repair": "Repeat repair", "warranty_eligible": "Possibly under warranty",
    "parts_price_outlier": "Parts price above typical", "duplicate": "Possible duplicate", "math_error": "Totals don't add up",
}
TEMPLATE_PARAGRAPHS = {
    "labour_over_benchmark": "We found {n} {inv} where the labour hours billed were well above what the same job usually takes, a possible overbilling of about {amt}. It is likely worth asking the shop to explain the extra time before the next invoice is paid.",
    "repeat_repair": "We found {n} {rep} of the same component on the same vehicle soon after the first repair, worth about {amt}. These are possible quality problems with the earlier repair; ask the shop whether the repeat work should be covered.",
    "warranty_eligible": "We found {n} {rep} where a part was replaced again inside its likely warranty period, worth about {amt}. These are possible warranty claims; check the earlier invoice and file a claim with the parts supplier.",
    "parts_price_outlier": "We found {n} {inv} where a part was billed well above its usual price, a possible overcharge of about {amt}. It is likely worth comparing these prices with your other shops.",
    "duplicate": "We found {n} {inv} that look like the same work billed more than once, about {amt} in total. Please check these against your payment records so a possible double payment can be recovered.",
    "math_error": "We found {n} {inv} where the printed totals do not add up, a possible difference of about {amt}. Ask the shop to correct these invoices or credit the difference.",
}


def load_settings() -> dict:
    return json.loads((Path(__file__).parent.parent / "report_settings.json").read_text())


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _bars(rows: dict[str, list], top: int = 8) -> list[dict]:
    items = sorted(({"label": k, "count": v[0], "amount": float(v[1])} for k, v in rows.items()), key=lambda r: -r["amount"])
    if len(items) > top:
        rest = items[top:]
        items = items[:top] + [{"label": "Other", "count": sum(r["count"] for r in rest), "amount": sum(r["amount"] for r in rest)}]
    return items


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!?])\s+", " ".join(text.split()))[0]


def audit_period(dates: list) -> str | None:
    """'Jan 2024 – Sep 2026' from invoice dates, ignoring misread years (the future, or more than 5 years back) so a single bad date can't show on the cover."""
    today = date.today()
    ok = [d for d in dates if d and date(today.year - 5, today.month, 1) <= d <= today]
    return f"{min(ok):%b %Y} – {max(ok):%b %Y}" if ok else None


def open_flag_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Flag).where(Flag.status == FlagStatus.open)) or 0


def has_run_checks(db: Session) -> bool:
    return (db.scalar(select(func.count()).select_from(FlagRun).where(FlagRun.status == "done")) or 0) > 0


def _paragraphs(rows_by_type: dict[str, dict], provider) -> dict[str, str]:
    """AI paragraph per flag type; falls back to the template, and replaces anything accusing or unhedged."""
    out = {t: TEMPLATE_PARAGRAPHS[t].format(
        n=d["count"], amt=money(d["amount"]), inv=_plural(d["count"], "invoice", "invoices"), rep=_plural(d["count"], "repair", "repairs"))
        for t, d in rows_by_type.items()}
    if provider is None or not rows_by_type:
        return out
    payload = [{"type": t, "label": TYPE_LABELS[t], "count": d["count"], "total_dollars": round(d["amount"], 2),
                "examples": d["examples"][:3], "template_paragraph": out[t]} for t, d in rows_by_type.items()]
    try:
        for it in provider.narrate(payload).items:
            text = " ".join(it.paragraph.split())
            if it.type in out and text and not BANNED.search(text) and HEDGE.search(text) and len(text) <= 900:
                out[it.type] = text
    except Exception as e:  # noqa: BLE001
        log.warning("narrative skipped: %s", type(e).__name__)
    return out


def build_snapshot(db: Session, client: Client, offer_text: str | None, provider, expires_at) -> dict:
    cfg = load_settings()
    rows = db.execute(
        select(Flag, Invoice, InvoiceLine).join(Invoice, Invoice.id == Flag.invoice_id).outerjoin(InvoiceLine, InvoiceLine.id == Flag.line_id)
        .where(Flag.status.in_([FlagStatus.accepted, FlagStatus.edited])).order_by(Flag.estimated_dollar_impact.desc())
    ).all()
    invoices = db.execute(select(Invoice.invoice_date, Invoice.total)).all()
    total_spend = float(sum((t for _, t in invoices if t is not None), Decimal(0)))
    period = audit_period([d for d, _ in invoices])
    recoverable = float(sum((f.estimated_dollar_impact for f, _, _ in rows), Decimal(0)))
    empty = not rows

    by_type: dict[str, list] = {}
    by_shop: dict[str, list] = {}
    by_vehicle: dict[str, list] = {}
    detail: dict[str, dict] = {}
    for f, inv, _ln in rows:
        amt = f.estimated_dollar_impact
        for d, k in ((by_type, f.type.value), (by_shop, inv.shop_name_raw or "Unknown shop"), (by_vehicle, inv.unit_number or "Unknown unit")):
            cur = d.setdefault(k, [0, Decimal(0)])
            cur[0] += 1
            cur[1] += amt
        t = detail.setdefault(f.type.value, {"count": 0, "amount": 0.0, "examples": []})
        t["count"] += 1
        t["amount"] += float(amt)
        t["examples"].append(f.plain_english_reason)

    paragraphs = _paragraphs(detail, provider)
    bt = _bars({TYPE_LABELS[k]: v for k, v in by_type.items()})
    type_key = {TYPE_LABELS[k]: k for k in by_type}
    for r in bt:
        r["key"] = type_key.get(r["label"], "other")
    n_inv = len(invoices)
    pct = round(100 * recoverable / total_spend, 1) if total_spend else 0.0
    if empty:
        headline = f"No likely overbilling was found in the {n_inv} invoices we reviewed."
    else:
        headline = f"{money(recoverable)} likely recoverable, {pct}% of {money(total_spend)} reviewed"

    return {
        "empty": empty,
        "branding": {k: cfg[k] for k in ("company_name", "tagline", "accent", "ink", "money", "highlight", "footer", "logo_text")},
        "cover": {"client_name": client.name, "audit_date": date.today().isoformat(), "invoices_reviewed": n_inv, "period": period},
        "summary": {
            "total_spend": total_spend, "recoverable": recoverable, "pct_of_spend": pct, "flag_count": len(rows), "headline": headline,
            "top_findings": [{"sentence": f"{inv.shop_name_raw or 'Unknown shop'}, invoice {inv.invoice_number or 'n/a'}: {_first_sentence(f.plain_english_reason)}",
                              "amount": float(f.estimated_dollar_impact)} for f, inv, _ in rows[:5]],
        },
        "breakdown": {"by_type": bt, "by_shop": _bars(by_shop), "by_vehicle": _bars(by_vehicle)},
        "narratives": [{"type": t, "label": TYPE_LABELS[t], "count": d["count"], "amount": round(d["amount"], 2), "paragraph": paragraphs[t]}
                       for t, d in sorted(detail.items(), key=lambda kv: -kv[1]["amount"])],
        "appendix": [{"invoice_number": inv.invoice_number, "date": inv.invoice_date.isoformat() if inv.invoice_date else None,
                      "shop": inv.shop_name_raw, "unit": inv.unit_number, "reason": f.plain_english_reason,
                      "amount": float(f.estimated_dollar_impact), "type_label": TYPE_LABELS[f.type.value]}
                     for f, inv, _ in sorted(rows, key=lambda r: (r[1].invoice_date or date.min, r[1].invoice_number or ""))],
        "next_steps": {"text": (offer_text if offer_text is not None else cfg["default_offer_text"])},
        "note": cfg["note"],
        "expires_at": expires_at.isoformat() if expires_at else None,
    }

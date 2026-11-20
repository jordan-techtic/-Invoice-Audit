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
from ..models import Client, Flag, FlagRun, FlagStatus, Invoice, InvoiceLine, ReviewStatus

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
    "duplicate": "We found {n} {inv} that {look} like the same work billed more than once, about {amt} in total. Please check these against your payment records so a possible double payment can be recovered.",
    "math_error": "We found {n} {inv} where the printed figures do not add up, a possible difference of about {amt}. Ask the shop to correct these invoices or credit the difference.",
}


def offer_text_for(types: set[str]) -> str:
    """The next steps for a report: only the actions that fit the kinds of finding it contains."""
    cfg = load_settings()
    steps = ["Review the findings in this report with your maintenance team."]
    if types & {"labour_over_benchmark", "parts_price_outlier"}:
        steps.append("Ask the shops listed to look at the invoices flagged as likely overbilling.")
    if "math_error" in types:
        steps.append("Ask the shops listed to correct the invoices where the printed figures do not add up, or to credit the difference.")
    if "duplicate" in types:
        steps.append("Check the possible duplicates against your payment records so a double payment can be recovered.")
    if types & {"warranty_eligible", "repeat_repair"}:
        steps.append("Check the earlier invoice for each repair listed as repeated or possibly under warranty, and file a claim where it applies.")
    steps.append("Talk to us about a monthly audit so these items are caught as they happen.")
    return cfg["offer_intro"] + "\n\nNext steps:\n" + "\n".join(f"{n}. {t}" for n, t in enumerate(steps, start=1))


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
    if not ok:
        return None
    lo, hi = f"{min(ok):%b %Y}", f"{max(ok):%b %Y}"
    return lo if lo == hi else f"{lo} – {hi}"


def open_flag_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Flag).where(Flag.status == FlagStatus.open)) or 0


def flags_basis(db: Session) -> str:
    """A fingerprint of the decisions a report is built from (which flags are accepted or edited, and for how much)."""
    import hashlib

    rows = db.execute(select(Flag.id, Flag.status, Flag.estimated_dollar_impact).where(Flag.status.in_([FlagStatus.accepted, FlagStatus.edited]))).all()
    blob = "|".join(sorted(f"{i}:{st.value}:{amt}" for i, st, amt in rows))
    return hashlib.sha256(blob.encode()).hexdigest()


def accepted_flags_with_changed_inputs(db: Session) -> int:
    """Accepted or edited flags whose underlying numbers changed after the decision (or no longer produce the flag)."""
    rows = db.scalars(select(Flag).where(Flag.status.in_([FlagStatus.accepted, FlagStatus.edited]))).all()
    return sum(1 for f in rows if (f.details or {}).get("inputs_changed") or (f.details or {}).get("no_longer_applies"))


def has_run_checks(db: Session) -> bool:
    return (db.scalar(select(func.count()).select_from(FlagRun).where(FlagRun.status == "done")) or 0) > 0


_COUNTED = re.compile(r"\b(\d+)\s+(?:invoices?|repairs?|findings?)\b", re.I)


def _figures_ok(text: str, d: dict) -> bool:
    """The paragraph quotes only the dollar total, counts and example figures we computed."""
    from ..flags.explain import figures_match, numbers_in

    allowed = [d["amount"]] + [float(x.replace(",", "")) for e in d["examples"] for x in re.findall(r"\$\s?(\d[\d,]*(?:\.\d+)?)", e)]
    if not figures_match(text, allowed):
        return False
    return all(int(n) in {d["count"], d.get("invoices", d["count"])} for n in _COUNTED.findall(text))


def _paragraphs(rows_by_type: dict[str, dict], provider) -> dict[str, str]:
    """AI paragraph per flag type; falls back to the template, and replaces anything accusing, unhedged or quoting a figure we did not compute."""
    out = {t: TEMPLATE_PARAGRAPHS[t].format(
        n=(d["count"] if t in ("repeat_repair", "warranty_eligible") else d.get("invoices", d["count"])), amt=money(d["amount"]),
        inv=_plural(d.get("invoices", d["count"]), "invoice", "invoices"), rep=_plural(d["count"], "repair", "repairs"),
        look=_plural(d.get("invoices", d["count"]), "looks", "look"))
        for t, d in rows_by_type.items()}
    if provider is None or not rows_by_type:
        return out
    payload = [{"type": t, "label": TYPE_LABELS[t], "count": d["count"], "total_dollars": round(d["amount"], 2),
                "examples": d["examples"][:3], "template_paragraph": out[t]} for t, d in rows_by_type.items()]
    try:
        for it in provider.narrate(payload).items:
            text = " ".join(it.paragraph.split())
            if it.type in out and text and not BANNED.search(text) and HEDGE.search(text) and len(text) <= 900 and _figures_ok(text, rows_by_type[it.type]):
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
    # invoices still waiting for review are not "reviewed": leave them out of the count, the spend and the period
    invoices = db.execute(select(Invoice.invoice_date, Invoice.total).where(Invoice.review_status != ReviewStatus.needs_review)).all()
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
        t = detail.setdefault(f.type.value, {"count": 0, "amount": 0.0, "examples": [], "invoice_ids": set()})
        t["count"] += 1
        t["invoice_ids"].add(inv.id)
        t["invoices"] = len(t["invoice_ids"])
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
        "next_steps": {"text": (offer_text if offer_text is not None else offer_text_for(set(detail)))},
        "note": cfg["note"] + (cfg.get("note_reviewed", "") if rows and all(f.reviewed_by for f, _, _ in rows) else ""),
        "basis": flags_basis(db),
        "expires_at": expires_at.isoformat() if expires_at else None,
    }

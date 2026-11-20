"""Run the whole flag pipeline for one client: reference data -> rules -> AI explanations -> store."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import get_settings
from ..models import (
    DEFAULT_CLIENT_SETTINGS, Client, Flag, FlagExplanationCache, FlagRun, FlagStatus, FlagType, Invoice, LabourBenchmark, Severity, Vehicle,
    VmrsCode, WarrantyRule,
)
from ..services.normalize import normalize_shop_name
from . import reference
from .explain import clamp_score, evidence_hash, sanitize
from .rules import ALL_RULES
from .uncertain import uncertain_fields
from .types import Context, FlagDraft, InvoiceView, LineView, WarrantyView, severity

log = logging.getLogger("audit.flags")  # never log evidence or invoice contents
BATCH = 15


def _norm_unit(u: str | None) -> str | None:
    return "".join(c for c in u.upper() if c.isalnum()) if u else None


def load_views(db: Session) -> list[InvoiceView]:
    invs = db.scalars(select(Invoice).options(selectinload(Invoice.lines)).order_by(Invoice.created_at, Invoice.page_start)).all()
    vin_to_unit = {i.vin: _norm_unit(i.unit_number) for i in invs if i.vin and i.unit_number}  # one unit may print the VIN on only some invoices
    # The client's imported fleet list is authoritative: it names the unit for a VIN and gives each unit its class.
    fleet = db.scalars(select(Vehicle)).all()
    fleet_vin = {v.vin: _norm_unit(v.unit_number) for v in fleet if v.vin}
    fleet_class = {_norm_unit(v.unit_number): v.vehicle_class for v in fleet if v.vehicle_class}
    views = []
    for n, i in enumerate(invs):
        unit = _norm_unit(i.unit_number) or fleet_vin.get(i.vin) or (vin_to_unit.get(i.vin) or i.vin)
        views.append(InvoiceView(
            id=str(i.id), order=n, shop_key=normalize_shop_name(i.shop_name_raw) if i.shop_name_raw else None, shop_name=i.shop_name_raw,
            invoice_number=i.invoice_number, invoice_date=i.invoice_date, unit_key=unit, odometer=i.odometer, vehicle_class=fleet_class.get(unit),
            subtotal=i.subtotal, tax=i.tax, total=i.total,
            lines=[LineView(id=str(ln.id), invoice_id=str(i.id), line_no=ln.line_no, description=ln.description, part_number=ln.part_number,
                            qty=ln.qty, parts_price=ln.parts_price, labour_hours=ln.labour_hours, labour_rate=ln.labour_rate,
                            line_total=ln.line_total, vmrs_code=ln.vmrs_code) for ln in i.lines],
        ))
    return views


def run_rules(ctx: Context) -> list[FlagDraft]:
    drafts: list[FlagDraft] = []
    for rule in ALL_RULES:
        drafts.extend(rule.run(ctx))
    # A repair that is both a repeat and a warranty case is one finding: keep the warranty flag, don't double count dollars.
    warranty_lines = {d.line_id for d in drafts if d.type == "warranty_eligible"}
    return [d for d in drafts if not (d.type == "repeat_repair" and d.line_id in warranty_lines)]


def _explain(db: Session, drafts: list[FlagDraft], run: FlagRun, notes: list[str]) -> dict[str, tuple[str, float | None]]:
    """Return evidence_hash -> (reason, ai_score). Falls back to the rule's template on any failure."""
    s = get_settings()
    out: dict[str, tuple[str, float | None]] = {}
    need: list[FlagDraft] = []
    for d in drafts:
        h = evidence_hash(d)
        cached = db.scalar(select(FlagExplanationCache).where(FlagExplanationCache.evidence_hash == h))
        if cached:
            out[h] = (cached.reason, cached.ai_score)
        else:
            need.append(d)
    if not need:
        return out
    try:
        from ..services.extraction import get_provider

        provider = get_provider()
    except Exception as e:  # noqa: BLE001  (missing key, AI off, ZDR not confirmed...)
        notes.append("AI explanations unavailable, so standard wording was used.")
        log.warning("explanations skipped: %s", type(e).__name__)
        for d in need:
            out[evidence_hash(d)] = (d.template_reason, None)
        return out

    by_invoice: dict[str, list[FlagDraft]] = {}
    for d in need:
        by_invoice.setdefault(d.invoice_id, []).append(d)
    failures = 0
    for group in by_invoice.values():
        for i in range(0, len(group), BATCH):
            chunk = group[i:i + BATCH]
            payload = [{"index": n, "type": d.type, "estimated_dollars": float(d.impact), "evidence": d.evidence,
                        "template_reason": d.template_reason} for n, d in enumerate(chunk)]
            try:
                res = provider.explain(payload)
                run.input_tokens += res.usage.input_tokens
                run.output_tokens += res.usage.output_tokens
                by_idx = {it.index: it for it in res.items}
            except Exception as e:  # noqa: BLE001
                failures += 1
                log.warning("explain batch failed: %s", type(e).__name__)
                by_idx = {}
            for n, d in enumerate(chunk):
                h = evidence_hash(d)
                it = by_idx.get(n)
                reason = sanitize(it.reason if it else None, d.template_reason)
                score = clamp_score(it.ai_score) if it else None
                out[h] = (reason, score)
                if it and reason != d.template_reason:
                    db.add(FlagExplanationCache(evidence_hash=h, reason=reason, ai_score=score))
    if failures:
        notes.append(f"AI explanations failed for {failures} batch(es); standard wording was used for those flags.")
    cost = (run.input_tokens * s.price_input_per_mtok + run.output_tokens * s.price_output_per_mtok) / 1_000_000
    run.cost_usd = Decimal(str(round(cost, 5)))
    db.flush()
    return out


def run_flag_engine(db: Session, run: FlagRun | None = None, only_invoice: str | None = None) -> dict:
    """``db`` must be bound to a client. With ``only_invoice``, only that invoice's flags are added or removed
    (the rules still see all invoices, since repeats and duplicates depend on history). Returns a summary dict."""
    client = db.get(Client, db.info["client_id"])
    cfg = {**DEFAULT_CLIENT_SETTINGS, **(client.settings or {})}
    run = run or FlagRun(status="running")
    run.input_tokens, run.output_tokens = run.input_tokens or 0, run.output_tokens or 0
    notes: list[str] = []

    views = load_views(db)
    benchmarks, baselines = reference.recompute(db, views, cfg)
    warranty = {w.vmrs_code: WarrantyView(w.vmrs_code, w.component, w.months, w.miles, w.covers) for w in db.scalars(select(WarrantyRule))}
    entered = db.scalars(select(LabourBenchmark).where(LabourBenchmark.source != reference.CLIENT_SOURCE)).all()  # imported or typed in
    licensed = {b.vmrs_code for b in entered if b.vehicle_class is None}  # a value for all vehicles beats the client's own class medians
    class_bench = {k: m for k, (m, _) in reference.labour_class_medians(views, int(cfg["labour_min_samples"])).items() if k[0] not in licensed}
    class_bench.update({(b.vmrs_code, b.vehicle_class): b.benchmark_hours for b in entered if b.vehicle_class})  # a value for one class beats everything
    names = {c.code: c.component for c in db.scalars(select(VmrsCode))}
    ctx = Context(invoices=views, config=cfg, benchmarks=benchmarks, class_benchmarks=class_bench, baselines=baselines, warranty=warranty,
                  code_names=names, notes=notes)
    drafts = run_rules(ctx)
    from ..models import FieldConfidence

    needs_review = {(str(r.record_id), r.field) for r in db.scalars(select(FieldConfidence).where(FieldConfidence.needs_review.is_(True)))}
    lines_of = {v.id: [ln.id for ln in v.lines] for v in views}
    for d in drafts:
        u = uncertain_fields(d, needs_review, lines_of)
        if u:
            d.evidence["extraction_uncertain"] = u
    if only_invoice:
        drafts = [d for d in drafts if d.invoice_id == only_invoice]

    explained = _explain(db, drafts, run, notes)

    q = select(Flag).where(Flag.invoice_id == uuid.UUID(only_invoice)) if only_invoice else select(Flag)
    existing = {f.dedupe_key: f for f in db.scalars(q)}
    keep: set[str] = set()
    added = removed = 0
    for d in drafts:
        h = evidence_hash(d)
        reason, score = explained.get(h, (d.template_reason, None))
        sev = Severity(severity(d.impact, cfg))
        keep.add(d.dedupe_key)
        f = existing.get(d.dedupe_key)
        if f is None:
            added += 1
            db.add(Flag(
                invoice_id=uuid.UUID(d.invoice_id), line_id=uuid.UUID(d.line_id) if d.line_id else None,
                related_invoice_id=uuid.UUID(d.related_invoice_id) if d.related_invoice_id else None,
                type=FlagType(d.type), severity=sev, estimated_dollar_impact=d.impact, plain_english_reason=reason,
                details=d.evidence, ai_score=score, dedupe_key=d.dedupe_key, evidence_hash=h, status=FlagStatus.open,
            ))
        elif f.status == FlagStatus.open:  # never overwrite an analyst's decision
            f.severity, f.estimated_dollar_impact, f.plain_english_reason = sev, d.impact, reason
            f.details, f.ai_score, f.evidence_hash = d.evidence, score, h
    for key, f in existing.items():
        if key not in keep and f.status == FlagStatus.open:
            removed += 1
            db.delete(f)
    db.flush()

    by_type: dict[str, int] = {}
    for d in drafts:
        by_type[d.type] = by_type.get(d.type, 0) + 1
    summary = {"flags": len(drafts), "by_type": by_type, "notes": notes, "invoices": len(views),
               "benchmarked_job_types": len(benchmarks), "priced_parts": len(baselines), "added": added, "removed": removed}
    run.summary = summary
    return summary

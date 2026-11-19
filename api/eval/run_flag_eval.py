"""Measure the flag rules against the planted problems in the synthetic answer key.

Invoices are loaded straight from the answer key (i.e. perfectly extracted) so this isolates the RULES from extraction
errors. Use --vmrs lookup to classify lines with the real keyword lookup instead of the key's codes.

  python -m eval.run_flag_eval --synthetic /synthetic/out [--vmrs key|lookup] [--explain off|provider]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import uuid
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

os.environ["QUEUE_INLINE"] = "true"

from sqlalchemy import delete, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import client_session, system_session  # noqa: E402
from app.models import DEFAULT_CLIENT_SETTINGS, Client, Flag, FlagRun, Invoice, InvoiceLine  # noqa: E402
from app.seed import seed_vmrs  # noqa: E402
from app.services.defaults import ensure_default_warranty_rules  # noqa: E402
from app.services.normalize import normalize_description  # noqa: E402

PLANT_TO_FLAG = {"inflated_hours": "labour_over_benchmark", "repeat_repair": "repeat_repair", "warranty_case": "warranty_eligible",
                 "parts_price_outlier": "parts_price_outlier", "duplicate_invoice": "duplicate", "math_error": "math_error"}
D = lambda x: Decimal(str(x))


def planted_dollars(kind: str, p: dict, inv: dict) -> Decimal:
    note = p["note"] or ""
    line = next((ln for ln in inv["lines"] if ln["line_no"] == p["line_no"]), None) if p["line_no"] else None
    nums = [D(x) for x in re.findall(r"-?\d+(?:\.\d+)?", note)]
    if kind == "math_error":
        m = re.search(r"printed ([\d.]+), correct ([\d.]+)", note)
        return abs(D(m.group(1)) - D(m.group(2))) if m else Decimal(0)
    if kind == "inflated_hours":
        m = re.search(r"hours ([\d.]+) vs typical ([\d.]+)", note)
        return (D(m.group(1)) - D(m.group(2))) * D(line["labour_rate"]) if m and line else Decimal(0)
    if kind == "parts_price_outlier":
        m = re.search(r"unit price ([\d.]+) vs typical ([\d.]+)", note)
        return (D(m.group(1)) - D(m.group(2))) * D(line.get("qty") or 1) if m and line else Decimal(0)
    if kind in ("repeat_repair", "warranty_case"):
        return D(line["line_total"]) if line else Decimal(0)
    if kind == "duplicate_invoice":
        return D(inv["header"]["total"])
    return Decimal(0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", required=True)
    ap.add_argument("--vmrs", choices=["key", "lookup"], default="key")
    ap.add_argument("--warranty", choices=["defaults", "aligned"], default="defaults",
                    help="aligned = only the components the synthetic key plants warranty cases on (alternator, starter, water pump, turbo)")
    ap.add_argument("--explain", choices=["off", "provider"], default="off")
    ap.add_argument("--out", default="/app/eval_out")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    if a.explain == "off":
        os.environ["AI_PROVIDER"] = "fake"
        get_settings.cache_clear()

    key = json.loads((Path(a.synthetic) / "answer_key.json").read_text())
    with system_session() as db:
        seed_vmrs(db)
        c = Client(name=f"FlagEval {time.strftime('%H:%M:%S')}", slug=f"fe-{uuid.uuid4().hex[:8]}", inbound_email_token=uuid.uuid4().hex[:12],
                   settings=dict(DEFAULT_CLIENT_SETTINGS))
        db.add(c)
        db.flush()
        ensure_default_warranty_rules(db, c.id)
        if a.warranty == "aligned":
            from app.models import WarrantyRule

            db.execute(delete(WarrantyRule).where(WarrantyRule.client_id == c.id, WarrantyRule.vmrs_code.notin_(["031-001-001", "032-001-001", "042-001-002", "041-001-003"])))
        db.commit()
        cid = c.id

    from app.services.vmrs import load_codes, lookup

    by_key: dict[str, dict] = {}
    for f in key["files"]:
        if f.get("exact_duplicate_of"):
            continue  # byte-identical copies are dropped at upload, never reach the rules
        for inv in f["invoices"]:
            by_key.setdefault(inv["key_id"], inv)

    inv_key: dict[str, str] = {}            # db invoice id -> key_id
    line_key: dict[str, tuple[str, int]] = {}
    with client_session(cid) as db:
        codes = load_codes(db) if a.vmrs == "lookup" else []
        for kid, inv in by_key.items():
            h = inv["header"]
            row = Invoice(shop_name_raw=h["shop_name"], shop_address=h.get("shop_address"), invoice_number=h["invoice_number"],
                          invoice_date=h["invoice_date"] and __import__("datetime").date.fromisoformat(h["invoice_date"]), unit_number=h["unit_number"],
                          vin=h["vin"], odometer=h["odometer"], subtotal=h["subtotal"], tax=h["tax"], total=h["total"])
            db.add(row)
            db.flush()
            inv_key[str(row.id)] = kid
            for ln in inv["lines"]:
                code = ln["vmrs_code"]
                if a.vmrs == "lookup":
                    hit = lookup(normalize_description(ln["description"]), codes)
                    code = hit.code if hit else None
                r = InvoiceLine(invoice_id=row.id, line_no=ln["line_no"], description=ln["description"], part_number=ln["part_number"], qty=ln["qty"],
                                parts_price=ln["parts_price"], labour_hours=ln["labour_hours"], labour_rate=ln["labour_rate"],
                                line_total=ln["line_total"], vmrs_code=code)
                db.add(r)
                db.flush()
                line_key[str(r.id)] = (kid, ln["line_no"])
        db.commit()

    from app.flags.engine import run_flag_engine

    t0 = time.monotonic()
    with client_session(cid) as db:
        run = FlagRun(status="running")
        db.add(run)
        db.flush()
        summary = run_flag_engine(db, run)
        db.commit()
        secs = time.monotonic() - t0
        flags = [(str(f.invoice_id), str(f.line_id) if f.line_id else None, f.type.value, float(f.estimated_dollar_impact), f.plain_english_reason, f.details)
                 for f in db.scalars(select(Flag))]
        run_cost, run_in, run_out = float(run.cost_usd), run.input_tokens, run.output_tokens

    # ---- truth
    planted: dict[str, list[dict]] = defaultdict(list)
    for kid, inv in by_key.items():
        for p in inv["planted"]:
            t = PLANT_TO_FLAG[p["type"]]
            entry = {"key_id": kid, "line_no": p["line_no"], "dollars": planted_dollars(p["type"], p, inv), "matched": False}
            if p["type"] == "duplicate_invoice":
                m = re.search(r"INV-\d+", p["note"] or "")
                entry["pair"] = {kid, m.group(0)} if m else {kid}
            planted[t].append(entry)

    def match(flag_type, inv_id, line_id):
        kid = inv_key[inv_id]
        for e in planted[flag_type]:
            if flag_type == "duplicate":
                if kid in e["pair"] and line_id is None:
                    return e
            elif flag_type == "math_error":
                if e["key_id"] == kid:
                    return e
            elif line_id and line_key[line_id] == (e["key_id"], e["line_no"]):
                return e
        return None

    per = {t: {"planted": len(planted[t]), "flags": 0, "tp": 0, "tp_dollars": 0.0, "fp_dollars": 0.0, "fp_examples": []} for t in PLANT_TO_FLAG.values()}
    for inv_id, line_id, t, impact, reason, ev in flags:
        r = per[t]
        r["flags"] += 1
        e = match(t, inv_id, line_id)
        if e:
            r["tp"] += 1
            r["tp_dollars"] += impact
            e["matched"] = True
        else:
            r["fp_dollars"] += impact
            if len(r["fp_examples"]) < 6:
                r["fp_examples"].append({"invoice": inv_key[inv_id], "line": line_key[line_id][1] if line_id else None, "impact": impact, "evidence": ev})
    for t, r in per.items():
        found = len({id(e) for e in planted[t] if e["matched"]})
        r["found"] = found
        r["recall_pct"] = round(100 * found / r["planted"], 1) if r["planted"] else None
        r["precision_pct"] = round(100 * r["tp"] / r["flags"], 1) if r["flags"] else None
        r["planted_dollars"] = round(float(sum(e["dollars"] for e in planted[t])), 2)
        r["tp_dollars"], r["fp_dollars"] = round(r["tp_dollars"], 2), round(r["fp_dollars"], 2)
    for t, r in per.items():
        r["missed"] = [{"key_id": e["key_id"], "line": e["line_no"], "dollars": float(e["dollars"])} for e in planted[t] if not e["matched"]]
    tot_flags = sum(r["flags"] for r in per.values())
    tot_tp = sum(r["tp"] for r in per.values())
    tot_pl = sum(r["planted"] for r in per.values())
    tot_found = sum(r["found"] for r in per.values())
    n_inv = len(by_key)
    report = {
        "vmrs_source": a.vmrs, "warranty_rules": a.warranty, "invoices": n_inv, "flags": tot_flags, "true_positive_flags": tot_tp,
        "overall_precision_pct": round(100 * tot_tp / tot_flags, 1) if tot_flags else None,
        "overall_recall_pct": round(100 * tot_found / tot_pl, 1) if tot_pl else None,
        "planted_total": tot_pl, "planted_found": tot_found,
        "flagged_dollars_total": round(sum(f[3] for f in flags), 2),
        "flagged_dollars_on_planted": round(sum(r["tp_dollars"] for r in per.values()), 2),
        "planted_dollars_total": round(sum(r["planted_dollars"] for r in per.values()), 2),
        "per_rule": per, "run_summary": summary, "engine_seconds": round(secs, 2),
        "explanation_cost_usd": run_cost, "explanation_tokens": [run_in, run_out],
        "explanation_cost_per_invoice_usd": round(run_cost / max(n_inv, 1), 5),
    }
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"flag_eval_{a.vmrs}_{a.warranty}.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\ninvoices={n_inv} flags={tot_flags} precision={report['overall_precision_pct']}% recall={report['overall_recall_pct']}%")
    for t, r in per.items():
        print(f"{t:24s} planted={r['planted']:3d} found={r['found']:3d} flags={r['flags']:3d} tp={r['tp']:3d} "
              f"recall={r['recall_pct']}% precision={r['precision_pct']}%  $planted={r['planted_dollars']} $tp={r['tp_dollars']} $fp={r['fp_dollars']}")
    if not a.keep:
        with system_session() as db:
            db.execute(delete(Client).where(Client.id == cid))
            db.commit()


if __name__ == "__main__":
    main()

"""Measure the flag rules against synthetic_dataset_v1 (the 992-invoice set with truth/ and answer_key/ folders).

Invoices are loaded from truth/invoices.json exactly AS PRINTED (so planted maths errors are present), i.e. perfect
extraction. This isolates the RULES from reading errors. Run against the *test* database, not the dev one:

  DATABASE_URL=postgresql+psycopg://audit:audit@127.0.0.1:5432/audit_test \
  python -m eval.run_flag_eval_v1 --dataset /path/to/synthetic_dataset_v1 [--config defaults|aligned] [--bench median|published]

--config defaults : the app's shipped client settings and default warranty rules (what a new client gets).
--config aligned  : thresholds from the dataset's master/thresholds_and_rules.json, warranty rules from warranty_rules.csv,
                    routine jobs (PM / inspection / service) excluded from the repeat rule.
--bench median    : labour benchmark = the client's own median per VMRS code (the app's normal behaviour).
--bench published : import master/jobs_vmrs.csv as licensed benchmarks (one value per VMRS code; see note in output).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import time
import uuid
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

os.environ["QUEUE_INLINE"] = "true"
os.environ["AI_PROVIDER"] = "fake"  # template wording only; no AI call

from sqlalchemy import delete, select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, client_session, engine, system_session  # noqa: E402
from app.models import (  # noqa: E402
    DEFAULT_CLIENT_SETTINGS, Client, Flag, FlagRun, Invoice, InvoiceLine, LabourBenchmark, WarrantyRule,
)
from app.seed import seed_vmrs  # noqa: E402
from app.services.defaults import ensure_default_warranty_rules  # noqa: E402

D = lambda x: None if x is None else Decimal(str(x))  # noqa: E731

TRUTH_TO_ENGINE = {"labour_above_benchmark": "labour_over_benchmark", "repeat_repair": "repeat_repair", "warranty_eligible": "warranty_eligible",
                   "parts_price_outlier": "parts_price_outlier", "duplicate_invoice": "duplicate", "duplicate_line_item": "duplicate",
                   "maths_error": "math_error"}
HN_TO_ENGINE = {"parts_price_below_threshold": {"parts_price_outlier"}, "labour_below_threshold": {"labour_over_benchmark"},
                "labour_with_justification_note": {"labour_over_benchmark"}, "lookalike_not_duplicate": {"duplicate"},
                "same_job_different_position": {"repeat_repair", "warranty_eligible"}, "warranty_just_expired": {"warranty_eligible"}}
RATIO = {"repeat_repair", "warranty_eligible"}  # the engine reports one finding per repair; either type is accepted for either truth row


def read_csv(p: Path) -> list[dict]:
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--config", choices=["defaults", "aligned"], default="aligned")
    ap.add_argument("--bench", choices=["median", "published"], default="median")
    ap.add_argument("--out", default="eval_out")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    ds = Path(a.dataset)
    if not engine.url.database.endswith("_test"):
        raise SystemExit(f"refusing to run against database {engine.url.database!r}; point DATABASE_URL at the *_test database")

    truth = json.loads((ds / "truth/invoices.json").read_text())
    rules = json.loads((ds / "master/thresholds_and_rules.json").read_text())
    jobs = read_csv(ds / "master/jobs_vmrs.csv")
    wrules = read_csv(ds / "master/warranty_rules.csv")
    flags_key = read_csv(ds / "answer_key/flags.csv")
    hn_key = read_csv(ds / "answer_key/hard_negatives.csv")

    Base.metadata.create_all(engine)
    cfg = dict(DEFAULT_CLIENT_SETTINGS)
    routine_codes = sorted({j["vmrs_code"] for j in jobs if j["job_kind"] != "repair"})
    if a.config == "aligned":
        cfg.update(labour_over_benchmark_pct=int(rules["labour_over_benchmark_pct"] * 100), repeat_repair_days=rules["repeat_repair_days"],
                   repeat_repair_miles=rules["repeat_repair_miles"], parts_outlier_pct=int((rules["parts_price_outlier_ratio"] - 1) * 100),
                   parts_min_samples=rules["parts_price_min_observations"], repeat_exclude_codes=routine_codes)

    with system_session() as db:
        seed_vmrs(db)
        c = Client(name=f"V1Eval {time.strftime('%H:%M:%S')}", slug=f"v1-{uuid.uuid4().hex[:8]}", inbound_email_token=uuid.uuid4().hex[:12], settings=cfg)
        db.add(c)
        db.flush()
        if a.config == "defaults":
            ensure_default_warranty_rules(db, c.id)
        else:
            comp_code = {}
            for t in truth:
                for ln in t["line_items"]:
                    if ln["component"] and ln["vmrs_code"]:
                        comp_code.setdefault(ln["component"], ln["vmrs_code"])
            for w in wrules:
                code = comp_code.get(w["component"])
                if code:  # components never billed in the set cannot be matched anyway
                    miles = None if w["warranty_miles"] == "unlimited" else int(w["warranty_miles"])
                    db.add(WarrantyRule(client_id=c.id, vmrs_code=code, component=w["description"], months=int(w["warranty_months"]), miles=miles))
        if a.bench == "published":
            by: dict[str, list[float]] = defaultdict(list)
            for j in jobs:
                by[j["vmrs_code"]].append(float(j["benchmark_hours"]))
            for code, v in by.items():
                db.add(LabourBenchmark(client_id=c.id, vmrs_code=code, benchmark_hours=D(round(statistics.median(v), 2)), source="licensed:dataset_v1"))
        db.commit()
        cid = c.id

    inv_key: dict[str, str] = {}
    line_key: dict[str, tuple[str, int]] = {}
    with client_session(cid) as db:
        for t in truth:
            h = t["header"]
            tp = t["totals_printed"]
            row = Invoice(shop_name_raw=h["shop_name"], shop_address=h["shop_address"], invoice_number=h["invoice_number"],
                          invoice_date=date.fromisoformat(h["invoice_date"]), unit_number=h["unit_number"], vin=h["vin"], odometer=h["odometer"],
                          subtotal=D(round(tp["parts_subtotal"] + tp["labor_subtotal"], 2)), tax=D(tp["tax"]), total=D(tp["total"]))
            db.add(row)
            db.flush()
            inv_key[str(row.id)] = t["invoice_id"]
            for ln in t["line_items"]:
                r = InvoiceLine(invoice_id=row.id, line_no=ln["line_no"], description=ln["description"], part_number=ln["part_number"],
                                qty=D(ln["quantity"]), parts_price=D(ln["unit_price"]), labour_hours=D(ln["labor_hours"]), labour_rate=D(ln["labor_rate"]),
                                line_total=D(ln["line_total_printed"]), vmrs_code=ln["vmrs_code"])
                db.add(r)
                db.flush()
                line_key[str(r.id)] = (t["invoice_id"], ln["line_no"])
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
        found = [dict(inv=inv_key[str(f.invoice_id)], rel=inv_key.get(str(f.related_invoice_id)), line=line_key[str(f.line_id)][1] if f.line_id else None,
                      type=f.type.value, dollars=float(f.estimated_dollar_impact), ev=f.details) for f in db.scalars(select(Flag))]

    # ---------------- scoring ----------------
    def lines_of(row) -> set[int]:
        return {int(x) for x in row["line_no"].replace(",", ";").split(";") if x.strip()}

    truth_rows = []
    for r in flags_key:
        truth_rows.append(dict(id=r["flag_id"], inv=r["invoice_id"], rel=r["related_invoice_id"] or None, etype=TRUTH_TO_ENGINE[r["flag_type"]], ttype=r["flag_type"],
                               lines=lines_of(r) if r["line_no"] else set(), dollars=float(r["expected_dollar_impact"]),
                               counts=r["counts_toward_total"] == "True", also=set((r["also_acceptable"] or "").split(";")) - {""}, matched=False))

    def matches(f, t) -> bool:
        if t["ttype"] == "duplicate_invoice":
            if f["type"] != "duplicate" or f["line"] is not None:
                return False
            return {f["inv"], f["rel"]} & {t["inv"], t["rel"]} != set()
        if t["ttype"] == "duplicate_line_item":
            return f["type"] == "duplicate" and f["inv"] == t["inv"] and f["line"] in t["lines"] | {None}
        if t["ttype"] == "maths_error":
            return f["type"] == "math_error" and f["inv"] == t["inv"]
        if t["etype"] in RATIO:
            return f["type"] in RATIO and f["inv"] == t["inv"]
        return f["type"] == t["etype"] and f["inv"] == t["inv"] and f["line"] in t["lines"]

    tp = Counter()
    tp_dollars = defaultdict(float)
    fp_list = []
    dup_pairs = {frozenset({t["inv"], t["rel"]}) for t in truth_rows if t["ttype"] == "duplicate_invoice"}
    dup_invs = {i for p in dup_pairs for i in p}
    for f in found:
        hit = next((t for t in truth_rows if matches(f, t)), None)
        if hit is None and f["type"] in RATIO and f["inv"] in dup_invs:
            hit = "acceptable"  # a repeat/warranty flag on either invoice of a planted duplicate pair is not penalised
        if hit is None and f["type"] == "duplicate" and f["rel"] is not None and f["line"] is None and frozenset({f["inv"], f["rel"]}) in dup_pairs:
            hit = "acceptable"
        if hit is None:
            fp_list.append(f)
            continue
        tp[f["type"]] += 1
        if hit != "acceptable":
            hit["matched"] = True
            if hit["etype"] in RATIO:  # one repair can carry both a repeat and a warranty row in the key; the engine reports it once
                for t in truth_rows:
                    if t["etype"] in RATIO and t["inv"] == hit["inv"]:
                        t["matched"] = True
            tp_dollars[f["type"]] += f["dollars"]

    hn_hits = []
    for h in hn_key:
        want = HN_TO_ENGINE[h["flag_type"]]
        hl = lines_of(h) if h["line_no"] else set()
        for f in fp_list:
            if f["type"] in want and f["inv"] == h["invoice_id"] and (not hl or f["line"] is None or f["line"] in hl):
                hn_hits.append((h["flag_type"], h["invoice_id"], f["type"]))
                break
    hn_by = Counter(x[0] for x in hn_hits)
    hn_total = Counter(h["flag_type"] for h in hn_key)

    per = {}
    for et in sorted(set(TRUTH_TO_ENGINE.values())):
        rows = [t for t in truth_rows if t["etype"] == et]
        fl = [f for f in found if f["type"] == et]
        fps = [f for f in fp_list if f["type"] == et]
        per[et] = dict(planted=len(rows), found=sum(t["matched"] for t in rows), flags=len(fl), false_positives=len(fps),
                       recall_pct=round(100 * sum(t["matched"] for t in rows) / len(rows), 1) if rows else None,
                       precision_pct=round(100 * (len(fl) - len(fps)) / len(fl), 1) if fl else None)
    n_found, n_planted = sum(t["matched"] for t in truth_rows), len(truth_rows)
    n_fp, n_flags = len(fp_list), len(found)
    counted = [t for t in truth_rows if t["counts"]]
    report = {
        "config": a.config, "bench": a.bench, "invoices": len(truth), "engine_flags": n_flags, "false_positive_flags": n_fp,
        "overall_precision_pct": round(100 * (n_flags - n_fp) / n_flags, 1) if n_flags else None,
        "overall_recall_pct": round(100 * n_found / n_planted, 1),
        "planted_found": f"{n_found}/{n_planted}",
        "expected_recoverable_usd": round(sum(t["dollars"] for t in counted), 2),
        "recovered_usd_on_true_flags": round(sum(tp_dollars.values()), 2),
        "false_positive_usd": round(sum(f["dollars"] for f in fp_list), 2),
        "hard_negatives_tripped": {k: f"{hn_by.get(k, 0)}/{v}" for k, v in hn_total.items()},
        "per_rule": per, "run_summary": summary, "engine_seconds": round(secs, 2),
        "false_positive_examples": {et: [dict(inv=f["inv"], line=f["line"], dollars=f["dollars"], ev=f["ev"]) for f in fp_list if f["type"] == et][:4] for et in per},
        "missed": [dict(id=t["id"], inv=t["inv"], type=t["ttype"], lines=sorted(t["lines"]), dollars=t["dollars"]) for t in truth_rows if not t["matched"]],
    }
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"flag_eval_v1_{a.config}_{a.bench}.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\nconfig={a.config} bench={a.bench} invoices={len(truth)} flags={n_flags} FP={n_fp} precision={report['overall_precision_pct']}% recall={report['overall_recall_pct']}% ({n_found}/{n_planted})")
    print(f"$ expected {report['expected_recoverable_usd']}  $ recovered on true flags {report['recovered_usd_on_true_flags']}  $ on false positives {report['false_positive_usd']}")
    for t, r in per.items():
        print(f"  {t:24s} planted={r['planted']:3d} found={r['found']:3d} flags={r['flags']:3d} FP={r['false_positives']:3d} recall={r['recall_pct']}% precision={r['precision_pct']}%")
    print("  hard negatives tripped:", report["hard_negatives_tripped"])
    if not a.keep:
        with system_session() as db:
            db.execute(delete(Client).where(Client.id == cid))
            db.commit()


if __name__ == "__main__":
    main()

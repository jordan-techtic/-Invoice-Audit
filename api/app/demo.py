"""End-to-end demo on the synthetic invoices.   python -m app.demo [--limit N]

1 create a demo client  2 load + extract every synthetic file  3 run checks  4 'analyst' review: accept flags that match the
answer key, dismiss the rest  5 create the report + PDF  6 print and save the metrics.

Extraction uses the configured provider (AI_PROVIDER=openai with a key = real). With no key it uses the OFFLINE ORACLE,
which replays the answer key with injected read errors: everything after extraction is real, extraction accuracy is not.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
import uuid
from collections import defaultdict
from pathlib import Path

os.environ["QUEUE_INLINE"] = "true"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from app.config import get_settings  # noqa: E402

OFFLINE = os.environ.get("AI_PROVIDER", "openai") in ("fake", "oracle") or not (os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
if OFFLINE:
    os.environ["AI_PROVIDER"] = "oracle"
    get_settings.cache_clear()

from app.db import client_session, system_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (DEFAULT_CLIENT_SETTINGS, Client, ExtractionRun, Flag, FlagRun, Invoice, InvoiceLine, Upload, UploadSource, UploadStatus)  # noqa: E402
from app.seed import main as seed_main  # noqa: E402
from app.services.defaults import ensure_default_warranty_rules  # noqa: E402
from app.services.ingest import ingest_file  # noqa: E402
from eval.oracle import pages_for_file  # noqa: E402
from eval.run_eval import HEADER, LINE, Tally, pct, same  # noqa: E402
from eval.run_flag_eval import PLANT_TO_FLAG, planted_dollars  # noqa: E402

DEMO_NAME = "Demo Fleet (synthetic)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", default="/synthetic/out")
    ap.add_argument("--out", default="/demo")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    t_start = time.monotonic()
    banner = ("OFFLINE ORACLE: extraction replays the answer key with injected errors (no AI key set). Accuracy below is NOT a model result."
              if OFFLINE else f"REAL AI: {get_settings().ai_provider} / {get_settings().openai_model if get_settings().ai_provider == 'openai' else get_settings().claude_model}")
    print(f"\n== Repair invoice audit demo ==\n{banner}\n")

    seed_main()
    from app import storage

    storage.ensure_bucket()
    key = json.loads((Path(a.synthetic) / "answer_key.json").read_text())
    files = key["files"][: a.limit] if a.limit else key["files"]

    with system_session() as db:  # clean state for the demo client only
        for c in db.scalars(select(Client).where(Client.name == DEMO_NAME)).all():
            storage.delete_prefix(storage.client_prefix(c.id))
            db.delete(c)
        db.commit()
        c = Client(name=DEMO_NAME, slug=f"demo-{uuid.uuid4().hex[:6]}", inbound_email_token=uuid.uuid4().hex[:12], settings=dict(DEFAULT_CLIENT_SETTINGS))
        db.add(c)
        db.flush()
        ensure_default_warranty_rules(db, c.id)
        db.commit()
        cid = c.id
    print(f"[1/6] Created client '{DEMO_NAME}'")

    from app.services.extraction.fake import FakeProvider

    rng = random.Random(1)
    inv_key: dict[str, tuple[str, dict]] = {}       # db invoice id -> (key_id, key invoice)
    line_key: dict[str, tuple[str, int]] = {}
    header_t, line_t, overall = defaultdict(Tally), defaultdict(Tally), Tally()
    kind_t: dict[str, Tally] = defaultdict(Tally)
    vmrs = [0, 0]
    n_dup_expected = n_dup_found = n_failed = n_invoices_expected = retries = 0
    split_ok = split_n = 0
    t_extract = 0.0
    for i, entry in enumerate(files, start=1):
        data = (Path(a.synthetic) / entry["file"]).read_bytes()
        if OFFLINE:
            it = iter(pages_for_file(entry, rng))
            FakeProvider.responder = lambda _img, it=it: next(it)
        t0 = time.monotonic()
        with client_session(cid) as db:
            db.info["user_id"] = None
            up = ingest_file(db, filename=Path(entry["file"]).name, data=data, source=UploadSource.web)
            # Rate limits and timeouts are temporary: do what an operator does and press Retry, up to 3 times.
            from app.services.pipeline import process_upload

            for attempt in range(3):
                if up.status != UploadStatus.failed:
                    break
                time.sleep(45 * (attempt + 1))
                retries += 1
                if OFFLINE:
                    it = iter(pages_for_file(entry, rng))
                    FakeProvider.responder = lambda _img, it=it: next(it)
                process_upload(str(cid), str(up.id))
                db.refresh(up)
            t_extract += time.monotonic() - t0
            if entry.get("exact_duplicate_of"):
                n_dup_expected += 1
                n_dup_found += up.status == UploadStatus.duplicate
                continue
            if up.status == UploadStatus.failed:
                n_failed += 1
                continue
            invs = db.scalars(select(Invoice).where(Invoice.source_upload_id == up.id).order_by(Invoice.page_start)).all()
            want = sorted(entry["invoices"], key=lambda x: x["page_start"])
            n_invoices_expected += len(want)
            split_n += 1
            split_ok += [(x.page_start, x.page_end) for x in invs] == [(w["page_start"], w["page_end"]) for w in want]
            for pos, w in enumerate(want):
                inv = invs[pos] if pos < len(invs) else None
                if inv is None:
                    continue
                inv_key[str(inv.id)] = (w["key_id"], w)
                got_lines = inv.lines
                for ln in got_lines:
                    line_key[str(ln.id)] = (w["key_id"], ln.line_no)
                for f in HEADER:
                    ok = same(f, inv.shop_name_raw if f == "shop_name" else getattr(inv, f), w["header"].get(f))
                    for t in (header_t[f], overall, kind_t[entry["kind"]]):
                        t.add(ok, False)
                for n, wl in enumerate(w["lines"]):
                    gl = got_lines[n] if n < len(got_lines) else None
                    for f in LINE:
                        ok = same(f, None if gl is None else getattr(gl, f), wl.get(f))
                        for t in (line_t[f], overall, kind_t[entry["kind"]]):
                            t.add(ok, False)
                    vmrs[1] += 1
                    vmrs[0] += bool(gl is not None and gl.vmrs_code == wl["vmrs_code"])
        if i % 40 == 0:
            print(f"      read {i}/{len(files)} files...")
    with client_session(cid) as db:
        n_invoices = db.scalar(select(func.count()).select_from(Invoice))
        runs = db.scalars(select(ExtractionRun)).all()
    print(f"[2/6] Read {len(files)} files -> {n_invoices} invoices ({t_extract:.0f}s); duplicates skipped {n_dup_found}/{n_dup_expected}; failed files {n_failed} (after {retries} automatic retries)")

    # ---- checks via the real API
    c = TestClient(app)
    assert c.post("/auth/login", json={"email": "admin@audit-demo.com", "password": "admin-password-123"}).status_code == 200
    t0 = time.monotonic()
    job = c.post(f"/clients/{cid}/run-flags").json()
    run = c.get(f"/clients/{cid}/flag-runs/{job['job_id']}").json()
    t_flags = time.monotonic() - t0
    flags = c.get(f"/clients/{cid}/flags").json()["flags"]
    print(f"[3/6] Ran checks: {len(flags)} flags in {t_flags:.1f}s ({run['status']})  {run['summary'].get('notes') or ''}")

    # ---- planted truth + analyst review simulation
    planted: dict[str, list[dict]] = defaultdict(list)
    by_key = {k: v for k, v in {kid: w for kid, w in inv_key.values()}.items()}
    for kid, w in by_key.items():
        for p in w["planted"]:
            e = {"key_id": kid, "line_no": p["line_no"], "dollars": planted_dollars(p["type"], p, w), "matched": False}
            if p["type"] == "duplicate_invoice":
                m = re.search(r"INV-\d+", p["note"] or "")
                e["pair"] = {kid, m.group(0)} if m else {kid}
            planted[PLANT_TO_FLAG[p["type"]]].append(e)
    flag_rows = {}
    with client_session(cid) as db:
        for f in db.scalars(select(Flag)):
            flag_rows[str(f.id)] = (str(f.invoice_id), str(f.line_id) if f.line_id else None, f.type.value)

    def match(t, inv_id, line_id):
        kid = inv_key[inv_id][0]
        for e in planted[t]:
            if t == "duplicate":
                if kid in e["pair"] and line_id is None:
                    return e
            elif t == "math_error":
                if e["key_id"] == kid:
                    return e
            elif line_id and line_key.get(line_id) == (e["key_id"], e["line_no"]):
                return e
        return None

    per = {t: {"planted": len(planted[t]), "flags": 0, "tp": 0} for t in PLANT_TO_FLAG.values()}
    accepted = dismissed = corrected = 0
    for fl in flags:
        inv_id, line_id, t = flag_rows[fl["id"]]
        per[t]["flags"] += 1
        e = match(t, inv_id, line_id) if inv_id in inv_key else None
        if e:
            per[t]["tp"] += 1
            e["matched"] = True
            # The simulated analyst looks at the image: a flag whose amount is far from the planted amount is a misread number
            # (e.g. a corrupted digit making a $25,000 'maths error'), so it is edited to the true amount, as a person would.
            truth = float(e["dollars"])
            if truth and abs(fl["impact"] - truth) > max(25.0, 0.25 * truth):
                c.post(f"/clients/{cid}/flags/{fl['id']}/edit", json={"amount": round(truth, 2), "note": "amount corrected from the image"})
                corrected += 1
            else:
                c.post(f"/clients/{cid}/flags/{fl['id']}/accept", json={"note": "matches answer key"})
            accepted += 1
        else:
            reason = "wrong_extraction" if fl.get("check_extraction_first") else "not_real_issue"
            c.post(f"/clients/{cid}/flags/{fl['id']}/dismiss", json={"reason": reason, "note": "no matching planted problem"})
            dismissed += 1
            per[t]["fp_uncertain"] = per[t].get("fp_uncertain", 0) + (1 if fl.get("check_extraction_first") else 0)
    for t, r in per.items():
        r["found"] = len({id(e) for e in planted[t] if e["matched"]})
        r["recall_pct"] = pct(r["found"], r["planted"])
        r["precision_pct"] = pct(r["tp"], r["flags"])
    tot_flags, tot_tp = sum(r["flags"] for r in per.values()), sum(r["tp"] for r in per.values())
    fp_total = tot_flags - tot_tp
    fp_uncertain = sum(r.get("fp_uncertain", 0) for r in per.values())
    confident = [fl for fl in flags if not fl.get("check_extraction_first")]
    conf_tp = sum(1 for fl in confident if (lambda t=flag_rows[fl["id"]]: t[0] in inv_key and match(t[2], t[0], t[1]) is not None)())
    tot_pl, tot_found = sum(r["planted"] for r in per.values()), sum(r["found"] for r in per.values())
    print(f"[4/6] Review: accepted {accepted} flags that match the answer key ({corrected} with the amount corrected from the image), dismissed {dismissed}")

    # ---- report
    c.post(f"/clients/{cid}/audit-complete")
    r = c.post(f"/clients/{cid}/reports", json={})
    assert r.status_code == 201, r.text
    rep = r.json()
    pdf = c.get(f"/clients/{cid}/reports/{rep['id']}/pdf")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "sample_report.pdf").write_bytes(pdf.content)
    snap = c.get(f"/clients/{cid}/reports/{rep['id']}").json()
    print(f"[5/6] Report v{rep['version']}: {snap['summary']['headline']}  -> {out}/sample_report.pdf")
    print(f"      Dashboard link: {rep['share_url']}")

    # ---- metrics
    cost = sum(float(x.cost_usd) for x in runs)
    wall = time.monotonic() - t_start
    metrics = {
        "mode": "offline_oracle" if OFFLINE else "real_ai", "files": len(files), "invoices": n_invoices, "invoices_expected": n_invoices_expected,
        "exact_duplicates_skipped": f"{n_dup_found}/{n_dup_expected}", "failed_files": n_failed, "retries": retries, "split_correct_pct": pct(split_ok, split_n),
        "field_accuracy_pct": overall.as_dict()["accuracy_pct"], "fields_compared": overall.n,
        "per_field_accuracy_pct": {**{f: header_t[f].as_dict()["accuracy_pct"] for f in HEADER}, **{"line." + f: line_t[f].as_dict()["accuracy_pct"] for f in LINE}},
        "per_file_kind_accuracy_pct": {k: v.as_dict()["accuracy_pct"] for k, v in kind_t.items()}, "vmrs_accuracy_pct": pct(*vmrs),
        "ai_seconds_per_invoice": round(sum(x.duration_ms for x in runs) / 1000 / max(n_invoices, 1), 2),
        "flags": tot_flags, "flag_precision_pct": pct(tot_tp, tot_flags), "false_positives": fp_total, "false_positives_marked_check_extraction": fp_uncertain,
        "confident_flags": len(confident), "confident_flag_precision_pct": pct(conf_tp, len(confident)), "flag_recall_pct": pct(tot_found, tot_pl), "per_rule": per,
        "planted_total": tot_pl, "planted_found": tot_found, "accepted": accepted, "amount_corrected": corrected, "dismissed": dismissed,
        "report": {"recoverable": snap["summary"]["recoverable"], "pct_of_spend": snap["summary"]["pct_of_spend"], "total_spend": snap["summary"]["total_spend"],
                   "flag_count": snap["summary"]["flag_count"], "share_url": rep["share_url"], "pdf_bytes": len(pdf.content)},
        "seconds_extraction_per_invoice": round(t_extract / max(n_invoices, 1), 3), "seconds_checks": round(t_flags, 2),
        "seconds_total_200": round(wall, 1), "extraction_cost_usd": None if OFFLINE else round(cost, 4),
        "cost_per_invoice_usd": None if OFFLINE else round((cost + run.get("cost_usd", 0)) / max(n_invoices, 1), 5),
        "flag_explanation_cost_usd": run.get("cost_usd"),
    }
    (out / "summary.json").write_text(json.dumps(metrics, indent=2, default=str))
    print("\n[6/6] Summary")
    print(f"  invoices {n_invoices} | field accuracy {metrics['field_accuracy_pct']}% ({'oracle, not a model result' if OFFLINE else 'real'}) | split ok {metrics['split_correct_pct']}%")
    print(f"  flags {tot_flags} | precision {metrics['flag_precision_pct']}% | recall {metrics['flag_recall_pct']}% | report ${snap['summary']['recoverable']:,.2f} ({snap['summary']['pct_of_spend']}% of spend)")
    print(f"  of {fp_total} false flags, {fp_uncertain} were already marked 'check extraction first'; precision of the other {len(confident)} flags: {metrics['confident_flag_precision_pct']}%")
    for t, rr in per.items():
        print(f"    {t:24s} planted {rr['planted']:2d} found {rr['found']:2d} recall {rr['recall_pct']:5}% | flags {rr['flags']:2d} precision {rr['precision_pct']}%")
    print(f"  time: extraction {metrics['seconds_extraction_per_invoice']}s/invoice, total {metrics['seconds_total_200']}s | cost/invoice {metrics['cost_per_invoice_usd']}")


if __name__ == "__main__":
    main()

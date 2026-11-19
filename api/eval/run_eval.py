"""Run the pipeline on the synthetic set and measure it against the answer key.

Usage (inside the api container):
  python -m eval.run_eval --synthetic /synthetic/out --provider openai|claude|oracle [--limit 50] [--out /app/eval_out]
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import random
import re
import time
import uuid
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

os.environ["QUEUE_INLINE"] = "true"

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import client_session, system_session  # noqa: E402
from app.models import DEFAULT_CLIENT_SETTINGS, Client, ExtractionRun, FieldConfidence, Invoice, Upload, UploadSource, UploadStatus  # noqa: E402
from app.seed import seed_vmrs  # noqa: E402
from app.services.ingest import RejectedFile, ingest_file  # noqa: E402
from app.services.normalize import normalize_shop_name  # noqa: E402

HEADER = ["shop_name", "shop_address", "invoice_number", "invoice_date", "unit_number", "vin", "odometer", "subtotal", "tax", "total"]
LINE = ["description", "part_number", "qty", "parts_price", "labour_hours", "labour_rate", "line_total"]
MONEY = {"subtotal", "tax", "total", "parts_price", "labour_rate", "line_total"}


def _alnum(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower()) if s is not None else ""


def same(field: str, got, want) -> bool:
    if want is None:
        return got in (None, "")
    if got in (None, ""):
        return False
    if field in MONEY:
        return Decimal(str(got)).quantize(Decimal("0.01")) == Decimal(str(want)).quantize(Decimal("0.01"))
    if field in ("qty", "labour_hours"):
        return Decimal(str(got)) == Decimal(str(want))
    if field == "odometer":
        return int(got) == int(want)
    if field == "invoice_date":
        return str(got) == str(want)
    if field == "shop_name":
        return normalize_shop_name(str(got)) == normalize_shop_name(str(want))
    if field == "description":
        return difflib.SequenceMatcher(None, _alnum(got), _alnum(want)).ratio() >= 0.9
    return _alnum(got) == _alnum(want)


def pct(a, b) -> float:
    return round(100.0 * a / b, 2) if b else 0.0


class Tally:
    def __init__(self):
        self.n = self.ok = self.reviewed = self.wrong = self.wrong_caught = self.ok_flagged = 0

    def add(self, correct: bool, review: bool):
        self.n += 1
        self.ok += correct
        self.reviewed += review
        if not correct:
            self.wrong += 1
            self.wrong_caught += review
        elif review:
            self.ok_flagged += 1

    def as_dict(self):
        return {"fields": self.n, "accuracy_pct": pct(self.ok, self.n), "sent_to_review_pct": pct(self.reviewed, self.n),
                "wrong": self.wrong, "wrong_caught_pct": pct(self.wrong_caught, self.wrong)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", required=True)
    ap.add_argument("--provider", choices=["openai", "claude", "oracle"], required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="/app/eval_out")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    root = Path(a.synthetic)
    key = json.loads((root / "answer_key.json").read_text())
    files = key["files"][: a.limit] if a.limit else key["files"]

    s = get_settings()
    if a.provider == "oracle":
        os.environ["AI_PROVIDER"] = "oracle"
        get_settings.cache_clear()
        from app.services.extraction.fake import FakeProvider

        FakeProvider.reset()
    else:
        os.environ["AI_PROVIDER"] = a.provider
        get_settings.cache_clear()

    from app import storage

    storage.ensure_bucket()
    with system_session() as db:
        seed_vmrs(db)
        c = Client(name=f"Eval {time.strftime('%Y-%m-%d %H:%M:%S')}", slug=f"eval-{uuid.uuid4().hex[:8]}", inbound_email_token=uuid.uuid4().hex[:12])
        c.settings = dict(DEFAULT_CLIENT_SETTINGS)
        db.add(c)
        db.commit()
        cid = c.id

    rng = random.Random(a.seed)
    header_t, line_t = defaultdict(Tally), defaultdict(Tally)
    kind_t: dict[str, Tally] = defaultdict(Tally)
    overall, header_all, vmrs = Tally(), Tally(), [0, 0]
    split_ok = split_n = dup_expected = dup_found = failed = 0
    invoices_total = 0
    mismatches: dict[str, list] = defaultdict(list)
    wall_total = 0.0
    sources = defaultdict(int)

    from app.services.extraction.fake import FakeProvider

    for entry in files:
        data = (root / entry["file"]).read_bytes()
        if a.provider == "oracle":
            pages = iter(__import__("eval.oracle", fromlist=["x"]).pages_for_file(entry, rng))
            FakeProvider.responder = lambda _img, it=pages: next(it)
        t0 = time.monotonic()
        with client_session(cid) as db:
            db.info["user_id"] = None
            try:
                up = ingest_file(db, filename=Path(entry["file"]).name, data=data, source=UploadSource.web)
            except RejectedFile as e:
                failed += 1
                mismatches["rejected"].append((entry["file"], str(e)))
                continue
            wall_total += time.monotonic() - t0
            if entry.get("exact_duplicate_of"):
                dup_expected += 1
                dup_found += up.status == UploadStatus.duplicate
                continue
            if up.status == UploadStatus.failed:
                failed += 1
                mismatches["failed_upload"].append((entry["file"], up.status_detail))
            invs = db.scalars(select(Invoice).where(Invoice.source_upload_id == up.id).order_by(Invoice.page_start)).all()
            want = sorted(entry["invoices"], key=lambda i: i["page_start"])
            invoices_total += len(want)
            split_n += 1
            split_ok += [(i.page_start, i.page_end) for i in invs] == [(w["page_start"], w["page_end"]) for w in want]
            if len(invs) != len(want):
                mismatches["split"].append((entry["file"], f"expected {len(want)} invoices, got {len(invs)}"))
            conf_rows = {}
            ids = [i.id for i in invs] + [ln.id for i in invs for ln in i.lines]
            for fc in db.scalars(select(FieldConfidence).where(FieldConfidence.record_id.in_(ids))) if ids else []:
                conf_rows[(fc.record_id, fc.field)] = fc.needs_review
            for pos, w in enumerate(want):
                inv = invs[pos] if pos < len(invs) else None
                for f in HEADER:
                    got = None if inv is None else (inv.shop_name_raw if f == "shop_name" else getattr(inv, f))
                    ok = same(f, got, w["header"].get(f))
                    rv = bool(inv and conf_rows.get((inv.id, f)))
                    for t in (header_t[f], overall, header_all, kind_t[entry["kind"]]):
                        t.add(ok, rv)
                    if not ok and len(mismatches[f]) < 6:
                        mismatches[f].append((entry["file"], entry["kind"], str(got), str(w["header"].get(f))))
                got_lines = inv.lines if inv else []
                for n, wl in enumerate(w["lines"]):
                    gl = got_lines[n] if n < len(got_lines) else None
                    for f in LINE:
                        ok = same(f, None if gl is None else getattr(gl, f), wl.get(f))
                        rv = bool(gl and conf_rows.get((gl.id, f)))
                        for t in (line_t[f], overall, kind_t[entry["kind"]]):
                            t.add(ok, rv)
                        if not ok and len(mismatches["line_" + f]) < 6:
                            mismatches["line_" + f].append((entry["file"], entry["kind"], str(None if gl is None else getattr(gl, f)), str(wl.get(f))))
                    vmrs[1] += 1
                    if gl is not None and gl.vmrs_code == wl["vmrs_code"]:
                        vmrs[0] += 1
                    elif len(mismatches["vmrs"]) < 10:
                        mismatches["vmrs"].append((entry["file"], wl["description"], gl.vmrs_code if gl else None, wl["vmrs_code"]))
                    if gl is not None:
                        sources[gl.vmrs_source or "none"] += 1
                if len(got_lines) != len(w["lines"]):
                    mismatches["line_count"].append((entry["file"], f"expected {len(w['lines'])}, got {len(got_lines)}"))

    with client_session(cid) as db:
        runs = db.scalars(select(ExtractionRun)).all()
    cost = sum(float(r.cost_usd) for r in runs)
    ai_ms = sum(r.duration_ms for r in runs)
    report = {
        "provider": a.provider,
        "model": {"openai": get_settings().openai_model, "claude": get_settings().claude_model}.get(a.provider, "oracle (offline; no image is read)"),
        "files": len(files), "invoices": invoices_total,
        "overall": overall.as_dict(), "header_only": header_all.as_dict(),
        "per_field": {**{f: header_t[f].as_dict() for f in HEADER}, **{"line." + f: line_t[f].as_dict() for f in LINE}},
        "per_file_kind": {k: v.as_dict() for k, v in kind_t.items()},
        "vmrs_accuracy_pct": pct(*vmrs), "vmrs_sources": dict(sources),
        "split_correct_pct": pct(split_ok, split_n), "exact_duplicates_caught": f"{dup_found}/{dup_expected}",
        "failed_files": failed,
        "avg_wall_seconds_per_invoice": round(wall_total / max(invoices_total, 1), 3),
        "avg_ai_seconds_per_invoice": round(ai_ms / 1000 / max(invoices_total, 1), 3),
        "avg_cost_usd_per_invoice": round(cost / max(invoices_total, 1), 4),
        "total_cost_usd": round(cost, 2),
        "examples": {k: v[:6] for k, v in mismatches.items()},
    }
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"eval_{a.provider}.json").write_text(json.dumps(report, indent=2, default=str))
    o = report["overall"]
    print(f"\nprovider={a.provider} files={len(files)} invoices={invoices_total}")
    print(f"overall accuracy {o['accuracy_pct']}% | header-only {report['header_only']['accuracy_pct']}% | sent to review {o['sent_to_review_pct']}% "
          f"| wrong fields caught {o['wrong_caught_pct']}% | vmrs {report['vmrs_accuracy_pct']}% | split ok {report['split_correct_pct']}%")
    print("worst fields:", sorted(((v["accuracy_pct"], k) for k, v in report["per_field"].items()))[:5])


if __name__ == "__main__":
    main()

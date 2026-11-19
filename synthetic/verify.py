#!/usr/bin/env python3
"""Verify an output dir: python verify.py --out out"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data import vin_valid       # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="out")
a = ap.parse_args()
out = a.out
key = json.load(open(os.path.join(out, "answer_key.json")))
meta = json.load(open(os.path.join(out, "generation_meta.json")))
errs = []


def err(m):
    errs.append(m)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def txt(p):
    return subprocess.run(["pdftotext", "-layout", p, "-"], capture_output=True, text=True).stdout


def pages(p):
    m = re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", p], capture_output=True, text=True).stdout)
    return int(m.group(1))


files = key["files"]
uniq = {}
kinds = collections.Counter()
dirs = collections.Counter()
for f in files:
    p = os.path.join(out, f["file"])
    if not os.path.isfile(p):
        err(f"missing file {f['file']}")
        continue
    kinds[f["kind"]] += 1
    dirs[f["file"].split("/")[0]] += 1
    if f["exact_duplicate_of"]:
        if sha(p) != sha(os.path.join(out, f["exact_duplicate_of"])):
            err(f"exact dup differs {f['file']}")
    for inv in f["invoices"]:
        uniq.setdefault(inv["key_id"], inv)
    # media checks
    if f["file"].endswith(".pdf"):
        np_ = pages(p)
        if np_ != max(i["page_end"] for i in f["invoices"]):
            err(f"page count mismatch {f['file']}: {np_}")
        t = txt(p)
        if f["kind"] in ("clean_pdf", "multi_pdf"):
            tt = t.replace(",", "")
            for inv in f["invoices"]:
                h = inv["header"]
                for need in (h["invoice_number"], h["unit_number"], f"{h['total']:.2f}", f"{h['subtotal']:.2f}", f"{h['tax']:.2f}"):
                    if need not in tt:
                        err(f"{f['file']} {inv['key_id']}: '{need}' not in text layer")
                if h["vin"] and h["vin"] not in tt:
                    err(f"{f['file']} {inv['key_id']}: vin missing")
                for ln in inv["lines"]:
                    if f"{ln['line_total']:.2f}" not in tt:
                        err(f"{f['file']} {inv['key_id']}: line total {ln['line_total']} missing")
                if inv["page_end"] > inv["page_start"] and "Page 1 of 2" not in t:
                    err(f"{f['file']}: expected 'Page 1 of 2'")
        elif len(t.strip()) > 0:
            err(f"{f['file']}: scan has text layer")

# math
for kid, inv in uniq.items():
    h, L = inv["header"], inv["lines"]
    mp = [p for p in inv["planted"] if p["type"] == "math_error"]
    field = None
    corr = None
    if mp:
        m = re.search(r"field=(\w+).*?correct ([\d.]+)", mp[0]["note"])
        field, corr = m.group(1), float(m.group(2))
    bad_line = mp[0]["line_no"] if field == "line_total" else None
    tot = 0.0
    taxable = 0.0
    for ln in L:
        lt = ln["line_total"]
        if ln["line_no"] == bad_line:
            lt = corr
        if ln["labour_hours"] is not None:
            exp = round((ln["parts_price"] or 0) + ln["labour_hours"] * ln["labour_rate"], 2)
            if abs(exp - lt) > .011:
                err(f"{kid} line {ln['line_no']} math {exp} vs {lt}")
        elif ln["parts_price"] is not None and abs(ln["parts_price"] - lt) > .011 and ln["part_number"] is None:
            err(f"{kid} line {ln['line_no']} parts/total")
        tot += lt
        taxable += (ln["parts_price"] or 0) if ln["vmrs_code"] else lt
    tot = round(tot, 2)
    sub, tax, total = h["subtotal"], h["tax"], h["total"]
    esub = corr if field == "subtotal" else sub
    etax = corr if field == "tax" else tax
    etot = corr if field == "total" else total
    if abs(tot - esub) > .011:
        err(f"{kid} subtotal {esub} vs sum {tot}")
    if abs(round(esub + etax, 2) - etot) > .011:
        err(f"{kid} total {etot} vs {esub}+{etax}")
    rate = meta[kid]["tax_rate"]
    if abs(round(taxable * rate, 2) - etax) > .011:
        err(f"{kid} tax {etax} vs rate calc {round(taxable * rate, 2)}")
    if field:       # printed value must actually differ
        printed = {"subtotal": sub, "tax": tax, "total": total}.get(field)
        if printed is not None and abs(printed - corr) < .005:
            err(f"{kid} planted math error not visible")
    if h["vin"]:
        if vin_valid(h["vin"]) != inv["vin_check_digit_valid"]:
            err(f"{kid} vin flag wrong")
    elif inv["vin_check_digit_valid"] is not None:
        err(f"{kid} vin flag without vin")
    d = dt.date.fromisoformat(h["invoice_date"])
    if not dt.date(2024, 1, 1) <= d <= dt.date(2026, 10, 31):
        err(f"{kid} date {d}")

# per-unit odometer monotonic + planted consistency
by_unit = collections.defaultdict(list)
for kid, inv in uniq.items():
    by_unit[inv["header"]["unit_number"]].append((inv["header"]["invoice_date"], kid, inv))
# duplicates (re-renders) are same invoice; skip them for timeline
dupkids = {k for k, i in uniq.items() if any(p["type"] == "duplicate_invoice" for p in i["planted"])}
for u, lst in by_unit.items():
    lst = sorted([x for x in lst if x[1] not in dupkids])
    last = 0
    for d, kid, inv in lst:
        o = inv["header"]["odometer"]
        if o is None:
            continue
        if o < last:
            err(f"odometer decreases {u} {kid}")
        last = o


def codes(inv):
    return {l["vmrs_code"] for l in inv["lines"] if l["vmrs_code"]}


for u, lst in by_unit.items():
    lst = sorted([x for x in lst if x[1] not in dupkids])
    for d, kid, inv in lst:
        ptypes = {p["type"] for p in inv["planted"]}
        for t in ("repeat_repair", "warranty_case"):
            if t in ptypes:
                dd = dt.date.fromisoformat(d)
                ok = False
                for d2, k2, i2 in lst:
                    if k2 == kid:
                        continue
                    gap = (dd - dt.date.fromisoformat(d2)).days
                    common = codes(inv) & codes(i2)
                    if gap <= 0 or not common:
                        continue
                    mi = None if inv["header"]["odometer"] is None else inv["header"]["odometer"] - i2["header"]["odometer"]
                    if t == "repeat_repair" and 30 <= gap <= 60 and (mi is None or mi <= 8000):
                        ok = True
                    if t == "warranty_case" and gap <= 365 and (mi is not None and mi <= 100000) and common & {"031-001-001", "032-001-001", "042-001-002", "041-001-003"}:
                        ok = True
                if not ok:
                    err(f"{kid} {t} has no matching earlier invoice")
        # unplanted unintended repeats
        if not ({"repeat_repair", "warranty_case"} & ptypes):
            for d2, k2, i2 in lst:
                gap = (dt.date.fromisoformat(d) - dt.date.fromisoformat(d2)).days
                if 0 < gap <= 60 and codes(inv) & codes(i2):
                    err(f"{kid} unplanted repeat of {k2}")

# duplicate invoices
for kid in dupkids:
    inv = uniq[kid]
    ref = re.search(r"INV-\d+", [p for p in inv["planted"] if p["type"] == "duplicate_invoice"][0]["note"]).group(0)
    o = uniq[ref]
    for k in ("shop_name", "invoice_number", "invoice_date", "unit_number"):
        if o["header"][k].upper() != inv["header"][k].upper():
            err(f"dup {kid} vs {ref} differs in {k}")
    if meta[kid]["layout"] == meta[ref]["layout"]:
        err(f"dup {kid} same layout as {ref}")

# summary
pt = collections.Counter()
planted_inv = 0
for inv in uniq.values():
    if inv["planted"]:
        planted_inv += 1
    for p in inv["planted"]:
        pt[p["type"]] += 1
print("\n=== SUMMARY ===")
print(f"files in key: {len(files)}   unique invoices (key_ids): {len(uniq)}   (seed {key['generated_with']['seed']}, count {key['generated_with']['count']})")
print("\nfiles per kind")
for k, v in sorted(kinds.items()):
    print(f"  {k:14s}{v:5d}")
print("files per dir")
for k, v in sorted(dirs.items()):
    print(f"  {k + '/':14s}{v:5d}")
print(f"exact byte duplicate files: {sum(1 for f in files if f['exact_duplicate_of'])}")
print(f"multi PDFs: {[len(f['invoices']) for f in files if f['kind'] == 'multi_pdf']} invoices each; 2-page invoices: "
      f"{sum(1 for f in files if f['kind'] == 'multi_pdf' for i in f['invoices'] if i['page_end'] > i['page_start'])}")
print("\nplanted problems (invoice count)")
for k, v in sorted(pt.items()):
    print(f"  {k:22s}{v:4d}")
print(f"  invoices with a planted problem: {planted_inv} / {len(uniq)} = {planted_inv / len(uniq):.1%}")
print(f"invoices with invalid VIN check digit: {sum(1 for i in uniq.values() if i['vin_check_digit_valid'] is False)}")
lay = collections.Counter(m["layout"] for m in meta.values())
print("layouts:", dict(sorted(lay.items())), " shops:", len({i['header']['shop_name'].upper() for i in uniq.values()}),
      " units:", len(by_unit))
print("\nerrors:", len(errs))
for e in errs[:40]:
    print("  ", e)
sys.exit(1 if errs else 0)

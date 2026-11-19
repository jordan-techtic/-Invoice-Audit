#!/usr/bin/env python3
"""Synthetic US heavy-duty repair invoice generator.  python generate.py --out out --count 200 --seed 7"""
import os
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
import argparse
import copy
import datetime as dt
import io
import json
import random
import shutil
import sys
import tempfile
import time
from multiprocessing import Pool

import numpy as np
import cv2
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import data as D          # noqa: E402
import render as RN       # noqa: E402
import degrade as DG      # noqa: E402

KEY_LINE_FIELDS = ["line_no", "description", "part_number", "qty", "parts_price", "labour_hours", "labour_rate", "line_total", "vmrs_code"]


# ------------------------------------------------------------------ line building
def build_lines(ev, L, shop):
    mode, up = L["mode"], (lambda s: s.upper()) if L["upper"] else (lambda s: s)
    rate = shop["rate"]
    lines = []
    for ji, j in enumerate(ev["jobs"]):
        labour = round(j["hours"] * rate, 2)
        pn = j["pn"] if (L["pn"] and j["pn"]) else None
        blank = dict(part_number=None, qty=None, parts_price=None, labour_hours=None, labour_rate=None, unit_price=None, lump=None, _job=ji, vmrs_code=j["code"])
        if mode in ("combined_hrs", "combined_text", "combined_lump"):
            ln = dict(blank, kind="job", description=up(j["desc"]), part_number=pn, qty=(j["qty"] if (L["qty"] and j["pn"]) else None),
                      parts_price=(j["parts"] if j["pn"] else None), line_total=round(j["parts"] + labour, 2))
            if mode == "combined_lump":
                ln["lump"] = labour
            else:
                ln.update(labour_hours=j["hours"], labour_rate=rate)
            lines.append(ln)
        else:
            if j["pn"]:
                lines.append(dict(blank, kind="parts", description=up(j["part_desc"]), part_number=pn, qty=j["qty"], parts_price=j["parts"],
                                  unit_price=j["unit_price"], line_total=j["parts"]))
            ln = dict(blank, kind="labour", description=up("Labor - " + j["desc"]), line_total=labour)
            if mode == "separate_hrs":
                ln.update(labour_hours=j["hours"], labour_rate=rate)
            lines.append(ln)
    if L.get("sect"):
        lines.sort(key=lambda l: 0 if l["kind"] == "parts" else 1)
    labour_total = sum(round(j["hours"] * rate, 2) for j in ev["jobs"])
    fees = []
    if shop["supplies"]:
        s = shop["supplies"]
        fees.append((shop["sup_label"], s[1] if s[0] == "flat" else min(round(s[1] * labour_total, 2), s[2])))
    if shop["env"] and any(D.CAT[j["code"]][4] for j in ev["jobs"]):
        fees.append((shop["env_label"], shop["env"]))
    for lab, amt in fees:
        lines.append(dict(kind="fee", description=up(lab), part_number=None, qty=None, parts_price=None, labour_hours=None, labour_rate=None,
                          unit_price=None, lump=None, _job=None, vmrs_code=None, line_total=round(amt, 2)))
    for i, ln in enumerate(lines):
        ln["line_no"] = i + 1
    taxable = sum(j["parts"] for j in ev["jobs"]) + sum(a for _, a in fees)
    return lines, round(taxable * shop["tax"], 2), labour_total


def wrong_amount(v, rng):
    opts = []
    for d in (5, 10, 15, 20, 25, 40, 50, 75, 100):
        opts += [v + d, v - d]
    s = f"{v:.2f}"
    ip = s.split(".")[0]
    if len(ip) >= 3 and ip[-1] != ip[-2]:
        t = ip[:-2] + ip[-1] + ip[-2]
        opts.append(float(t + "." + s.split(".")[1]))
    opts = [round(o, 2) for o in opts if o > 0 and abs(o - v) > 0.004]
    return rng.choice(opts)


def finalize(ev, L, shop, rng, dup_of=None):
    lines, tax, _ = build_lines(ev, L, shop)
    sub = round(sum(l["line_total"] for l in lines), 2)
    total = round(sub + tax, 2)
    planted = []
    unit = ev["unit"]
    vin = None
    valid = None
    if L["vin"]:
        vin = D.bad_check(unit["vin"], rng) if ev["vin_bad"] else unit["vin"]
        valid = D.vin_valid(vin)
    pr_sub, pr_tax, pr_total = sub, tax, total
    if dup_of is None:
        for p in ev["planted"]:
            if p["type"] == "math_error":
                continue
            ji = p["job"]
            mine = [l for l in lines if l["_job"] == ji]
            if p["what"] == "hours":
                tgt = [l for l in mine if l["labour_hours"] is not None][0]
                j = ev["jobs"][ji]
                note = f'hours {j["hours"]} vs typical {j["typ_hours"]} (+{(j["hours"] / j["typ_hours"] - 1) * 100:.0f}%)'
            elif p["what"] == "part":
                tgt = [l for l in mine if l["parts_price"] is not None][0]
                j = ev["jobs"][ji]
                note = f'unit price {j["unit_price"]:.2f} vs typical {j["typ_price"]:.2f} (+{(j["unit_price"] / j["typ_price"] - 1) * 100:.0f}%) for {j["pn"]}'
            else:
                tgt = mine[0]
                note = None      # filled after key ids exist
            planted.append(dict(type=p["type"], line_no=tgt["line_no"], note=note, _ref=p.get("pred")))
        if ev["math"]:
            kind = ev["math"]
            if kind == "line_total":
                tgt = rng.choice(lines)
                true = tgt["line_total"]
                tgt["line_total"] = wrong_amount(true, rng)
                planted.append(dict(type="math_error", line_no=tgt["line_no"], note=f'field=line_total (line {tgt["line_no"]}); printed {tgt["line_total"]:.2f}, correct {true:.2f}'))
            elif kind == "subtotal":
                pr_sub = wrong_amount(sub, rng)
                planted.append(dict(type="math_error", line_no=None, note=f"field=subtotal; printed {pr_sub:.2f}, correct {sub:.2f}"))
            elif kind == "tax":
                alt = round((tax / shop["tax"] if shop["tax"] else 0) * 0 + sum(l["line_total"] for l in lines) * shop["tax"], 2)
                pr_tax = alt if abs(alt - tax) >= 1 else round(tax + rng.choice([4.5, 7.25, 12.0, 18.4]), 2)
                planted.append(dict(type="math_error", line_no=None, note=f"field=tax; printed {pr_tax:.2f}, correct {tax:.2f}"))
            else:
                pr_total = wrong_amount(total, rng)
                planted.append(dict(type="math_error", line_no=None, note=f"field=total; printed {pr_total:.2f}, correct {total:.2f}"))
    else:
        planted.append(dict(type="duplicate_invoice", line_no=None, note=None, _dup=dup_of))
    up = (lambda s: s.upper()) if L["upper"] else (lambda s: s)
    header = dict(shop_name=up(shop["name"]) if L["header"] == "mono" else shop["name"],
                  shop_address=up(shop["addr"]) if L["header"] == "mono" else shop["addr"],
                  invoice_number=ev["number"], invoice_date=ev["date"].isoformat(), unit_number=unit["unit"], vin=vin,
                  odometer=ev["odo"], subtotal=pr_sub, tax=pr_tax, total=pr_total)
    extra = dict(po=str(rng.randint(10000, 99999)), ro=str(rng.randint(100000, 999999)), drv=rng.choice(D.NAMES), terms=rng.choice(["Net 30", "Net 15", "Due on receipt", "Net 45"]))
    taxlab = ("SALES TAX" if L["upper"] else f'Sales Tax ({shop["tax"] * 100:g}%)')
    return dict(shop=shop, L=L, header=header, lines=lines, planted=planted, vin_valid=valid, extra=extra, tax_label=taxlab,
                _tax_rate=shop["tax"])


# ------------------------------------------------------------------ rendering workers
def _init_worker():
    cv2.setNumThreads(1)


def render_job(job):
    path, medium, hw, invs, caps, seed = job["path"], job["medium"], job["hw"], job["invs"], job["caps"], job["seed"]
    rng = np.random.default_rng(seed)
    info = {}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if medium == "pdf":
        RN.make_pdf(path, invs, None, caps)
        return job["path"], info
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.join(td, "p.pdf")
        hwset = {"unit", "odo", "hrs", "total"} if hw else None
        _, marks = RN.make_pdf(tmp, invs, [hwset], caps)
        dpi = 150 if medium == "scan" else (230 if job["mp"] == "hi" else 190)
        img = DG.rasterize(tmp, dpi, 1, 1)[0]
        if hw:
            img = DG.hand_overlay(img, marks[0], dpi, rng)
            info["handwritten_fields"] = sorted({m["name"] for m in marks[0]})
        if medium == "scan":
            g, ang = DG.scan_look(img, rng)
            g.save(path, "PDF", resolution=dpi, quality=int(rng.integers(60, 80)), creationDate=time.gmtime(1767225600), modDate=time.gmtime(1767225600))
            info["skew_deg"] = round(ang, 2)
        else:
            out, pinfo = DG.photo_look(img, rng, job["mp"])
            out.save(path, "JPEG", quality=int(rng.integers(55, 86)))
            info.update(pinfo)
    return job["path"], info


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    a = ap.parse_args()
    t0 = time.time()
    seed, count = a.seed, a.count
    cv2.setNumThreads(1)
    out = os.path.abspath(a.out)
    if os.path.isdir(out):
        for sub in ("pdf", "scans", "photos", "multi"):
            shutil.rmtree(os.path.join(out, sub), ignore_errors=True)
    os.makedirs(out, exist_ok=True)
    rng = random.Random(seed)
    sc = count / 200.0
    n = lambda x: max(1, round(x * sc))
    shops = D.make_shops(rng)
    fleet = D.make_fleet(rng, shops)
    n_rep, n_war = n(9), n(7)
    events = D.build_events(rng, shops, fleet, count, n_rep, n_war)
    D.assign_odometers(rng, events, fleet)
    D.assign_numbers(rng, events, shops)
    counts = dict(inflated=n(12), outlier=n(10), math=n(12), badvin=3, dup=4)
    dups = D.plant(rng, events, shops, RN.LAYOUTS, counts)

    # ---- entries
    entries = []
    ev_entry = {}
    for i, ev in enumerate(events):
        L = RN.layout_for(ev["shop"])
        inv = finalize(ev, L, ev["shop"], random.Random(f"{seed}-e{i}"))
        ent = dict(ev=ev, inv=inv, is_dup=False)
        entries.append(ent)
        ev_entry[id(ev)] = ent
    dup_entries = []
    for i, ev in enumerate(dups):
        orig = ev_entry[id(ev)]
        cands = [s for s in shops if s["layout"] != orig["inv"]["L"]["id"]]
        o = random.Random(f"{seed}-d{i}").choice(cands)
        L2 = RN.layout_for(o)
        inv = finalize(ev, L2, ev["shop"], random.Random(f"{seed}-dd{i}"), dup_of=ev)
        ent = dict(ev=ev, inv=inv, is_dup=True, orig=orig)
        dup_entries.append(ent)
    all_entries = entries + dup_entries

    # ---- multi-pdf groups: consecutive invoices of one shop
    by_shop = {}
    for ent in entries:
        by_shop.setdefault(ent["ev"]["shop"]["idx"], []).append(ent)
    order = sorted(by_shop, key=lambda k: -len(by_shop[k]))
    multi_sizes = [3, 4, 5] if count >= 100 else [3, 3, 3]
    multi_groups = []
    for sz, sidx in zip(multi_sizes, order[:3]):
        grp = sorted(by_shop[sidx], key=lambda e: (e["ev"]["date"], e["ev"]["number"]))
        # prefer events with >=4 lines so some can span pages; take a consecutive window
        best = max(range(0, len(grp) - sz + 1), key=lambda s: sum(len(e["inv"]["lines"]) >= 4 for e in grp[s:s + sz]))
        multi_groups.append(grp[best:best + sz])
    in_multi = {id(e) for g in multi_groups for e in g}
    span_pat = [[1], [0, 2], [1, 3]]

    # ---- single-file media assignment
    rest = [e for e in all_entries if id(e) not in in_multi]
    r2 = random.Random(f"{seed}-media")
    r2.shuffle(rest)
    S = len(rest)
    n_hw = round(20 * sc)
    n_scan_t = round(S * 38 / 192)
    n_photo_t = round(S * 60 / 192)
    hw_scan, hw_photo = n_hw // 2, n_hw - n_hw // 2
    elig = [e for e in rest if e["inv"]["L"]["id"] != "L6" and e["inv"]["L"]["mode"] != "x"]
    hw_ents = elig[:n_hw]
    hw_ids = {id(e) for e in hw_ents}
    others = [e for e in rest if id(e) not in hw_ids]
    plan = []      # (entry, kind, medium, hw)
    for k, e in enumerate(hw_ents):
        plan.append((e, "handwritten", "scan" if k < hw_scan else "photo", True))
    ns, np_ = n_scan_t - hw_scan, n_photo_t - hw_photo
    for k, e in enumerate(others):
        if k < ns:
            plan.append((e, "skewed_scan", "scan", False))
        elif k < ns + np_:
            plan.append((e, "phone_photo", "photo", False))
        else:
            plan.append((e, "clean_pdf", "pdf", False))
    r2.shuffle(plan)
    files = []
    cnt = dict(pdf=0, scan=0, photo=0)
    for e, kind, medium, hw in plan:
        cnt[medium] += 1
        d, pre, ext = dict(pdf=("pdf", "inv", "pdf"), scan=("scans", "scan", "pdf"), photo=("photos", "photo", "jpg"))[medium]
        files.append(dict(file=f"{d}/{pre}_{cnt[medium]:04d}.{ext}", kind=kind, medium=medium, hw=hw, ents=[e], caps=[None]))
    for gi, g in enumerate(multi_groups):
        caps = []
        for k, e in enumerate(g):
            nr = len(e["inv"]["lines"])
            caps.append(max(1, nr - 2) if (k in span_pat[gi] and nr >= 3) else None)
        files.append(dict(file=f"multi/multi_{gi + 1:04d}.pdf", kind="multi_pdf", medium="pdf", hw=False, ents=g, caps=caps))
    # exact duplicates
    singles = [f for f in files if f["kind"] != "multi_pdf"]
    r3 = random.Random(f"{seed}-exact")
    dupfiles = []
    for medium in ("pdf", "pdf", "scan", "photo"):
        cand = [f for f in singles if f["medium"] == medium and f not in [x["src"] for x in dupfiles]]
        src = r3.choice(cand)
        cnt[medium] += 1
        d, pre, ext = dict(pdf=("pdf", "inv", "pdf"), scan=("scans", "scan", "pdf"), photo=("photos", "photo", "jpg"))[medium]
        dupfiles.append(dict(file=f"{d}/{pre}_{cnt[medium]:04d}.{ext}", kind=src["kind"], medium=medium, hw=src["hw"], ents=src["ents"],
                             caps=src["caps"], src=src, exact=src["file"]))
    files.sort(key=lambda f: f["file"])

    # ---- key ids (files in path order, dup files reuse)
    kid = 0
    for f in files:
        f["ids"] = []
        for e in f["ents"]:
            kid += 1
            e["key_id"] = f"INV-{kid:04d}"
            f["ids"].append(e["key_id"])
    for e in all_entries:
        if "key_id" not in e:
            raise SystemExit("unassigned entry")
    for f in dupfiles:
        f["ids"] = f["src"]["ids"]
    ev_kid = {id(e["ev"]): e["key_id"] for e in entries}
    ev_ent = {id(e["ev"]): e for e in entries}

    # ---- fill planted notes
    for e in all_entries:
        for p in e["inv"]["planted"]:
            if "_dup" in p:
                p["note"] = f'same shop/invoice number/lines as {ev_kid[id(p["_dup"])]} re-rendered with a different layout'
            elif p.get("_ref") is not None:
                pred = p["_ref"]
                ev = e["ev"]
                days = (ev["date"] - pred["date"]).days
                miles = None if ev["odo"] is None else ev["odo"] - pred["odo"]
                code = ev["jobs"][0]["code"]
                if p["type"] == "repeat_repair":
                    p["note"] = f'{code} repeated on same unit {days} days' + (f' / {miles} mi' if miles is not None else '') + f' after {ev_kid[id(pred)]}'
                else:
                    p["note"] = f'{code} replaced again {days} days' + (f' / {miles} mi' if miles is not None else '') + f' after {ev_kid[id(pred)]} (within 12 months & 100k mi)'
    # ---- pages
    for f in files:
        page = 1
        f["pages"] = []
        for e, cap in zip(f["ents"], f["caps"]):
            npg = RN.count_pages(e["inv"], cap)
            f["pages"].append((page, page + npg - 1))
            page += npg
        if f["kind"] != "multi_pdf":
            assert f["pages"][0] == (1, 1), (f["file"], f["pages"])

    # ---- render
    jobs = []
    for i, f in enumerate(files):
        jobs.append(dict(path=os.path.join(out, f["file"]), medium=f["medium"], hw=f["hw"], invs=[{k: v for k, v in e["inv"].items() if k != "planted"} for e in f["ents"]], caps=f["caps"],
                         seed=seed * 100003 + i, mp="hi" if (i * 7919 + seed) % 10 < 4 else "lo"))
    if a.workers > 1:
        with Pool(a.workers, initializer=_init_worker) as p:
            res = p.map(render_job, jobs, chunksize=2)
    else:
        res = [render_job(j) for j in jobs]
    infos = {os.path.relpath(p, out): inf for p, inf in res}
    for f in dupfiles:
        shutil.copyfile(os.path.join(out, f["exact"]), os.path.join(out, f["file"]))

    # ---- answer key
    def inv_json(e, pg):
        inv = e["inv"]
        lines = [{k: ln[k] for k in KEY_LINE_FIELDS} for ln in inv["lines"]]
        for ln in lines:
            for k in ("parts_price", "labour_rate", "line_total"):
                if ln[k] is not None:
                    ln[k] = round(float(ln[k]), 2)
            if ln["qty"] is not None:
                ln["qty"] = float(ln["qty"])
            if ln["labour_hours"] is not None:
                ln["labour_hours"] = float(ln["labour_hours"])
        h = dict(inv["header"])
        for k in ("subtotal", "tax", "total"):
            h[k] = round(float(h[k]), 2)
        planted = [dict(type=p["type"], line_no=p["line_no"], note=p["note"]) for p in inv["planted"]]
        return dict(key_id=e["key_id"], page_start=pg[0], page_end=pg[1], header=h, lines=lines, planted=planted,
                    vin_check_digit_valid=inv["vin_valid"])

    key_files = []
    for f in sorted(files + dupfiles, key=lambda f: f["file"]):
        key_files.append(dict(file=f["file"], kind=f["kind"], exact_duplicate_of=f.get("exact"),
                              invoices=[inv_json(e, pg) for e, pg in zip(f["ents"], f["pages"] if "pages" in f else f["src"]["pages"])]))
    total_inv = len({e["key_id"] for e in all_entries})
    key = {"generated_with": {"seed": seed, "count": count}, "files": key_files}
    with open(os.path.join(out, "answer_key.json"), "w") as fh:
        json.dump(key, fh, indent=1)
    meta = {}
    for f in files + dupfiles:
        for e in f["ents"]:
            meta.setdefault(e["key_id"], dict(layout=e["inv"]["L"]["id"], tax_rate=e["inv"]["_tax_rate"], dup_entry=e["is_dup"], files=[]))["files"].append(
                dict(file=f["file"], **infos.get(f["file"], infos.get(f.get("exact"), {}))))
    with open(os.path.join(out, "generation_meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)
    print(f"wrote {len(files) + len(dupfiles)} files, {total_inv} invoices (key ids) in {time.time() - t0:.0f}s -> {out}")


if __name__ == "__main__":
    main()

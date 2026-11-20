"""Reference data in Settings: thresholds, warranty rules CSV and the vehicle list, and proof the rule engine uses them.

Tests that read the real dataset files are skipped when the dataset is not on this machine
(set DATASET_V1_DIR to its synthetic_dataset_v1 folder)."""

import csv
import io
import os
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db import client_session
from app.flags import reference
from app.flags.engine import run_flag_engine
from app.flags.rules import duplicate, labour, repeat, warranty
from app.models import Flag, Vehicle, WarrantyRule
from app.services.extraction.fake import FakeProvider

from .flag_helpers import I, L, ctx, d, rule
from .test_flags_engine import add_invoice

DATASET = Path(os.environ.get("DATASET_V1_DIR", Path.home() / "Downloads/files/synthetic_dataset_v1_full/synthetic_dataset_v1"))
need_dataset = pytest.mark.skipif(not (DATASET / "master/vehicles.csv").exists(), reason="dataset files not on this machine")
CODE = "042-001-002"


def csv_bytes(header: list[str], rows: list[list]) -> bytes:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    w.writerows(rows)
    return out.getvalue().encode()


def post_file(client, path: str, data: bytes, name="file.csv", **form):
    return client.post(path, files={"file": (name, data, "text/csv")}, data=form)


WARRANTY_HEADER = ["component", "warranty_months", "warranty_miles", "covers"]


# ======================================================================= rules use the new settings
def pair(o1, o2, d1, d2, **kw):
    return [I("a", 0, num="1", dt=d1, odo=o1, lines=[L("a", code=CODE, total=300)]),
            I("b", 1, num="2", dt=d2, odo=o2, lines=[L("b", code=CODE, total=450)], **kw)]


def test_repeat_and_needs_both_days_and_miles():
    cfg = {"repeat_condition": "and"}
    inside = pair(100_000, 105_000, d(2025, 1, 1), d(2025, 2, 1))
    assert len(repeat.run(ctx(inside, cfg=cfg))) == 1
    too_far = pair(100_000, 130_000, d(2025, 1, 1), d(2025, 2, 1))     # in the days, but 30,000 miles
    assert repeat.run(ctx(too_far, cfg=cfg)) == []
    too_late = pair(100_000, 101_000, d(2025, 1, 1), d(2025, 9, 1))    # in the miles, but 8 months
    assert repeat.run(ctx(too_late, cfg=cfg)) == []


def test_repeat_and_uses_days_alone_when_miles_are_unknown():
    c = ctx(pair(None, None, d(2025, 1, 1), d(2025, 2, 1)), cfg={"repeat_condition": "and"})
    assert len(repeat.run(c)) == 1


def test_repeat_or_is_still_the_default():
    too_far = pair(100_000, 130_000, d(2025, 1, 1), d(2025, 2, 1))
    too_late = pair(100_000, 101_000, d(2025, 1, 1), d(2025, 9, 1))
    assert len(repeat.run(ctx(too_far))) == 1 and len(repeat.run(ctx(too_late))) == 1  # either limit is enough, as before


def test_trailers_repeat_on_days_only():
    inv = pair(None, None, d(2025, 1, 1), d(2025, 9, 1))
    for i in inv:
        i.vehicle_class, i.odometer = "trailer", 50_000   # a stray odometer on a trailer is ignored
    inv[1].odometer = 51_000
    assert repeat.run(ctx(inv)) == []  # 8 months apart, 1,000 "miles": would flag on miles, but trailers use days only


def test_warranty_parts_only_claims_the_parts_not_the_labour():
    first = I("a", 0, num="1", dt=d(2025, 1, 1), lines=[L("a", code=CODE, total=300)])
    second = I("b", 1, num="2", dt=d(2025, 2, 1), lines=[L("b", 1, code=CODE, price=180, qty=1, total=180),
                                                           L("b", 2, code=CODE, hours=2, rate=100, total=200)])
    both = warranty.run(ctx([first, second], warranty=rule(CODE, "Water pump", 12, 100000)))
    assert both[0].impact == D("380")
    from app.flags.types import WarrantyView
    parts = warranty.run(ctx([first, second], warranty={CODE: WarrantyView(CODE, "Water pump", 12, 100000, "parts")}))
    assert parts[0].impact == D("180") and parts[0].evidence["covers"] == "parts" and "parts only" in parts[0].template_reason


def test_warranty_parts_only_has_nothing_to_claim_on_a_labour_only_repeat():
    from app.flags.types import WarrantyView
    first = I("a", 0, num="1", dt=d(2025, 1, 1), lines=[L("a", code=CODE, total=300)])
    second = I("b", 1, num="2", dt=d(2025, 2, 1), lines=[L("b", code=CODE, hours=2, rate=100, total=200)])
    assert warranty.run(ctx([first, second], warranty={CODE: WarrantyView(CODE, "Water pump", 12, 100000, "parts")})) == []


def test_duplicate_window_catches_a_resubmission_with_a_new_number_and_date():
    mk = lambda i, n, day, unit="T1": I(i, n, num=f"N{n}", dt=d(2025, 3, day), unit=unit, lines=[L(i, code=CODE, total=500)], total=500)  # noqa: E731
    near = [mk("a", 0, 1), mk("b", 1, 6)]
    assert duplicate.run(ctx(near)) == []                                               # window 0: the date has to match
    flags = duplicate.run(ctx(near, cfg={"duplicate_window_days": 10}))
    assert len(flags) == 1 and flags[0].invoice_id == "b" and flags[0].evidence["window_days"] == 10
    assert duplicate.run(ctx([mk("a", 0, 1), mk("b", 1, 20)], cfg={"duplicate_window_days": 10})) == []          # too far apart
    assert duplicate.run(ctx([mk("a", 0, 1), mk("b", 1, 3, unit="T2")], cfg={"duplicate_window_days": 10})) == []  # different unit


def test_labour_uses_the_vehicle_class_baseline_when_it_has_one():
    inv = I("x", 0, lines=[L("x", code=CODE, hours=1.6, rate=100)])
    inv.vehicle_class = "trailer"
    c = ctx([inv], benchmarks={CODE: D("1.4")}, class_benchmarks={(CODE, "trailer"): D("0.9")})
    f = labour.run(c)
    assert len(f) == 1 and f[0].evidence["benchmark_hours"] == 0.9 and f[0].evidence["vehicle_class"] == "trailer"
    inv.vehicle_class = "tractor"   # no tractor baseline: falls back to the all-vehicles 1.4 h, and 1.6 h is only 14% over
    assert labour.run(ctx([inv], benchmarks={CODE: D("1.4")}, class_benchmarks={(CODE, "trailer"): D("0.9")})) == []


def test_labour_class_medians_split_by_class():
    views = []
    for n in range(5):
        a = I(f"t{n}", n, unit=f"T{n}", lines=[L(f"t{n}", code=CODE, hours=1.4, rate=100)]); a.vehicle_class = "tractor"
        b = I(f"r{n}", n + 9, unit=f"R{n}", lines=[L(f"r{n}", code=CODE, hours=0.9, rate=100)]); b.vehicle_class = "trailer"
        views += [a, b]
    views.append(I("n", 99, unit="X", lines=[L("n", code=CODE, hours=5, rate=100)]))   # unit not on the fleet list: not counted
    got = reference.labour_class_medians(views, 5)
    assert got == {(CODE, "tractor"): (D("1.40"), 5), (CODE, "trailer"): (D("0.90"), 5)}


# ======================================================================= settings
def test_client_settings_always_show_every_threshold(admin_client, world):
    s = admin_client.get(f"/clients/{world['a']}").json()["settings"]   # the test client was saved with empty settings
    assert s["repeat_condition"] == "or" and s["duplicate_window_days"] == 0 and s["math_tolerance"] == 1.0


def test_settings_are_validated(admin_client, world):
    url = f"/clients/{world['a']}"
    ok = admin_client.patch(url, json={"settings": {"repeat_condition": "AND", "duplicate_window_days": 10, "parts_outlier_pct": 50.0}})
    assert ok.status_code == 200 and ok.json()["settings"]["repeat_condition"] == "and" and ok.json()["settings"]["duplicate_window_days"] == 10
    for bad in ({"repeat_condition": "maybe"}, {"repeat_repair_days": -5}, {"parts_min_samples": 2.5}, {"math_tolerance": "lots"},
                {"labour_over_benchmark_pct": True}, {"duplicate_window_days": 9999}):
        r = admin_client.patch(url, json={"settings": bad})
        assert r.status_code == 422, bad
    assert admin_client.get(url).json()["settings"]["repeat_condition"] == "and"   # the rejected requests changed nothing


def test_only_admins_can_import(analyst_client, world):
    cid = world["a"]
    assert post_file(analyst_client, f"/clients/{cid}/vehicles/import", b"unit,vehicle_class\nT-1,tractor\n").status_code == 403
    assert post_file(analyst_client, f"/clients/{cid}/warranty-rules/import", csv_bytes(WARRANTY_HEADER, [["x", 12, 1, "parts"]])).status_code == 403
    assert post_file(analyst_client, f"/clients/{cid}/settings/import-thresholds", b"{}").status_code == 403
    assert analyst_client.get(f"/clients/{cid}/vehicles").status_code == 200   # but they can read the list


@need_dataset
def test_thresholds_file_from_the_dataset_fills_the_form_without_saving(admin_client, world):
    raw = (DATASET / "master/thresholds_and_rules.json").read_bytes()
    r = post_file(admin_client, f"/clients/{world['a']}/settings/import-thresholds", raw, "thresholds_and_rules.json")
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert s == {"labour_over_benchmark_pct": 20.0, "repeat_repair_days": 90, "repeat_repair_miles": 15000, "parts_outlier_pct": 50.0,
                 "parts_single_shop_multiple": 1.5, "parts_min_samples": 5, "duplicate_window_days": 10}
    assert "warranty_rule" in r.json()["ignored"]
    assert admin_client.get(f"/clients/{world['a']}").json()["settings"]["repeat_repair_miles"] == 10000   # review first, then save


def test_thresholds_file_problems_are_explained(admin_client, world):
    url = f"/clients/{world['a']}/settings/import-thresholds"
    assert "valid JSON" in post_file(admin_client, url, b"not json").json()["detail"]
    assert "expected threshold names" in post_file(admin_client, url, b'{"hello": 1}').json()["detail"]
    r = post_file(admin_client, url, b'{"labour_over_benchmark_pct": 20}')   # 20 where the file format wants a fraction like 0.2
    assert r.status_code == 422 and "Labour over benchmark" in r.json()["detail"]


# ======================================================================= warranty import
@need_dataset
def test_warranty_import_reads_all_35_dataset_components(admin_client, world):
    cid = world["a"]
    r = post_file(admin_client, f"/clients/{cid}/warranty-rules/import", (DATASET / "master/warranty_rules.csv").read_bytes(), "warranty_rules.csv")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"] == 35 and body["skipped"] == []
    assert body["added"] + body["updated"] + len(body["merged"]) == 35   # every component is accounted for
    assert body["merged"] == [] and body["added"] + body["updated"] == 35   # each component has its own job code
    rules = {x["component"]: x for x in admin_client.get(f"/clients/{cid}/warranty-rules").json()}
    battery = next(x for n, x in rules.items() if n.startswith("Battery"))
    assert battery["months"] == 18 and battery["miles"] is None and battery["covers"] == "parts+labour"     # 'unlimited'
    brake_chamber = next(x for n, x in rules.items() if n.startswith("Brake chamber"))
    assert brake_chamber["covers"] == "parts" and brake_chamber["miles"] == 100000
    assert sum(1 for x in rules.values() if x["covers"] == "parts") >= 5
    again = post_file(admin_client, f"/clients/{cid}/warranty-rules/import", (DATASET / "master/warranty_rules.csv").read_bytes()).json()
    assert again["added"] == 0 and again["updated"] == body["added"] + body["updated"]       # importing twice changes nothing


def test_warranty_import_lists_every_bad_row_and_imports_nothing(admin_client, world):
    cid = world["a"]
    before = len(admin_client.get(f"/clients/{cid}/warranty-rules").json())
    data = csv_bytes(WARRANTY_HEADER, [["alternator", "twelve", 100000, "parts"], ["starter", 24, "lots", "parts"], ["battery", 18, "unlimited", "everything"],
                                       ["", 12, 1000, "parts"], ["water_pump", 12, 100000, "parts"], ["water_pump", 12, 100000, "parts"]])
    r = post_file(admin_client, f"/clients/{cid}/warranty-rules/import", data)
    assert r.status_code == 422
    errs = r.json()["errors"]
    assert [(e["row"], e["field"]) for e in errs] == [(2, "warranty_months"), (3, "warranty_miles"), (4, "covers"), (5, "component"), (7, "component")]
    assert "5 problems found" in r.json()["detail"] and "nothing was imported" in r.json()["detail"]
    assert len(admin_client.get(f"/clients/{cid}/warranty-rules").json()) == before


def test_warranty_import_names_the_missing_columns(admin_client, world):
    r = post_file(admin_client, f"/clients/{world['a']}/warranty-rules/import", csv_bytes(["component", "months"], [["x", 12]]))
    assert r.status_code == 422 and "warranty_months, warranty_miles, covers" in r.json()["detail"] and "Columns found: component, months" in r.json()["detail"]
    assert "isn't a text CSV" in post_file(admin_client, f"/clients/{world['a']}/warranty-rules/import", b"\xff\xfe\x00bad").json()["detail"]


def test_warranty_import_reports_rows_with_no_matching_job_code_and_keeps_the_rest(admin_client, world):
    data = csv_bytes(WARRANTY_HEADER, [["water_pump", 12, 100000, "parts+labour"], ["zzz_unknown_widget", 12, 1000, "parts"]])
    r = post_file(admin_client, f"/clients/{world['a']}/warranty-rules/import", data)
    assert r.status_code == 200
    assert [s["component"] for s in r.json()["skipped"]] == ["zzz_unknown_widget"] and r.json()["added"] == 1


def test_warranty_import_replace_mode_swaps_the_whole_list(admin_client, world):
    cid = world["a"]
    data = csv_bytes(WARRANTY_HEADER, [["water_pump", 12, 100000, "parts"]])
    r = post_file(admin_client, f"/clients/{cid}/warranty-rules/import", data, mode="replace")
    assert r.status_code == 200 and r.json()["total_rules"] == 1
    assert [x["component"] for x in admin_client.get(f"/clients/{cid}/warranty-rules").json()] == ["Water pump"]   # the alternator rule is gone


def test_rules_can_be_added_and_edited_with_covers(admin_client, world):
    cid = world["a"]
    r = admin_client.post(f"/clients/{cid}/warranty-rules", json={"vmrs_code": CODE, "component": "Water pump", "months": 12, "miles": 1000, "covers": "parts"})
    assert r.status_code == 201 and r.json()["covers"] == "parts"
    rid = r.json()["id"]
    assert admin_client.put(f"/clients/{cid}/warranty-rules/{rid}", json={"covers": "parts+labour"}).json()["covers"] == "parts+labour"
    assert admin_client.post(f"/clients/{cid}/warranty-rules", json={"vmrs_code": "042-001-001", "component": "x", "months": 1, "covers": "all"}).status_code == 422


# ======================================================================= vehicles import
@need_dataset
def test_vehicles_import_reads_all_135_dataset_vehicles(admin_client, world):
    cid = world["a"]
    raw = (DATASET / "master/vehicles.csv").read_bytes()
    r = post_file(admin_client, f"/clients/{cid}/vehicles/import", raw, "vehicles.csv")
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == 135 and r.json()["added"] == 135 and r.json()["updated"] == 0
    rows = admin_client.get(f"/clients/{cid}/vehicles").json()
    assert len(rows) == 135
    by_class = {}
    for v in rows:
        by_class[v["vehicle_class"]] = by_class.get(v["vehicle_class"], 0) + 1
    assert by_class == {"tractor": 55, "trailer": 40, "box_truck": 26, "van": 14}
    t = next(v for v in rows if v["unit_number"] == "T-1001")
    assert (t["vin"], t["year"], t["make"], t["model"], t["start_odometer"]) == ("3AKR385S6NA911417", 2022, "Freightliner", "Cascadia", 204973)
    trailer = next(v for v in rows if v["unit_number"] == "TR-5301")
    assert trailer["start_odometer"] is None   # trailers have no odometer
    again = post_file(admin_client, f"/clients/{cid}/vehicles/import", raw).json()
    assert again["added"] == 0 and again["updated"] == 135 and len(admin_client.get(f"/clients/{cid}/vehicles").json()) == 135


def test_vehicles_import_lists_every_bad_row_and_imports_nothing(admin_client, world):
    cid = world["a"]
    header = ["unit", "vin", "vehicle_class", "year", "make", "model", "start_odometer"]
    data = csv_bytes(header, [["T-1", "1XKZ19EY0LC884472", "tractor", 2020, "Kenworth", "T680", 1000],
                              ["T-1", "1XKZ19EY0LC884472", "tractor", 2020, "Kenworth", "T680", 1000],      # same unit and VIN again
                              ["T-2", "SHORT", "tractor", 2020, "", "", ""],
                              ["T-3", "", "", 2020, "", "", ""],
                              ["T-4", "", "van", "20x0", "", "", "lots"]])
    r = post_file(admin_client, f"/clients/{cid}/vehicles/import", data)
    assert r.status_code == 422
    got = sorted((e["row"], e["field"]) for e in r.json()["errors"])
    assert got == [(3, "unit"), (3, "vin"), (4, "vin"), (5, "vehicle_class"), (6, "start_odometer"), (6, "year")]
    assert admin_client.get(f"/clients/{cid}/vehicles").json() == []     # nothing imported


def test_vehicles_import_needs_unit_and_class_columns(admin_client, world):
    r = post_file(admin_client, f"/clients/{world['a']}/vehicles/import", csv_bytes(["unit", "vin"], [["T-1", ""]]))
    assert r.status_code == 422 and "missing the column: vehicle_class" in r.json()["detail"]
    assert post_file(admin_client, f"/clients/{world['a']}/vehicles/import", b"unit,vehicle_class\n").status_code == 422   # header only


def test_vehicles_import_updates_a_unit_an_invoice_already_created(admin_client, world):
    cid = world["a"]
    with client_session(cid) as db:
        db.add(Vehicle(unit_number="T1001"))   # created from an invoice that printed the number without the dash
        db.commit()
    r = post_file(admin_client, f"/clients/{cid}/vehicles/import", b"unit,vehicle_class,vin\nT-1001,tractor,3AKR385S6NA911417\n")
    assert r.json()["added"] == 0 and r.json()["updated"] == 1
    rows = admin_client.get(f"/clients/{cid}/vehicles").json()
    assert len(rows) == 1 and rows[0]["vehicle_class"] == "tractor" and rows[0]["vin"] == "3AKR385S6NA911417"


def test_vehicles_are_kept_apart_per_client(admin_client, world):
    post_file(admin_client, f"/clients/{world['a']}/vehicles/import", b"unit,vehicle_class\nT-1,tractor\n")
    assert admin_client.get(f"/clients/{world['b']}/vehicles").json() == []


# ======================================================================= the engine really uses what was imported
def test_imported_vehicle_classes_change_the_labour_flags(admin_client, world):
    """Six DOT inspections at ~1.0 h on tractors, five at 0.5 h on trailers, then one 0.8 h on a trailer. Over all vehicles the
    typical time is 1.0 h, so 0.8 h looks fine; for a trailer (0.5 h) it is 60% over."""
    FakeProvider.reset()
    cid = world["a"]
    with client_session(cid) as db:
        for i in range(6):
            add_invoice(db, f"T{i}", date(2025, 1 + i, 3), unit=f"T-{i}", lines=[("DOT inspection", CODE, D("1.0"), D("100"), None, D("100"))], total=D("100"))
        for i in range(5):
            add_invoice(db, f"R{i}", date(2025, 1 + i, 9), unit=f"TR-{i}", lines=[("DOT inspection", CODE, D("0.5"), D("100"), None, D("50"))], total=D("50"))
        add_invoice(db, "BIG", date(2026, 1, 9), unit="TR-9", lines=[("DOT inspection", CODE, D("0.8"), D("100"), None, D("80"))], total=D("80"))
        db.commit()
    with client_session(cid) as db:
        run_flag_engine(db)
        db.commit()
        assert not [f for f in db.scalars(select(Flag)) if f.type.value == "labour_over_benchmark"]   # no fleet list yet
    fleet = "unit,vehicle_class\n" + "".join(f"T-{i},tractor\n" for i in range(6)) + "".join(f"TR-{i},trailer\n" for i in [0, 1, 2, 3, 4, 9])
    assert post_file(admin_client, f"/clients/{cid}/vehicles/import", fleet.encode()).status_code == 200
    with client_session(cid) as db:
        run_flag_engine(db)
        db.commit()
        flags = [f for f in db.scalars(select(Flag)) if f.type.value == "labour_over_benchmark"]
        assert len(flags) == 1 and flags[0].details["vehicle_class"] == "trailer" and flags[0].details["benchmark_hours"] == 0.5


def test_a_vin_on_the_fleet_list_finds_the_unit_for_repeat_history(admin_client, world):
    """The second invoice prints only the VIN. With the fleet list the engine knows which unit it is, so the repeat is found."""
    FakeProvider.reset()
    cid = world["a"]
    vin = "3AKR385S6NA911417"
    assert post_file(admin_client, f"/clients/{cid}/vehicles/import", f"unit,vehicle_class,vin\nT-1001,tractor,{vin}\n".encode()).status_code == 200
    with client_session(cid) as db:
        add_invoice(db, "A1", date(2025, 3, 1), unit="T-1001", shop="Acme", odo=100000, lines=[("Water pump", CODE, D("2"), D("100"), None, D("300"))], total=D("300"))
        b = add_invoice(db, "A2", date(2025, 3, 20), unit=None, shop="Acme", odo=101000, lines=[("Water pump", CODE, D("2"), D("100"), None, D("320"))], total=D("320"))
        b.vin = vin
        db.commit()
    with client_session(cid) as db:
        run_flag_engine(db)
        db.commit()
        assert [f.type.value for f in db.scalars(select(Flag)) if f.type.value in ("repeat_repair", "warranty_eligible")]


def test_imported_covers_changes_the_claimable_amount(admin_client, world):
    FakeProvider.reset()
    cid = world["a"]
    csv_in = csv_bytes(WARRANTY_HEADER, [["water_pump", 12, 100000, "parts"]])
    assert post_file(admin_client, f"/clients/{cid}/warranty-rules/import", csv_in, mode="replace").status_code == 200
    with client_session(cid) as db:
        add_invoice(db, "W1", date(2025, 3, 1), unit="T-7", shop="Acme", odo=100000, lines=[("Water pump", CODE, None, None, D("200"), D("200"))], total=D("200"))
        add_invoice(db, "W2", date(2025, 4, 1), unit="T-7", shop="Acme", odo=101000,
                          lines=[("Water pump", CODE, None, None, D("210"), D("210")), ("Labour water pump", CODE, D("3"), D("100"), None, D("300"))], total=D("510"))
        db.commit()
    with client_session(cid) as db:
        run_flag_engine(db)
        db.commit()
        f = next(f for f in db.scalars(select(Flag)) if f.type.value == "warranty_eligible")
        assert f.estimated_dollar_impact == D("210.00") and f.details["covers"] == "parts"   # the labour is not claimable


# ======================================================================= add and remove: everything in Settings is the client's own data
def test_a_vehicle_can_be_added_edited_and_removed(admin_client, world):
    cid = world["a"]
    body = {"unit_number": "T-9001", "vehicle_class": "Box Truck", "vin": "3akr385s6na911417", "year": 2022, "make": "Freightliner", "model": "M2", "start_odometer": 1200}
    r = admin_client.post(f"/clients/{cid}/vehicles", json=body)
    assert r.status_code == 201 and r.json()["vehicle_class"] == "box_truck" and r.json()["vin"] == "3AKR385S6NA911417"   # tidied on the way in
    vid = r.json()["id"]
    assert admin_client.post(f"/clients/{cid}/vehicles", json={**body, "unit_number": "T9001"}).status_code == 409           # same unit, spelled differently
    edited = admin_client.put(f"/clients/{cid}/vehicles/{vid}", json={**body, "vehicle_class": "tractor", "unit_number": "T-9001"})
    assert edited.status_code == 200 and edited.json()["vehicle_class"] == "tractor"
    assert admin_client.post(f"/clients/{cid}/vehicles", json={**body, "unit_number": "T-9002", "vin": "123"}).status_code == 422
    assert admin_client.post(f"/clients/{cid}/vehicles", json={**body, "unit_number": "T-9002", "vehicle_class": "!!"}).status_code == 422
    assert admin_client.delete(f"/clients/{cid}/vehicles/{vid}").status_code == 204
    assert admin_client.get(f"/clients/{cid}/vehicles").json() == []
    assert admin_client.delete(f"/clients/{cid}/vehicles/{vid}").status_code == 404


def test_removing_a_vehicle_keeps_the_invoices_that_pointed_at_it(admin_client, world):
    from app.models import Invoice

    cid = world["a"]
    with client_session(cid) as db:
        v = Vehicle(unit_number="T-77")
        db.add(v)
        db.flush()
        inv = add_invoice(db, "V1", date(2025, 1, 1), unit="T-77", total=D("10"))
        inv.vehicle_id = v.id
        iid = inv.id
        db.commit()
    assert admin_client.delete(f"/clients/{cid}/vehicles").json() == {"removed": 1}
    with client_session(cid) as db:
        inv = db.get(Invoice, iid)
        assert inv is not None and inv.vehicle_id is None and inv.unit_number == "T-77"


def test_remove_all_clears_each_list_for_that_client_only(admin_client, world):
    a, b = world["a"], world["b"]
    for cid in (a, b):
        post_file(admin_client, f"/clients/{cid}/vehicles/import", b"unit,vehicle_class\nT-1,tractor\nT-2,van\n")
    assert admin_client.delete(f"/clients/{a}/vehicles").json() == {"removed": 2}
    assert admin_client.get(f"/clients/{a}/vehicles").json() == [] and len(admin_client.get(f"/clients/{b}/vehicles").json()) == 2
    assert admin_client.delete(f"/clients/{a}/warranty-rules").json() == {"removed": 1}      # the one rule the test client was made with
    assert admin_client.get(f"/clients/{a}/warranty-rules").json() == [] and len(admin_client.get(f"/clients/{b}/warranty-rules").json()) == 1


def test_only_admins_can_remove(analyst_client, world):
    cid = world["a"]
    assert analyst_client.delete(f"/clients/{cid}/vehicles").status_code == 403
    assert analyst_client.delete(f"/clients/{cid}/warranty-rules").status_code == 403
    assert analyst_client.delete(f"/clients/{cid}/benchmarks").status_code == 403
    assert analyst_client.post(f"/clients/{cid}/benchmarks", json={"vmrs_code": CODE, "benchmark_hours": 1}).status_code == 403


def test_benchmarks_can_be_typed_in_listed_and_removed(admin_client, world):
    cid = world["a"]
    r = admin_client.post(f"/clients/{cid}/benchmarks", json={"vmrs_code": CODE, "benchmark_hours": 2.5})
    assert r.status_code == 201
    admin_client.post(f"/clients/{cid}/benchmarks", json={"vmrs_code": CODE, "benchmark_hours": 1.5, "vehicle_class": "Trailer"})
    rows = admin_client.get(f"/clients/{cid}/benchmarks").json()
    assert [(x["vehicle_class"], x["hours"], x["source"]) for x in rows] == [(None, 2.5, "manual"), ("trailer", 1.5, "manual")]
    assert admin_client.post(f"/clients/{cid}/benchmarks", json={"vmrs_code": CODE, "benchmark_hours": 3}).status_code == 409   # same code, all vehicles
    assert admin_client.post(f"/clients/{cid}/benchmarks", json={"vmrs_code": "000-0", "benchmark_hours": 3}).status_code == 422
    assert admin_client.post(f"/clients/{cid}/benchmarks", json={"vmrs_code": CODE, "benchmark_hours": 0}).status_code == 422
    assert admin_client.delete(f"/clients/{cid}/benchmarks/{r.json()['id']}").status_code == 204
    assert len(admin_client.get(f"/clients/{cid}/benchmarks").json()) == 1


def test_computed_benchmarks_cannot_be_removed_but_remove_all_keeps_them(admin_client, world):
    FakeProvider.reset()
    cid = world["a"]
    with client_session(cid) as db:
        for i in range(6):
            add_invoice(db, f"B{i}", date(2025, 1 + i, 3), unit=f"U-{i}", lines=[("Water pump", CODE, D("2.0"), D("100"), None, D("200"))], total=D("200"))
        db.commit()
    with client_session(cid) as db:
        run_flag_engine(db)
        db.commit()
    admin_client.post(f"/clients/{cid}/benchmarks", json={"vmrs_code": "042-001-001", "benchmark_hours": 4})
    rows = admin_client.get(f"/clients/{cid}/benchmarks").json()
    computed = next(x for x in rows if x["source"] == "client_median")
    assert admin_client.delete(f"/clients/{cid}/benchmarks/{computed['id']}").status_code == 409
    assert admin_client.delete(f"/clients/{cid}/benchmarks").json() == {"removed": 1}
    assert [x["source"] for x in admin_client.get(f"/clients/{cid}/benchmarks").json()] == ["client_median"]


@need_dataset
def test_benchmark_jobs_file_from_the_dataset_imports_by_class(admin_client, world):
    cid = world["a"]
    raw = (DATASET / "master/jobs_vmrs.csv").read_bytes()
    r = post_file(admin_client, f"/clients/{cid}/benchmarks/import-jobs", raw, "jobs_vmrs.csv")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"] == 139 and body["imported"] + len(body["merged"]) + len(body["skipped"]) == 139
    assert body["imported"] == 139 and body["skipped"] == [] and body["merged"] == []   # every job and class has its own value
    rows = admin_client.get(f"/clients/{cid}/benchmarks").json()
    assert len(rows) == body["imported"] and {x["vehicle_class"] for x in rows} == {"tractor", "trailer", "box_truck", "van"}
    assert {x["source"] for x in rows} == {"licensed:jobs"}
    again = post_file(admin_client, f"/clients/{cid}/benchmarks/import-jobs", raw).json()
    assert again["imported"] == body["imported"] and len(admin_client.get(f"/clients/{cid}/benchmarks").json()) == body["imported"]   # replaced, not doubled


def test_benchmark_jobs_file_problems_are_explained(admin_client, world):
    url = f"/clients/{world['a']}/benchmarks/import-jobs"
    r = post_file(admin_client, url, csv_bytes(["description", "vehicle_class", "benchmark_hours"], [["Water pump", "", "abc"], ["Water pump", "trailer", "-1"]]))
    assert r.status_code == 422 and sorted((e["row"], e["field"]) for e in r.json()["errors"]) == [(2, "benchmark_hours"), (2, "vehicle_class"), (3, "benchmark_hours")]
    assert "names the job" in post_file(admin_client, url, csv_bytes(["vehicle_class", "benchmark_hours"], [["van", 1]])).json()["detail"]
    assert "benchmark_hours" in post_file(admin_client, url, csv_bytes(["description", "vehicle_class"], [["Water pump", "van"]])).json()["detail"]


def test_a_benchmark_for_one_vehicle_class_drives_the_labour_flags(admin_client, world):
    """No history to build a typical time from; a typed-in 0.5 h for trailers is all there is, and it is used."""
    FakeProvider.reset()
    cid = world["a"]
    post_file(admin_client, f"/clients/{cid}/vehicles/import", b"unit,vehicle_class\nTR-1,trailer\nT-1,tractor\n")
    assert admin_client.post(f"/clients/{cid}/benchmarks", json={"vmrs_code": CODE, "benchmark_hours": 0.5, "vehicle_class": "trailer"}).status_code == 201
    with client_session(cid) as db:
        add_invoice(db, "L1", date(2025, 1, 1), unit="TR-1", lines=[("Water pump", CODE, D("1.0"), D("100"), None, D("100"))], total=D("100"))
        add_invoice(db, "L2", date(2025, 1, 2), unit="T-1", lines=[("Water pump", CODE, D("1.0"), D("100"), None, D("100"))], total=D("100"))
        db.commit()
    with client_session(cid) as db:
        run_flag_engine(db)
        db.commit()
        flags = [f for f in db.scalars(select(Flag)) if f.type.value == "labour_over_benchmark"]
        assert len(flags) == 1 and flags[0].details["vehicle_class"] == "trailer" and flags[0].details["benchmark_hours"] == 0.5   # the tractor has no benchmark


# ---- artifact X8: the model drops "T-" from a unit number on some invoices; the client's own fleet list says which truck it is
def test_an_invoice_unit_that_lost_its_prefix_is_the_same_truck_as_the_fleet_unit(admin_client, world):
    FakeProvider.reset()
    cid = world["a"]
    post_file(admin_client, f"/clients/{cid}/vehicles/import", b"unit,vehicle_class\nT-1026,tractor\nTR-5310,trailer\n")
    with client_session(cid) as db:
        add_invoice(db, "R1", date(2025, 6, 1), unit="T-1026", odo=100000, lines=[("Water pump", CODE, D("2.0"), D("100"), None, D("300"))], total=D("300"))
        add_invoice(db, "R2", date(2025, 6, 20), unit="1026", odo=101000, lines=[("Water pump", CODE, D("2.0"), D("100"), None, D("450"))], total=D("450"))
        db.commit()
    with client_session(cid) as db:
        run_flag_engine(db)
        db.commit()
        repeats = [f for f in db.scalars(select(Flag)) if f.type.value == "repeat_repair"]
        assert len(repeats) == 1 and repeats[0].details["unit"] == "T1026"      # one truck, so the second pump job is a repeat

"""Fleet, shops, job catalogue, event timeline and planted-problem logic (no rendering)."""
import copy
import datetime as dt

D0 = dt.date(2024, 1, 5)
D1 = dt.date(2026, 9, 25)          # last invoice date (today is 2026-11-01 for the dataset)

# ---------------------------------------------------------------- VIN
_TR = {**{str(i): i for i in range(10)},
       **dict(zip("ABCDEFGH", range(1, 9))), **dict(zip("JKLMN", range(1, 6))), "P": 7, "R": 9,
       **dict(zip("STUVWXYZ", [2, 3, 4, 5, 6, 7, 8, 9]))}
_WT = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]
VIN_CHARS = "0123456789ABCDEFGHJKLMNPRSTUVWXYZ"


def vin_check_char(vin17):
    s = sum(_TR[ch] * w for ch, w in zip(vin17, _WT))
    r = s % 11
    return "X" if r == 10 else str(r)


def vin_valid(vin):
    return len(vin) == 17 and vin[8] == vin_check_char(vin)


def make_vin(rng, wmi, year_ch):
    body = wmi + "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(5))
    plant = rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ123456789")
    serial = "".join(rng.choice("0123456789") for _ in range(6))
    v = body + "0" + year_ch + plant + serial
    return v[:8] + vin_check_char(v) + v[9:]


def bad_check(vin, rng):
    good = vin[8]
    c = rng.choice([x for x in "0123456789X" if x != good])
    return vin[:8] + c + vin[9:]


# ---------------------------------------------------------------- shops
# name, address, phone, state, tax, labour rate, layout, accent(rgb), font
SHOPS_RAW = [
    ("Lone Star Truck & Trailer Repair", "4120 Industrial Blvd, Dallas, TX 75247", "(214) 555-0139", .0825, 118, "L1", (.10, .25, .55), "helv"),
    ("Red River Diesel Service", "2208 SE 29th St, Oklahoma City, OK 73129", "(405) 555-0172", .08625, 105, "L2", (.60, .10, .10), "helv"),
    ("Peach State Fleet Services", "1180 Fulton Industrial Blvd SW, Atlanta, GA 30336", "(404) 555-0108", .08, 112, "L3", (.05, .40, .20), "times"),
    ("Buckeye Heavy Duty Repair", "3550 Alum Creek Dr, Columbus, OH 43207", "(614) 555-0155", .075, 98, "L4", (0, 0, 0), "cour"),
    ("Golden State Truck Center", "2750 Patton Way, Bakersfield, CA 93308", "(661) 555-0120", .0775, 138, "L5", (.85, .45, .05), "helv"),
    ("I-35 Diesel & Trailer", "910 N Interstate 35, Waco, TX 76705", "(254) 555-0166", .0825, 102, "L6", (.15, .15, .15), "helv"),
    ("Heartland Mobile Truck Repair", "5612 W 21st St N, Wichita, KS 67205", "(316) 555-0147", .075, 96, "L7", (.2, .2, .2), "times"),
    ("Southern Pride Truck Service", "2630 Moreland Ave, Memphis, TN 38118", "(901) 555-0183", .0925, 108, "L8", (.35, .10, .45), "times"),
    ("Midway Truck Parts & Service", "7100 Channahon Rd, Joliet, IL 60436", "(815) 555-0129", .0825, 124, "L1", (.0, .45, .50), "times"),
    ("Delta Reefer & Diesel", "1805 Airport Rd, Little Rock, AR 72206", "(501) 555-0194", .095, 99, "L2", (.0, .30, .45), "helv"),
    ("Cornerstone Fleet Repair", "8800 Westpark Dr, Houston, TX 77063", "(713) 555-0111", .0825, 128, "L5", (.45, .05, .05), "helv"),
    ("Sun Corridor Truck Care", "4411 S 43rd Ave, Phoenix, AZ 85043", "(602) 555-0138", .086, 115, "L6", (.75, .30, .0), "helv"),
    ("Black Gold Diesel Works", "3300 N Sheridan Rd, Tulsa, OK 74115", "(918) 555-0176", .0852, 101, "L4", (0, 0, 0), "cour"),
    ("Tri-County Truck & Trailer", "1920 Outer Loop, Louisville, KY 40219", "(502) 555-0152", .06, 110, "L7", (.25, .25, .30), "times"),
]
PREFIXES = ["", "INV-", "R", "", "WO", "", "", "INV", "", "SI-", "", "R-", "", ""]
FLEET_NAME = "Redline Carriers, Inc."
FLEET_ADDR = "6100 Logistics Pkwy, Fort Worth, TX 76177"


def make_shops(rng):
    shops = []
    for i, (n, a, p, tax, rate, lay, acc, font) in enumerate(SHOPS_RAW):
        sup = rng.choice([None, ("flat", rng.choice([12.0, 15.0, 18.0, 20.0, 25.0, 35.0])), ("pct", rng.choice([0.04, 0.05, 0.06]), rng.choice([30.0, 40.0, 45.0]))])
        env = rng.choice([None, 6.0, 8.5, 12.0, 15.0, 25.0])
        shops.append(dict(idx=i, name=n, addr=a, phone=p, tax=tax, rate=float(rate), layout=lay, accent=acc, font=font,
                          supplies=sup, env=env, pfac=round(rng.uniform(.95, 1.07), 3),
                          prefix=PREFIXES[i], num=rng.randint(10000, 60000) if PREFIXES[i] != "WO" else rng.randint(2000, 9000),
                          sup_label=rng.choice(["Shop Supplies", "Shop supplies", "Misc Supplies", "Shop Supplies/Haz Mat"]),
                          env_label=rng.choice(["Environmental Fee", "Env. fee", "Haz waste disposal", "Environmental/Disposal"])))
    return shops


# ---------------------------------------------------------------- catalogue
# code: (typical hours, trailer ok, [(pn, part desc, typical unit price, qty choices)], [desc templates], env-fee eligible)
CAT = {
    "013-001-001": (4.5, True, [("BS-4707Q", "Brake shoe kit w/ hardware", 118.0, (2, 4)), ("SP-4709", "Brake shoes reman 16.5x7", 96.0, (2, 4))],
                    ["Reline {axle} brakes, new shoes & hardware", "R&R brake shoes {axle} both sides", "Brake job {axle} - shoes, springs, drums turned", "Replace {axle} brake shoes/hardware, adj slacks"], False),
    "013-001-007": (1.2, True, [("BC-3030", "Brake chamber T30/30 spring brake", 92.0, (1, 2)), ("BC-2430", "Brake chamber T24 service", 74.0, (1, 2))],
                    ["R&R {side} rear brake chamber", "Replaced bad spring brake chamber {side}", "Brake chamber {side} leaking - replaced", "R&R spring brake chamber, adjusted slack"], False),
    "013-002-002": (1.5, False, [("AD-109", "Air dryer cartridge AD-IP", 138.0, (1,)), ("AD-9R", "Air dryer assy AD-9 reman", 312.0, (1,))],
                    ["Replace air dryer cartridge, drain tanks", "R&R air dryer, purged system, checked governor", "Air dryer replaced - oil in tanks", "Rebuild air dryer / new desiccant"], False),
    "031-001-001": (1.8, False, [("AL-8600", "Alternator 12V 160A 22SI", 385.0, (1,)), ("AL-4902", "Alternator 12V 200A", 428.0, (1,))],
                    ["R&R alt", "Replace alternator, tested charging sys", "Alternator not charging - R&R, load tested 14.2V", "R&R alternator & belt check"], False),
    "032-001-001": (1.5, False, [("ST-1115", "Starter 12V 39MT", 340.0, (1,)), ("ST-8200", "Starter motor 12V 42MT", 395.0, (1,))],
                    ["R&R starter", "Replace starter - no crank, cleaned cables/terminals", "Starter motor replaced, tested", "Slow crank, R&R starter"], False),
    "031-002-001": (0.8, False, [("BAT-31P", "Battery grp 31 1000CCA", 188.0, (2, 3, 4)), ("BAT-31M", "Battery 31 AGM 950CCA", 215.0, (2, 3, 4))],
                    ["Replace batteries, clean terminals", "Install new group 31 batts", "R&R batteries - tested bad", "New batteries & cable ends"], True),
    "042-001-002": (4.5, False, [("WP-5300", "Water pump ISX/DD15", 285.0, (1,)), ("WP-2210", "Water pump w/ gasket kit", 262.0, (1,))],
                    ["R&R water pump, refill coolant, pressure tested", "Replace water pump - weeping at weep hole", "Water pump replaced, burped system", "R&R w/pump & thermostat"], True),
    "042-001-001": (6.0, False, [("RAD-9600", "Radiator aluminum core", 1150.0, (1,)), ("RAD-4410", "Radiator assy w/ hoses", 1285.0, (1,))],
                    ["Replace radiator, hoses & clamps, coolant", "R&R rad - leaking at tank seam", "Radiator replaced, pressure tested cooling sys"], True),
    "041-001-003": (6.5, False, [("TB-7640", "Turbocharger reman VGT", 2450.0, (1,)), ("TB-1180", "Turbo assy new", 2890.0, (1,))],
                    ["R&R turbo, new gaskets, checked boost leaks", "Replace turbocharger - low boost", "Turbo swap, oil feed line replaced"], False),
    "023-001-001": (11.0, False, [("CL-1560", "Clutch kit 15.5 2-plate", 1050.0, (1,)), ("CL-1450", "Clutch assy 14in", 890.0, (1,))],
                    ["Replace clutch, resurface flywheel", "R&R clutch assy, new release bearing", "Clutch job - pulled trans, installed kit"], False),
    "018-001-001": (2.4, True, [("WS-370003A", "Wheel seal {axle}", 38.0, (2, 4)), ("WS-370066", "Hub seal oil bath", 44.0, (2, 4))],
                    ["Replace {axle} wheel seals both sides", "R&R wheel seals {side} {axle}", "Leaking hub seal {side}, replaced seal & repacked", "R&R {axle} seals w/ new oil"], True),
    "018-001-002": (3.0, True, [("WB-HM218248", "Wheel bearing set inner/outer", 165.0, (1, 2)), ("WB-JM207049", "Bearing kit w/ cups", 142.0, (1, 2))],
                    ["R&R {side} wheel bearing {axle}", "Replace wheel bearings {axle}, new seals", "Bearing noise {side} - replaced bearing set"], False),
    "017-001-001": (1.6, False, [("TR-29575S", "295/75R22.5 steer tire", 485.0, (1, 2)), ("TR-11R225S", "11R22.5 steer tire", 455.0, (1, 2))],
                    ["Install new steer tire(s), mount/balance", "Replace steer tires {side}", "R&R steer tire, balanced, torqued lugs", "New steer tires mounted & balanced"], True),
    "017-001-002": (2.4, True, [("TR-29575D", "295/75R22.5 drive tire", 398.0, (2, 4)), ("TR-11R225D", "11R22.5 drive tire retread", 265.0, (2, 4))],
                    ["Mount & balance new drive tires", "Replace drive tires {axle}", "R&R drive tires, torqued lugs, set air", "Drive tires mtd & balanced, set air"], True),
    "016-001-003": (1.4, True, [("AS-W01358", "Air spring 1R12", 142.0, (1, 2)), ("AS-1R12-428", "Air bag rolling lobe", 128.0, (1, 2))],
                    ["Replace {side} air bag", "R&R air springs, checked ride height", "Air leak rear susp - new air spring {side}"], False),
    "016-001-002": (1.0, True, [("SH-85024", "Shock absorber HD", 68.0, (2,)), ("SH-83144", "Shock absorber cab/susp", 72.0, (1, 2))],
                    ["Replace shocks", "R&R {side} shock, bushings", "Leaking shocks replaced"], False),
    "015-001-003": (1.5, False, [("TRE-ES3478", "Tie rod end LH thread", 96.0, (1, 2)), ("TRE-ES800", "Tie rod end RH thread", 92.0, (1, 2))],
                    ["R&R tie rod ends, set toe", "Replace {side} tie rod end, align front end", "Loose tie rod end - replaced, toe & align"], False),
    "024-001-001": (1.8, False, [("UJ-5-153X", "U-joint 1710 series", 54.0, (2,)), ("UJ-5-674X", "U-joint 1810 series", 62.0, (1, 2))],
                    ["R&R u-joints driveline", "Replace u-joint, greased slip yoke", "Driveshaft vibration - new u-joints"], False),
    "045-001-001": (1.5, False, [("PM-15W40", "Oil & filter kit 15W-40 CK-4", 142.0, (1,)), ("PM-DD15", "Oil/filter kit DD15 w/ fuel filter", 168.0, (1,))],
                    ["PM service - oil & filter, lube chassis", "PM A: change oil/filters, grease, inspect", "Oil change, lube, safety check", "PM svc 15W40, chassis lube, check fluids"], True),
    "044-001-002": (0.8, False, [("FF-FS1000", "Fuel filter/water sep.", 62.0, (1, 2)), ("FF-FS19764", "Fuel filter set", 118.0, (1,))],
                    ["Replace fuel filters", "R&R primary & secondary fuel filters, primed", "Fuel filter change - hard start"], False),
    "043-001-001": (2.5, False, [("DPF-GK1", "DPF gasket/clamp kit", 85.0, (1,))],
                    ["DPF cleaned & baked, new gaskets", "R&R DPF, thermal clean, reinstall", "DPF clean - regen failing"], False),
    "043-001-002": (3.0, False, [("DEF-DM44", "DEF dosing valve", 640.0, (1,)), ("DEF-PU01", "DEF pump assy", 745.0, (1,))],
                    ["Replace DEF dosing unit, cleared codes", "R&R SCR DEF pump", "DEF fault - replaced dosing valve, tested"], False),
    "034-001-001": (0.5, True, [("HL-HB01", "Headlamp assy LED", 95.0, (1,)), ("HL-9007", "Headlight bulb pair", 24.0, (1,))],
                    ["Replace {side} headlamp", "R&R headlight {side}", "Headlamp out - new assy"], False),
    "001-001-001": (3.5, False, [("AC-CP7100", "A/C compressor w/ clutch", 520.0, (1,)), ("AC-CP4300", "A/C compressor reman", 445.0, (1,))],
                    ["R&R A/C compressor, evac & recharge", "Replace AC compressor, new drier", "No cold air - compressor replaced, recharged"], True),
    "045-001-007": (0.7, False, [("BLT-K080", "Serpentine belt", 48.0, (1,)), ("BLT-K081", "Belt & tensioner kit", 215.0, (1,))],
                    ["Replace serp belt", "R&R serpentine belt, checked tensioner", "Belt squeal - new belt"], False),
    "042-001-005": (2.0, False, [("FC-9100", "Fan clutch assy", 410.0, (1,)), ("FC-3300", "Fan clutch Horton", 455.0, (1,))],
                    ["R&R fan clutch", "Replace fan clutch - fan always on", "Fan clutch bad, replaced & tested"], False),
    "071-001-003": (2.5, True, [("RF-PMK", "Reefer PM kit belts/filters/oil", 185.0, (1,)), ("RF-TK1", "Reefer service kit", 210.0, (1,))],
                    ["Reefer unit PM service", "Reefer svc - oil, filters, belts, checked defrost", "Service reefer unit, tested pull-down"], True),
    "045-001-008": (1.5, False, [],
                    ["Engine diagnostics, scan & test", "Scan tool diag - checked fault codes", "Diagnose check engine light, found codes", "Computer diag / inspect wiring"], False),
}
TRAILER_ONLY = {"071-001-003"}
WARRANTY_CODES = ["031-001-001", "032-001-001", "042-001-002", "041-001-003"]
REPEAT_CODES = ["013-001-001", "013-001-007", "018-001-001", "018-001-002", "016-001-003", "015-001-003",
                "024-001-001", "044-001-002", "013-002-002", "016-001-002", "045-001-007"]
AXLES = ["drive axle", "rear axle", "front axle", "tandem", "steer axle"]
T_AXLES = ["trailer axle #1", "axle #2", "tandem", "rear trailer axle"]
SIDES = ["LH", "RH", "driver side", "pass. side", "both sides"]
NAMES = ["M. Alvarez", "K. Nguyen", "D. Brooks", "R. Whitfield", "T. Okafor", "J. Delgado", "S. Kowalski", "B. Henry", "C. Ruiz", "L. Patel"]


def window(code):
    if code in WARRANTY_CODES:
        return 400
    if code == "045-001-001":
        return 80
    return 120


# ---------------------------------------------------------------- fleet
def make_fleet(rng, shops, n=40):
    tract = [("1XK", "J"), ("1XP", "K"), ("1FU", "L"), ("3AK", "M"), ("4V4", "N"), ("1HS", "J"), ("3HS", "K"), ("1FV", "H")]
    trail = [("1JJ", "J"), ("1GR", "K"), ("1UY", "L")]
    units = []
    used = set()
    ntr = 6
    for i in range(n):
        trailer = i >= n - ntr
        if trailer:
            num = f"TR-{rng.randint(1, 30):02d}"
        elif i % 2 == 0:
            num = f"T-{rng.randint(100, 480)}"
        else:
            num = str(rng.randint(2100, 2399))
        while num in used:
            num = num + "A" if trailer else str(rng.randint(2400, 2999))
        used.add(num)
        wmi, yc = rng.choice(trail if trailer else tract)
        units.append(dict(unit=num, vin=make_vin(rng, wmi, yc), trailer=trailer, reefer=trailer and i % 2 == 0,
                          start=rng.randint(150000, 520000), rate=rng.randint(55000, 98000),
                          home=[i % len(shops)] + rng.sample([k for k in range(len(shops)) if k != i % len(shops)], 2)))
    return units


# ---------------------------------------------------------------- jobs
def make_job(rng, code, shop, unit, inflate=False, outlier=False):
    hrs, _, pns, descs, _ = CAT[code]
    h = round(hrs * rng.uniform(0.9, 1.12), 1)
    if inflate:
        h = round(hrs * rng.uniform(1.45, 1.95), 1)
        h = max(h, round(hrs * 1.4 + 0.05, 1))
    h = max(h, 0.3)
    job = dict(code=code, hours=h, typ_hours=hrs, desc=rng.choice(descs).format(axle=rng.choice(T_AXLES if unit["trailer"] else AXLES), side=rng.choice(SIDES)),
               pn=None, part_desc=None, qty=None, unit_price=None, parts=0.0, typ_price=None)
    if pns:
        pn, pd, price, qs = rng.choice(pns)
        q = rng.choice(qs)
        up = price * shop["pfac"] * rng.uniform(0.97, 1.04)
        if outlier:
            up = price * rng.uniform(1.45, 1.95)
        up = round(up, 2)
        job.update(pn=pn, part_desc=pd.format(axle=rng.choice(T_AXLES if unit["trailer"] else AXLES)), qty=float(q), unit_price=up,
                   parts=round(q * up, 2), typ_price=price)
    return job


def allowed_codes(unit):
    out = []
    for c, v in CAT.items():
        if unit["trailer"]:
            if v[1] and (c != "071-001-003" or unit["reefer"]):
                out.append(c)
        elif c not in TRAILER_ONLY:
            out.append(c)
    return out


def wk(d):
    return d - dt.timedelta(days=max(0, d.weekday() - 4))


def rand_date(rng, lo, hi):
    return wk(lo + dt.timedelta(days=rng.randint(0, (hi - lo).days)))


def build_events(rng, shops, fleet, count, n_repeat, n_warr):
    events = []
    locks = []

    def conflict(unit, code, date, ignore=()):
        for e in events:
            if e["unit"] is not unit or id(e) in ignore:
                continue
            for j in e["jobs"]:
                if j["code"] == code and abs((e["date"] - date).days) < window(code):
                    return True
        return False

    def locked(unit, date):
        return any(u is unit and a - dt.timedelta(days=3) <= date <= b + dt.timedelta(days=3) for u, a, b in locks)

    def pick_shop(unit, prev=None):
        if prev is not None and rng.random() < .6:
            return shops[prev]
        return shops[rng.choice(unit["home"])]

    def extras(unit, date, shop, ev_jobs, k):
        for _ in range(k * 4):
            if len(ev_jobs) >= 1 + k:
                break
            code = rng.choice(allowed_codes(unit))
            if code in [j["code"] for j in ev_jobs] or conflict(unit, code, date):
                continue
            ev_jobs.append(make_job(rng, code, shop, unit))

    def new_event(unit, date, shop, jobs, **kw):
        e = dict(unit=unit, date=date, shop=shop, jobs=jobs, planted=[], cap=None, role=None, vin_bad=False, math=None)
        e.update(kw)
        events.append(e)
        return e

    for kind, n in (("repeat", n_repeat), ("warranty", n_warr)):
        made = 0
        tries = 0
        while made < n and tries < 2000:
            tries += 1
            if kind == "repeat":
                unit = rng.choice(fleet)
                pool = [c for c in REPEAT_CODES if c in allowed_codes(unit)]
                gap = rng.randint(33, 57)
                d1 = rand_date(rng, D0 + dt.timedelta(days=5), dt.date(2026, 7, 15))
            else:
                unit = rng.choice([u for u in fleet if not u["trailer"]])
                pool = list(WARRANTY_CODES)
                gap = rng.randint(100, 300)
                d1 = rand_date(rng, D0 + dt.timedelta(days=5), dt.date(2025, 11, 20))
            code = rng.choice(pool)
            d2 = wk(d1 + dt.timedelta(days=gap))
            g = (d2 - d1).days
            if d2 > D1 or (kind == "repeat" and not 30 <= g <= 60) or (kind == "warranty" and g < 95):
                continue
            if conflict(unit, code, d1) or conflict(unit, code, d2) or locked(unit, d1) or locked(unit, d2):
                continue
            if any(u is unit and not (b < d1 or a > d2) for u, a, b in locks):
                continue
            s1 = pick_shop(unit)
            s2 = pick_shop(unit, s1["idx"])
            if kind == "warranty" or True:
                pass
            j1 = [make_job(rng, code, s1, unit)]
            j2 = [make_job(rng, code, s2, unit)]
            locks.append((unit, d1, d2))
            e1 = new_event(unit, d1, s1, j1, role="pred_" + kind)
            e2 = new_event(unit, d2, s2, j2, role=kind, pred=e1,
                           cap=(3500, 7400) if kind == "repeat" else None)
            for e in (e1, e2):
                extras(unit, e["date"], e["shop"], e["jobs"], rng.choice([0, 0, 1, 2]))
            e2["planted"].append(dict(type="repeat_repair" if kind == "repeat" else "warranty_case", job=0, what="job", pred=e1))
            made += 1

    guard = 0
    while len(events) < count and guard < 20000:
        guard += 1
        unit = rng.choice(fleet)
        date = rand_date(rng, D0, D1)
        if locked(unit, date):
            continue
        shop = pick_shop(unit)
        codes = allowed_codes(unit)
        n = rng.choices([1, 2, 3, 4], [.35, .35, .2, .1])[0]
        jobs = []
        for _ in range(n * 4):
            if len(jobs) >= n:
                break
            code = "045-001-001" if (not unit["trailer"] and not jobs and rng.random() < .22) else rng.choice(codes)
            if code in [j["code"] for j in jobs] or conflict(unit, code, date):
                continue
            jobs.append(make_job(rng, code, shop, unit))
        if jobs:
            new_event(unit, date, shop, jobs)
    return events


def assign_odometers(rng, events, fleet):
    for u in fleet:
        evs = sorted([e for e in events if e["unit"] is u], key=lambda e: (e["date"], id(e)))
        odo = float(u["start"])
        prev = D0 - dt.timedelta(days=0)
        for e in evs:
            if u["trailer"]:
                e["odo"] = None
                continue
            days = (e["date"] - prev).days
            odo += max(days, 0) * u["rate"] / 365.0 * rng.uniform(0.85, 1.15) + rng.uniform(5, 40)
            if e.get("cap") and e.get("pred") is not None:
                odo = min(odo, e["pred"]["odo"] + rng.randint(*e["cap"]))
                odo = max(odo, e["pred"]["odo"] + 600)
            e["odo"] = int(round(odo))
            odo = e["odo"]
            prev = e["date"]


def assign_numbers(rng, events, shops):
    for s in shops:
        n = s["num"]
        for e in sorted([e for e in events if e["shop"] is s], key=lambda e: (e["date"], id(e))):
            n += rng.randint(1, 9)
            e["number"] = f'{s["prefix"]}{n}'


def plant(rng, events, shops, layouts, counts):
    """Mutates events: inflated hours, price outliers, math errors, bad VIN, picks duplicates."""
    free = [e for e in events if e["role"] is None]
    rng.shuffle(free)

    def take(pred, n):
        out = []
        for e in free:
            if len(out) >= n:
                break
            if not e["planted"] and not e["vin_bad"] and not e.get("dup_src") and pred(e):
                out.append(e)
        return out

    def hrs_layout(e):
        return layouts[e["shop"]["layout"]]["hours"]

    # inflated hours
    for e in take(lambda e: hrs_layout(e) and any(j["typ_hours"] >= 1.0 for j in e["jobs"]), counts["inflated"]):
        i = rng.choice([k for k, j in enumerate(e["jobs"]) if j["typ_hours"] >= 1.0])
        e["jobs"][i] = make_job(rng, e["jobs"][i]["code"], e["shop"], e["unit"], inflate=True)
        e["planted"].append(dict(type="inflated_hours", job=i, what="hours"))
    for e in take(lambda e: any(j["typ_price"] and j["typ_price"] >= 50 for j in e["jobs"]), counts["outlier"]):
        i = rng.choice([k for k, j in enumerate(e["jobs"]) if j["typ_price"] and j["typ_price"] >= 50])
        keep = e["jobs"][i]
        j = make_job(rng, keep["code"], e["shop"], e["unit"], outlier=True)
        e["jobs"][i] = j
        e["planted"].append(dict(type="parts_price_outlier", job=i, what="part"))
    for k, e in enumerate(take(lambda e: True, counts["math"])):
        e["math"] = ["line_total", "subtotal", "tax", "total"][k % 4]
        e["planted"].append(dict(type="math_error", job=None, what="math"))
    for e in take(lambda e: layouts[e["shop"]["layout"]]["vin"], counts["badvin"]):
        e["vin_bad"] = True
    dups = take(lambda e: True, counts["dup"])
    for e in dups:
        e["dup_src"] = True
    return dups

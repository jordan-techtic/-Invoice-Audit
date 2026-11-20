"""Parsing and validation for the reference data in Settings: thresholds, warranty rules and the vehicle list.

Pure functions (no database, no HTTP) so they are easy to test. The files are read exactly as supplied; nothing about a
particular dataset is built in. Every function returns ALL the problems it finds, with the row number, so the person
importing can fix the file in one pass.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field

from .normalize import normalize_description, normalize_vin
from .vmrs import lookup

MAX_BYTES = 1_000_000


@dataclass
class RowError:
    row: int  # spreadsheet row number (the header is row 1); 0 = the file as a whole
    message: str
    field: str | None = None

    def out(self) -> dict:
        return {"row": self.row, "field": self.field, "message": self.message}


class FileProblem(Exception):
    """The file can't be read at all (wrong type, missing columns, too big)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _headers(names: list[str] | None) -> list[str]:
    return [re.sub(r"\s+", "_", (n or "").strip().lower()) for n in (names or [])]


def read_csv(raw: bytes, required: list[str], aliases: dict[str, str] | None = None) -> tuple[list[tuple[int, dict[str, str]]], list[str]]:
    """Return ([(row_number, {column: value})], columns). Raises FileProblem if the file or its header is unusable."""
    if len(raw) > MAX_BYTES:
        raise FileProblem("That file is larger than 1 MB. Split it and import the parts.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise FileProblem("That file isn't a text CSV. Export it as CSV (UTF-8) and try again.")
    reader = csv.reader(io.StringIO(text))
    try:
        head = next(reader)
    except StopIteration:
        raise FileProblem("The file is empty. Choose a CSV with a header row and at least one data row.")
    cols = [(aliases or {}).get(c, c) for c in _headers(head)]
    missing = [c for c in required if c not in cols]
    if missing:
        found = ", ".join(c for c in cols if c) or "none"
        raise FileProblem(f"The CSV is missing the column{'s' if len(missing) > 1 else ''}: {', '.join(missing)}. "
                          f"Columns found: {found}. Add {'them' if len(missing) > 1 else 'it'} to the header row and import again.")
    rows: list[tuple[int, dict[str, str]]] = []
    for n, rec in enumerate(reader, start=2):
        if not any((c or "").strip() for c in rec):
            continue  # blank line
        rows.append((n, {cols[i]: (rec[i] if i < len(rec) else "").strip() for i in range(len(cols)) if cols[i]}))
    if not rows:
        raise FileProblem("The file has a header row but no data rows.")
    return rows, cols


def _int(value: str, lo: int, hi: int) -> int | None:
    try:
        n = int(re.sub(r"[,_\s]", "", value))
    except ValueError:
        return None
    return n if lo <= n <= hi else None


# ------------------------------------------------------------------ warranty rules

UNLIMITED = {"", "unlimited", "none", "no limit", "n/a", "na", "-"}


def normalize_covers(v: str) -> str | None:
    s = re.sub(r"[^a-z]+", " ", v.lower()).strip()
    if s == "parts":
        return "parts"
    if s in {"parts labour", "parts labor", "parts and labour", "parts and labor", "parts labour and parts"}:
        return "parts+labour"
    return None


@dataclass
class WarrantyRow:
    row: int
    component: str  # name shown in the app
    vmrs_code: str
    months: int
    miles: int | None
    covers: str
    source_components: list[str] = field(default_factory=list)


@dataclass
class WarrantyParse:
    rules: list[WarrantyRow] = field(default_factory=list)
    merged: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    rows: int = 0


def parse_warranty(raw: bytes, codes: list) -> WarrantyParse:
    """``codes`` are the app's VMRS codes (objects with .code and .keywords). Each CSV row is matched to the job code the app
    itself gives to an invoice line with that description, so the rule applies to the lines it should."""
    rows, cols = read_csv(raw, ["component", "warranty_months", "warranty_miles", "covers"])
    out = WarrantyParse(rows=len(rows))
    valid = {c.code for c in codes}
    seen_components: dict[str, int] = {}
    by_code: dict[str, WarrantyRow] = {}
    for n, r in rows:
        comp = r.get("component", "")
        bad = len(out.errors)
        if not comp:
            out.errors.append(RowError(n, "The component is empty.", "component"))
        elif len(comp) > 200:
            out.errors.append(RowError(n, "The component is longer than 200 characters.", "component"))
        elif comp.lower() in seen_components:
            out.errors.append(RowError(n, f"'{comp}' appears twice (first on row {seen_components[comp.lower()]}). Keep one row per component.", "component"))
        else:
            seen_components[comp.lower()] = n
        months = _int(r.get("warranty_months", ""), 1, 240)
        if months is None:
            out.errors.append(RowError(n, f"warranty_months '{r.get('warranty_months', '')}' must be a whole number of months from 1 to 240.", "warranty_months"))
        raw_miles = r.get("warranty_miles", "")
        miles: int | None = None
        if raw_miles.strip().lower() not in UNLIMITED:
            miles = _int(raw_miles, 1, 10_000_000)
            if miles is None:
                out.errors.append(RowError(n, f"warranty_miles '{raw_miles}' must be a number of miles, or 'unlimited' (or blank) for no limit.", "warranty_miles"))
        covers = normalize_covers(r.get("covers", ""))
        if covers is None:
            out.errors.append(RowError(n, f"covers '{r.get('covers', '')}' must be 'parts' or 'parts+labour'.", "covers"))
        explicit = r.get("vmrs_code", "")
        if explicit and explicit not in valid:
            out.errors.append(RowError(n, f"vmrs_code '{explicit}' isn't a job code the app knows.", "vmrs_code"))
        if len(out.errors) > bad or months is None or covers is None or not comp:
            continue
        code = explicit
        if not code:
            for text in (r.get("description", ""), comp.replace("_", " ")):
                hit = lookup(normalize_description(text), codes) if text else None
                if hit:
                    code = hit.code
                    break
        if not code:
            out.skipped.append({"row": n, "component": comp, "reason": "No job code in the app matches this component. Add it by hand with the right job code."})
            continue
        name = r.get("description") or comp.replace("_", " ").capitalize()
        have = by_code.get(code)
        if have is None:
            by_code[code] = WarrantyRow(n, name, code, months, miles, covers, [comp])
        elif (have.months, have.miles, have.covers) == (months, miles, covers):
            # The app has one job code for both (for example a DEF doser and a NOx sensor) and the terms are the same: one rule covers both.
            have.component = f"{have.component} / {name}"[:200]
            have.source_components.append(comp)
            out.merged.append({"row": n, "component": comp, "into": have.source_components[0], "reason": "Same job code and same terms, so one rule covers both."})
        else:
            out.skipped.append({"row": n, "component": comp, "reason": f"Shares its job code with '{have.source_components[0]}' but has different terms. The app keeps one rule per job code."})
    out.rules = list(by_code.values())
    return out


# ------------------------------------------------------------------ vehicles


@dataclass
class VehicleRow:
    row: int
    unit_number: str
    vin: str | None
    vehicle_class: str
    year: int | None = None
    make: str | None = None
    model: str | None = None
    start_odometer: int | None = None


@dataclass
class VehicleParse:
    vehicles: list[VehicleRow] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    rows: int = 0


def norm_unit(u: str | None) -> str | None:
    return "".join(c for c in u.upper() if c.isalnum()) if u else None


def parse_vehicles(raw: bytes) -> VehicleParse:
    rows, cols = read_csv(raw, ["unit", "vehicle_class"], {"unit_number": "unit", "class": "vehicle_class", "odometer": "start_odometer"})
    out = VehicleParse(rows=len(rows))
    seen_unit: dict[str, int] = {}
    seen_vin: dict[str, int] = {}
    for n, r in rows:
        bad = len(out.errors)
        unit = r.get("unit", "")
        if not unit:
            out.errors.append(RowError(n, "The unit number is empty.", "unit"))
        elif len(unit) > 50:
            out.errors.append(RowError(n, "The unit number is longer than 50 characters.", "unit"))
        elif norm_unit(unit) in seen_unit:
            out.errors.append(RowError(n, f"Unit '{unit}' appears twice (first on row {seen_unit[norm_unit(unit)]}). Keep one row per unit.", "unit"))
        else:
            seen_unit[norm_unit(unit)] = n
        cls = re.sub(r"[\s\-]+", "_", r.get("vehicle_class", "").strip().lower())
        if not cls:
            out.errors.append(RowError(n, "The vehicle_class is empty (for example tractor, trailer, box_truck or van).", "vehicle_class"))
        elif not re.fullmatch(r"[a-z][a-z0-9_]{1,29}", cls):
            out.errors.append(RowError(n, f"vehicle_class '{r.get('vehicle_class')}' must be a short word like tractor, trailer, box_truck or van.", "vehicle_class"))
        vin: str | None = None
        if r.get("vin"):
            vin, status = normalize_vin(r["vin"])
            if status == "bad_length":
                out.errors.append(RowError(n, f"VIN '{r['vin']}' must be 17 characters.", "vin"))
                vin = None
            elif vin in seen_vin:
                out.errors.append(RowError(n, f"VIN {vin} is already used by row {seen_vin[vin]}.", "vin"))
            else:
                seen_vin[vin] = n
                if status == "bad_check":
                    out.warnings.append({"row": n, "message": f"VIN {vin} has a check digit that doesn't add up. Imported as it is; check it for a typo."})
        year = None
        if r.get("year"):
            year = _int(r["year"], 1950, 2100)
            if year is None:
                out.errors.append(RowError(n, f"year '{r['year']}' must be a four-digit year.", "year"))
        odo = None
        if r.get("start_odometer"):
            odo = _int(r["start_odometer"], 0, 10_000_000)
            if odo is None:
                out.errors.append(RowError(n, f"start_odometer '{r['start_odometer']}' must be a whole number of miles.", "start_odometer"))
        if len(out.errors) > bad:
            continue
        out.vehicles.append(VehicleRow(n, unit, vin, cls, year, (r.get("make") or None) and r["make"][:60], (r.get("model") or None) and r["model"][:80], odo))
    return out


# ------------------------------------------------------------------ labour benchmarks by vehicle class

CLASS_PATTERN = re.compile(r"[a-z][a-z0-9_]{1,29}")


def norm_class(v: str | None) -> str | None:
    """'Box Truck' -> 'box_truck'. None when it isn't a usable class name."""
    s = re.sub(r"[\s\-]+", "_", (v or "").strip().lower())
    return s if CLASS_PATTERN.fullmatch(s) else None


@dataclass
class BenchmarkRow:
    row: int
    vmrs_code: str
    vehicle_class: str
    hours: str  # kept as text for exact decimals
    job: str


@dataclass
class BenchmarkParse:
    rows_out: list[BenchmarkRow] = field(default_factory=list)
    merged: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    rows: int = 0


def parse_benchmark_jobs(raw: bytes, codes: list) -> BenchmarkParse:
    """A job list with a vehicle class: vehicle_class, benchmark_hours and a name for the job (description or job_key), or the
    app's own vmrs_code. Each job is matched to the job code the app gives invoice lines with that name."""
    from decimal import Decimal, InvalidOperation

    rows, cols = read_csv(raw, ["vehicle_class", "benchmark_hours"])
    if not ({"description", "job_key", "vmrs_code"} & set(cols)):
        raise FileProblem("The CSV needs a column that names the job: description, job_key or vmrs_code. "
                          f"Columns found: {', '.join(c for c in cols if c) or 'none'}.")
    out = BenchmarkParse(rows=len(rows))
    valid = {c.code for c in codes}
    taken: dict[tuple[str, str], BenchmarkRow] = {}
    for n, r in rows:
        bad = len(out.errors)
        cls = norm_class(r.get("vehicle_class"))
        if cls is None:
            out.errors.append(RowError(n, f"vehicle_class '{r.get('vehicle_class', '')}' must be a short word like tractor, trailer, box_truck or van.", "vehicle_class"))
        try:
            hours = Decimal(r.get("benchmark_hours", ""))
            if not Decimal(0) < hours <= Decimal(200):
                raise InvalidOperation
        except InvalidOperation:
            out.errors.append(RowError(n, f"benchmark_hours '{r.get('benchmark_hours', '')}' must be a number of hours above 0 and up to 200, like 2.5.", "benchmark_hours"))
        explicit = r.get("vmrs_code", "")
        if explicit and explicit in valid:
            code = explicit
        else:
            code = ""
        job = r.get("description") or r.get("job_key", "").replace("_", " ") or explicit
        if len(out.errors) > bad:
            continue
        if not code:
            for text in (r.get("description", ""), r.get("job_key", "").replace("_", " ")):
                hit = lookup(normalize_description(text), codes) if text else None
                if hit:
                    code = hit.code
                    break
        if not code:
            out.skipped.append({"row": n, "job": job, "reason": "No job code in the app matches this job. Add it by hand with the right job code."})
            continue
        key = (code, cls)
        have = taken.get(key)
        if have is None:
            taken[key] = BenchmarkRow(n, code, cls, r["benchmark_hours"], job)
        elif Decimal(have.hours) == hours:
            out.merged.append({"row": n, "job": job, "into": have.job, "reason": "Same job code, class and hours, so one value covers both."})
        else:
            out.skipped.append({"row": n, "job": job, "reason": f"Shares its job code with '{have.job}' for {cls.replace('_', ' ')} but has different hours ({r['benchmark_hours']} against {have.hours}). The app keeps one value per job code and class."})
    out.rows_out = list(taken.values())
    return out


# ------------------------------------------------------------------ thresholds / settings

_NUM = (int, float)


def _is_num(v) -> bool:
    return isinstance(v, _NUM) and not isinstance(v, bool)


# setting -> (kind, low, high, label). Kind "int" must be whole.
SETTING_RULES: dict[str, tuple[str, float, float, str]] = {
    "labour_over_benchmark_pct": ("num", 0, 500, "Labour over benchmark (%)"),
    "labour_min_samples": ("int", 1, 1000, "Labour samples needed"),
    "repeat_repair_days": ("int", 1, 3650, "Repeat repair days"),
    "repeat_repair_miles": ("int", 1, 1_000_000, "Repeat repair miles"),
    "parts_outlier_pct": ("num", 0, 1000, "Parts price over typical (%)"),
    "parts_single_shop_multiple": ("num", 1, 20, "Parts price multiple (single shop)"),
    "parts_min_samples": ("int", 1, 1000, "Parts samples needed"),
    "math_tolerance": ("num", 0, 1000, "Maths tolerance ($)"),
    "duplicate_window_days": ("int", 0, 365, "Duplicate window (days)"),
    "tax_min_invoices": ("int", 1, 1000, "Invoices needed for a shop's tax rate"),
    "tax_rate_tolerance_pct": ("num", 0, 100, "Tax rate tolerance (percentage points)"),
    "severity_high_dollars": ("num", 0, 10_000_000, "High severity from ($)"),
    "severity_medium_dollars": ("num", 0, 10_000_000, "Medium severity from ($)"),
}


def clean_settings(patch: dict) -> tuple[dict, list[str]]:
    """Validate the threshold values that are present in ``patch``. Returns (cleaned values, problems)."""
    clean: dict = {}
    problems: list[str] = []
    for k, v in patch.items():
        if k == "repeat_condition":
            if isinstance(v, str) and v.lower() in ("and", "or"):
                clean[k] = v.lower()
            else:
                problems.append("Repeat condition must be 'and' or 'or'.")
        elif k in SETTING_RULES:
            kind, lo, hi, label = SETTING_RULES[k]
            if not _is_num(v) or (kind == "int" and int(v) != v):
                problems.append(f"{label} must be {'a whole number' if kind == 'int' else 'a number'} from {lo:g} to {hi:g}.")
            elif not lo <= v <= hi:
                problems.append(f"{label} must be from {lo:g} to {hi:g}.")
            else:
                clean[k] = int(v) if kind == "int" else v
        else:
            clean[k] = v  # other settings (retention days, exclusion list) keep their own handling
    return clean, problems


# dataset file key -> app setting. Each entry is (setting, converter).
THRESHOLD_KEYS = {
    "labour_over_benchmark_pct": [("labour_over_benchmark_pct", lambda v: round(v * 100, 4))],  # the file stores a fraction: 0.2 -> 20 (%)
    "repeat_repair_days": [("repeat_repair_days", lambda v: v)],
    "repeat_repair_miles": [("repeat_repair_miles", lambda v: v)],
    "parts_price_outlier_ratio": [("parts_outlier_pct", lambda v: round((v - 1) * 100, 4)), ("parts_single_shop_multiple", lambda v: v)],  # 1.5x -> 50%
    "parts_price_min_observations": [("parts_min_samples", lambda v: v)],
    "duplicate_invoice_window_days": [("duplicate_window_days", lambda v: v)],
}


def thresholds_from_json(raw: bytes) -> tuple[dict, list[dict], list[str]]:
    """Read a thresholds_and_rules.json style file. Returns (settings, applied, ignored). Nothing is saved here."""
    if len(raw) > 200_000:
        raise FileProblem("That file is larger than 200 KB. A thresholds file is a few lines.")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise FileProblem("That file isn't valid JSON. Choose the thresholds_and_rules.json file.")
    if not isinstance(data, dict):
        raise FileProblem("The JSON must be an object of threshold names and values, like thresholds_and_rules.json.")
    settings: dict = {}
    applied: list[dict] = []
    for key, targets in THRESHOLD_KEYS.items():
        if key not in data:
            continue
        v = data[key]
        if not _is_num(v):
            raise FileProblem(f"'{key}' must be a number, but the file has {json.dumps(v)}.")
        for setting, conv in targets:
            settings[setting] = conv(v)
            applied.append({"file_key": key, "setting": setting, "value": settings[setting]})
    if not settings:
        raise FileProblem("None of the expected threshold names were found (for example labour_over_benchmark_pct, repeat_repair_days). Is this the right file?")
    clean, problems = clean_settings(settings)
    if problems:
        raise FileProblem("The file has a value that can't be used: " + " ".join(problems))
    return clean, applied, [k for k in data if k not in THRESHOLD_KEYS]

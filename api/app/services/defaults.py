"""Sensible default warranty rules, applied to every new client and editable in the UI.

Values reflect typical OEM / reman parts warranties on heavy-duty components.
They are a starting point, not a legal statement of any supplier's terms.
"""


def default_warranty_rules() -> list[dict]:
    return [
        {"vmrs_code": "031-001-001", "component": "Alternator", "months": 12, "miles": 100_000},
        {"vmrs_code": "032-001-001", "component": "Starter motor", "months": 12, "miles": 100_000},
        {"vmrs_code": "031-002-001", "component": "Battery", "months": 12, "miles": None},
        {"vmrs_code": "042-001-002", "component": "Water pump", "months": 12, "miles": 100_000},
        {"vmrs_code": "042-001-001", "component": "Radiator", "months": 12, "miles": 100_000},
        {"vmrs_code": "041-001-003", "component": "Turbocharger", "months": 24, "miles": 250_000},
        {"vmrs_code": "013-002-001", "component": "Air compressor", "months": 24, "miles": 200_000},
        {"vmrs_code": "023-001-001", "component": "Clutch assembly", "months": 12, "miles": 100_000},
        {"vmrs_code": "044-001-001", "component": "Fuel injector", "months": 12, "miles": 100_000},
        {"vmrs_code": "001-001-001", "component": "A/C compressor", "months": 12, "miles": 100_000},
        {"vmrs_code": "015-001-001", "component": "Power steering pump", "months": 12, "miles": 100_000},
        {"vmrs_code": "043-001-002", "component": "DEF/SCR system", "months": 24, "miles": 250_000},
    ]

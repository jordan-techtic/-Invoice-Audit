import pytest

from app.db import system_session
from app.services.normalize import normalize_description as nd
from app.services.vmrs import lookup, load_codes


@pytest.fixture(scope="module")
def codes():
    with system_session() as db:
        return load_codes(db)


@pytest.mark.parametrize("text,code", [
    ("R&R wheel seals RH rear axle", "018-001-001"),   # plural, and 'wheel seal' must beat 'wheel'
    ("Leaking shocks replaced", "016-001-002"),
    ("Replace steer tires LH", "017-001-001"),
    ("PM svc 15W40, chassis lube, check fluids", "045-001-001"),
    ("DEF fault - replaced dosing valve, tested", "043-001-002"),
    ("R&R alt", None),                                  # too vague for lookup: left for the AI
    ("Truck not charging, tested the system, found a loose ground", None),   # artifact L11: 'charging' alone is not an alternator job
    ("R&R alternator, charging system tested", "031-001-001"),
    # artifact L5: descriptions are normalised ('PM-A' becomes 'pm a'), and DOT inspections had no job code at all
    ("PM-A svc", "045-001-001"),
    ("Op: PM-A service", "045-001-001"),
    ("Labor - PM-B SERVICE", "045-001-009"),               # PM-B is a bigger service than PM-A: a shared code would blend their benchmark hours and make every PM-B look over
    ("PM-B svc", "045-001-009"),
    ("DOT annual inspection", "000-001-001"),
    ("Op: DOT annual inspection", "000-001-001"),
    ("FHWA ANNUAL INSP", "000-001-001"),
    ("Annual DOT insp", "000-001-001"),
    ("Trailer PM inspection", "000-001-002"),
    ("PM - TRAILER", "000-001-002"),
])
def test_lookup(codes, text, code):
    hit = lookup(nd(text), codes)
    assert (hit.code if hit else None) == code


from app.services.vmrs import is_fee_line


@pytest.mark.parametrize("text,fee", [
    ("Shop supplies", True), ("Environmental fee", True), ("HAZMAT disposal", True), ("Fuel surcharge", True), ("Sales tax", True),
    ("R&R water pump", False), ("Replace turbo wastegate actuator", False), ("Air dryer cartridge", False), ("", False),
])
def test_fee_lines_are_recognised(text, fee):
    assert is_fee_line(text) is fee

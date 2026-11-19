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
])
def test_lookup(codes, text, code):
    hit = lookup(nd(text), codes)
    assert (hit.code if hit else None) == code

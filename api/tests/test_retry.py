import json

import pytest

from app.services.extraction.base import ExtractionError
from app.services.extraction.fake import FakeProvider

from .helpers import page_json, script


def test_valid_first_try():
    script(page_json())
    r = FakeProvider(retries=1).extract_page(b"x")
    assert r.attempts == 1 and r.page.header.invoice_number.value == "48211"


def test_malformed_json_retries_once_then_succeeds():
    script("{not json", page_json())
    r = FakeProvider(retries=1).extract_page(b"x")
    assert r.attempts == 2 and FakeProvider.extract_calls == 2 and len(r.raw_responses) == 2


def test_schema_violation_retries():
    bad = json.dumps({"header": {"vin": {"value": "x", "confidence": 7}}})  # confidence out of range
    script(bad, page_json())
    assert FakeProvider(retries=1).extract_page(b"x").attempts == 2


def test_gives_up_after_retries_with_clear_message_and_no_content_leak():
    secret = "SUPERSECRET-VIN-123"
    bad = json.dumps({"header": {"vin": {"value": secret, "confidence": 7}}})
    script(bad, bad)
    with pytest.raises(ExtractionError) as e:
        FakeProvider(retries=1).extract_page(b"x")
    assert secret not in str(e.value)
    assert "Retry the file" in str(e.value)
    assert FakeProvider.extract_calls == 2  # one retry only


def test_retries_are_configurable():
    script("bad", "bad", "bad", page_json())
    assert FakeProvider(retries=3).extract_page(b"x").attempts == 4


def test_classify_retry():
    FakeProvider.reset()
    FakeProvider.classify_scripted = ["oops", json.dumps({"items": [{"index": 0, "vmrs_code": "031-001-001", "confidence": 0.9}]})]
    out = FakeProvider(retries=1).classify(["alt"], "codes")
    assert out.attempts == 2 and out.items[0].vmrs_code == "031-001-001"

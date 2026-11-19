"""Offline provider for tests and the pipeline-plumbing eval. It does NOT read images.

Behaviour is injected: ``scripted`` is a queue of raw responses (use it to test retry logic) and
``responder`` is a callable ``(image_bytes) -> raw_json_text`` (the offline eval uses it to replay answer-key data
with injected noise). Results from this provider say nothing about real model accuracy.
"""

from __future__ import annotations

import hashlib
import json
from typing import Callable

from ...config import get_settings
from .base import ExtractionProvider, RawResponse, Usage
from .schema import PageExtraction


class FakeProvider(ExtractionProvider):
    name = "fake"
    model = "fake-1"
    scripted: list[str] = []
    classify_scripted: list[str] = []
    explain_scripted: list[str] = []
    explain_calls = 0
    explain_fail = False
    narrative_fail = False
    narrative_scripted: list[str] = []
    narrative_calls = 0
    last_payloads: dict = {}
    responder: Callable[[bytes], str] | None = None
    extract_calls = 0
    classify_calls = 0

    def __init__(self, retries: int = 1):
        self.retries = retries

    @classmethod
    def reset(cls) -> None:
        cls.scripted, cls.classify_scripted, cls.explain_scripted, cls.responder = [], [], [], None
        cls.extract_calls = cls.classify_calls = cls.explain_calls = 0
        cls.explain_fail = False
        cls.narrative_fail, cls.narrative_scripted, cls.narrative_calls = False, [], 0

    def _raw_extract(self, image: bytes, media_type: str, correction: str | None) -> RawResponse:
        type(self).extract_calls += 1
        if type(self).scripted:
            text = type(self).scripted.pop(0)
        elif type(self).responder:
            text = type(self).responder(image)
        elif get_settings().fake_provider_demo:
            text = _demo_page(image)
        else:
            text = PageExtraction(is_invoice=False).model_dump_json()
        return RawResponse(text, Usage(1500, 600, 5))

    def _raw_explain(self, evidence_json: str, correction: str | None) -> RawResponse:
        type(self).explain_calls += 1
        type(self).last_payloads["explain"] = evidence_json
        if type(self).explain_fail:
            raise RuntimeError("explain unavailable")
        if type(self).explain_scripted:
            return RawResponse(type(self).explain_scripted.pop(0), Usage(300, 100, 3))
        return RawResponse(_explain_default(evidence_json), Usage(300, 100, 3))

    def _raw_narrative(self, payload_json: str, correction: str | None) -> RawResponse:
        type(self).narrative_calls += 1
        type(self).last_payloads["narrative"] = payload_json
        if type(self).narrative_fail:
            raise RuntimeError("narrative unavailable")
        if type(self).narrative_scripted:
            return RawResponse(type(self).narrative_scripted.pop(0), Usage(500, 200, 3))
        items = [{"type": it["type"], "paragraph": it.get("template_paragraph", "These findings are possible savings.")} for it in json.loads(payload_json)]
        return RawResponse(json.dumps({"items": items}), Usage(500, 200, 3))

    def _raw_classify(self, descriptions: list[str], codes_text: str, correction: str | None) -> RawResponse:
        type(self).classify_calls += 1
        type(self).last_payloads["classify"] = list(descriptions)
        if type(self).classify_scripted:
            return RawResponse(type(self).classify_scripted.pop(0), Usage(400, 80, 3))
        items = [{"index": i, "vmrs_code": None, "confidence": 0.0} for i in range(len(descriptions))]
        return RawResponse(json.dumps({"items": items}), Usage(400, 80, 3))


def _demo_page(image: bytes) -> str:
    """Canned invoice for UI demos and the Playwright test (FAKE_PROVIDER_DEMO=true). One unreadable odometer."""
    h = hashlib.sha1(image).hexdigest()
    sc = lambda v, c=0.95: {"value": v, "confidence": c}
    return json.dumps({
        "is_invoice": True, "page_number": 1, "page_count": 1, "rotation_degrees": 0,
        "header": {"shop_name": sc("Demo Truck Repair"), "shop_address": sc("100 Demo Rd, Dallas, TX"), "invoice_number": sc("DEMO-" + h[:6].upper()),
                   "invoice_date": sc("03/14/2026"), "unit_number": sc("T-114"), "vin": sc("1M8GDM9AXKP042788"),
                   "odometer": sc("412880", 0.55), "subtotal": sc("580.00"), "tax": sc("0.00"), "total": sc("580.00")},
        "lines": [{"description": sc("R&R alternator"), "part_number": sc("ALT-8800"), "qty": sc(1), "parts_price": sc("350.00"),
                   "labour_hours": sc(2.0), "labour_rate": sc("115.00"), "line_total": sc("580.00")}],
    })


def _explain_default(evidence_json: str) -> str:
    """Offline explainer: echoes the rule's own template reason (hedged) and a flat score."""
    items = json.loads(evidence_json)
    return json.dumps({"items": [{"index": it["index"], "reason": it.get("template_reason", "Possible issue."), "ai_score": 0.8} for it in items]})

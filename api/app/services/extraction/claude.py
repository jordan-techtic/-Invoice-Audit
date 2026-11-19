"""Claude vision provider. Uses forced tool-use so output is structured JSON."""

from __future__ import annotations

import base64
import json
import time

from ...config import Settings
from .base import ExtractionError, ExtractionProvider, RawResponse, Usage
from ...prompts import load
from .schema import tool_input_schema

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "vmrs_code": {"type": ["string", "null"]},
                    "confidence": {"type": "number"},
                },
                "required": ["index", "vmrs_code", "confidence"],
            },
        }
    },
    "required": ["items"],
}


class ClaudeVisionProvider(ExtractionProvider):
    name = "claude"

    def __init__(self, settings: Settings):
        if not settings.ai_enabled:
            raise ExtractionError("AI extraction is turned off for this deployment (AI_ENABLED=false).")
        if settings.ai_zero_retention_required and not settings.ai_zdr_confirmed:
            raise ExtractionError(
                "Zero data retention isn't confirmed. Arrange it with Anthropic, then set AI_ZDR_CONFIRMED=true "
                "(or set AI_ZERO_RETENTION_REQUIRED=false for non-client test data)."
            )
        if not settings.anthropic_api_key:
            raise ExtractionError("ANTHROPIC_API_KEY is not set. Add it to .env and restart the worker.")
        import anthropic

        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=3)
        self.model = settings.claude_model
        self.retries = settings.extraction_retries

    def _call(self, system: list[dict], tool: dict, content: list[dict]) -> RawResponse:
        t0 = time.monotonic()
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=8000,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": content}],
        )
        block = next((b for b in msg.content if b.type == "tool_use"), None)
        text = json.dumps(block.input) if block else ""
        usage = Usage(msg.usage.input_tokens, msg.usage.output_tokens, int((time.monotonic() - t0) * 1000))
        return RawResponse(text, usage)

    def _raw_extract(self, image: bytes, media_type: str, correction: str | None) -> RawResponse:
        tool = {
            "name": "record_invoice_page",
            "description": "Record the fields visible on this invoice page.",
            "input_schema": tool_input_schema(),
        }
        content: list[dict] = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(image).decode()}},
            {"type": "text", "text": load("extraction_user") + (f"\n\n{correction}" if correction else "")},
        ]
        return self._call([{"type": "text", "text": load("extraction_system"), "cache_control": {"type": "ephemeral"}}], tool, content)

    def _raw_explain(self, evidence_json: str, correction: str | None) -> RawResponse:
        from .schema_explain import EXPLAIN_SCHEMA

        tool = {"name": "record_reasons", "description": "Record a reason and score per flag.", "input_schema": EXPLAIN_SCHEMA}
        content = [{"type": "text", "text": f"Flags:\n{evidence_json}" + (f"\n\n{correction}" if correction else "")}]
        return self._call([{"type": "text", "text": load("explain_system")}], tool, content)

    def _raw_narrative(self, payload_json: str, correction: str | None) -> RawResponse:
        from .schema_explain import NARRATIVE_SCHEMA

        tool = {"name": "record_paragraphs", "description": "Record one paragraph per flag type.", "input_schema": NARRATIVE_SCHEMA}
        content = [{"type": "text", "text": f"Findings by type:\n{payload_json}" + (f"\n\n{correction}" if correction else "")}]
        return self._call([{"type": "text", "text": load("narrative_system")}], tool, content)

    def _raw_classify(self, descriptions: list[str], codes_text: str, correction: str | None) -> RawResponse:
        tool = {"name": "record_codes", "description": "Record the VMRS code for each description.", "input_schema": CLASSIFY_SCHEMA}
        system = [
            {"type": "text", "text": load("classify_system")},
            {"type": "text", "text": "VMRS codes:\n" + codes_text, "cache_control": {"type": "ephemeral"}},
        ]
        listing = "\n".join(f"{i}: {d}" for i, d in enumerate(descriptions))
        content = [{"type": "text", "text": f"Descriptions:\n{listing}" + (f"\n\n{correction}" if correction else "")}]
        return self._call(system, tool, content)

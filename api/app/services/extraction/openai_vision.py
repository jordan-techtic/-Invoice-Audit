"""OpenAI vision provider. Uses JSON-schema structured output (strict) for extraction, classification and explanations."""

from __future__ import annotations

import base64
import time

from ...config import Settings
from ...prompts import load
from .base import ExtractionError, ExtractionProvider, RawResponse, Usage
from .claude import CLASSIFY_SCHEMA
from .schema import tool_input_schema
from .schema_explain import EXPLAIN_SCHEMA, NARRATIVE_SCHEMA

_DROP = {"default", "title", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength"}


def strictify(node):
    """Make a JSON schema acceptable to OpenAI strict mode: every property required, no extra properties,
    no unsupported validation keywords (our pydantic models still enforce ranges after the call)."""
    if isinstance(node, dict):
        out = {k: strictify(v) for k, v in node.items() if k not in _DROP}
        if out.get("type") == "object" or "properties" in out:
            props = out.get("properties", {})
            out["properties"] = props
            out["required"] = list(props)
            out["additionalProperties"] = False
        return out
    if isinstance(node, list):
        return [strictify(v) for v in node]
    return node


class OpenAIVisionProvider(ExtractionProvider):
    name = "openai"

    def __init__(self, settings: Settings):
        if not settings.ai_enabled:
            raise ExtractionError("AI extraction is turned off for this deployment (AI_ENABLED=false).")
        if settings.ai_zero_retention_required and not settings.ai_zdr_confirmed:
            raise ExtractionError(
                "Zero data retention isn't confirmed. Arrange it with OpenAI, then set AI_ZDR_CONFIRMED=true "
                "(or set AI_ZERO_RETENTION_REQUIRED=false for non-client test data)."
            )
        if not settings.openai_api_key:
            raise ExtractionError("OPENAI_API_KEY is not set. Add it to .env and restart the worker.")
        from openai import OpenAI

        self._client = OpenAI(api_key=settings.openai_api_key, max_retries=3)
        self.model = settings.openai_model
        self.retries = settings.extraction_retries
        self._page_schema = strictify(tool_input_schema())

    def _call(self, system: str, user_content: list[dict], schema_name: str, schema: dict) -> RawResponse:
        t0 = time.monotonic()
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_content}],
            response_format={"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
            temperature=0,
        )
        text = resp.choices[0].message.content or ""
        u = resp.usage
        return RawResponse(text, Usage(u.prompt_tokens, u.completion_tokens, int((time.monotonic() - t0) * 1000)))

    def _raw_extract(self, image: bytes, media_type: str, correction: str | None) -> RawResponse:
        b64 = base64.b64encode(image).decode()
        content = [
            {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64}", "detail": "high"}},
            {"type": "text", "text": load("extraction_user") + (f"\n\n{correction}" if correction else "")},
        ]
        return self._call(load("extraction_system"), content, "invoice_page", self._page_schema)

    def _raw_classify(self, descriptions: list[str], codes_text: str, correction: str | None) -> RawResponse:
        listing = "\n".join(f"{i}: {d}" for i, d in enumerate(descriptions))
        system = load("classify_system") + "\n\nVMRS codes:\n" + codes_text
        content = [{"type": "text", "text": f"Descriptions:\n{listing}" + (f"\n\n{correction}" if correction else "")}]
        return self._call(system, content, "vmrs_codes", strictify(CLASSIFY_SCHEMA))

    def _raw_explain(self, evidence_json: str, correction: str | None) -> RawResponse:
        content = [{"type": "text", "text": f"Flags:\n{evidence_json}" + (f"\n\n{correction}" if correction else "")}]
        return self._call(load("explain_system"), content, "flag_reasons", strictify(EXPLAIN_SCHEMA))

    def _raw_narrative(self, payload_json: str, correction: str | None) -> RawResponse:
        content = [{"type": "text", "text": f"Findings by type:\n{payload_json}" + (f"\n\n{correction}" if correction else "")}]
        return self._call(load("narrative_system"), content, "report_paragraphs", strictify(NARRATIVE_SCHEMA))

import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.extraction.base import ExtractionError
from app.services.extraction.openai_vision import OpenAIVisionProvider, strictify
from app.services.extraction.schema import tool_input_schema

from .helpers import page_json


def _settings(**kw):
    return Settings(env="local", openai_api_key="sk-test-not-real", ai_zdr_confirmed=True, **kw)


def test_strict_schema_requires_every_property_and_forbids_extras():
    def walk(n):
        if isinstance(n, dict):
            if "properties" in n:
                assert n["additionalProperties"] is False and set(n["required"]) == set(n["properties"])
            assert "default" not in n and "minimum" not in n and "$ref" not in n
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(strictify(tool_input_schema()))


def test_refuses_without_key_or_zdr_confirmation():
    with pytest.raises(ExtractionError, match="OPENAI_API_KEY"):
        OpenAIVisionProvider(Settings(env="local", openai_api_key=None, ai_zdr_confirmed=True))
    with pytest.raises(ExtractionError, match="Zero data retention"):
        OpenAIVisionProvider(Settings(env="local", openai_api_key="sk-x", ai_zdr_confirmed=False))


def test_extract_sends_image_and_json_schema_and_parses(monkeypatch):
    p = OpenAIVisionProvider(_settings(openai_model="gpt-test"))
    seen = {}

    def create(**kw):
        seen.update(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=page_json(inv="OAI-1")))],
                               usage=SimpleNamespace(prompt_tokens=1200, completion_tokens=400))

    p._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    r = p.extract_page(b"\xff\xd8fake")
    assert r.page.header.invoice_number.value == "OAI-1" and (r.usage.input_tokens, r.usage.output_tokens) == (1200, 400)
    assert seen["model"] == "gpt-test" and seen["response_format"]["type"] == "json_schema" and seen["response_format"]["json_schema"]["strict"] is True
    assert seen["messages"][1]["content"][0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_provider_setting_selects_provider():
    from app.services.extraction import get_provider
    from app.services.extraction.fake import FakeProvider

    assert isinstance(get_provider(Settings(env="local", ai_provider="fake")), FakeProvider)
    with pytest.raises(ExtractionError, match="Unknown AI_PROVIDER"):
        get_provider(Settings(env="local", ai_provider="nope"))
    assert Settings.model_fields["ai_provider"].default == "openai"  # the default provider (tests override it via env)


def test_api_key_never_appears_in_error_messages():
    with pytest.raises(ExtractionError) as e:
        OpenAIVisionProvider(Settings(env="local", openai_api_key="sk-secret-123", ai_zdr_confirmed=False))
    assert "sk-secret-123" not in str(e.value)

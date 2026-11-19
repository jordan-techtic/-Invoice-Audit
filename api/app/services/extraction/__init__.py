from ...config import Settings, get_settings
from .base import ExtractionError, ExtractionProvider


def get_provider(settings: Settings | None = None) -> ExtractionProvider:
    p = _make(settings or get_settings())
    p.redact = (settings or get_settings()).ai_redact_before_send
    return p


def _make(settings: Settings) -> ExtractionProvider:
    """One provider setting (AI_PROVIDER) drives extraction, VMRS classification and flag explanations."""
    s = settings
    if s.ai_provider == "openai":
        from .openai_vision import OpenAIVisionProvider

        return OpenAIVisionProvider(s)
    if s.ai_provider == "claude":
        from .claude import ClaudeVisionProvider

        return ClaudeVisionProvider(s)
    if s.ai_provider in ("fake", "oracle"):
        from .fake import FakeProvider

        return FakeProvider(retries=s.extraction_retries)
    raise ExtractionError(f"Unknown AI_PROVIDER '{s.ai_provider}'. Use openai or claude.")


__all__ = ["ExtractionProvider", "ExtractionError", "get_provider"]

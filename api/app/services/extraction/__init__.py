from ...config import Settings, get_settings
from .base import ExtractionError, ExtractionProvider


def get_provider(settings: Settings | None = None) -> ExtractionProvider:
    s = settings or get_settings()
    if s.extraction_provider == "claude":
        from .claude import ClaudeVisionProvider

        return ClaudeVisionProvider(s)
    if s.extraction_provider in ("fake", "oracle"):
        from .fake import FakeProvider

        return FakeProvider(retries=s.extraction_retries)
    raise ExtractionError(f"Unknown EXTRACTION_PROVIDER '{s.extraction_provider}'. Use claude.")


__all__ = ["ExtractionProvider", "ExtractionError", "get_provider"]

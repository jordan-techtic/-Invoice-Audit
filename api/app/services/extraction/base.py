"""ExtractionProvider interface plus the shared validate-and-retry loop.

A provider only implements ``_raw_extract`` / ``_raw_classify`` (one model call each).
Parsing, schema validation and the retry-with-error-message loop live here so every
provider (Claude, Textract adapter, Azure adapter, test fakes) behaves the same.

Privacy: error messages built here include field locations and rule names only,
never the values the model returned (those are invoice contents).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from .schema import PageExtraction


class ExtractionError(Exception):
    """Raised when a page still can't be parsed after retries. Message is safe to show to users."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.duration_ms += other.duration_ms


@dataclass
class RawResponse:
    text: str
    usage: Usage = field(default_factory=Usage)


@dataclass
class PageResult:
    page: PageExtraction
    raw_responses: list[str]
    usage: Usage
    attempts: int


class LineClass(BaseModel):
    index: int
    vmrs_code: str | None = None
    confidence: float = 0.0


class ClassifyResult(BaseModel):
    items: list[LineClass]


@dataclass
class ClassifyOutcome:
    items: list[LineClass]
    raw_responses: list[str]
    usage: Usage
    attempts: int


def safe_error_summary(exc: Exception) -> str:
    """Describe a parse failure without echoing any model output."""
    if isinstance(exc, ValidationError):
        parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['type']}" for e in exc.errors()[:8]]
        return "schema errors at " + "; ".join(parts)
    if isinstance(exc, json.JSONDecodeError):
        return f"not valid JSON (at position {exc.pos})"
    return type(exc).__name__


class ExtractionProvider(ABC):
    name: str = "base"
    model: str = "n/a"
    retries: int = 1

    @abstractmethod
    def _raw_extract(self, image: bytes, media_type: str, correction: str | None) -> RawResponse: ...

    @abstractmethod
    def _raw_classify(self, descriptions: list[str], codes_text: str, correction: str | None) -> RawResponse: ...

    def extract_page(self, image: bytes, media_type: str = "image/jpeg") -> PageResult:
        correction: str | None = None
        usage, raws = Usage(), []
        last = "unknown"
        for attempt in range(1, self.retries + 2):
            resp = self._raw_extract(image, media_type, correction)
            usage.add(resp.usage)
            raws.append(resp.text)
            try:
                page = PageExtraction.model_validate(json.loads(resp.text))
                return PageResult(page, raws, usage, attempt)
            except (json.JSONDecodeError, ValidationError) as e:
                last = safe_error_summary(e)
                correction = (
                    f"Your previous answer was rejected: {last}. "
                    "Return only the structured result that matches the schema exactly."
                )
        raise ExtractionError(
            f"The AI returned an answer we couldn't read after {self.retries + 1} tries ({last}). "
            "Retry the file; if it fails again, check that the image is legible."
        )

    def classify(self, descriptions: list[str], codes_text: str) -> ClassifyOutcome:
        correction: str | None = None
        usage, raws = Usage(), []
        last = "unknown"
        for attempt in range(1, self.retries + 2):
            resp = self._raw_classify(descriptions, codes_text, correction)
            usage.add(resp.usage)
            raws.append(resp.text)
            try:
                res = ClassifyResult.model_validate(json.loads(resp.text))
                return ClassifyOutcome(res.items, raws, usage, attempt)
            except (json.JSONDecodeError, ValidationError) as e:
                last = safe_error_summary(e)
                correction = f"Your previous answer was rejected: {last}. Return only the structured result."
        raise ExtractionError(f"Job-code classification failed after {self.retries + 1} tries ({last}).")

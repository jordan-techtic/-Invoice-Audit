"""AI explanation and scoring of flags the rules already found. The AI never creates or removes flags."""

from __future__ import annotations

import hashlib
import json
import re

from ..prompts import PROMPT_VERSION
from .types import FlagDraft

BANNED = re.compile(r"\b(fraud\w*|steal\w*|stole\w*|theft|scam\w*|proof|proves?|proven|guilty|cheat\w*|definitely|certainly|for sure)\b", re.I)
HEDGE = re.compile(r"\b(likely|possible|possibly|may)\b", re.I)


def evidence_hash(d: FlagDraft) -> str:
    blob = json.dumps({"v": PROMPT_VERSION, "t": d.type, "e": d.evidence, "i": float(d.impact)}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def sanitize(reason: str | None, template: str) -> str:
    """Keep the AI's wording only if it is hedged, free of accusation words, and at most 2 sentences."""
    if not reason:
        return template
    text = " ".join(reason.split())
    sentences = re.split(r"(?<=[.!?])\s+", text)
    text = " ".join(sentences[:2]).strip()
    if not text or BANNED.search(text) or not HEDGE.search(text) or len(text) > 400:
        return template
    return text


def clamp_score(x) -> float | None:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return None

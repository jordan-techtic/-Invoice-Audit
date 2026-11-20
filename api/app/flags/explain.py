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


_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")


def numbers_in(obj) -> list[float]:
    """Every number found in a nested evidence structure (the figures the AI is allowed to quote)."""
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out += numbers_in(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out += numbers_in(v)
    return out


def allowed_numbers(d: FlagDraft) -> list[float]:
    return numbers_in(d.evidence) + [float(d.impact)]


def figures_match(text: str, allowed: list[float]) -> bool:
    """Every dollar figure in ``text`` is one of the allowed numbers (exactly, or rounded to the dollar)."""
    for m in _MONEY.finditer(text):
        x = float(m.group(1).replace(",", ""))
        if not any(abs(x - a) <= 0.011 or abs(x - round(a)) <= 0.011 or abs(round(x) - round(a)) < 0.5 and abs(x - a) <= 1.0 for a in allowed):
            return False
    return True


def sanitize(reason: str | None, template: str, allowed: list[float] | None = None) -> str:
    """Keep the AI's wording only if it is hedged, free of accusation words, at most 2 sentences, and (when ``allowed`` is given)
    quotes no dollar figure that is not in the evidence."""
    if not reason:
        return template
    text = " ".join(reason.split())
    sentences = re.split(r"(?<=[.!?])\s+", text)
    text = " ".join(sentences[:2]).strip()
    if not text or BANNED.search(text) or not HEDGE.search(text) or len(text) > 400:
        return template
    if allowed is not None and not figures_match(text, allowed):
        return template
    return text


def clamp_score(x) -> float | None:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return None

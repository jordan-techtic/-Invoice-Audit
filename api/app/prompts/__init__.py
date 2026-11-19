"""All model prompts live in this folder as .txt files so they are easy to tune. Edit the text, no code change."""

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent
PROMPT_VERSION = "p3-1"  # bump when prompts change meaningfully; part of the explanation cache key


@lru_cache
def load(name: str) -> str:
    return (_DIR / f"{name}.txt").read_text().strip()

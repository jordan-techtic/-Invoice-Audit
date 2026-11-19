"""Tiny wrapper over RQ. In inline mode (tests, offline eval) jobs run synchronously in-process."""

from __future__ import annotations

import importlib
from functools import lru_cache

from redis import Redis
from rq import Queue

from .config import get_settings


@lru_cache
def _redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


def enqueue(queue_name: str, dotted_func: str, *args) -> None:
    if get_settings().queue_inline:
        mod, fn = dotted_func.rsplit(".", 1)
        getattr(importlib.import_module(mod), fn)(*args)
        return
    Queue(queue_name, connection=_redis()).enqueue(dotted_func, *args, job_timeout=900)

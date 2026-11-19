"""RQ job entrypoints. Workers import this module: ``rq worker extraction``."""

from .services.pipeline import process_upload  # noqa: F401

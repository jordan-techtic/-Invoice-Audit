"""Scrub secrets from every log line, whatever logged them."""

import logging

from .config import get_settings


class SecretScrubber(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        s = get_settings()
        secrets = [v for v in (s.openai_api_key, s.anthropic_api_key, s.jwt_secret, s.data_encryption_key, s.s3_secret_key, s.inbound_email_secret) if v]
        if secrets:
            msg = record.getMessage()
            for sec in secrets:
                msg = msg.replace(sec, "***")
            record.msg, record.args = msg, ()
        return True


def install() -> None:
    f = SecretScrubber()
    for h in logging.getLogger().handlers:
        h.addFilter(f)
    logging.getLogger().addFilter(f)

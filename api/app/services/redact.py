"""Optional masking of VINs and phone numbers in TEXT sent to the AI provider (AI_REDACT_BEFORE_SEND=true).

Page images are sent as they are: masking pixels would need OCR first, which is out of scope for this prototype.
"""

import re

VIN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)")


def redact_text(s: str) -> str:
    return PHONE.sub("[phone]", VIN.sub("[VIN]", s))

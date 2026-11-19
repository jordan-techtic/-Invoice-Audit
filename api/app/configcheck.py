"""List what is and isn't configured for a real deployment.   python -m app.configcheck [--strict]"""

import sys

from .config import get_settings

DEFAULT_JWT = ("change-me", "local-dev")


def checks() -> list[tuple[str, bool, str, bool]]:
    """(name, ok, how to fix, critical)"""
    s = get_settings()
    key_ok = bool(s.openai_api_key if s.ai_provider == "openai" else s.anthropic_api_key if s.ai_provider == "claude" else True)
    return [
        ("AI provider key present", key_ok, "Set OPENAI_API_KEY (or ANTHROPIC_API_KEY when AI_PROVIDER=claude)", True),
        ("AI zero-retention confirmed", s.ai_zdr_confirmed, "Arrange zero retention with the provider, then set AI_ZDR_CONFIRMED=true", True),
        ("ENV is production", s.env != "local", "Set ENV=production", True),
        ("JWT secret set", not s.jwt_secret.startswith(DEFAULT_JWT), "Set JWT_SECRET to a long random value", True),
        ("Data encryption key set", s.env != "local" or s.data_encryption_key != "", "Set DATA_ENCRYPTION_KEY (Fernet key)", True),
        ("Session cookie is Secure", s.cookie_secure, "Set COOKIE_SECURE=true (needs HTTPS)", True),
        ("Public URL uses HTTPS", s.public_base_url.startswith("https://"), "Set PUBLIC_BASE_URL to the https:// address", True),
        ("Object storage encrypted (SSE)", bool(s.s3_sse), "Set S3_SSE=AES256 (or aws:kms) and enable bucket default encryption", True),
        ("Object storage is AWS S3 in a US region", s.s3_endpoint_url in (None, "") and s.s3_region.startswith("us-"), "Unset S3_ENDPOINT_URL and use a us-* region", True),
        ("Inbound email secret changed", s.inbound_email_secret != "local-inbound-secret", "Set INBOUND_EMAIL_SECRET", True),
        ("Storage credentials changed", s.s3_secret_key != "minioadmin", "Use real S3 credentials", True),
        ("Redact VIN/phone before sending to AI", s.ai_redact_before_send, "Optional: AI_REDACT_BEFORE_SEND=true", False),
    ]


def main() -> int:
    bad = 0
    for name, ok, fix, critical in checks():
        print(f"[{'ok' if ok else 'NOT SET' if critical else 'off'}] {name}" + ("" if ok else f"  ->  {fix}"))
        bad += (not ok) and critical
    print(f"\n{bad} required item(s) not set." if bad else "\nAll required items are set.")
    return 1 if (bad and "--strict" in sys.argv) else 0


if __name__ == "__main__":
    sys.exit(main())

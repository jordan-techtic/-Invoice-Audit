from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "local"
    database_url: str = "postgresql+psycopg://audit:audit@localhost:5433/audit"
    redis_url: str = "redis://localhost:6380/0"

    # Auth
    jwt_secret: str = "change-me-in-production-please-32b"
    jwt_ttl_minutes: int = 60 * 10
    cookie_secure: bool = False

    # Encryption key for raw model responses and other sensitive blobs (Fernet, base64 32 bytes)
    data_encryption_key: str = ""  # dev only; set DATA_ENCRYPTION_KEY in prod

    # Object storage: s3 (MinIO/AWS) or postgres (blobs in stored_objects — no MinIO)
    storage_backend: str = "s3"  # s3 | postgres
    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_bucket: str = "invoice-audit"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_sse: str | None = None  # "AES256" or "aws:kms" in production

    # AI
    anthropic_api_key: str | None = None
    ai_provider: str = "openai"  # openai | claude | fake | oracle
    fake_provider_demo: bool = False  # fake provider returns canned invoice data (local/Playwright)
    claude_model: str = "claude-sonnet-5-5"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    # Zero-retention: when true we only send data to the AI API under a ZDR agreement
    # and never to any other third party. Set false to disable all AI calls.
    ai_enabled: bool = True
    ai_zero_retention_required: bool = True

    # Zero-retention must be agreed with Anthropic at the org level; this flag records that we confirmed it.
    # With ai_zero_retention_required=true the Claude provider refuses to run until it is set.
    ai_zdr_confirmed: bool = False
    confidence_threshold: float = 0.80
    extraction_retries: int = 1  # retries after the first malformed response
    ai_redact_before_send: bool = False  # mask VINs and phone numbers in TEXT sent to the AI (page images can't be masked)
    login_max_attempts: int = 5
    login_window_seconds: int = 900
    max_upload_mb: int = 25
    max_pdf_pages: int = 100
    queue_inline: bool = False  # tests and the offline eval run jobs synchronously
    # Price per million tokens, used only to estimate cost per invoice (defaults are gpt-4o list prices: verify them).
    price_input_per_mtok: float = 2.5
    price_output_per_mtok: float = 10.0

    # Inbound email webhook shared secret
    inbound_email_secret: str = "local-inbound-secret"

    # Data retention
    raw_file_retention_days: int = 90

    public_base_url: str = "http://localhost:3000"

    @model_validator(mode="after")
    def _dev_defaults(self) -> "Settings":
        if not self.data_encryption_key:
            if self.env != "local":
                raise ValueError("DATA_ENCRYPTION_KEY must be set outside local development.")
            self.data_encryption_key = "Y-WE8i1So3msDGEgcZ78ryHuXPCJ5GnkcqRaWZkgCxA="  # dev only
        if self.env != "local" and self.jwt_secret.startswith(("change-me", "local-dev")):
            raise ValueError("JWT_SECRET must be set outside local development.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

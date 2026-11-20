"""ORM models. Every table except users and vmrs_codes carries client_id."""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, ClientScoped, IdMixin, utcnow

Money = Numeric(12, 2)


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


class Role(str, enum.Enum):
    admin = "admin"
    analyst = "analyst"


class UploadStatus(str, enum.Enum):
    queued = "queued"
    reading = "reading"
    needs_review = "needs_review"
    done = "done"
    failed = "failed"
    duplicate = "duplicate"


class UploadSource(str, enum.Enum):
    web = "web"
    email = "email"


class ReviewStatus(str, enum.Enum):
    needs_review = "needs_review"
    ready = "ready"
    reviewed = "reviewed"


class FlagType(str, enum.Enum):
    labour_over_benchmark = "labour_over_benchmark"
    repeat_repair = "repeat_repair"
    warranty_eligible = "warranty_eligible"
    parts_price_outlier = "parts_price_outlier"
    duplicate = "duplicate"
    math_error = "math_error"


class FlagStatus(str, enum.Enum):
    open = "open"
    accepted = "accepted"
    dismissed = "dismissed"
    edited = "edited"


class Severity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


DEFAULT_CLIENT_SETTINGS: dict = {
    # extraction
    "confidence_threshold": 0.80,
    "math_tolerance": 1.00,
    # flag rules
    "labour_over_benchmark_pct": 20,
    "labour_min_samples": 5,
    "repeat_repair_days": 90,
    "repeat_repair_miles": 10000,
    "repeat_condition": "or",     # "or": days OR miles is enough; "and": must be within days AND miles (trailers: days only)
    "duplicate_window_days": 0,   # 0: a duplicate invoice must have the same date; N: same shop, unit and total within N days
    "repeat_exclude_codes": [  # routine, recurring work: not a "repeat repair"
        "045-001-001", "045-001-008", "044-001-002", "041-001-001", "043-001-001",
        "001-001-005", "017-001-004", "017-001-005", "071-001-003", "042-001-006",
        "000-001-001", "000-001-002", "045-001-009",   # annual DOT inspection, trailer preventive maintenance, PM-B service
    ],
    "parts_outlier_pct": 25,
    "parts_single_shop_multiple": 1.5,
    "parts_min_samples": 3,
    "severity_high_dollars": 500,
    "severity_medium_dollars": 150,
}


# ---------------------------------------------------------------- tenancy / staff


class Client(IdMixin, Base):
    __tablename__ = "clients"
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    inbound_email_token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, default=lambda: dict(DEFAULT_CLIENT_SETTINGS), nullable=False)
    service_offer_text: Mapped[str | None] = mapped_column(Text)
    audit_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_files_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # A client "is" its own scope, so expose client_id for uniform handling.
    @property
    def client_id(self) -> uuid.UUID:
        return self.id


class User(IdMixin, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(_enum(Role, "role"), nullable=False, default=Role.analyst)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class UserClient(Base):
    """Which analysts may work on which client. Admins can access every client.

    Not ClientScoped on purpose: it is the access-control table read *before* a
    client is bound to the session.
    """

    __tablename__ = "user_clients"
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True
    )


# ---------------------------------------------------------------- ingestion


class Upload(IdMixin, ClientScoped, Base):
    __tablename__ = "uploads"
    # Not unique: exact duplicates get their own "skipped" row so the user can see what was dropped.
    __table_args__ = (Index("ix_upload_client_hash", "client_id", "sha256"),)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[UploadSource] = mapped_column(_enum(UploadSource, "upload_source"), nullable=False)
    status: Mapped[UploadStatus] = mapped_column(
        _enum(UploadStatus, "upload_status"), nullable=False, default=UploadStatus.queued
    )
    status_detail: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    invoice_count: Mapped[int | None] = mapped_column(Integer)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("uploads.id"))
    raw_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExtractionRun(IdMixin, ClientScoped, Base):
    """One AI call. Raw response is stored encrypted for audit; never logged."""

    __tablename__ = "extraction_runs"
    upload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("uploads.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(String(50), nullable=False, default="extraction")
    attempts: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 5), default=0, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw_response_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    ok: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class VmrsCache(IdMixin, ClientScoped, Base):
    """Classification cache keyed by normalised description, to avoid paying twice for the same text."""

    __tablename__ = "vmrs_cache"
    __table_args__ = (UniqueConstraint("client_id", "norm_description", name="uq_vmrs_cache"),)
    norm_description: Mapped[str] = mapped_column(String(300), nullable=False)
    vmrs_code: Mapped[str | None] = mapped_column(String(11))
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)


class Shop(IdMixin, ClientScoped, Base):
    __tablename__ = "shops"
    __table_args__ = (UniqueConstraint("client_id", "normalized_name", name="uq_shop_client_name"),)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)


class Vehicle(IdMixin, ClientScoped, Base):
    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("client_id", "unit_number", name="uq_vehicle_client_unit"),)
    unit_number: Mapped[str] = mapped_column(String(50), nullable=False)
    vin: Mapped[str | None] = mapped_column(String(17))
    # Fleet master data (imported from a vehicles CSV in Settings). The rules use the class (per-class labour baselines,
    # trailers repeat on days only) and the VIN (to find the unit when an invoice prints only the VIN).
    vehicle_class: Mapped[str | None] = mapped_column(String(30))
    year: Mapped[int | None] = mapped_column(Integer)
    make: Mapped[str | None] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(80))
    start_odometer: Mapped[int | None] = mapped_column(Integer)


class Invoice(IdMixin, ClientScoped, Base):
    __tablename__ = "invoices"
    shop_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("shops.id"), index=True)
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("vehicles.id"), index=True)
    source_upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("uploads.id", ondelete="SET NULL"), index=True
    )
    page_start: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    shop_name_raw: Mapped[str | None] = mapped_column(String(200))
    shop_address: Mapped[str | None] = mapped_column(String(300))
    invoice_number: Mapped[str | None] = mapped_column(String(80), index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    unit_number: Mapped[str | None] = mapped_column(String(50))
    vin: Mapped[str | None] = mapped_column(String(17))
    odometer: Mapped[int | None] = mapped_column(Integer)
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    tax: Mapped[Decimal | None] = mapped_column(Money)
    total: Mapped[Decimal | None] = mapped_column(Money)
    review_status: Mapped[ReviewStatus] = mapped_column(
        _enum(ReviewStatus, "review_status"), nullable=False, default=ReviewStatus.needs_review
    )

    shop: Mapped[Shop | None] = relationship()
    vehicle: Mapped[Vehicle | None] = relationship()
    lines: Mapped[list[InvoiceLine]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceLine.line_no"
    )


class InvoiceLine(IdMixin, ClientScoped, Base):
    __tablename__ = "invoice_lines"
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    part_number: Mapped[str | None] = mapped_column(String(80), index=True)
    qty: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    parts_price: Mapped[Decimal | None] = mapped_column(Money)  # unit price
    labour_hours: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    labour_rate: Mapped[Decimal | None] = mapped_column(Money)
    line_total: Mapped[Decimal | None] = mapped_column(Money)
    vmrs_code: Mapped[str | None] = mapped_column(String(11), index=True)
    vmrs_confidence: Mapped[float | None] = mapped_column(Float)
    vmrs_source: Mapped[str | None] = mapped_column(String(20))  # lookup | ai | analyst
    page_no: Mapped[int | None] = mapped_column(Integer)  # page of the upload this line is on
    y_center: Mapped[float | None] = mapped_column(Float)  # model's estimate of the line's vertical position, 0 (top) to 1 (bottom)

    invoice: Mapped[Invoice] = relationship(back_populates="lines")


class FieldConfidence(IdMixin, ClientScoped, Base):
    __tablename__ = "field_confidence"
    __table_args__ = (UniqueConstraint("record_type", "record_id", "field", name="uq_field_conf"),)
    record_type: Mapped[str] = mapped_column(String(20), nullable=False)  # invoice | line
    record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(50), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(String(300))  # plain-language reason shown to the analyst
    corrected_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---------------------------------------------------------------- reference data


class VmrsCode(Base):
    """Global lookup (not client data)."""

    __tablename__ = "vmrs_codes"
    code: Mapped[str] = mapped_column(String(11), primary_key=True)  # e.g. 031-002-001
    system: Mapped[str] = mapped_column(String(100), nullable=False)
    component: Mapped[str] = mapped_column(String(200), nullable=False)
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="")


class LabourBenchmark(IdMixin, ClientScoped, Base):
    __tablename__ = "reference_labour_benchmarks"
    # One value per job code, vehicle class (blank = every vehicle) and source.
    __table_args__ = (Index("uq_bench", "client_id", "vmrs_code", text("coalesce(vehicle_class, '')"), "source", unique=True),)
    vmrs_code: Mapped[str] = mapped_column(String(11), nullable=False)
    vehicle_class: Mapped[str | None] = mapped_column(String(30))
    benchmark_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    sample_count: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(50), nullable=False)  # client_median (computed) | licensed:<name> | manual


class WarrantyRule(IdMixin, ClientScoped, Base):
    __tablename__ = "warranty_rules"
    __table_args__ = (UniqueConstraint("client_id", "vmrs_code", name="uq_warranty"),)
    vmrs_code: Mapped[str] = mapped_column(String(11), nullable=False)
    component: Mapped[str] = mapped_column(String(200), nullable=False)
    months: Mapped[int] = mapped_column(Integer, nullable=False)
    miles: Mapped[int | None] = mapped_column(Integer)
    covers: Mapped[str] = mapped_column(String(12), nullable=False, default="parts+labour", server_default="parts+labour")  # parts | parts+labour


class PartsPriceBaseline(IdMixin, ClientScoped, Base):
    __tablename__ = "parts_price_baseline"
    __table_args__ = (UniqueConstraint("client_id", "part_number", name="uq_parts_baseline"),)
    part_number: Mapped[str] = mapped_column(String(80), nullable=False)
    median_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    shop_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------- findings


class Flag(IdMixin, ClientScoped, Base):
    __tablename__ = "flags"
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), index=True
    )
    line_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoice_lines.id", ondelete="CASCADE"), index=True
    )
    related_invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="SET NULL")
    )
    type: Mapped[FlagType] = mapped_column(_enum(FlagType, "flag_type"), nullable=False, index=True)
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "severity"), nullable=False)
    estimated_dollar_impact: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0)
    plain_english_reason: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ai_score: Mapped[float | None] = mapped_column(Float)
    dismiss_reason: Mapped[str | None] = mapped_column(String(30))  # wrong_extraction|valid_reason|not_real_issue|other
    original_impact: Mapped[Decimal | None] = mapped_column(Money)  # set the first time an analyst edits the amount
    original_reason: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False, index=True)  # same finding => same key across runs
    evidence_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[FlagStatus] = mapped_column(
        _enum(FlagStatus, "flag_status"), nullable=False, default=FlagStatus.open, index=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analyst_note: Mapped[str | None] = mapped_column(Text)

    invoice: Mapped[Invoice] = relationship(foreign_keys=[invoice_id])
    line: Mapped[InvoiceLine | None] = relationship()


class FlagRun(IdMixin, ClientScoped, Base):
    """One run of reference data + rules + AI explanations. Its id is the 'job id' the API returns."""

    __tablename__ = "flag_runs"
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")  # queued|running|done|failed
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 5), nullable=False, default=0)


class FlagExplanationCache(IdMixin, ClientScoped, Base):
    __tablename__ = "flag_explanation_cache"
    __table_args__ = (UniqueConstraint("client_id", "evidence_hash", name="uq_flag_expl"),)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    ai_score: Mapped[float | None] = mapped_column(Float)


class Report(IdMixin, ClientScoped, Base):
    __tablename__ = "reports"
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    generated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500))
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # frozen content: later edits never change a report
    recoverable: Mapped[Decimal] = mapped_column(Money, nullable=False, default=0)
    flag_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    share_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    share_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # so an admin can copy the link again; the DB never holds it in clear
    share_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StoredObject(Base):
    """Raw files and derived page images when STORAGE_BACKEND=postgres (local dev, no object store needed)."""

    __tablename__ = "stored_objects"
    key: Mapped[str] = mapped_column(String(500), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="application/octet-stream")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditLog(IdMixin, Base):
    """Who viewed, edited or exported what. client_id is null for staff-level events (e.g. login)."""

    __tablename__ = "audit_log"
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # view | edit | export | delete | login
    object_type: Mapped[str] = mapped_column(String(50), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))

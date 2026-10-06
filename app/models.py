from datetime import datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


JSON_DOCUMENT = JSON().with_variant(JSONB, "postgresql")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="viewer", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    cohort_year: Mapped[int | None] = mapped_column(Integer, index=True)
    age_at_diagnosis: Mapped[int | None] = mapped_column(Integer, index=True)
    sex: Mapped[str | None] = mapped_column(String(16), index=True)
    diagnosis_date: Mapped[datetime | None] = mapped_column(Date, index=True)
    primary_site: Mapped[str | None] = mapped_column(String(128), index=True)
    ajcc_stage: Mapped[str | None] = mapped_column(String(16), index=True)
    survival_status: Mapped[str | None] = mapped_column(String(16), index=True)
    record_data: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    source_version: Mapped[str] = mapped_column(String(32), default="v0.1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    entity_type: Mapped[str] = mapped_column(String(32), default="patient")
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    before_data: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    after_data: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    remote_addr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class ReleaseSnapshot(Base):
    """Append-only manifest for a recoverable full-database backup."""
    __tablename__ = "release_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(128), index=True)
    reason: Mapped[str] = mapped_column(Text)
    storage_path: Mapped[str] = mapped_column(Text)
    storage_sha256: Mapped[str] = mapped_column(String(64))
    dataset_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    patient_count: Mapped[int] = mapped_column(Integer)
    audit_log_count: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

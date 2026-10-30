from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.infrastructure.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid4())


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    seller_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="uploading_documents")
    stage_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SourceDocument(Base):
    __tablename__ = "source_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    seller_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("extraction_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_format: Mapped[str] = mapped_column(String(16), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class NormalizedSource(Base):
    __tablename__ = "normalized_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("extraction_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    seller_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    original_reference: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extraction_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class CompanyIntelligenceRecord(Base):
    __tablename__ = "company_intelligence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("extraction_jobs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    seller_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    body: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ProfileSuggestion(Base):
    __tablename__ = "profile_suggestions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    seller_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("extraction_jobs.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    body: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

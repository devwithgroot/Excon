from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.infrastructure.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid4())


class Seller(Base):
    __tablename__ = "sellers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    approved_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    approved_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    runs: Mapped[list["ResearchRun"]] = relationship(back_populates="seller")


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    runs: Mapped[list["ResearchRun"]] = relationship(back_populates="lead")


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    seller_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sellers.id", ondelete="SET NULL"), nullable=True
    )
    lead_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    collected: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    missing: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tools_used: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    gap_decisions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    targeted_attempts: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    seller_profile: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    seller: Mapped[Seller | None] = relationship(back_populates="runs")
    lead: Mapped[Lead] = relationship(back_populates="runs")
    evidence_items: Mapped[list["EvidenceItemRecord"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class EvidenceItemRecord(Base):
    __tablename__ = "evidence_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    field_key: Mapped[str] = mapped_column(String(128), nullable=False)
    extracted_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    method: Mapped[str] = mapped_column(String(64), nullable=False, default="provider")
    freshness: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    run: Mapped[ResearchRun] = relationship(back_populates="evidence_items")


class SellerProfileVersion(Base):
    __tablename__ = "seller_profile_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    seller_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sellers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class LeadReportRecord(Base):
    __tablename__ = "lead_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    seller_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sellers.id", ondelete="SET NULL"), nullable=True
    )
    seller_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scores: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    body: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    recommendation: Mapped[str] = mapped_column(String(32), nullable=False, default="consider")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class OutreachDraftRecord(Base):
    __tablename__ = "outreach_drafts"
    __table_args__ = (
        UniqueConstraint("run_id", "person_evidence_id", name="uq_outreach_drafts_run_person"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("research_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seller_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sellers.id", ondelete="SET NULL"), nullable=True
    )
    person_evidence_id: Mapped[str] = mapped_column(String(36), nullable=False)
    person_name: Mapped[str] = mapped_column(String(255), nullable=False)
    person_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    person_linkedin_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    offering: Mapped[str | None] = mapped_column(Text, nullable=True)
    offering_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    relevance: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cited_facts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    linkedin_connect: Mapped[str] = mapped_column(Text, nullable=False, default="")
    linkedin_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    whatsapp: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    body: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class OutreachDraftVersion(Base):
    __tablename__ = "outreach_draft_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    draft_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("outreach_drafts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

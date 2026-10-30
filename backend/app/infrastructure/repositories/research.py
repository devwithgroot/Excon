from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.collected_research import CollectedResearch
from app.domain.evidence import EvidenceItem
from app.domain.outreach import OutreachDraft
from app.domain.report import LeadReportBody
from app.domain.seller_profile import SellerProfile
from app.infrastructure.models.research import (
    EvidenceItemRecord,
    Lead,
    LeadReportRecord,
    OutreachDraftRecord,
    OutreachDraftVersion,
    ResearchRun,
    Seller,
    SellerProfileVersion,
)


class ResearchStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_seller(
        self,
        *,
        company_name: str,
        name: str | None = None,
        website_url: str | None = None,
    ) -> Seller:
        seller = Seller(company_name=company_name, name=name, website_url=website_url, profile={})
        self.session.add(seller)
        self.session.flush()
        return seller

    def create_lead(
        self,
        *,
        company_name: str,
        domain: str | None = None,
        website_url: str | None = None,
    ) -> Lead:
        lead = Lead(company_name=company_name, domain=domain, website_url=website_url)
        self.session.add(lead)
        self.session.flush()
        return lead

    def create_run(
        self,
        *,
        lead: Lead,
        seller: Seller | None = None,
        collected: dict | None = None,
    ) -> ResearchRun:
        run = ResearchRun(
            seller_id=seller.id if seller else None,
            lead_id=lead.id,
            status="running",
            collected=collected or CollectedResearch().model_dump(mode="json"),
            missing=CollectedResearch().missing_parameters(),
            tools_used=[],
            gap_decisions=[],
            targeted_attempts={},
            seller_profile=(seller.approved_profile or seller.profile) if seller else None,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def get_seller(self, seller_id: str) -> Seller | None:
        return self.session.get(Seller, seller_id)

    def save_seller_draft(self, seller: Seller, profile: SellerProfile) -> Seller:
        dumped = profile.model_dump(mode="json")
        dumped["status"] = "draft"
        dumped["version"] = seller.approved_version or 0
        seller.profile = dumped
        if not seller.approved_profile:
            seller.status = "draft"
        seller.updated_at = datetime.now(timezone.utc)
        self.session.flush()
        return seller

    def approve_seller(self, seller: Seller, profile: SellerProfile) -> Seller:
        version = (seller.approved_version or 0) + 1
        dumped = profile.model_dump(mode="json")
        dumped["status"] = "approved"
        dumped["version"] = version
        seller.profile = dumped
        seller.approved_profile = dumped
        seller.approved_version = version
        seller.status = "approved"
        seller.updated_at = datetime.now(timezone.utc)
        self.session.add(
            SellerProfileVersion(
                seller_id=seller.id,
                version=version,
                profile=dumped,
            )
        )
        self.session.flush()
        return seller

    def list_seller_versions(self, seller_id: str) -> list[SellerProfileVersion]:
        return list(
            self.session.scalars(
                select(SellerProfileVersion)
                .where(SellerProfileVersion.seller_id == seller_id)
                .order_by(SellerProfileVersion.version)
            )
        )

    def persist_run(
        self,
        run_id: str,
        *,
        status: str,
        collected: CollectedResearch,
        tools_used: list[str],
        gap_decisions: list[dict],
        targeted_attempts: dict,
        seller_profile: dict | None,
        error: str | None = None,
    ) -> ResearchRun | None:
        run = self.session.get(ResearchRun, run_id)
        if run is None:
            return None
        run.status = status
        run.collected = collected.model_dump(mode="json")
        run.missing = collected.missing_parameters()
        run.tools_used = tools_used
        run.gap_decisions = gap_decisions
        run.targeted_attempts = targeted_attempts
        run.seller_profile = seller_profile
        run.error = error
        run.updated_at = datetime.now(timezone.utc)
        self._replace_evidence(run, collected.evidence)
        self.session.flush()
        return run

    def get_run(self, run_id: str) -> ResearchRun | None:
        return self.session.get(ResearchRun, run_id)

    def save_report(self, report: LeadReportBody) -> LeadReportRecord:
        existing = self.session.scalar(
            select(LeadReportRecord).where(LeadReportRecord.run_id == report.run_id)
        )
        body = report.model_dump(mode="json")
        if existing is None:
            row = LeadReportRecord(
                id=report.report_id,
                run_id=report.run_id,
                seller_id=report.seller_id,
                seller_version=report.seller_version,
                scores=report.scores.model_dump(mode="json"),
                body=body,
                recommendation=report.scores.recommendation,
            )
            self.session.add(row)
            self.session.flush()
            return row
        existing.seller_id = report.seller_id
        existing.seller_version = report.seller_version
        existing.scores = report.scores.model_dump(mode="json")
        existing.body = body
        existing.recommendation = report.scores.recommendation
        self.session.flush()
        return existing

    def get_report_for_run(self, run_id: str) -> LeadReportRecord | None:
        return self.session.scalar(select(LeadReportRecord).where(LeadReportRecord.run_id == run_id))

    def get_report(self, report_id: str) -> LeadReportRecord | None:
        return self.session.get(LeadReportRecord, report_id)

    def list_drafts_for_run(self, run_id: str) -> list[OutreachDraftRecord]:
        return list(
            self.session.scalars(
                select(OutreachDraftRecord)
                .where(OutreachDraftRecord.run_id == run_id)
                .order_by(OutreachDraftRecord.created_at)
            )
        )

    def get_draft(self, draft_id: str) -> OutreachDraftRecord | None:
        return self.session.get(OutreachDraftRecord, draft_id)

    def upsert_draft(self, draft: OutreachDraft) -> OutreachDraftRecord:
        existing = self.session.scalar(
            select(OutreachDraftRecord).where(
                OutreachDraftRecord.run_id == draft.run_id,
                OutreachDraftRecord.person_evidence_id == draft.person_evidence_id,
            )
        )
        body = draft.model_dump(mode="json")
        if existing is None:
            row = OutreachDraftRecord(
                id=draft.draft_id,
                run_id=draft.run_id,
                seller_id=draft.seller_id,
                person_evidence_id=draft.person_evidence_id,
                person_name=draft.person_name,
                person_title=draft.person_title,
                person_linkedin_url=draft.person_linkedin_url,
                offering=draft.offering,
                offering_reason=draft.offering_reason,
                relevance=draft.relevance,
                cited_facts=draft.cited_facts,
                linkedin_connect=draft.linkedin_connect,
                linkedin_message=draft.linkedin_message,
                whatsapp=draft.whatsapp,
                status=draft.status,
                version=draft.version,
                body=body,
            )
            self.session.add(row)
            self.session.flush()
            return row
        if existing.status == "approved":
            return existing
        self._archive_draft(existing)
        existing.seller_id = draft.seller_id
        existing.person_name = draft.person_name
        existing.person_title = draft.person_title
        existing.person_linkedin_url = draft.person_linkedin_url
        existing.offering = draft.offering
        existing.offering_reason = draft.offering_reason
        existing.relevance = draft.relevance
        existing.cited_facts = draft.cited_facts
        existing.linkedin_connect = draft.linkedin_connect
        existing.linkedin_message = draft.linkedin_message
        existing.whatsapp = draft.whatsapp
        existing.status = "draft"
        existing.version = (existing.version or 1) + 1
        existing.body = body
        existing.updated_at = datetime.now(timezone.utc)
        self.session.flush()
        return existing

    def save_draft_edit(self, row: OutreachDraftRecord, draft: OutreachDraft) -> OutreachDraftRecord:
        self._archive_draft(row)
        row.linkedin_connect = draft.linkedin_connect
        row.linkedin_message = draft.linkedin_message
        row.whatsapp = draft.whatsapp
        row.status = "draft"
        row.version = (row.version or 1) + 1
        row.updated_at = datetime.now(timezone.utc)
        dumped = draft.model_dump(mode="json")
        dumped["status"] = row.status
        dumped["version"] = row.version
        dumped["draft_id"] = row.id
        row.body = dumped
        self.session.flush()
        return row

    def set_draft_status(self, row: OutreachDraftRecord, status: str) -> OutreachDraftRecord:
        row.status = status
        row.updated_at = datetime.now(timezone.utc)
        body = dict(row.body or {})
        body["status"] = status
        row.body = body
        self.session.flush()
        return row

    def _archive_draft(self, row: OutreachDraftRecord) -> None:
        self.session.add(
            OutreachDraftVersion(
                draft_id=row.id,
                version=row.version or 1,
                body=dict(row.body or {}),
            )
        )

    def _replace_evidence(self, run: ResearchRun, items: list[EvidenceItem]) -> None:
        run.evidence_items.clear()
        self.session.flush()
        for item in items:
            run.evidence_items.append(
                EvidenceItemRecord(
                    id=item.evidence_id or str(uuid4()),
                    run_id=run.id,
                    field_key=item.field_key,
                    extracted_value=item.extracted_value,
                    source_url=item.source_url,
                    source_type=item.source_type.value
                    if hasattr(item.source_type, "value")
                    else str(item.source_type),
                    published_at=item.source_published_at,
                    retrieved_at=item.retrieved_at,
                    excerpt=item.supporting_excerpt,
                    method=item.extraction_method,
                    freshness=item.freshness.value
                    if hasattr(item.freshness, "value")
                    else str(item.freshness),
                    confidence=item.confidence,
                )
            )

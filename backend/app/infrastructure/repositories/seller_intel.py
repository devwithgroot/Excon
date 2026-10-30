from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.application.seller_intel.document_models import ParsedDocument, Source
from app.domain.company_intelligence import CompanyIntelligence, ProspectSuggestion
from app.infrastructure.models.seller_intel import (
    CompanyIntelligenceRecord,
    ExtractionJob,
    NormalizedSource,
    ProfileSuggestion,
    SourceDocument,
)

ACTIVE_STATUSES = ("queued", "running")


class SellerIntelStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_job(self, seller_id: str) -> ExtractionJob:
        job = ExtractionJob(seller_id=seller_id, status="queued", stage="uploading_documents", warnings=[], summary={})
        self.session.add(job)
        self.session.flush()
        return job

    def get_job(self, job_id: str) -> ExtractionJob | None:
        return self.session.get(ExtractionJob, job_id)

    def latest_job(self, seller_id: str) -> ExtractionJob | None:
        return self.session.scalar(
            select(ExtractionJob).where(ExtractionJob.seller_id == seller_id).order_by(ExtractionJob.created_at.desc())
        )

    def set_stage(self, job_id: str, *, stage: str, index: int, detail: str | None = None, status: str = "running") -> None:
        job = self.session.get(ExtractionJob, job_id)
        if job is None:
            return
        job.status = status
        job.stage = stage
        job.stage_index = index
        job.detail = detail
        self.session.flush()

    def finish_job(
        self,
        job_id: str,
        *,
        status: str,
        error: str | None = None,
        warnings: list[str] | None = None,
        summary: dict | None = None,
    ) -> None:
        job = self.session.get(ExtractionJob, job_id)
        if job is None:
            return
        job.status = status
        job.error = error
        job.warnings = list(warnings or [])
        job.summary = dict(summary or {})
        job.finished_at = datetime.now(timezone.utc)
        if status in {"succeeded", "partial"}:
            job.stage = "ready_for_review"
        self.session.flush()

    def fail_interrupted_jobs(self) -> int:
        result = self.session.execute(
            update(ExtractionJob)
            .where(ExtractionJob.status.in_(ACTIVE_STATUSES))
            .values(
                status="failed",
                error="interrupted: the API restarted while this job was running. Start the extraction again.",
                finished_at=datetime.now(timezone.utc),
            )
        )
        return result.rowcount or 0

    def add_document(
        self,
        *,
        document_id: str,
        seller_id: str,
        job_id: str,
        filename: str,
        original_format: str,
        mime_type: str | None,
        size_bytes: int,
        storage_path: str | None,
        sha256: str | None,
        parse_status: str = "pending",
        parse_error: str | None = None,
    ) -> SourceDocument:
        row = SourceDocument(
            id=document_id,
            seller_id=seller_id,
            job_id=job_id,
            filename=filename,
            original_format=original_format,
            mime_type=mime_type,
            size_bytes=size_bytes,
            storage_path=storage_path,
            sha256=sha256,
            parse_status=parse_status,
            parse_error=parse_error,
        )
        self.session.add(row)
        self.session.flush()
        return row

    def documents_for_job(self, job_id: str) -> list[SourceDocument]:
        return list(
            self.session.scalars(
                select(SourceDocument).where(SourceDocument.job_id == job_id).order_by(SourceDocument.created_at)
            )
        )

    def record_parse(self, document: ParsedDocument) -> None:
        row = self.session.get(SourceDocument, document.document_id)
        if row is None:
            return
        row.parse_status = document.status.value
        row.parse_error = document.error
        row.page_count = document.page_count
        self.session.flush()

    def save_sources(self, *, job_id: str, seller_id: str, sources: list[Source]) -> None:
        for source in sources:
            self.session.merge(
                NormalizedSource(
                    id=source.source_id,
                    job_id=job_id,
                    seller_id=seller_id,
                    source_type=source.source_type.value,
                    source_name=source.source_name[:500],
                    source_url=source.source_url,
                    original_reference=source.original_content_reference,
                    markdown=source.normalized_markdown,
                    extraction_status=source.extraction_status,
                    error=source.error,
                )
            )
        self.session.flush()

    def save_intelligence(self, *, job_id: str, seller_id: str, intelligence: CompanyIntelligence) -> None:
        self.session.add(
            CompanyIntelligenceRecord(job_id=job_id, seller_id=seller_id, body=intelligence.model_dump(mode="json"))
        )
        self.session.flush()

    def save_suggestions(self, *, job_id: str, seller_id: str, suggestions: list[ProspectSuggestion]) -> None:
        for suggestion in suggestions:
            self.session.add(
                ProfileSuggestion(
                    id=suggestion.suggestion_id,
                    seller_id=seller_id,
                    job_id=job_id,
                    status=suggestion.status,
                    body=suggestion.model_dump(mode="json"),
                )
            )
        self.session.flush()

    def set_suggestion_status(self, suggestion_id: str, status: str) -> None:
        row = self.session.get(ProfileSuggestion, suggestion_id)
        if row is None:
            return
        row.status = status
        row.body = {**(row.body or {}), "status": status}
        self.session.flush()

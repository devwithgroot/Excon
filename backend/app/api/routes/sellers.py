from datetime import datetime
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.application.seller_intel import pipeline
from app.application.seller_intel.document_parser import DocumentRejected, validate_upload
from app.application.seller_intel.profile_builder import domain_from_url, minimal_profile
from app.application.seller_intel.profile_validator import check_profile, completeness
from app.config import get_settings
from app.domain.seller_profile import FieldTrace, SellerProfile
from app.infrastructure.database import get_db, get_session_factory
from app.infrastructure.repositories.research import ResearchStore
from app.infrastructure.repositories.seller_intel import SellerIntelStore
from app.infrastructure.uploads import save_upload

router = APIRouter(tags=["sellers"])

USER_FIELDS = (
    "company_name",
    "contact_name",
    "website_url",
    "industry",
    "sub_industry",
    "description",
    "business_model",
    "market_positioning",
    "geography",
    "company_size",
    "products",
    "services",
    "features",
    "value_proposition",
    "problems_solved",
    "differentiators",
    "limitations",
    "customer_segments",
    "industries_served",
    "use_cases",
    "icp",
)


class SellerCreateRequest(BaseModel):
    name: str | None = None
    company_name: str
    website_url: str | None = None
    profile: SellerProfile | None = None


class SellerDraftPatch(BaseModel):
    profile: SellerProfile


class DocumentStatus(BaseModel):
    document_id: str
    filename: str
    format: str
    size_bytes: int
    status: str
    error: str | None = None
    page_count: int | None = None


class JobResponse(BaseModel):
    job_id: str
    seller_id: str
    status: str
    stage: str
    stage_label: str
    stage_index: int
    stage_total: int = len(pipeline.STAGES)
    stages: list[str] = Field(default_factory=lambda: list(pipeline.STAGES))
    detail: str | None = None
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)
    documents: list[DocumentStatus] = Field(default_factory=list)
    created_at: datetime | None = None
    finished_at: datetime | None = None


class SellerResponse(BaseModel):
    seller_id: str
    status: str
    approved_version: int
    draft: SellerProfile
    approved: SellerProfile | None = None
    job: JobResponse | None = None


class ExtractionStatusResponse(JobResponse):
    seller: SellerResponse | None = None


def seller_llm():
    return pipeline.default_llm()


def seller_search():
    return pipeline.default_search()


def _profile(raw: dict | None, fallback_name: str) -> SellerProfile:
    if raw:
        return SellerProfile.model_validate(raw)
    return SellerProfile(company_name=fallback_name)


def _job_response(intel: SellerIntelStore, job) -> JobResponse:
    return JobResponse(
        job_id=job.id,
        seller_id=job.seller_id,
        status=job.status,
        stage=job.stage,
        stage_label=pipeline.STAGE_LABELS.get(job.stage, job.stage),
        stage_index=job.stage_index,
        detail=job.detail,
        error=job.error,
        warnings=list(job.warnings or []),
        summary=dict(job.summary or {}),
        documents=[
            DocumentStatus(
                document_id=row.id,
                filename=row.filename,
                format=row.original_format,
                size_bytes=row.size_bytes,
                status=row.parse_status,
                error=row.parse_error,
                page_count=row.page_count,
            )
            for row in intel.documents_for_job(job.id)
        ],
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


def _response(seller, db: Session | None = None) -> SellerResponse:
    draft = _profile(seller.profile, seller.company_name)
    approved = SellerProfile.model_validate(seller.approved_profile) if seller.approved_profile else None
    job = None
    if db is not None:
        intel = SellerIntelStore(db)
        latest = intel.latest_job(seller.id)
        job = _job_response(intel, latest) if latest else None
    return SellerResponse(
        seller_id=seller.id,
        status=seller.status,
        approved_version=seller.approved_version or 0,
        draft=draft,
        approved=approved,
        job=job,
    )


def _require_seller(store: ResearchStore, seller_id: str):
    seller = store.get_seller(seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="Seller not found")
    return seller


def _clean_website(website_url: str) -> str:
    url = website_url.strip()
    if url and "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or "." not in (parsed.hostname or ""):
        raise HTTPException(status_code=400, detail="Enter a valid company website, for example https://example.com")
    return url.rstrip("/")


@router.post("/sellers/extract", response_model=JobResponse, status_code=202)
async def extract_seller(
    background: BackgroundTasks,
    name: str = Form(...),
    company_name: str = Form(...),
    website_url: str = Form(...),
    files: list[UploadFile] | None = File(None),
) -> JobResponse:
    """Accepts the onboarding form and starts a background extraction job; poll GET /sellers/extract/{job_id}."""
    settings = get_settings()
    name, company_name = name.strip(), company_name.strip()
    if not name or not company_name:
        raise HTTPException(status_code=400, detail="Name and company name are required")
    website = _clean_website(website_url)
    files = files or []
    if len(files) > settings.upload_max_files:
        raise HTTPException(status_code=400, detail=f"At most {settings.upload_max_files} files can be uploaded")

    uploads: list[tuple[str, bytes, str | None]] = []
    for upload in files:
        data = await upload.read(settings.upload_max_bytes + 1)
        uploads.append((upload.filename or "upload", data, upload.content_type))

    db = get_session_factory()()
    try:
        research, intel = ResearchStore(db), SellerIntelStore(db)
        seller = research.create_seller(company_name=company_name, name=name, website_url=website)
        draft = minimal_profile({"name": name, "company_name": company_name, "website_url": website}, seller_id=seller.id)
        research.save_seller_draft(seller, draft)
        job = intel.create_job(seller.id)
        for filename, data, mime_type in uploads:
            document_id = uuid4().hex
            try:
                fmt = validate_upload(filename, len(data), max_bytes=settings.upload_max_bytes)
            except DocumentRejected as exc:
                intel.add_document(
                    document_id=document_id,
                    seller_id=seller.id,
                    job_id=job.id,
                    filename=filename[:255],
                    original_format=(filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown")[:16],
                    mime_type=mime_type,
                    size_bytes=len(data),
                    storage_path=None,
                    sha256=None,
                    parse_status=exc.status.value,
                    parse_error=str(exc),
                )
                continue
            path, digest = save_upload(seller.id, document_id, filename, data)
            intel.add_document(
                document_id=document_id,
                seller_id=seller.id,
                job_id=job.id,
                filename=filename[:255],
                original_format=fmt,
                mime_type=mime_type,
                size_bytes=len(data),
                storage_path=path,
                sha256=digest,
            )
        intel.set_stage(job.id, stage="uploading_documents", index=0, detail=f"{len(uploads)} file(s) received", status="queued")
        db.commit()
        response = _job_response(intel, job)
    finally:
        db.close()

    background.add_task(
        pipeline.run_extraction_job,
        response.job_id,
        session_factory=get_session_factory(),
        mlx=seller_llm(),
        search=seller_search(),
    )
    return response


@router.get("/sellers/extract/{job_id}", response_model=ExtractionStatusResponse)
def extraction_status(job_id: str, db: Session = Depends(get_db)) -> ExtractionStatusResponse:
    intel = SellerIntelStore(db)
    job = intel.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Extraction job not found")
    body = _job_response(intel, job).model_dump()
    seller = None
    if job.status in {"succeeded", "partial", "failed"}:
        record = ResearchStore(db).get_seller(job.seller_id)
        seller = _response(record) if record else None
    return ExtractionStatusResponse(**body, seller=seller)


@router.post("/sellers", response_model=SellerResponse)
def create_seller(body: SellerCreateRequest, db: Session = Depends(get_db)) -> SellerResponse:
    """Manual onboarding without extraction."""
    store = ResearchStore(db)
    website = _clean_website(body.website_url) if body.website_url else None
    seller = store.create_seller(company_name=body.company_name, name=body.name, website_url=website)
    identity = {"name": body.name, "company_name": body.company_name, "website_url": website}
    profile = body.profile or minimal_profile(identity)
    profile = profile.model_copy(
        update={
            "seller_id": seller.id,
            "website_url": profile.website_url or website,
            "domain": profile.domain or domain_from_url(website),
        }
    )
    store.save_seller_draft(seller, profile)
    db.commit()
    db.refresh(seller)
    return _response(seller, db)


@router.get("/sellers/{seller_id}", response_model=SellerResponse)
def get_seller(seller_id: str, db: Session = Depends(get_db)) -> SellerResponse:
    return _response(_require_seller(ResearchStore(db), seller_id), db)


@router.get("/sellers/{seller_id}/draft", response_model=SellerResponse)
def get_seller_draft(seller_id: str, db: Session = Depends(get_db)) -> SellerResponse:
    return _response(_require_seller(ResearchStore(db), seller_id), db)


def _merge_edit(existing: SellerProfile, incoming: SellerProfile) -> SellerProfile:
    """User edits replace content fields; provenance stays server-owned and edited fields are flagged."""
    before, after = existing.model_dump(mode="json"), incoming.model_dump(mode="json")
    traces = {key: trace.model_copy() for key, trace in existing.traces.items()}
    for field in USER_FIELDS:
        if before.get(field) != after.get(field):
            trace = traces.get(field) or FieldTrace(support="explicit")
            traces[field] = trace.model_copy(update={"edited": True})
    merged = existing.model_copy(
        update={
            **{field: getattr(incoming, field) for field in USER_FIELDS},
            "domain": incoming.domain or domain_from_url(incoming.website_url) or existing.domain,
            "traces": traces,
            "suggested_prospect_characteristics": _keep_suggestion_ids(existing, incoming),
        }
    )
    merged = SellerProfile.model_validate(merged.model_dump(mode="json"))
    merged, issues = check_profile(merged)
    merged.extraction_metadata.validation = issues
    merged.extraction_metadata.completeness = completeness(merged)
    return merged


def _keep_suggestion_ids(existing: SellerProfile, incoming: SellerProfile):
    statuses = {item.suggestion_id: item.status for item in incoming.suggested_prospect_characteristics}
    return [
        item.model_copy(update={"status": statuses.get(item.suggestion_id, item.status)})
        for item in existing.suggested_prospect_characteristics
    ]


@router.patch("/sellers/{seller_id}/draft", response_model=SellerResponse)
def patch_seller_draft(seller_id: str, body: SellerDraftPatch, db: Session = Depends(get_db)) -> SellerResponse:
    store = ResearchStore(db)
    seller = _require_seller(store, seller_id)
    existing = _profile(seller.profile, seller.company_name)
    store.save_seller_draft(seller, _merge_edit(existing, body.profile))
    db.commit()
    db.refresh(seller)
    return _response(seller, db)


def _set_suggestion(seller_id: str, suggestion_id: str, status: str, db: Session) -> SellerResponse:
    store = ResearchStore(db)
    seller = _require_seller(store, seller_id)
    draft = _profile(seller.profile, seller.company_name)
    if not any(item.suggestion_id == suggestion_id for item in draft.suggested_prospect_characteristics):
        raise HTTPException(status_code=404, detail="Suggestion not found")
    draft.suggested_prospect_characteristics = [
        item.model_copy(update={"status": status}) if item.suggestion_id == suggestion_id else item
        for item in draft.suggested_prospect_characteristics
    ]
    store.save_seller_draft(seller, draft)
    SellerIntelStore(db).set_suggestion_status(suggestion_id, status)
    db.commit()
    db.refresh(seller)
    return _response(seller, db)


@router.post("/sellers/{seller_id}/suggestions/{suggestion_id}/accept", response_model=SellerResponse)
def accept_suggestion(seller_id: str, suggestion_id: str, db: Session = Depends(get_db)) -> SellerResponse:
    return _set_suggestion(seller_id, suggestion_id, "accepted", db)


@router.post("/sellers/{seller_id}/suggestions/{suggestion_id}/reject", response_model=SellerResponse)
def reject_suggestion(seller_id: str, suggestion_id: str, db: Session = Depends(get_db)) -> SellerResponse:
    return _set_suggestion(seller_id, suggestion_id, "rejected", db)


@router.post("/sellers/{seller_id}/approve", response_model=SellerResponse)
def approve_seller(seller_id: str, db: Session = Depends(get_db)) -> SellerResponse:
    store = ResearchStore(db)
    seller = _require_seller(store, seller_id)
    latest = SellerIntelStore(db).latest_job(seller_id)
    if latest is not None and latest.status in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Extraction is still running; wait for it to finish")
    draft = _profile(seller.profile, seller.company_name)
    if not draft.company_name.strip():
        raise HTTPException(status_code=400, detail="Company name is required before approval")
    if not (draft.products or draft.services):
        raise HTTPException(status_code=400, detail="Add at least one product or service before approval")
    store.approve_seller(seller, draft)
    db.commit()
    db.refresh(seller)
    return _response(seller, db)

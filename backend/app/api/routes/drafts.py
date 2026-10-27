from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.domain.collected_research import CollectedResearch
from app.domain.outreach import OutreachBatch, OutreachDraft
from app.domain.report import LeadReportBody
from app.domain.seller_profile import SellerProfile
from app.graphs.outreach import run_outreach
from app.infrastructure.database import get_db, get_session_factory
from app.infrastructure.repositories.research import ResearchStore

router = APIRouter(tags=["drafts"])


class DraftPatch(BaseModel):
    linkedin_connect: str
    linkedin_message: str
    whatsapp: str


def _seller_for_run(store: ResearchStore, run) -> tuple[SellerProfile | None, str | None, str | None]:
    contact = None
    if run.seller_id:
        seller = store.get_seller(run.seller_id)
        if seller:
            contact = seller.name
            if seller.approved_profile:
                profile = SellerProfile.model_validate(seller.approved_profile)
                return profile, seller.id, contact or profile.contact_name
            if seller.profile:
                profile = SellerProfile.model_validate(seller.profile)
                return profile, seller.id, contact or profile.contact_name
    if run.seller_profile:
        profile = SellerProfile.model_validate(run.seller_profile)
        return profile, run.seller_id, contact or profile.contact_name
    return None, run.seller_id, contact


def _draft_from_row(row) -> OutreachDraft:
    payload = dict(row.body or {})
    payload.update(
        {
            "draft_id": row.id,
            "run_id": row.run_id,
            "seller_id": row.seller_id,
            "person_evidence_id": row.person_evidence_id,
            "person_name": row.person_name,
            "person_title": row.person_title,
            "person_linkedin_url": row.person_linkedin_url,
            "offering": row.offering,
            "offering_reason": row.offering_reason,
            "relevance": row.relevance,
            "cited_facts": row.cited_facts or [],
            "linkedin_connect": row.linkedin_connect,
            "linkedin_message": row.linkedin_message,
            "whatsapp": row.whatsapp,
            "status": row.status,
            "version": row.version,
        }
    )
    return OutreachDraft.model_validate(payload)


def _batch(run_id: str, store: ResearchStore, status: str = "ready") -> OutreachBatch:
    rows = store.list_drafts_for_run(run_id)
    return OutreachBatch(
        run_id=run_id,
        status=status if rows else "empty",
        drafts=[_draft_from_row(row) for row in rows],
    )


@router.post("/research/runs/{run_id}/drafts", response_model=OutreachBatch)
async def create_run_drafts(run_id: str, db: Session = Depends(get_db)) -> OutreachBatch:
    store = ResearchStore(db)
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    collected = CollectedResearch.model_validate(run.collected or {})
    seller, seller_id, contact = _seller_for_run(store, run)
    report_row = store.get_report_for_run(run_id)
    report = LeadReportBody.model_validate(report_row.body) if report_row else None
    lead_name = run.lead.company_name if run.lead else collected.company.name.value
    batch = await run_outreach(
        run_id=run.id,
        collected=collected,
        seller=seller,
        seller_id=seller_id,
        report=report,
        contact_name=contact,
        lead_name=lead_name,
        session_factory=get_session_factory(),
    )
    return batch


@router.get("/research/runs/{run_id}/drafts", response_model=OutreachBatch)
def list_run_drafts(run_id: str, db: Session = Depends(get_db)) -> OutreachBatch:
    store = ResearchStore(db)
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    return _batch(run_id, store)


@router.get("/drafts/{draft_id}", response_model=OutreachDraft)
def get_draft(draft_id: str, db: Session = Depends(get_db)) -> OutreachDraft:
    row = ResearchStore(db).get_draft(draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return _draft_from_row(row)


@router.patch("/drafts/{draft_id}", response_model=OutreachDraft)
def patch_draft(draft_id: str, body: DraftPatch, db: Session = Depends(get_db)) -> OutreachDraft:
    store = ResearchStore(db)
    row = store.get_draft(draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    current = _draft_from_row(row)
    updated = current.model_copy(
        update={
            "linkedin_connect": body.linkedin_connect,
            "linkedin_message": body.linkedin_message,
            "whatsapp": body.whatsapp,
        }
    )
    row = store.save_draft_edit(row, updated)
    db.commit()
    return _draft_from_row(row)


@router.post("/drafts/{draft_id}/approve", response_model=OutreachDraft)
def approve_draft(draft_id: str, db: Session = Depends(get_db)) -> OutreachDraft:
    store = ResearchStore(db)
    row = store.get_draft(draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    if not (row.linkedin_connect or "").strip() or not (row.whatsapp or "").strip():
        raise HTTPException(status_code=400, detail="Draft is empty")
    row = store.set_draft_status(row, "approved")
    db.commit()
    return _draft_from_row(row)


@router.post("/drafts/{draft_id}/reject", response_model=OutreachDraft)
def reject_draft(draft_id: str, db: Session = Depends(get_db)) -> OutreachDraft:
    store = ResearchStore(db)
    row = store.get_draft(draft_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    row = store.set_draft_status(row, "rejected")
    db.commit()
    return _draft_from_row(row)

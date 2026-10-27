import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.application.seller_extract import extract_seller_profile, seller_profile_from_patch
from app.domain.seller_profile import SellerProfile
from app.domain.tool_contract import DocumentInput
from app.infrastructure.database import get_db, get_session_factory
from app.infrastructure.repositories.research import ResearchStore

router = APIRouter(tags=["sellers"])


class SellerExtractRequest(BaseModel):
    name: str | None = None
    company_name: str
    website_url: str | None = None
    company_domain: str | None = None
    documents: list[DocumentInput] = Field(default_factory=list)


class SellerCreateRequest(BaseModel):
    name: str | None = None
    company_name: str
    website_url: str | None = None
    profile: SellerProfile | None = None


class SellerDraftPatch(BaseModel):
    profile: SellerProfile


class SellerResponse(BaseModel):
    seller_id: str
    status: str
    approved_version: int
    draft: SellerProfile
    approved: SellerProfile | None = None


def _prefer_existing(existing: SellerProfile, extracted: SellerProfile) -> SellerProfile:
    """Keep fields the user already typed; fill only blanks from extraction."""
    current = existing.model_dump()
    incoming = extracted.model_dump()
    for key, value in current.items():
        if key == "icp":
            icp = dict(incoming.get("icp") or {})
            for icp_key, icp_value in (value or {}).items():
                if icp_value:
                    icp[icp_key] = icp_value
            incoming["icp"] = icp
        elif value:
            incoming[key] = value
    return SellerProfile.model_validate(incoming)


def _profile(raw: dict | None, fallback_name: str) -> SellerProfile:
    if raw:
        return SellerProfile.model_validate(raw)
    return SellerProfile(company_name=fallback_name)


def _response(seller) -> SellerResponse:
    draft = _profile(seller.profile, seller.company_name)
    approved = SellerProfile.model_validate(seller.approved_profile) if seller.approved_profile else None
    return SellerResponse(
        seller_id=seller.id,
        status=seller.status,
        approved_version=seller.approved_version or 0,
        draft=draft,
        approved=approved,
    )


@router.post("/sellers/extract", response_model=SellerResponse)
async def extract_seller(body: SellerExtractRequest) -> SellerResponse:
    try:
        profile = await asyncio.wait_for(
            extract_seller_profile(body.model_dump(), mlx=None),
            timeout=10,
        )
    except TimeoutError:
        profile = seller_profile_from_patch(body.model_dump())

    def persist() -> SellerResponse:
        db = get_session_factory()()
        try:
            store = ResearchStore(db)
            seller = store.upsert_seller(
                company_name=body.company_name,
                name=body.name,
                website_url=body.website_url,
            )
            merged = _prefer_existing(_profile(seller.profile, seller.company_name), profile)
            store.save_seller_draft(seller, merged)
            db.commit()
            db.refresh(seller)
            return _response(seller)
        finally:
            db.close()

    return await asyncio.to_thread(persist)


@router.post("/sellers", response_model=SellerResponse)
def create_seller(body: SellerCreateRequest, db: Session = Depends(get_db)) -> SellerResponse:
    store = ResearchStore(db)
    seller = store.upsert_seller(
        company_name=body.company_name,
        name=body.name,
        website_url=body.website_url,
    )
    profile = body.profile or seller_profile_from_patch(body.model_dump())
    store.save_seller_draft(seller, profile)
    db.commit()
    db.refresh(seller)
    return _response(seller)


@router.get("/sellers/{seller_id}", response_model=SellerResponse)
def get_seller(seller_id: str, db: Session = Depends(get_db)) -> SellerResponse:
    seller = ResearchStore(db).get_seller(seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="Seller not found")
    return _response(seller)


@router.patch("/sellers/{seller_id}/draft", response_model=SellerResponse)
def patch_seller_draft(
    seller_id: str,
    body: SellerDraftPatch,
    db: Session = Depends(get_db),
) -> SellerResponse:
    store = ResearchStore(db)
    seller = store.get_seller(seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="Seller not found")
    store.save_seller_draft(seller, body.profile)
    db.commit()
    db.refresh(seller)
    return _response(seller)


@router.post("/sellers/{seller_id}/approve", response_model=SellerResponse)
def approve_seller(seller_id: str, db: Session = Depends(get_db)) -> SellerResponse:
    store = ResearchStore(db)
    seller = store.get_seller(seller_id)
    if seller is None:
        raise HTTPException(status_code=404, detail="Seller not found")
    draft = _profile(seller.profile, seller.company_name)
    if not draft.company_name.strip():
        raise HTTPException(status_code=400, detail="Company name is required before approval")
    store.approve_seller(seller, draft)
    db.commit()
    db.refresh(seller)
    return _response(seller)

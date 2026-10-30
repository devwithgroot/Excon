from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.schemas import CreateRunRequest, LeadIn, ResearchRunResponse
from app.domain.collected_research import CollectedResearch
from app.domain.gap import GapDecision
from app.domain.seller_profile import SellerProfile
from app.domain.tool_contract import ToolRequest
from app.graphs.research import run_research
from app.infrastructure.database import get_db, get_session_factory
from app.infrastructure.models.research import ResearchRun
from app.infrastructure.repositories.research import ResearchStore

router = APIRouter(tags=["research"])


def _response_from_state(state: dict) -> ResearchRunResponse:
    collected = CollectedResearch.model_validate(state.get("collected") or {})
    profile_raw = state.get("seller_profile")
    return ResearchRunResponse(
        run_id=state.get("run_id") or "",
        status=state.get("status") or "partial",
        lead=LeadIn(
            company_name=state.get("company_name") or "",
            company_domain=state.get("company_domain"),
            website_url=state.get("website_url"),
        ),
        seller_profile=SellerProfile.model_validate(profile_raw) if profile_raw else None,
        collected=collected,
        missing=state.get("missing") or collected.missing_parameters(),
        tools_used=list(state.get("tools_used") or []),
        gap_decisions=[GapDecision.model_validate(item) for item in state.get("gap_decisions") or []],
        targeted_attempts=dict(state.get("targeted_attempts") or {}),
        error=state.get("error"),
    )


def _response_from_row(run: ResearchRun) -> ResearchRunResponse:
    collected = CollectedResearch.model_validate(run.collected or {})
    lead = run.lead
    return ResearchRunResponse(
        run_id=run.id,
        status=run.status,
        lead=LeadIn(
            company_name=lead.company_name if lead else "",
            company_domain=lead.domain if lead else None,
            website_url=lead.website_url if lead else None,
        ),
        seller_profile=SellerProfile.model_validate(run.seller_profile) if run.seller_profile else None,
        collected=collected,
        missing=list(run.missing or collected.missing_parameters()),
        tools_used=list(run.tools_used or []),
        gap_decisions=[GapDecision.model_validate(item) for item in run.gap_decisions or []],
        targeted_attempts=dict(run.targeted_attempts or {}),
        error=run.error,
    )


@router.post("/research/runs", response_model=ResearchRunResponse)
async def create_research_run(body: CreateRunRequest) -> ResearchRunResponse:
    """Start a LangGraph research run for a lead (and optional seller context)."""
    seller_input = body.seller.model_dump() if body.seller else None
    if body.seller_id:
        session = get_session_factory()()
        try:
            seller = ResearchStore(session).get_seller(body.seller_id)
        finally:
            session.close()
        if seller is None:
            raise HTTPException(status_code=404, detail="Seller not found")
        if not seller.approved_profile:
            raise HTTPException(status_code=409, detail="Approve the seller profile before researching leads")
        seller_input = {
            "seller_id": seller.id,
            "name": seller.name,
            "company_name": seller.company_name,
            "website_url": seller.website_url,
            "approved_profile": seller.approved_profile,
        }
    state = await run_research(
        ToolRequest(
            company_name=body.lead.company_name,
            company_domain=body.lead.company_domain,
            website_url=body.lead.website_url,
        ),
        seller_input=seller_input,
        session_factory=get_session_factory(),
    )
    return _response_from_state(state)


@router.get("/research/runs/{run_id}", response_model=ResearchRunResponse)
def get_research_run(run_id: str, db: Session = Depends(get_db)) -> ResearchRunResponse:
    run = ResearchStore(db).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Research run not found")
    return _response_from_row(run)


@router.post("/research/run", response_model=ResearchRunResponse)
async def research_run(request: ToolRequest) -> ResearchRunResponse:
    """Lead-only alias. The graph is still the only path to the tools."""
    state = await run_research(request, session_factory=get_session_factory())
    return _response_from_state(state)

from pydantic import BaseModel, Field

from app.domain.collected_research import CollectedResearch
from app.domain.gap import GapDecision
from app.domain.seller_profile import SellerProfile
from app.domain.tool_contract import DocumentInput


class LeadIn(BaseModel):
    company_name: str
    company_domain: str | None = None
    website_url: str | None = None


class SellerIn(BaseModel):
    name: str | None = None
    company_name: str
    website_url: str | None = None
    company_domain: str | None = None
    documents: list[DocumentInput] = Field(default_factory=list)


class CreateRunRequest(BaseModel):
    lead: LeadIn
    seller: SellerIn | None = None
    seller_id: str | None = None


class ResearchRunResponse(BaseModel):
    run_id: str
    status: str
    lead: LeadIn
    seller_profile: SellerProfile | None = None
    collected: CollectedResearch
    missing: list[str] = Field(default_factory=list)
    tools_used: list[str] = Field(default_factory=list)
    gap_decisions: list[GapDecision] = Field(default_factory=list)
    targeted_attempts: dict[str, int] = Field(default_factory=dict)
    error: str | None = None

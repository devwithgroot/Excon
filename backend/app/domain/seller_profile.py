from pydantic import BaseModel, Field

from app.domain.evidence import EvidenceItem


class SellerICP(BaseModel):
    target_industries: str | None = None
    company_size: str | None = None
    geography: str | None = None
    departments_roles: str | None = None
    problems: str | None = None
    buying_signals: str | None = None
    exclusions: str | None = None
    preferred: str | None = None


class SellerProfile(BaseModel):
    """Seller-side snapshot. Never merged into the lead's CollectedResearch."""

    company_name: str
    contact_name: str | None = None
    domain: str | None = None
    website_url: str | None = None
    industry: str | None = None
    description: str | None = None
    geography: str | None = None
    size: str | None = None
    products: str | None = None
    services: str | None = None
    features: str | None = None
    problems_solved: str | None = None
    differentiators: str | None = None
    limitations: str | None = None
    icp: SellerICP = Field(default_factory=SellerICP)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    status: str = "draft"
    version: int = 0

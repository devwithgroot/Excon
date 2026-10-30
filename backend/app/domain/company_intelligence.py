"""Analysis-stage output, before it is mapped into the reviewable SellerProfile."""

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from app.domain.evidence import EvidenceItem, Support

ClaimCategory = Literal[
    "description",
    "industry",
    "business_model",
    "geography",
    "company_size",
    "product",
    "service",
    "feature",
    "use_case",
    "industry_served",
    "customer_segment",
    "value_proposition",
    "problem_solved",
    "differentiator",
    "limitation",
]

SINGLE_VALUE_CATEGORIES = ("industry", "business_model", "company_size")
REQUIRED_CATEGORIES = ("description", "industry", "product_or_service", "customer_segment", "problem_solved")


class Traced(BaseModel):
    """A value plus where it came from. Empty evidence means it is an interpretation."""

    value: str
    evidence_ids: list[str] = Field(default_factory=list)
    support: Support = "explicit"


class ProductInfo(BaseModel):
    name: str
    description: str | None = None
    features: list[str] = Field(default_factory=list)
    target_users: list[str] = Field(default_factory=list)
    problems_solved: list[str] = Field(default_factory=list)
    business_value: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    support: Support = "explicit"


class ServiceInfo(BaseModel):
    name: str
    description: str | None = None
    target_customer: str | None = None
    business_outcome: str | None = None
    use_cases: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    support: Support = "explicit"


class ConsolidatedFact(BaseModel):
    fact_id: str
    category: ClaimCategory
    value: str
    name: str | None = None
    variants: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    support: Support = "explicit"
    confidence: float = Field(default=0.6, ge=0, le=1)


class ConflictValue(BaseModel):
    value: str
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)


class Conflict(BaseModel):
    field: str
    values: list[ConflictValue]
    note: str = ""


class ProposedICP(BaseModel):
    target_industries: list[str] = Field(default_factory=list)
    company_types: list[str] = Field(default_factory=list)
    company_size: str | None = None
    geography: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    decision_maker_roles: list[str] = Field(default_factory=list)
    customer_problems: list[str] = Field(default_factory=list)
    buying_signals: list[str] = Field(default_factory=list)
    business_requirements: list[str] = Field(default_factory=list)
    preferred_characteristics: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    reasons_to_buy: list[str] = Field(default_factory=list)


class ProspectSuggestion(BaseModel):
    """An LLM recommendation, never a verified fact about real customers."""

    suggestion_id: str = Field(default_factory=lambda: f"sug_{uuid4().hex[:10]}")
    prospect_type: str
    why_relevant: str = ""
    matching_offering: str | None = None
    problem_addressed: str | None = None
    decision_makers: list[str] = Field(default_factory=list)
    buying_signals: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    support: Support = "inferred"
    status: Literal["pending", "accepted", "rejected"] = "pending"


class CompanyIntelligence(BaseModel):
    company_name: str
    website_url: str | None = None
    industry: Traced | None = None
    sub_industry: Traced | None = None
    description: Traced | None = None
    business_model: Traced | None = None
    market_positioning: Traced | None = None
    company_size: Traced | None = None
    geography: list[Traced] = Field(default_factory=list)
    products: list[ProductInfo] = Field(default_factory=list)
    services: list[ServiceInfo] = Field(default_factory=list)
    features: list[Traced] = Field(default_factory=list)
    value_proposition: Traced | None = None
    problems_solved: list[Traced] = Field(default_factory=list)
    differentiators: list[Traced] = Field(default_factory=list)
    limitations: list[Traced] = Field(default_factory=list)
    customer_segments: list[Traced] = Field(default_factory=list)
    industries_served: list[Traced] = Field(default_factory=list)
    use_cases: list[Traced] = Field(default_factory=list)
    icp: ProposedICP = Field(default_factory=ProposedICP)
    prospect_suggestions: list[ProspectSuggestion] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)
    evidence: list[EvidenceItem] = Field(default_factory=list)

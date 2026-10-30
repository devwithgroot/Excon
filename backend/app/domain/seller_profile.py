"""Reviewable seller profile: what the UI shows and what research, scoring and outreach consume.

Older rows stored every field as one string (products="A, B", icp.target_industries="x, y").
`_upgrade_legacy` converts that shape on load so existing database records keep validating.
"""

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.company_intelligence import Conflict, ProspectSuggestion
from app.domain.evidence import EvidenceItem, Support

PIPELINE_VERSION = "seller-intel/v1"
LIST_SPLIT = re.compile(r"\s*(?:[,;|/\n]|\band\b(?=\s+[A-Z]))\s*")


def _clean_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "")).strip(" .;,")
        if text and text.lower() not in seen:
            seen.add(text.lower())
            out.append(text)
    return out


def _split(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part for part in LIST_SPLIT.split(value) if part.strip()]
    return value


class ProductItem(BaseModel):
    name: str
    description: str | None = None
    features: list[str] = Field(default_factory=list)
    target_users: list[str] = Field(default_factory=list)
    problems_solved: list[str] = Field(default_factory=list)
    business_value: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    support: Support = "explicit"

    _lists = field_validator("features", "target_users", "problems_solved", mode="before")(_clean_list)


class ServiceItem(BaseModel):
    name: str
    description: str | None = None
    target_customer: str | None = None
    business_outcome: str | None = None
    use_cases: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    support: Support = "explicit"

    _lists = field_validator("use_cases", mode="before")(_clean_list)


ICP_LIST_FIELDS = (
    "target_industries",
    "company_types",
    "geography",
    "departments",
    "decision_maker_roles",
    "customer_problems",
    "buying_signals",
    "business_requirements",
    "preferred_characteristics",
    "exclusions",
    "reasons_to_buy",
)


class SellerICP(BaseModel):
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

    _lists = field_validator(*ICP_LIST_FIELDS, mode="before")(_clean_list)

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        renames = {
            "departments_roles": "departments",
            "problems": "customer_problems",
            "preferred": "preferred_characteristics",
        }
        for old, new in renames.items():
            if old in data and new not in data:
                data[new] = data.pop(old)
            else:
                data.pop(old, None)
        for key in ("target_industries", "geography", "departments", "buying_signals"):
            data[key] = _split(data.get(key))
        return data


class FieldTrace(BaseModel):
    evidence_ids: list[str] = Field(default_factory=list)
    support: Support = "explicit"
    confidence: float | None = None
    edited: bool = False


class SourceSummary(BaseModel):
    source_id: str
    source_type: str
    name: str
    url: str | None = None
    status: str
    error: str | None = None


class ValidationIssue(BaseModel):
    field: str
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    resolved: bool = False


class ExtractionMetadata(BaseModel):
    job_id: str | None = None
    status: Literal["complete", "partial", "failed", "manual"] = "manual"
    pipeline_version: str = PIPELINE_VERSION
    sources: list[SourceSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    validation: list[ValidationIssue] = Field(default_factory=list)
    completeness: float = 0
    completed_at: datetime | None = None


PROFILE_LIST_FIELDS = (
    "geography",
    "features",
    "problems_solved",
    "differentiators",
    "limitations",
    "customer_segments",
    "industries_served",
    "use_cases",
)


class SellerProfile(BaseModel):
    """Seller-side snapshot. Never merged into the lead's CollectedResearch."""

    seller_id: str | None = None
    company_name: str
    contact_name: str | None = None
    domain: str | None = None
    website_url: str | None = None
    industry: str | None = None
    sub_industry: str | None = None
    description: str | None = None
    business_model: str | None = None
    market_positioning: str | None = None
    geography: list[str] = Field(default_factory=list)
    company_size: str | None = None
    products: list[ProductItem] = Field(default_factory=list)
    services: list[ServiceItem] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)
    value_proposition: str | None = None
    problems_solved: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    customer_segments: list[str] = Field(default_factory=list)
    industries_served: list[str] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    icp: SellerICP = Field(default_factory=SellerICP)
    suggested_prospect_characteristics: list[ProspectSuggestion] = Field(default_factory=list)
    traces: dict[str, FieldTrace] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    extraction_metadata: ExtractionMetadata | None = None
    status: Literal["draft", "approved"] = "draft"
    version: int = 0

    _lists = field_validator(*PROFILE_LIST_FIELDS, mode="before")(_clean_list)

    @field_validator(
        "industry", "sub_industry", "description", "business_model", "market_positioning",
        "company_size", "value_proposition", "contact_name", "domain", "website_url",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = re.sub(r"\s+", " ", value).strip()
            return value or None
        return value

    @field_validator("products", "services", mode="before")
    @classmethod
    def _offerings(cls, value: Any) -> Any:
        items = _split(value) if isinstance(value, str) else (value or [])
        out: list[Any] = []
        seen: set[str] = set()
        for item in items:
            if isinstance(item, str):
                item = {"name": item}
            if isinstance(item, BaseModel):
                item = item.model_dump()
            if not isinstance(item, dict) or "name" not in item:
                out.append(item)
                continue
            name = re.sub(r"\s+", " ", str(item.get("name") or "")).strip(" .;,")
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            out.append({**item, "name": name})
        return out

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "size" in data:
            legacy_size = data.pop("size")
            data.setdefault("company_size", legacy_size)
        for key in ("geography", "features"):
            data[key] = _split(data.get(key))
        return data


def offering_names(profile: SellerProfile | None) -> list[str]:
    if profile is None:
        return []
    return [item.name for item in [*profile.products, *profile.services]]


def offerings_text(profile: SellerProfile | None) -> str:
    return ", ".join(offering_names(profile))


def accepted_suggestions(profile: SellerProfile | None) -> list[ProspectSuggestion]:
    if profile is None:
        return []
    return [item for item in profile.suggested_prospect_characteristics if item.status == "accepted"]


def profile_text(profile: SellerProfile | None) -> str:
    """Everything scoring may match against. Pending or rejected suggestions are excluded."""
    if profile is None:
        return ""
    parts: list[str] = []
    for product in profile.products:
        parts += [product.name, product.description or "", *product.features, *product.problems_solved, *product.target_users]
    for service in profile.services:
        parts += [service.name, service.description or "", service.target_customer or "", *service.use_cases]
    parts += [
        profile.industry or "",
        profile.description or "",
        profile.value_proposition or "",
        *profile.features,
        *profile.problems_solved,
        *profile.differentiators,
        *profile.industries_served,
        *profile.use_cases,
    ]
    icp = profile.icp
    parts += [*icp.target_industries, *icp.customer_problems, *icp.buying_signals, *icp.preferred_characteristics]
    parts += [*icp.decision_maker_roles, *icp.departments, *icp.company_types]
    for suggestion in accepted_suggestions(profile):
        parts += [suggestion.prospect_type, suggestion.problem_addressed or "", *suggestion.buying_signals]
    return " ".join(part for part in parts if part)

"""Stage 12: map CompanyIntelligence into the reviewable SellerProfile, one category to one field."""

from datetime import datetime, timezone
from urllib.parse import urlparse

from app.application.seller_intel.document_models import Source
from app.domain.company_intelligence import CompanyIntelligence, ProposedICP, Traced
from app.domain.seller_profile import (
    ExtractionMetadata,
    FieldTrace,
    ProductItem,
    SellerICP,
    SellerProfile,
    ServiceItem,
    SourceSummary,
)

SINGLE_FIELDS = (
    "industry",
    "sub_industry",
    "description",
    "business_model",
    "market_positioning",
    "company_size",
    "value_proposition",
)
LIST_FIELDS = (
    "geography",
    "features",
    "problems_solved",
    "differentiators",
    "limitations",
    "customer_segments",
    "industries_served",
    "use_cases",
)


def domain_from_url(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url).hostname
    return host.lower().removeprefix("www.") if host else None


def _trace(items: list[Traced], confidence: float | None) -> FieldTrace:
    evidence = list(dict.fromkeys(e for item in items for e in item.evidence_ids))
    support = "explicit" if any(item.support == "explicit" for item in items) else "inferred"
    return FieldTrace(evidence_ids=evidence, support=support, confidence=confidence)


def icp_from_proposal(proposal: ProposedICP) -> SellerICP:
    return SellerICP.model_validate(proposal.model_dump())


def build_profile(
    intelligence: CompanyIntelligence,
    *,
    contact_name: str | None,
    seller_id: str | None = None,
    sources: list[Source] | None = None,
    job_id: str | None = None,
    warnings: list[str] | None = None,
) -> SellerProfile:
    data: dict = {
        "seller_id": seller_id,
        "company_name": intelligence.company_name,
        "contact_name": contact_name,
        "website_url": intelligence.website_url,
        "domain": domain_from_url(intelligence.website_url),
    }
    traces: dict[str, FieldTrace] = {}
    for field in SINGLE_FIELDS:
        value: Traced | None = getattr(intelligence, field)
        data[field] = value.value if value else None
        if value:
            traces[field] = _trace([value], intelligence.confidence.get(field))
    for field in LIST_FIELDS:
        items: list[Traced] = getattr(intelligence, field)
        data[field] = [item.value for item in items]
        if items:
            traces[field] = _trace(items, intelligence.confidence.get(field))

    data["products"] = [ProductItem.model_validate(item.model_dump()) for item in intelligence.products]
    data["services"] = [ServiceItem.model_validate(item.model_dump()) for item in intelligence.services]
    data["icp"] = icp_from_proposal(intelligence.icp)
    traces["icp"] = FieldTrace(support="inferred", confidence=None)
    data["suggested_prospect_characteristics"] = intelligence.prospect_suggestions
    data["traces"] = traces

    used = _used_evidence_ids(data, traces, intelligence)
    data["evidence"] = [item for item in intelligence.evidence if item.evidence_id in used]
    data["evidence_ids"] = [item.evidence_id for item in data["evidence"]]
    data["extraction_metadata"] = ExtractionMetadata(
        job_id=job_id,
        status="complete",
        sources=[
            SourceSummary(
                source_id=source.source_id,
                source_type=source.source_type.value,
                name=source.source_name,
                url=source.source_url,
                status=source.extraction_status,
                error=source.error,
            )
            for source in sources or []
        ],
        warnings=list(warnings or []),
        missing=list(intelligence.missing),
        conflicts=list(intelligence.conflicts),
        completed_at=datetime.now(timezone.utc),
    )
    return SellerProfile.model_validate(data)


def _used_evidence_ids(data: dict, traces: dict[str, FieldTrace], intelligence: CompanyIntelligence) -> set[str]:
    used = {e for trace in traces.values() for e in trace.evidence_ids}
    for item in [*data["products"], *data["services"], *data["suggested_prospect_characteristics"]]:
        used.update(item.evidence_ids)
    for conflict in intelligence.conflicts:
        for value in conflict.values:
            used.update(value.evidence_ids)
    return used


def minimal_profile(seller_input: dict, *, seller_id: str | None = None) -> SellerProfile:
    """Identity-only draft used before extraction finishes or when the user fills it in by hand."""
    website = seller_input.get("website_url") or None
    return SellerProfile(
        seller_id=seller_id,
        company_name=seller_input.get("company_name") or "",
        contact_name=seller_input.get("name") or None,
        website_url=website,
        domain=domain_from_url(website),
        status="draft",
    )

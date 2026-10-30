"""Stage 13: validate the built profile. Safe fixes are applied; everything else is reported."""

import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.application.seller_intel.evidence_consolidator import similar
from app.domain.seller_profile import FieldTrace, SellerProfile, ValidationIssue

logger = logging.getLogger(__name__)

COMPLETENESS_FIELDS = (
    "description",
    "industry",
    "offerings",
    "problems_solved",
    "value_proposition",
    "customer_segments",
    "geography",
    "differentiators",
    "icp.target_industries",
    "icp.decision_maker_roles",
)

DESCRIPTION_SYSTEM = """Write a 1-2 sentence plain description of the seller company "{company}"
using only the listed offerings and facts. No claims beyond them. Return {{"description": "..."}}."""


class _DescriptionRepair(BaseModel):
    description: str = Field(max_length=400)


def _filled(profile: SellerProfile, field: str) -> bool:
    if field == "offerings":
        return bool(profile.products or profile.services)
    if field.startswith("icp."):
        return bool(getattr(profile.icp, field.split(".", 1)[1]))
    return bool(getattr(profile, field))


def completeness(profile: SellerProfile) -> float:
    return round(sum(_filled(profile, field) for field in COMPLETENESS_FIELDS) / len(COMPLETENESS_FIELDS), 2)


def check_profile(profile: SellerProfile) -> tuple[SellerProfile, list[ValidationIssue]]:
    """Deterministic checks. Returns a repaired copy and the issues found."""
    issues: list[ValidationIssue] = []
    try:
        profile = SellerProfile.model_validate(profile.model_dump(mode="json"))
    except ValidationError as exc:
        issues.append(ValidationIssue(field="profile", severity="error", code="schema_invalid", message=str(exc)[:500]))
        return profile, issues

    if not profile.company_name.strip():
        issues.append(ValidationIssue(field="company_name", severity="error", code="missing_required", message="Company name is required."))
    if not profile.website_url:
        issues.append(ValidationIssue(field="website_url", severity="error", code="missing_required", message="Company website is required."))
    if not (profile.products or profile.services):
        issues.append(ValidationIssue(field="products", severity="error", code="missing_offerings", message="No product or service could be evidenced. Add at least one before approving."))
    if not profile.description:
        issues.append(ValidationIssue(field="description", severity="warning", code="missing_required", message="No company description was found."))

    known = {item.evidence_id for item in profile.evidence}
    dangling = 0
    for name, trace in list(profile.traces.items()):
        kept = [e for e in trace.evidence_ids if e in known]
        dangling += len(trace.evidence_ids) - len(kept)
        profile.traces[name] = trace.model_copy(update={"evidence_ids": kept})
    for item in [*profile.products, *profile.services, *profile.suggested_prospect_characteristics]:
        kept = [e for e in item.evidence_ids if e in known]
        dangling += len(item.evidence_ids) - len(kept)
        item.evidence_ids = kept
    if dangling:
        issues.append(ValidationIssue(field="evidence", severity="warning", code="dangling_evidence", message=f"Removed {dangling} evidence references that point to no stored evidence.", resolved=True))

    product_names = [item.name for item in profile.products]
    for service in profile.services:
        if any(similar(service.name, name) for name in product_names):
            issues.append(ValidationIssue(field="services", severity="warning", code="product_service_overlap", message=f"“{service.name}” is listed as both a product and a service. Keep it in one place."))
    for product in profile.products:
        if any(similar(product.name, feature) and product.name.lower() != feature.lower() for feature in profile.features):
            issues.append(ValidationIssue(field="products", severity="info", code="possible_feature", message=f"“{product.name}” also appears as a feature; check it is a product."))
        if not product.evidence_ids:
            issues.append(ValidationIssue(field="products", severity="warning", code="unsupported_claim", message=f"Product “{product.name}” has no supporting evidence."))

    for name, trace in profile.traces.items():
        if name != "icp" and trace.support == "inferred":
            issues.append(ValidationIssue(field=name, severity="info", code="inferred", message=f"{name.replace('_', ' ')} is an interpretation, not a direct quote from a source."))

    metadata = profile.extraction_metadata
    if metadata is not None:
        for conflict in metadata.conflicts:
            values = " vs ".join(value.value for value in conflict.values[:3])
            issues.append(ValidationIssue(field=conflict.field, severity="warning", code="conflict", message=f"Sources disagree: {values}"))
    return profile, issues


async def validate_profile(profile: SellerProfile, *, mlx: Any = None) -> SellerProfile:
    """Check, attempt one targeted repair for a missing description, re-check, record the report."""
    profile, issues = check_profile(profile)
    needs_description = any(issue.field == "description" and issue.code == "missing_required" for issue in issues)
    if needs_description and mlx is not None and (profile.products or profile.services):
        repaired = await _repair_description(profile, mlx)
        if repaired:
            profile.description = repaired
            evidence = [e for item in [*profile.products, *profile.services] for e in item.evidence_ids]
            profile.traces["description"] = FieldTrace(evidence_ids=list(dict.fromkeys(evidence)), support="inferred", confidence=0.4)
            profile, issues = check_profile(profile)
    if profile.extraction_metadata is not None:
        profile.extraction_metadata.validation = issues
        profile.extraction_metadata.completeness = completeness(profile)
        if any(issue.severity == "error" for issue in issues) and profile.extraction_metadata.status == "complete":
            profile.extraction_metadata.status = "partial"
    return profile


async def _repair_description(profile: SellerProfile, mlx: Any) -> str | None:
    lines = [f"- product: {item.name}: {item.description or ''}" for item in profile.products]
    lines += [f"- service: {item.name}: {item.description or ''}" for item in profile.services]
    lines += [f"- industry: {profile.industry}"] if profile.industry else []
    lines += [f"- serves: {segment}" for segment in profile.customer_segments[:3]]
    try:
        result = await mlx.complete_model(
            DESCRIPTION_SYSTEM.format(company=profile.company_name),
            "\n".join(lines),
            _DescriptionRepair,
            max_tokens=300,
        )
    except Exception as exc:
        logger.info("description repair failed: %s", exc)
        return None
    return result.description.strip() if result and result.description.strip() else None

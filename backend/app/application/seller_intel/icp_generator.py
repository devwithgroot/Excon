"""Stage 9: propose an ICP and prospect characteristics. Output is a recommendation, never a fact."""

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.application.seller_intel.evidence_consolidator import similar
from app.domain.company_intelligence import CompanyIntelligence, ProposedICP, ProspectSuggestion, Traced

logger = logging.getLogger(__name__)

PROMPT_VERSION = "icp-generate/v1"
MAX_SUGGESTIONS = 5

SYSTEM = """You design an Ideal Customer Profile (ICP) for the seller company "{company}".
You receive its analyzed profile. Answer: who should this company sell to?

Rules:
- Base every recommendation on the profile. Cite the profile item ids you used in "basis" (e.g. ["P1","S2"]).
- These are proposals. Do not name real customer companies. Do not state revenue, headcount or adoption numbers.
- Size ranges in company_size are allowed as a recommendation (e.g. "20-500 employees").
- exclusions: segments that are a poor fit, starting with anything the profile lists as a limitation.
- suggestions: up to {limit} prospect types, each specific (industry + situation + scale) and tied to one offering.
- Keep every list item short (under 12 words).
"""


class SuggestionOut(BaseModel):
    prospect_type: str
    why_relevant: str = ""
    matching_offering: str | None = None
    problem_addressed: str | None = None
    decision_makers: list[str] = Field(default_factory=list)
    buying_signals: list[str] = Field(default_factory=list)
    basis: list[str] = Field(default_factory=list)


class IcpOutput(ProposedICP):
    suggestions: list[SuggestionOut] = Field(default_factory=list)


def profile_prompt(intelligence: CompanyIntelligence) -> tuple[str, dict[str, list[str]]]:
    """Render the profile with short ids, and map each id to its evidence ids."""
    lines: list[str] = []
    basis: dict[str, list[str]] = {}

    def add(prefix: str, number: int, label: str, text: str, evidence: list[str]) -> None:
        item_id = f"{prefix}{number}"
        basis[item_id] = evidence
        lines.append(f"{item_id} {label}: {text}")

    for field in ("description", "industry", "business_model", "value_proposition", "company_size"):
        value: Traced | None = getattr(intelligence, field)
        if value:
            add("C", len(basis) + 1, field, value.value, value.evidence_ids)
    for number, product in enumerate(intelligence.products, start=1):
        detail = "; ".join(filter(None, [product.description, ", ".join(product.target_users), ", ".join(product.problems_solved)]))
        add("P", number, "product", f"{product.name} - {detail}" if detail else product.name, product.evidence_ids)
    for number, service in enumerate(intelligence.services, start=1):
        detail = "; ".join(filter(None, [service.description, service.target_customer, service.business_outcome]))
        add("S", number, "service", f"{service.name} - {detail}" if detail else service.name, service.evidence_ids)
    groups = (
        ("I", "industry served", intelligence.industries_served),
        ("G", "customer segment", intelligence.customer_segments),
        ("R", "problem solved", intelligence.problems_solved),
        ("U", "use case", intelligence.use_cases),
        ("D", "differentiator", intelligence.differentiators),
        ("L", "limitation", intelligence.limitations),
        ("Y", "geography", intelligence.geography),
    )
    for prefix, label, items in groups:
        for number, item in enumerate(items, start=1):
            add(prefix, number, label, item.value, item.evidence_ids)
    return "\n".join(lines), basis


async def generate_icp(intelligence: CompanyIntelligence, *, mlx: Any) -> tuple[ProposedICP, list[ProspectSuggestion], list[str]]:
    warnings: list[str] = []
    baseline = icp_from_intelligence(intelligence)
    if mlx is None or not (intelligence.products or intelligence.services):
        return baseline, [], warnings
    prompt, basis = profile_prompt(intelligence)
    try:
        output = await mlx.complete_model(
            SYSTEM.format(company=intelligence.company_name, limit=MAX_SUGGESTIONS),
            f"Seller profile:\n{prompt}",
            IcpOutput,
            max_tokens=2500,
        )
    except Exception as exc:
        logger.warning("icp generation failed: %s", exc)
        output = None
    if output is None:
        warnings.append("icp_llm_failed: ICP filled only from extracted facts, no prospect suggestions")
        return baseline, [], warnings

    icp = ProposedICP(**{field: getattr(output, field) for field in ProposedICP.model_fields})
    for field in ProposedICP.model_fields:
        value = getattr(icp, field)
        if isinstance(value, list):
            setattr(icp, field, _merge_lists(getattr(baseline, field), value))
    icp.company_size = icp.company_size or baseline.company_size

    offering_ids = {f"P{n}": item.name for n, item in enumerate(intelligence.products, start=1)}
    offering_ids |= {f"S{n}": item.name for n, item in enumerate(intelligence.services, start=1)}
    suggestions: list[ProspectSuggestion] = []
    for item in output.suggestions[:MAX_SUGGESTIONS]:
        if not item.prospect_type.strip():
            continue
        evidence = [e for ref in item.basis for e in basis.get(re.sub(r"[^A-Za-z0-9]", "", ref).upper(), [])]
        offering = (item.matching_offering or "").strip() or None
        if offering and offering.upper() in offering_ids:
            offering = offering_ids[offering.upper()]
        suggestions.append(
            ProspectSuggestion(
                prospect_type=item.prospect_type.strip(),
                why_relevant=item.why_relevant.strip(),
                matching_offering=offering,
                problem_addressed=item.problem_addressed,
                decision_makers=_merge_lists([], item.decision_makers),
                buying_signals=_merge_lists([], item.buying_signals),
                evidence_ids=list(dict.fromkeys(evidence)),
            )
        )
    return icp, suggestions, warnings


def icp_from_intelligence(intelligence: CompanyIntelligence) -> ProposedICP:
    """Fact-derived ICP baseline: only what the sources themselves say about customers."""
    users = [user for product in intelligence.products for user in product.target_users]
    customers = [service.target_customer for service in intelligence.services if service.target_customer]
    return ProposedICP(
        target_industries=_merge_lists([], [item.value for item in intelligence.industries_served]),
        company_types=_merge_lists([], [item.value for item in intelligence.customer_segments] + customers),
        geography=_merge_lists([], [item.value for item in intelligence.geography]),
        decision_maker_roles=[],
        departments=_merge_lists([], users),
        customer_problems=_merge_lists([], [item.value for item in intelligence.problems_solved]),
        exclusions=_merge_lists([], [item.value for item in intelligence.limitations]),
    )


def _merge_lists(first: list[str], second: list[str]) -> list[str]:
    out: list[str] = []
    for value in [*first, *second]:
        cleaned = re.sub(r"\s+", " ", value or "").strip(" .;,")
        if cleaned and not any(similar(cleaned, existing) for existing in out):
            out.append(cleaned)
    return out

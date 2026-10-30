"""Stage 8: one LLM call that organizes consolidated facts into business categories.

Every analyzed item must cite fact ids. Items without valid citations, or that drift
away from what the cited facts say, are kept only as "inferred".
"""

import logging
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.application.seller_intel.evidence_consolidator import Consolidation, similar
from app.domain.company_intelligence import (
    CompanyIntelligence,
    ConsolidatedFact,
    ProductInfo,
    ServiceInfo,
    Traced,
)

logger = logging.getLogger(__name__)

PROMPT_VERSION = "company-analyze/v1"
MAX_FACTS = 140

SYSTEM = """You are a B2B analyst. Organize the numbered facts about the seller company "{company}"
into a structured company profile.

Rules:
- Use only the facts. Every item must list the fact ids it is based on in "facts" (e.g. ["F3","F7"]).
- Do not invent products, services, customers, numbers, locations or sizes.
- product = a packaged offering it sells; service = work it performs for clients; feature = a capability
  of a product. Never turn a feature into a product, or a product into a service.
- Attach features, target users and problems to the product they belong to when the facts say so.
- industry = the company's own industry; industries_served = industries it sells to.
- company_size and geography only if a fact states them.
- description: 1-2 sentences in plain words, built from the facts.
- A fact may list several wordings separated by " / ". Pick one wording; never copy the whole list.
- Leave a field null or [] when the facts do not support it.
"""


def _as_list(value: Any) -> Any:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _fact_list(value: Any) -> Any:
    if isinstance(value, str):
        return re.findall(r"F\d+", value, flags=re.I) or [value]
    return value


class TracedOut(BaseModel):
    """Small models often answer a bare string; it is kept but has no citations, so it ends up inferred."""

    value: str
    facts: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _lenient(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"value": data}
        if isinstance(data, dict):
            return {**data, "facts": _fact_list(data.get("facts") or [])}
        return data


class _Named(BaseModel):
    @model_validator(mode="before")
    @classmethod
    def _lenient(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"name": data}
        if isinstance(data, dict):
            return {**data, "facts": _fact_list(data.get("facts") or [])}
        return data


class ProductOut(_Named):
    name: str
    description: str | None = None
    features: list[str] = Field(default_factory=list)
    target_users: list[str] = Field(default_factory=list)
    problems_solved: list[str] = Field(default_factory=list)
    business_value: str | None = None
    facts: list[str] = Field(default_factory=list)

    @field_validator("features", "target_users", "problems_solved", mode="before")
    @classmethod
    def _as_list(cls, value: Any) -> Any:
        return _as_list(value)


class ServiceOut(_Named):
    name: str
    description: str | None = None
    target_customer: str | None = None
    business_outcome: str | None = None
    use_cases: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)

    @field_validator("use_cases", mode="before")
    @classmethod
    def _as_list(cls, value: Any) -> Any:
        return _as_list(value)


class AnalysisOutput(BaseModel):
    industry: TracedOut | None = None
    sub_industry: TracedOut | None = None
    description: TracedOut | None = None
    business_model: TracedOut | None = None
    market_positioning: TracedOut | None = None
    company_size: TracedOut | None = None
    geography: list[TracedOut] = Field(default_factory=list)
    products: list[ProductOut] = Field(default_factory=list)
    services: list[ServiceOut] = Field(default_factory=list)
    features: list[TracedOut] = Field(default_factory=list)
    value_proposition: TracedOut | None = None
    problems_solved: list[TracedOut] = Field(default_factory=list)
    differentiators: list[TracedOut] = Field(default_factory=list)
    limitations: list[TracedOut] = Field(default_factory=list)
    customer_segments: list[TracedOut] = Field(default_factory=list)
    industries_served: list[TracedOut] = Field(default_factory=list)
    use_cases: list[TracedOut] = Field(default_factory=list)

    @field_validator(
        "geography", "products", "services", "features", "problems_solved", "differentiators",
        "limitations", "customer_segments", "industries_served", "use_cases",
        mode="before",
    )
    @classmethod
    def _as_list(cls, value: Any) -> Any:
        return _as_list(value)


STRICT_FIELDS = ("company_size", "geography")
TRACED_SINGLE = ("industry", "sub_industry", "description", "business_model", "market_positioning", "company_size", "value_proposition")
TRACED_LISTS = ("geography", "features", "problems_solved", "differentiators", "limitations", "customer_segments", "industries_served", "use_cases")
CATEGORY_FOR_LIST = {
    "geography": "geography",
    "features": "feature",
    "problems_solved": "problem_solved",
    "differentiators": "differentiator",
    "limitations": "limitation",
    "customer_segments": "customer_segment",
    "industries_served": "industry_served",
    "use_cases": "use_case",
}
CATEGORY_FOR_SINGLE = {
    "industry": "industry",
    "description": "description",
    "business_model": "business_model",
    "company_size": "company_size",
    "value_proposition": "value_proposition",
}


def facts_prompt(consolidation: Consolidation) -> str:
    lines = []
    for fact in consolidation.facts[:MAX_FACTS]:
        name = f" [{fact.name}]" if fact.name else ""
        text = " / ".join([fact.value, *fact.variants])[:300]
        lines.append(f"{fact.fact_id} ({fact.category}){name}: {text}")
    return "\n".join(lines)


async def analyze_company(
    consolidation: Consolidation,
    *,
    company_name: str,
    website_url: str | None,
    mlx: Any,
) -> tuple[CompanyIntelligence, list[str]]:
    """Returns (intelligence, warnings). Falls back to a fact-only mapping when the LLM fails."""
    warnings: list[str] = []
    output: AnalysisOutput | None = None
    if consolidation.facts and mlx is not None:
        try:
            output = await mlx.complete_model(
                SYSTEM.format(company=company_name),
                f"Facts:\n{facts_prompt(consolidation)}",
                AnalysisOutput,
                max_tokens=3500,
            )
        except Exception as exc:
            logger.warning("company analysis failed: %s", exc)
        if output is None:
            warnings.append("analysis_llm_failed: profile built directly from extracted facts")
    if output is None:
        intelligence = intelligence_from_facts(consolidation, company_name=company_name, website_url=website_url)
    else:
        intelligence = _resolve(output, consolidation, company_name=company_name, website_url=website_url)
    intelligence.conflicts = consolidation.conflicts
    intelligence.missing = consolidation.missing
    intelligence.evidence = consolidation.evidence
    return intelligence, warnings


def _facts_index(consolidation: Consolidation) -> dict[str, ConsolidatedFact]:
    return {fact.fact_id: fact for fact in consolidation.facts}


def _cited(ids: list[str], index: dict[str, ConsolidatedFact]) -> list[ConsolidatedFact]:
    normalized = [re.sub(r"[^A-Za-z0-9]", "", item).upper() for item in ids]
    return [index[item] for item in dict.fromkeys(normalized) if item in index]


def _overlap(value: str, facts: list[ConsolidatedFact]) -> float:
    tokens = set(re.findall(r"[a-z0-9]{4,}", value.lower()))
    if not tokens:
        return 1.0
    haystack = " ".join(f"{fact.name or ''} {fact.value} {' '.join(fact.variants)}" for fact in facts).lower()
    return sum(1 for token in tokens if token in haystack) / len(tokens)


def _trace(value: str | None, ids: list[str], index: dict[str, ConsolidatedFact], *, strict: bool = False) -> Traced | None:
    if not value or not value.strip():
        return None
    facts = _cited(ids, index)
    if not facts:
        return None if strict else Traced(value=value.strip(), support="inferred")
    evidence = [evidence_id for fact in facts for evidence_id in fact.evidence_ids]
    explicit = any(fact.support == "explicit" for fact in facts) and _overlap(value, facts) >= 0.4
    if strict and not explicit:
        return None
    return Traced(value=value.strip(), evidence_ids=list(dict.fromkeys(evidence)), support="explicit" if explicit else "inferred")


def _confidence(traced: Traced | None, index_by_evidence: dict[str, float]) -> float | None:
    if traced is None:
        return None
    if traced.support == "inferred" or not traced.evidence_ids:
        return 0.4
    scores = [index_by_evidence[item] for item in traced.evidence_ids if item in index_by_evidence]
    return round(max(scores), 2) if scores else 0.5


def _resolve(output: AnalysisOutput, consolidation: Consolidation, *, company_name: str, website_url: str | None) -> CompanyIntelligence:
    index = _facts_index(consolidation)
    data: dict[str, Any] = {"company_name": company_name, "website_url": website_url}
    for field in TRACED_SINGLE:
        item = getattr(output, field)
        value = item.value.split(" / ")[0] if item else None
        data[field] = _trace(value, item.facts, index, strict=field in STRICT_FIELDS) if item else None
    for field in TRACED_LISTS:
        traced = [_trace(item.value, item.facts, index, strict=field in STRICT_FIELDS) for item in getattr(output, field)]
        data[field] = _dedupe_traced([item for item in traced if item])

    products: list[ProductInfo] = []
    for item in output.products:
        facts = _cited(item.facts, index)
        if not facts or _overlap(item.name, facts) < 0.5:
            continue
        products.append(
            ProductInfo(
                name=item.name.strip(),
                description=item.description,
                features=_clean_list(item.features),
                target_users=_clean_list(item.target_users),
                problems_solved=_clean_list(item.problems_solved),
                business_value=item.business_value,
                evidence_ids=list(dict.fromkeys(e for fact in facts for e in fact.evidence_ids)),
                support="explicit" if any(fact.support == "explicit" for fact in facts) else "inferred",
            )
        )
    services: list[ServiceInfo] = []
    for item in output.services:
        facts = _cited(item.facts, index)
        if not facts or _overlap(item.name, facts) < 0.5:
            continue
        services.append(
            ServiceInfo(
                name=item.name.strip(),
                description=item.description,
                target_customer=item.target_customer,
                business_outcome=item.business_outcome,
                use_cases=_clean_list(item.use_cases),
                evidence_ids=list(dict.fromkeys(e for fact in facts for e in fact.evidence_ids)),
                support="explicit" if any(fact.support == "explicit" for fact in facts) else "inferred",
            )
        )
    products += _uncovered(consolidation.by_category("product"), products, ProductInfo)
    services += _uncovered(consolidation.by_category("service"), services, ServiceInfo)
    features = [feature for product in products for feature in product.features]
    data["products"] = products
    data["services"] = [service for service in services if not any(similar(service.name, f) for f in features)]

    intelligence = CompanyIntelligence(**data)
    _fill_gaps_from_facts(intelligence, consolidation)
    intelligence.confidence = _confidence_map(intelligence, consolidation)
    return intelligence


def _uncovered(facts: list[ConsolidatedFact], analyzed: list, model: type) -> list:
    """Product/service facts the analyzer skipped are kept rather than lost."""
    extra = []
    for fact in facts:
        label = fact.name or fact.value
        if any(similar(label, item.name) for item in analyzed):
            continue
        extra.append(
            model(
                name=label[:120],
                description=fact.value if fact.name else None,
                evidence_ids=fact.evidence_ids,
                support=fact.support,
            )
        )
    return extra


def _fill_gaps_from_facts(intelligence: CompanyIntelligence, consolidation: Consolidation) -> None:
    for field, category in CATEGORY_FOR_SINGLE.items():
        if getattr(intelligence, field) is None:
            facts = consolidation.by_category(category)
            if facts:
                best = max(facts, key=lambda fact: (fact.confidence, len(fact.value)))
                setattr(intelligence, field, _from_fact(best))
    for field, category in CATEGORY_FOR_LIST.items():
        current: list[Traced] = getattr(intelligence, field)
        for fact in consolidation.by_category(category):
            if not any(similar(fact.value, item.value) for item in current):
                current.append(_from_fact(fact))


def _from_fact(fact: ConsolidatedFact) -> Traced:
    return Traced(value=fact.value, evidence_ids=fact.evidence_ids, support=fact.support)


def intelligence_from_facts(consolidation: Consolidation, *, company_name: str, website_url: str | None) -> CompanyIntelligence:
    intelligence = CompanyIntelligence(company_name=company_name, website_url=website_url)
    intelligence.products = _uncovered(consolidation.by_category("product"), [], ProductInfo)
    intelligence.services = _uncovered(consolidation.by_category("service"), [], ServiceInfo)
    _fill_gaps_from_facts(intelligence, consolidation)
    intelligence.confidence = _confidence_map(intelligence, consolidation)
    return intelligence


def _confidence_map(intelligence: CompanyIntelligence, consolidation: Consolidation) -> dict[str, float]:
    by_evidence = {e: fact.confidence for fact in consolidation.facts for e in fact.evidence_ids}
    scores: dict[str, float] = {}
    for field in TRACED_SINGLE:
        value = _confidence(getattr(intelligence, field), by_evidence)
        if value is not None:
            scores[field] = value
    for field in TRACED_LISTS:
        values = [_confidence(item, by_evidence) for item in getattr(intelligence, field)]
        if values:
            scores[field] = round(sum(values) / len(values), 2)
    for field in ("products", "services"):
        items = getattr(intelligence, field)
        if items:
            values = [_confidence(Traced(value=i.name, evidence_ids=i.evidence_ids, support=i.support), by_evidence) for i in items]
            scores[field] = round(sum(values) / len(values), 2)
    return scores


def _clean_list(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", value or "").strip()
        if cleaned and not any(similar(cleaned, existing) for existing in out):
            out.append(cleaned)
    return out


def _dedupe_traced(items: list[Traced]) -> list[Traced]:
    out: list[Traced] = []
    for item in items:
        match = next((existing for existing in out if similar(existing.value, item.value)), None)
        if match is None:
            out.append(item)
        else:
            match.evidence_ids = list(dict.fromkeys(match.evidence_ids + item.evidence_ids))
            if item.support == "explicit":
                match.support = "explicit"
    return out

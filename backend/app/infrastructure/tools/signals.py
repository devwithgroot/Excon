"""LangChain tool: signals. Called by the LangGraph research agent."""

from datetime import datetime, timezone

from langchain_core.tools import StructuredTool

from app.domain.collected_research import (
    CollectedResearch,
    FieldValue,
    ParameterStatus,
    SignalsBlock,
)
from app.domain.evidence import EvidenceItem, SourceType
from app.domain.freshness import classify_freshness, is_usable
from app.domain.tool_contract import ToolRequest, ToolResult
from app.infrastructure.tools.tavily import TavilyClient, TavilyHit

SIGNAL_QUERIES = {
    "funding": "funding raised series investment",
    "hiring": "hiring jobs careers recruiting",
    "tech_shift": "technology stack AI cloud digital transformation",
    "acquisition": "acquisition acquired merger buyout",
    "new_product": "launches new product release feature",
    "expansion": "expansion new office market opens",
}

SIGNAL_KEYWORDS = {
    "funding": ("funding", "raised", "series", "venture", "seed", "investment"),
    "hiring": ("hiring", "job", "careers", "recruit", "opening"),
    "tech_shift": ("technology", "ai", "cloud", "platform", "digital"),
    "acquisition": ("acqui", "merger", "buyout", "takeover"),
    "new_product": ("launch", "product", "release", "unveil"),
    "expansion": ("expansion", "opens", "office", "market", "headcount"),
}


class SignalsTool:
    name = "signals"
    version = "1"
    fulfills = (
        "signals.funding",
        "signals.hiring",
        "signals.tech_shift",
        "signals.acquisition",
        "signals.new_product",
        "signals.expansion",
    )

    def __init__(self, tavily: TavilyClient | None = None) -> None:
        self.tavily = tavily or TavilyClient()

    async def execute(self, request: ToolRequest) -> ToolResult:
        retrieved_at = datetime.now(timezone.utc)
        evidence: list[EvidenceItem] = []
        values: dict[str, FieldValue] = {}
        try:
            queries = SIGNAL_QUERIES
            if request.focus and request.focus in SIGNAL_QUERIES:
                queries = {request.focus: SIGNAL_QUERIES[request.focus]}
            for field, extra in queries.items():
                query = f"{request.company_name} {extra}"
                hits = await self.tavily.search(query, days=90)
                usable = [hit for hit in hits if _hit_matches(field, hit)]
                field_value, items = _field_from_hits(field, usable, retrieved_at)
                values[field] = field_value
                evidence.extend(items)
        except Exception:
            return ToolResult(
                success=False,
                tool_name=self.name,
                error_code="signals_provider_error",
                retryable=True,
            )
        patch = CollectedResearch(
            signals=SignalsBlock(**values),
            evidence=evidence,
        )
        return ToolResult(
            success=True,
            tool_name=self.name,
            patch=patch,
            evidence=evidence,
        )


def _hit_matches(field: str, hit: TavilyHit) -> bool:
    blob = f"{hit.title} {hit.content}".lower()
    return any(keyword in blob for keyword in SIGNAL_KEYWORDS[field])


def _field_from_hits(
    field: str,
    hits: list[TavilyHit],
    retrieved_at: datetime,
) -> tuple[FieldValue, list[EvidenceItem]]:
    items: list[EvidenceItem] = []
    for hit in hits:
        freshness = classify_freshness(hit.published_at, now=retrieved_at)
        if not is_usable(freshness):
            continue
        excerpt = (hit.content or hit.title)[:400]
        items.append(
            EvidenceItem(
                field_key=f"signals.{field}",
                extracted_value=hit.title or excerpt[:160],
                source_url=hit.url or None,
                source_type=SourceType.web_search,
                source_published_at=hit.published_at,
                retrieved_at=retrieved_at,
                supporting_excerpt=excerpt,
                extraction_method="tavily",
                confidence=0.6,
                freshness=freshness,
            )
        )
    if not items:
        return FieldValue(status=ParameterStatus.not_found_this_run), []
    first = items[0]
    return (
        FieldValue(
            value=first.extracted_value,
            status=ParameterStatus.supported,
            evidence_ids=[item.evidence_id for item in items],
        ),
        items,
    )


def as_langchain_tool(instance: "SignalsTool | None" = None) -> StructuredTool:
    from app.tools.lc_tool import as_research_tool

    return as_research_tool(
        name="signals",
        description=(
            "Retrieve recent business signals: funding, hiring, tech shift, "
            "acquisition, new product, expansion. Does not invent facts."
        ),
        worker=instance or SignalsTool(),
    )


signals_tool = as_langchain_tool

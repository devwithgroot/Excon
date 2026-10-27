"""LangChain tool: news. Called by the LangGraph research agent."""

from datetime import datetime, timezone

from langchain_core.tools import StructuredTool

from app.domain.collected_research import CollectedResearch, NewsItem
from app.domain.evidence import EvidenceItem, SourceType
from app.domain.freshness import classify_freshness, is_usable
from app.domain.tool_contract import ToolRequest, ToolResult
from app.infrastructure.tools.tavily import TavilyClient


class NewsTool:
    name = "news"
    version = "1"
    fulfills = ("news",)

    def __init__(self, tavily: TavilyClient | None = None) -> None:
        self.tavily = tavily or TavilyClient()

    async def execute(self, request: ToolRequest) -> ToolResult:
        retrieved_at = datetime.now(timezone.utc)
        try:
            extra = "latest news announcement" if request.focus else "news"
            hits = await self.tavily.search(
                f"{request.company_name} {extra}",
                topic="news",
                days=90,
            )
        except Exception:
            return ToolResult(
                success=False,
                tool_name=self.name,
                error_code="news_provider_error",
                retryable=True,
            )

        news: list[NewsItem] = []
        evidence: list[EvidenceItem] = []
        for hit in hits:
            if not hit.url:
                continue
            freshness = classify_freshness(hit.published_at, now=retrieved_at)
            if not is_usable(freshness):
                continue
            excerpt = (hit.content or hit.title)[:400]
            item = EvidenceItem(
                field_key="news",
                extracted_value=hit.title,
                source_url=hit.url or None,
                source_type=SourceType.news,
                source_published_at=hit.published_at,
                retrieved_at=retrieved_at,
                supporting_excerpt=excerpt,
                extraction_method="tavily",
                confidence=0.65,
                freshness=freshness,
            )
            evidence.append(item)
            news.append(
                NewsItem(
                    title=hit.title,
                    url=hit.url,
                    published_at=hit.published_at.isoformat() if hit.published_at else None,
                    excerpt=excerpt,
                    evidence_id=item.evidence_id,
                )
            )
        patch = CollectedResearch(news=news, evidence=evidence)
        return ToolResult(success=True, tool_name=self.name, patch=patch, evidence=evidence)


def as_langchain_tool(instance: "NewsTool | None" = None) -> StructuredTool:
    from app.tools.lc_tool import as_research_tool

    return as_research_tool(
        name="news",
        description="Retrieve company news from the last 90 days. Does not invent headlines.",
        worker=instance or NewsTool(),
    )


news_tool = as_langchain_tool

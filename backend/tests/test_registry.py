from datetime import datetime, timedelta, timezone

from app.domain.collected_research import CollectedResearch, ParameterStatus
from app.domain.merge import merge_research
from app.domain.tool_contract import ToolRequest
from app.infrastructure.tools.mocks import FakeProspeoClient, FakeTavilyClient
from app.infrastructure.tools.news import NewsTool
from app.infrastructure.tools.people import PeopleTool
from app.infrastructure.tools.registry import TOOL_NAMES, default_registry, get_tool
from app.infrastructure.tools.signals import SignalsTool
from app.infrastructure.tools.tavily import TavilyHit
from app.infrastructure.tools.website_docs import WebsiteDocsTool


def test_registry_exposes_the_four_tools() -> None:
    registry = default_registry()
    assert tuple(registry) == TOOL_NAMES
    for name in TOOL_NAMES:
        tool = get_tool(name, registry)
        assert tool.name == name
        assert tool.fulfills


async def test_merge_of_all_tools_reports_remaining_gaps() -> None:
    published = datetime.now(timezone.utc) - timedelta(days=5)
    tavily = FakeTavilyClient(
        hits_by_keyword={
            "hiring": [
                TavilyHit(
                    title="Acme is hiring engineers",
                    url="https://news.example/hiring",
                    content="Acme is hiring engineers",
                    published_at=published,
                )
            ]
        },
        default=[
            TavilyHit(
                title="Acme plant update",
                url="https://news.example/plant",
                content="Acme plant update",
                published_at=published,
            )
        ],
    )

    async def fetch_page(url: str, **kwargs) -> str:
        return "<html><body>Acme is based in Austin. 80 employees.</body></html>"

    registry = default_registry(
        signals=SignalsTool(tavily),
        news=NewsTool(tavily),
        website_docs=WebsiteDocsTool(
            fetch_page=fetch_page,
            is_safe_url=lambda url: True,
            tavily=tavily,
            max_pages=1,
        ),
        people=PeopleTool(FakeProspeoClient([]), tavily),
    )
    request = ToolRequest(
        company_name="Acme",
        company_domain="acme.example",
        website_url="https://acme.example",
    )
    collected = CollectedResearch()
    for name in TOOL_NAMES:
        result = await get_tool(name, registry).execute(request)
        assert result.success
        collected = merge_research(collected, result.patch)

    missing = collected.missing_parameters()
    assert "people" in missing
    assert "signals.funding" in missing
    assert "signals.hiring" not in missing
    assert collected.company.headquarters.status == ParameterStatus.supported
    assert collected.news
    assert collected.people == []

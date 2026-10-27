from datetime import datetime, timedelta, timezone

from app.domain.tool_contract import ToolRequest
from app.infrastructure.tools.mocks import FakeTavilyClient
from app.infrastructure.tools.news import NewsTool
from app.infrastructure.tools.tavily import TavilyHit


def _hit(title: str, *, days_ago: int | None, url: str = "https://news.example/a") -> TavilyHit:
    published = None
    if days_ago is not None:
        published = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return TavilyHit(title=title, url=url, content=title, published_at=published)


async def test_news_keeps_fresh_and_drops_stale() -> None:
    tavily = FakeTavilyClient(
        default=[
            _hit("Acme opens a plant", days_ago=20),
            _hit("Old award", days_ago=200),
        ]
    )
    result = await NewsTool(tavily).execute(ToolRequest(company_name="Acme"))
    assert result.success
    assert [item.title for item in result.patch.news] == ["Acme opens a plant"]
    assert result.patch.company.name.value is None
    assert result.patch.people == []
    assert tavily.calls[0][1]["topic"] == "news"
    assert tavily.calls[0][1]["days"] == 90


async def test_news_keeps_undated_items() -> None:
    tavily = FakeTavilyClient(default=[_hit("Acme update", days_ago=None)])
    result = await NewsTool(tavily).execute(ToolRequest(company_name="Acme"))
    assert len(result.patch.news) == 1
    assert result.patch.news[0].published_at is None
    assert result.evidence[0].freshness.value == "unknown"


async def test_news_skips_empty_url() -> None:
    tavily = FakeTavilyClient(default=[_hit("No link", days_ago=5, url="")])
    result = await NewsTool(tavily).execute(ToolRequest(company_name="Acme"))
    assert result.patch.news == []

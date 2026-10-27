from datetime import datetime, timedelta, timezone

from app.domain.collected_research import ParameterStatus
from app.domain.tool_contract import ToolRequest
from app.infrastructure.tools.mocks import FakeTavilyClient
from app.infrastructure.tools.signals import SignalsTool
from app.infrastructure.tools.tavily import TavilyHit


def _hit(title: str, *, days_ago: int = 10, extra: str = "") -> TavilyHit:
    published = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return TavilyHit(
        title=title,
        url="https://news.example/item",
        content=f"{title} {extra}",
        published_at=published,
    )


async def test_signals_fills_only_matching_fields() -> None:
    tavily = FakeTavilyClient(
        hits_by_keyword={
            "funding": [_hit("Acme raised Series A funding")],
            "hiring": [_hit("Acme is hiring engineers")],
        }
    )
    result = await SignalsTool(tavily).execute(ToolRequest(company_name="Acme"))
    assert result.success
    assert result.patch.company.name.status == ParameterStatus.unknown
    assert result.patch.news == []
    assert result.patch.people == []
    assert result.patch.signals.funding.status == ParameterStatus.supported
    assert result.patch.signals.hiring.status == ParameterStatus.supported
    assert result.patch.signals.acquisition.status == ParameterStatus.not_found_this_run
    assert "raised Series A" in (result.patch.signals.funding.value or "")
    assert all(item.field_key.startswith("signals.") for item in result.evidence)


async def test_signals_rejects_stale_hits() -> None:
    tavily = FakeTavilyClient(
        hits_by_keyword={"funding": [_hit("Acme raised Series B funding", days_ago=200)]}
    )
    result = await SignalsTool(tavily).execute(ToolRequest(company_name="Acme"))
    assert result.patch.signals.funding.status == ParameterStatus.not_found_this_run
    assert result.patch.signals.funding.value is None
    assert result.evidence == []


async def test_signals_does_not_invent_from_unrelated_copy() -> None:
    tavily = FakeTavilyClient(
        hits_by_keyword={"funding": [_hit("Acme picnic photos", extra="community event")]}
    )
    result = await SignalsTool(tavily).execute(ToolRequest(company_name="Acme"))
    assert result.patch.signals.funding.status == ParameterStatus.not_found_this_run
    assert result.patch.signals.funding.value is None


async def test_signals_provider_error_is_retryable() -> None:
    class Boom:
        async def search(self, query: str, **kwargs):
            raise RuntimeError("TAVILY_API_KEY is not set")

    result = await SignalsTool(Boom()).execute(ToolRequest(company_name="Acme"))
    assert result.success is False
    assert result.retryable is True
    assert result.error_code == "signals_provider_error"

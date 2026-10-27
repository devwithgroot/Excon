from datetime import datetime, timezone

from app.domain.tool_contract import ToolRequest
from app.infrastructure.tools.mocks import FakeProspeoClient, FakeTavilyClient
from app.infrastructure.tools.people import (
    PeopleTool,
    build_named_search_payload,
    build_search_payload,
    extract_decision_makers,
    _map_person,
    _result_rows,
)
from app.infrastructure.tools.tavily import TavilyHit


def _hit(title: str, url: str, content: str) -> TavilyHit:
    return TavilyHit(title=title, url=url, content=content)


async def test_people_starts_from_web_then_enriches_contacts() -> None:
    tavily = FakeTavilyClient(
        default=[
            _hit(
                "Ada Lovelace - CTO at Acme | LinkedIn",
                "https://www.linkedin.com/in/ada-lovelace",
                "Ada Lovelace is CTO of Acme and a decision maker.",
            )
        ]
    )
    client = FakeProspeoClient(
        enrich_by_name={
            "ada lovelace": {
                "person_id": "p1",
                "full_name": "Ada Lovelace",
                "current_job_title": "CTO",
                "headline": "Leads product engineering",
                "linkedin_url": "https://www.linkedin.com/in/ada-lovelace",
                "email": {"revealed": True, "email": "ada@acme.example"},
                "mobile": {"revealed": True, "mobile": "+15550100"},
                "_company": {"name": "Acme", "website": "acme.example"},
            }
        }
    )
    result = await PeopleTool(client, tavily).execute(
        ToolRequest(company_name="Acme", company_domain="acme.example")
    )
    assert result.success
    assert len(result.patch.people) == 1
    person = result.patch.people[0]
    assert person.name == "Ada Lovelace"
    assert person.title == "CTO"
    assert person.email == "ada@acme.example"
    assert person.phone == "+15550100"
    assert person.linkedin_url == "https://www.linkedin.com/in/ada-lovelace"
    assert result.patch.company.name.value is None
    assert client.enrich_calls
    assert client.enrich_calls[0]["full_name"] == "Ada Lovelace"
    assert client.enrich_calls[0]["company_website"] == "acme.example"


async def test_people_keeps_web_person_when_prospeo_misses() -> None:
    tavily = FakeTavilyClient(
        default=[
            _hit(
                "Bob Owner - Founder at Acme",
                "https://news.example/bob",
                "Bob Owner is the founder and owner of Acme.",
            )
        ]
    )
    result = await PeopleTool(FakeProspeoClient(), tavily).execute(
        ToolRequest(company_name="Acme", company_domain="acme.example")
    )
    assert len(result.patch.people) == 1
    person = result.patch.people[0]
    assert person.name == "Bob Owner"
    assert person.email is None
    assert person.phone is None
    assert person.title and "Founder" in person.title


async def test_people_rejects_prospeo_row_from_wrong_company() -> None:
    tavily = FakeTavilyClient(
        default=[
            _hit(
                "Pat Example - CEO at Acme | LinkedIn",
                "https://www.linkedin.com/in/pat",
                "Pat Example is CEO of Acme.",
            )
        ]
    )
    client = FakeProspeoClient(
        enrich_by_name={
            "pat example": {
                "full_name": "Pat Example",
                "current_job_title": "CEO",
                "email": {"revealed": True, "email": "pat@other.com"},
                "_company": {"name": "Other Corp", "website": "other.com"},
            }
        }
    )
    result = await PeopleTool(client, tavily).execute(
        ToolRequest(company_name="Acme", company_domain="acme.example")
    )
    person = result.patch.people[0]
    assert person.name == "Pat Example"
    assert person.email is None


async def test_people_rejects_invalid_email() -> None:
    record, _ = _map_person(
        {"full_name": "Bob", "email": "not-an-email"},
        datetime.now(timezone.utc),
    )
    assert record is not None
    assert record.email is None


def test_extract_decision_makers_reads_linkedin_and_role() -> None:
    people = extract_decision_makers(
        [
            _hit(
                "Casey Founder - CEO at Acme | LinkedIn",
                "https://www.linkedin.com/in/casey",
                "Casey Founder, CEO of Acme",
            ),
            _hit("Picnic photos", "https://news.example/picnic", "Acme picnic"),
        ],
        "Acme",
    )
    assert len(people) == 1
    assert people[0].name == "Casey Founder"
    assert people[0].linkedin_url == "https://www.linkedin.com/in/casey"


def test_prospeo_payload_uses_filters_wrapper() -> None:
    assert build_search_payload("Stripe", "www.stripe.com") == {
        "page": 1,
        "filters": {"company": {"websites": {"include": ["stripe.com"]}}},
    }
    assert build_named_search_payload("Ada Lovelace", "Stripe", "stripe.com")["filters"][
        "person_name"
    ] == {"include": ["Ada Lovelace"]}


def test_maps_official_prospeo_person_object() -> None:
    rows = _result_rows(
        {
            "error": False,
            "results": [
                {
                    "person": {
                        "full_name": "Pat Example",
                        "current_job_title": "VP Sales",
                        "headline": "Leads revenue",
                        "linkedin_url": "https://www.linkedin.com/in/pat",
                        "email": {
                            "revealed": False,
                            "email": "pat@*****.com",
                        },
                        "mobile": {"revealed": False, "mobile": "+1 ***"},
                    }
                }
            ],
        }
    )
    record, item = _map_person(rows[0], datetime.now(timezone.utc))
    assert record is not None and item is not None
    assert record.name == "Pat Example"
    assert record.title == "VP Sales"
    assert record.email is None
    assert record.phone is None
    assert record.linkedin_url == "https://www.linkedin.com/in/pat"


async def test_people_missing_key_is_not_retryable() -> None:
    tavily = FakeTavilyClient()
    tavily.search = _raise_runtime  # type: ignore[method-assign]
    result = await PeopleTool(FakeProspeoClient(), tavily).execute(ToolRequest(company_name="Acme"))
    assert result.success is False
    assert result.retryable is False
    assert result.error_code == "people_not_configured"


async def test_people_provider_error_is_retryable() -> None:
    tavily = FakeTavilyClient()
    tavily.search = _raise_timeout  # type: ignore[method-assign]
    result = await PeopleTool(FakeProspeoClient(), tavily).execute(ToolRequest(company_name="Acme"))
    assert result.success is False
    assert result.retryable is True
    assert result.error_code == "people_provider_error"


async def _raise_runtime(query: str, **kwargs):
    raise RuntimeError("TAVILY_API_KEY is not set")


async def _raise_timeout(query: str, **kwargs):
    raise TimeoutError("search down")

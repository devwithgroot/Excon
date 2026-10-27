from app.domain.collected_research import ParameterStatus
from app.domain.tool_contract import DocumentInput, ToolRequest
from app.infrastructure.tools.http_safety import url_is_public_http
from app.infrastructure.tools.mocks import FakeMlxClient, FakeTavilyClient
from app.infrastructure.tools.tavily import TavilyHit
from app.infrastructure.tools.website_docs import WebsiteDocsTool


ACME_HTML = """
<html>
  <head>
    <title>Acme</title>
    <meta name="description" content="Acme builds industrial widgets.">
  </head>
  <body>
    Acme is headquartered in Austin, Texas.
    Industry: manufacturing.
    200 employees.
    Products include industrial widgets and sensors.
    Founded in 2011.
  </body>
</html>
"""

HOME_HTML = """
<html>
  <body>
    Welcome to Acme.
    <a href="/about">About us</a>
  </body>
</html>
"""

ABOUT_HTML = """
<html>
  <body>
    Acme is headquartered in Austin, Texas.
    200 employees.
    Products include industrial widgets and sensors.
    Founded in 2011.
    Industry: manufacturing.
  </body>
</html>
"""


def _pages(mapping: dict[str, str]):
    async def fetch_page(url: str, **kwargs) -> str:
        if url in mapping:
            return mapping[url]
        raise ValueError(f"missing page {url}")

    return fetch_page


async def test_website_docs_extracts_company_fields() -> None:
    tool = WebsiteDocsTool(
        fetch_page=_pages({"https://acme.example": ACME_HTML}),
        is_safe_url=lambda url: True,
        tavily=FakeTavilyClient(),
        max_pages=1,
    )
    result = await tool.execute(
        ToolRequest(
            company_name="Acme",
            company_domain="acme.example",
            website_url="https://acme.example",
        )
    )
    company = result.patch.company
    assert result.success
    assert company.name.status == ParameterStatus.supported
    assert company.domain.value == "acme.example"
    assert company.headquarters.value and "Austin" in company.headquarters.value
    assert company.size.value and "200" in company.size.value
    assert company.industry.value and "manufacturing" in company.industry.value.lower()
    assert company.products.value and "widgets" in company.products.value
    assert company.founded.value == "2011"
    assert result.patch.signals.funding.status == ParameterStatus.unknown
    assert result.patch.news == []
    assert result.patch.people == []
    assert all(item.field_key.startswith("company.") for item in result.evidence)


async def test_website_docs_reads_inner_pages_for_missing_fields() -> None:
    tool = WebsiteDocsTool(
        fetch_page=_pages(
            {
                "https://acme.example": HOME_HTML,
                "https://acme.example/about": ABOUT_HTML,
            }
        ),
        is_safe_url=lambda url: True,
        tavily=FakeTavilyClient(),
        max_pages=8,
    )
    result = await tool.execute(
        ToolRequest(
            company_name="Acme",
            company_domain="acme.example",
            website_url="https://acme.example",
        )
    )
    company = result.patch.company
    assert company.headquarters.value and "Austin" in company.headquarters.value
    assert company.size.status == ParameterStatus.supported
    assert company.products.status == ParameterStatus.supported
    assert company.founded.value == "2011"
    about_used = any(
        item.source_url and item.source_url.endswith("/about") for item in result.evidence
    )
    assert about_used


async def test_website_docs_uses_site_search_then_fetches_same_domain() -> None:
    tavily = FakeTavilyClient(
        hits_by_keyword={
            "headquarters": [
                TavilyHit(
                    title="Acme offices",
                    url="https://acme.example/locations",
                    content="Visit our offices",
                )
            ]
        }
    )

    async def fetch_page(url: str, **kwargs) -> str:
        if url.endswith("/locations"):
            return "<html><body>Acme is headquartered in Denver, Colorado.</body></html>"
        return "<html><body>Welcome to Acme.</body></html>"

    tool = WebsiteDocsTool(
        fetch_page=fetch_page,
        is_safe_url=lambda url: True,
        tavily=tavily,
        max_pages=8,
    )
    result = await tool.execute(
        ToolRequest(
            company_name="Acme",
            company_domain="acme.example",
            website_url="https://acme.example",
        )
    )
    assert result.patch.company.headquarters.value and "Denver" in result.patch.company.headquarters.value
    assert any("site:acme.example" in query for query, _ in tavily.calls)


async def test_website_docs_uses_uploaded_text() -> None:
    tool = WebsiteDocsTool(fetch_page=_unused_fetch, tavily=FakeTavilyClient())
    result = await tool.execute(
        ToolRequest(
            company_name="Acme",
            documents=[
                DocumentInput(
                    filename="profile.txt",
                    text="Acme is based in Denver. 40 employees. Industry: logistics. Founded in 2002.",
                )
            ],
        )
    )
    assert result.patch.company.headquarters.value and "Denver" in result.patch.company.headquarters.value
    assert result.patch.company.size.status == ParameterStatus.supported
    assert result.patch.company.founded.value == "2002"


async def test_website_docs_does_not_invent_missing_fields() -> None:
    tool = WebsiteDocsTool(
        fetch_page=_pages({"https://acme.example": "<html><body>Welcome to our site.</body></html>"}),
        is_safe_url=lambda url: True,
        tavily=FakeTavilyClient(),
        max_pages=1,
    )
    result = await tool.execute(
        ToolRequest(company_name="Acme", website_url="https://acme.example")
    )
    assert result.patch.company.industry.status == ParameterStatus.not_found_this_run
    assert result.patch.company.industry.value is None
    assert result.patch.company.headquarters.value is None


async def test_website_docs_drops_ungrounded_mlx_values() -> None:
    mlx = FakeMlxClient(
        {
            "industry": "quantum computing",
            "headquarters": "Mars Colony",
            "size": "1 million employees",
        }
    )
    tool = WebsiteDocsTool(
        mlx=mlx,
        fetch_page=_pages({"https://acme.example": "<html><body>Acme sells bolts.</body></html>"}),
        is_safe_url=lambda url: True,
        tavily=FakeTavilyClient(),
        max_pages=1,
    )
    result = await tool.execute(
        ToolRequest(company_name="Acme", website_url="https://acme.example")
    )
    assert result.patch.company.industry.value is None
    assert result.patch.company.headquarters.value is None
    assert result.patch.company.size.value is None
    assert mlx.calls


async def test_website_docs_skips_blocked_url() -> None:
    called = {"n": 0}

    async def fetch_page(url: str, **kwargs) -> str:
        called["n"] += 1
        raise AssertionError("fetch should not run for blocked URLs")

    tool = WebsiteDocsTool(fetch_page=fetch_page, tavily=FakeTavilyClient())
    result = await tool.execute(
        ToolRequest(company_name="Acme", website_url="http://127.0.0.1/secret")
    )
    assert called["n"] == 0
    assert url_is_public_http("http://127.0.0.1/secret") is False
    assert result.patch.company.name.status == ParameterStatus.not_found_this_run
    assert result.patch.company.industry.value is None


async def _unused_fetch(url: str, **kwargs) -> str:
    raise AssertionError("website should not be fetched when only documents are provided")

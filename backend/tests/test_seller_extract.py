import pytest

from app.application.seller_extract import (
    extract_seller_profile,
    heuristic_seller_fields,
    scrape_seller_site,
)

TEZBYTES_TEXT = """
TezBytes | Workflow Reviews, Automation & Custom Software for Indian MSMEs
BHIVE Premium HSR S6, Bengaluru - 560102, Karnataka, India
See what's really going on. Not what people think is going on.
An Ops Audit maps how work actually moves — who does what, where things get stuck,
and why everyone's chasing updates on WhatsApp.
We don't assume you need new software. The audit ends with a straight recommendation.
Examples of what we build: visit workflows, invoice chasing, lead capture.
TezBytes helps growing teams fix how work actually runs — starting with an Ops Audit,
then automations, custom software, or digital visibility when it makes sense.
TezBytes is an operations-first technology firm in India. We start with an Ops Audit
to map how work actually runs, then deliver workflow automation, custom software,
or digital visibility — only what your business needs.
"""


def test_heuristics_read_fieldaxis_homepage() -> None:
    found = heuristic_seller_fields(
        "FieldAXIS",
        """
        FieldAXIS — Field Operations & Sales Force Automation for Distributors
        Turning field activity into operational intelligence.
        Visits, orders, collections, and dealer context on one timeline — for growing
        networks that have outgrown WhatsApp and Excel but do not want enterprise complexity.
        Field operations on one dealer record. Loyalty for carpenters, painters, and influencers.
        Discovery first — then configuration, training, go-live.
        """,
    )
    assert "Sales Force" in found["products"] or "Field Operations" in found["products"]
    assert found["icp_industries"].lower().startswith("distributor")
    assert "Turning field" in found["description"] or "operational intelligence" in found["description"]


def test_heuristics_fill_seller_fields_from_marketing_copy() -> None:
    found = heuristic_seller_fields("TezBytes", TEZBYTES_TEXT)
    assert found["industry"]
    assert "Ops Audit" in found["products"] or "Automation" in found["products"]
    assert found["services"]
    assert "India" in found["geography"] or "Bengaluru" in found["geography"]
    assert "MSME" in found["icp_industries"] or "MSME" in found.get("icp_size", "")
    assert found["description"]
    assert found["problems_solved"]
    assert found["differentiators"]


@pytest.mark.asyncio
async def test_scrape_and_extract_without_mlx() -> None:
    homepage = """
    <html><head><title>TezBytes | Workflow Reviews, Automation & Custom Software for Indian MSMEs</title></head>
    <body>
    <a href="/about">About</a>
    <p>TezBytes is an operations-first technology firm in India.</p>
    <p>TezBytes helps growing teams fix how work actually runs — starting with an Ops Audit,
    then automations, custom software, or digital visibility.</p>
    <p>BHIVE Premium HSR, Bengaluru, India</p>
    </body></html>
    """
    about = """
    <html><body>
    <p>We start with an Ops Audit to map how work actually runs, then deliver workflow
    automation, custom software, or digital visibility — only what your business needs.</p>
    <p>An Ops Audit maps where things get stuck and why everyone's chasing updates on WhatsApp.</p>
    </body></html>
    """

    async def fake_fetch(url: str, timeout: float, max_bytes: int) -> str:
        if url.rstrip("/").endswith("/about"):
            return about
        return homepage

    text, evidence = await scrape_seller_site(
        "https://tezbytes.dev/",
        fetch_page=fake_fetch,
    )
    assert "Ops Audit" in text
    assert evidence

    profile = await extract_seller_profile(
        {
            "name": "Sandeep",
            "company_name": "Tezbytes Technologies",
            "website_url": "https://tezbytes.dev/",
        },
        mlx=None,
        fetch_page=fake_fetch,
    )
    assert profile.company_name == "Tezbytes Technologies"
    assert profile.products
    assert profile.services
    assert profile.description
    assert profile.industry
    assert profile.geography
    assert profile.icp.target_industries or profile.icp.company_size

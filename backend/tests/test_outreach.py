import pytest

from app.application.outreach import CONNECT_LIMIT, compose_batch, first_name
from app.domain.collected_research import (
    CollectedResearch,
    CompanyBlock,
    FieldValue,
    NewsItem,
    ParameterStatus,
    PersonRecord,
    SignalsBlock,
)
from app.domain.seller_profile import SellerProfile
from app.graphs.outreach import run_outreach


def _supported(value: str) -> FieldValue:
    return FieldValue(value=value, status=ParameterStatus.supported, evidence_ids=["e1"])


def _collected() -> CollectedResearch:
    return CollectedResearch(
        company=CompanyBlock(
            name=_supported("Acme Logistics"),
            description=_supported("Acme runs field technicians across depots."),
            industry=_supported("logistics"),
            products=_supported("depot dispatch"),
        ),
        signals=SignalsBlock(
            hiring=_supported("Hiring field engineers"),
            expansion=_supported("Opened a Pune depot"),
        ),
        news=[
            NewsItem(
                title="Acme opens Pune depot",
                url="https://news.example/acme",
                evidence_id="n1",
            )
        ],
        people=[
            PersonRecord(name="Priya Shah", title="Head of Operations", evidence_id="p1"),
            PersonRecord(name="Ravi Mehta", title="CEO", evidence_id="p2"),
        ],
    )


def _seller() -> SellerProfile:
    return SellerProfile(
        company_name="Tezbytes",
        contact_name="Alex",
        products="FieldAXIS, Field Operations & Sales Force Automation",
        services="field operations automation",
        problems_solved="turning field activity into operational intelligence",
        status="approved",
        version=1,
    )


def test_first_name_skips_honorific() -> None:
    assert first_name("Dr Priya Shah") == "Priya"
    assert first_name("Executive Assistant") == "there"


def test_compose_is_person_specific_and_grounded() -> None:
    drafts, skipped = compose_batch(
        run_id="run-1",
        collected=_collected(),
        seller=_seller(),
        contact_name="Alex",
    )
    assert not skipped
    assert len(drafts) == 2
    ops = next(item for item in drafts if item.person_name == "Priya Shah")
    ceo = next(item for item in drafts if item.person_name == "Ravi Mehta")
    assert len(ops.linkedin_connect) <= CONNECT_LIMIT
    assert "Priya" in ops.linkedin_connect
    assert "FieldAXIS" in ops.linkedin_connect or "Field Operations" in ops.linkedin_connect
    assert "Pune" in ops.linkedin_message or "Hiring" in ops.linkedin_message
    assert "funding" not in ops.linkedin_message.lower()
    assert "WhatsApp" not in ops.whatsapp
    assert "Priya" in ops.whatsapp
    assert "operations" in ops.relevance.lower()
    assert "Ravi" in ceo.linkedin_connect
    assert ceo.linkedin_connect != ops.linkedin_connect
    assert "company motion" in ceo.relevance.lower() or "CEO" in ceo.relevance


@pytest.mark.asyncio
async def test_outreach_graph_writes_drafts_without_db() -> None:
    batch = await run_outreach(
        run_id="run-graph",
        collected=_collected(),
        seller=_seller(),
        contact_name="Alex",
    )
    assert batch.status == "ready"
    assert len(batch.drafts) == 2
    assert all(item.linkedin_connect and item.whatsapp for item in batch.drafts)


@pytest.mark.asyncio
async def test_outreach_graph_empty_without_people() -> None:
    batch = await run_outreach(
        run_id="run-empty",
        collected=CollectedResearch(company=CompanyBlock(name=_supported("Solo Co"))),
        seller=_seller(),
    )
    assert batch.status == "no_recipients"
    assert batch.drafts == []

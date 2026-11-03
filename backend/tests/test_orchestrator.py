from datetime import datetime, timezone

from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.domain.evidence import EvidenceItem, SourceType
from app.domain.collected_research import (
    CollectedResearch,
    CompanyBlock,
    FieldValue,
    NewsItem,
    ParameterStatus,
    PersonRecord,
    SignalsBlock,
)
from app.domain.tool_contract import DocumentInput, ToolRequest, ToolResult
from app.graphs.research import run_research
from app.infrastructure.models.research import EvidenceItemRecord, ResearchRun, Seller
from app.infrastructure.tools.registry import TOOL_NAMES
from tests.conftest import sqlite_session_factory


def _supported(value: str) -> FieldValue:
    return FieldValue(value=value, status=ParameterStatus.supported, evidence_ids=["e1"])


class FakeResearchTool:
    def __init__(self, name: str, patch: CollectedResearch | None = None) -> None:
        self.name = name
        self.version = "1"
        self.fulfills = (name,)
        self.patch = patch or CollectedResearch()
        self.calls: list[ToolRequest] = []

    async def execute(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(success=True, tool_name=self.name, patch=self.patch)


class SequentialSignals(FakeResearchTool):
    def __init__(self) -> None:
        super().__init__("signals")
        self.first = CollectedResearch(
            signals=SignalsBlock(
                hiring=_supported("Acme is hiring engineers"),
                new_product=_supported("Acme launched a routing product"),
            )
        )
        self.retry = CollectedResearch(
            signals=SignalsBlock(funding=FieldValue(status=ParameterStatus.not_found_this_run))
        )

    async def execute(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        patch = self.retry if request.focus == "funding" else self.first
        return ToolResult(success=True, tool_name=self.name, patch=patch)


class SplitWebsite(FakeResearchTool):
    def __init__(self) -> None:
        super().__init__("website_docs")

    async def execute(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        if request.documents or "Seller" in request.company_name:
            patch = CollectedResearch(
                company=CompanyBlock(
                    name=_supported(request.company_name),
                    products=_supported("Seller CRM"),
                    description=_supported("We sell a CRM for freight brokers"),
                )
            )
        else:
            evidence = [
                EvidenceItem(
                    evidence_id="lead-hq",
                    field_key="company.headquarters",
                    extracted_value="Austin",
                    source_type=SourceType.website,
                    retrieved_at=datetime.now(timezone.utc),
                    supporting_excerpt="Acme is headquartered in Austin.",
                )
            ]
            patch = CollectedResearch(
                company=CompanyBlock(
                    name=_supported("Acme"),
                    headquarters=FieldValue(
                        value="Austin",
                        status=ParameterStatus.supported,
                        evidence_ids=["lead-hq"],
                    ),
                ),
                evidence=evidence,
            )
        return ToolResult(success=True, tool_name=self.name, patch=patch)


class SilentModel:
    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return AIMessage(content="stop")


def _base_registry(**overrides) -> dict[str, FakeResearchTool]:
    registry = {
        "signals": FakeResearchTool(
            "signals",
            CollectedResearch(signals=SignalsBlock(hiring=_supported("Acme is hiring"))),
        ),
        "news": FakeResearchTool(
            "news",
            CollectedResearch(
                news=[NewsItem(title="Acme update", url="https://news.example/a", evidence_id="n1")]
            ),
        ),
        "website_docs": FakeResearchTool(
            "website_docs",
            CollectedResearch(
                company=CompanyBlock(
                    name=_supported("Acme"),
                    headquarters=_supported("Austin"),
                )
            ),
        ),
        "people": FakeResearchTool(
            "people",
            CollectedResearch(people=[PersonRecord(name="Ada", title="CTO", evidence_id="p1")]),
        ),
    }
    registry.update(overrides)
    return registry


async def test_first_pass_merges_and_leaves_unsupported_funding() -> None:
    registry = _base_registry()
    state = await run_research(
        ToolRequest(company_name="Acme", company_domain="acme.example"),
        model=SilentModel(),
        registry=registry,
    )
    collected = CollectedResearch.model_validate(state["collected"])
    assert set(state["tools_used"]) == set(TOOL_NAMES)
    assert collected.signals.hiring.value == "Acme is hiring"
    assert collected.company.headquarters.value == "Austin"
    assert collected.people[0].name == "Ada"
    assert collected.signals.funding.status != ParameterStatus.supported
    assert "signals.funding" in collected.missing_parameters()
    funding = next(item for item in state["gap_decisions"] if item["field"] == "signals.funding")
    assert funding["verdict"] == "leave"
    assert state["targeted_attempts"] == {}


async def test_funding_retry_once_then_stays_missing() -> None:
    signals = SequentialSignals()
    registry = _base_registry(signals=signals)
    state = await run_research(
        ToolRequest(company_name="Acme"),
        model=SilentModel(),
        registry=registry,
    )
    collected = CollectedResearch.model_validate(state["collected"])
    assert collected.signals.hiring.status == ParameterStatus.supported
    assert collected.signals.funding.status == ParameterStatus.not_found_this_run
    assert collected.signals.funding.value is None
    assert state["targeted_attempts"]["signals.funding"] == 1
    assert any(call.focus == "funding" for call in signals.calls)
    decision = next(item for item in state["gap_decisions"] if item["field"] == "signals.funding")
    assert decision["retried"] is True
    assert decision["left_missing"] is True
    assert len(signals.calls) >= 2
    assert len([call for call in signals.calls if call.focus == "funding"]) == 1


async def test_seller_docs_do_not_leak_into_lead_company() -> None:
    website = SplitWebsite()
    registry = _base_registry(website_docs=website)
    factory = sqlite_session_factory()
    state = await run_research(
        ToolRequest(company_name="Acme"),
        model=SilentModel(),
        registry=registry,
        session_factory=factory,
        seller_input={
            "name": "Alex",
            "company_name": "Excon Seller Co",
            "website_url": "https://seller.example",
            "approved_profile": {"company_name": "Excon Seller Co", "products": "Seller CRM", "status": "approved"},
        },
    )
    collected = CollectedResearch.model_validate(state["collected"])
    profile = state["seller_profile"]
    assert [item["name"] for item in profile["products"]] == ["Seller CRM"]
    assert website.calls and all(call.company_name == "Acme" for call in website.calls), "seller site is never crawled by research"
    assert collected.company.products.value != "Seller CRM"
    assert collected.company.products.status != ParameterStatus.supported
    assert collected.company.name.value == "Acme"
    assert collected.company.headquarters.value == "Austin"
    session = factory()
    try:
        seller = session.scalar(select(Seller).where(Seller.company_name == "Excon Seller Co"))
        run = session.get(ResearchRun, state["run_id"])
        assert seller is not None
        assert run.seller_profile["products"][0]["name"] == "Seller CRM"
        assert run is not None
        assert run.status in {"partial", "complete"}
        assert run.collected["company"]["products"]["value"] != "Seller CRM"
        evidence_rows = session.scalars(select(EvidenceItemRecord)).all()
        assert evidence_rows
    finally:
        session.close()


class FailingModel:
    """Simulates an unreachable MLX planner — the router must still run every tool."""

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        raise ConnectionError("mlx unreachable")


async def test_planner_failure_falls_back_to_deterministic_router() -> None:
    state = await run_research(
        ToolRequest(company_name="Acme", company_domain="acme.example"),
        model=FailingModel(),
        registry=_base_registry(),
    )
    assert set(state["tools_used"]) == set(TOOL_NAMES)
    assert state["status"] in {"partial", "complete", "running"} or state.get("collected")
    collected = CollectedResearch.model_validate(state["collected"])
    assert collected.company.name.value == "Acme"
    assert collected.people[0].name == "Ada"


async def test_run_row_exists_in_sqlite() -> None:
    factory = sqlite_session_factory()
    state = await run_research(
        ToolRequest(company_name="Acme", company_domain="acme.example"),
        model=SilentModel(),
        registry=_base_registry(),
        session_factory=factory,
    )
    session = factory()
    try:
        run = session.get(ResearchRun, state["run_id"])
        assert run is not None
        assert run.status == "partial"
        assert "signals" in (run.tools_used or [])
        assert run.lead.company_name == "Acme"
        assert run.missing
    finally:
        session.close()


def test_document_input_is_available_for_seller_docs() -> None:
    doc = DocumentInput(filename="pitch.txt", text="We sell logistics software.")
    assert doc.filename == "pitch.txt"
    assert doc.text.startswith("We sell")

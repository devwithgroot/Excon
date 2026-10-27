from langchain_core.messages import AIMessage

from app.graphs.research import next_gap_tool, run_research
from app.domain.collected_research import (
    CollectedResearch,
    CompanyBlock,
    FieldValue,
    NewsItem,
    ParameterStatus,
    PersonRecord,
    SignalsBlock,
)
from app.domain.tool_contract import ToolRequest, ToolResult
from app.infrastructure.tools.registry import TOOL_NAMES


def _supported(value: str) -> FieldValue:
    return FieldValue(value=value, status=ParameterStatus.supported, evidence_ids=["e1"])


class FakeResearchTool:
    def __init__(self, name: str, patch: CollectedResearch) -> None:
        self.name = name
        self.version = "1"
        self.fulfills = (name,)
        self.patch = patch
        self.calls: list[ToolRequest] = []

    async def execute(self, request: ToolRequest) -> ToolResult:
        self.calls.append(request)
        return ToolResult(success=True, tool_name=self.name, patch=self.patch)


class SilentModel:
    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        return AIMessage(content="stop")


class OneShotAllToolsModel:
    def __init__(self) -> None:
        self.calls = 0

    def bind_tools(self, tools):
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls > 1:
            return AIMessage(content="done")
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "args": {
                        "company_name": "Acme",
                        "company_domain": "acme.example",
                        "website_url": "https://acme.example",
                    },
                    "id": f"call-{name}",
                    "type": "tool_call",
                }
                for name in TOOL_NAMES
            ],
        )


def _registry() -> dict[str, FakeResearchTool]:
    return {
        "signals": FakeResearchTool(
            "signals",
            CollectedResearch(
                signals=SignalsBlock(hiring=_supported("Acme is hiring")),
            ),
        ),
        "news": FakeResearchTool(
            "news",
            CollectedResearch(
                news=[
                    NewsItem(
                        title="Acme update",
                        url="https://news.example/a",
                        evidence_id="n1",
                    )
                ]
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
            CollectedResearch(
                people=[PersonRecord(name="Ada", title="CTO", evidence_id="p1")]
            ),
        ),
    }


def test_next_gap_tool_picks_unused_owner_of_missing_field() -> None:
    assert next_gap_tool(["signals.funding", "people"], ["signals"]) == "people"
    assert next_gap_tool(["company.headquarters"], []) == "website_docs"
    assert next_gap_tool(["news"], list(TOOL_NAMES)) is None


async def test_graph_gap_router_runs_all_tools_when_llm_does_not_call() -> None:
    registry = _registry()
    state = await run_research(
        ToolRequest(company_name="Acme", company_domain="acme.example"),
        model=SilentModel(),
        registry=registry,
    )
    assert set(state["tools_used"]) == set(TOOL_NAMES)
    collected = CollectedResearch.model_validate(state["collected"])
    assert collected.signals.hiring.value == "Acme is hiring"
    assert collected.company.name.value == "Acme"
    assert collected.news
    assert collected.people[0].name == "Ada"
    assert "signals.funding" in collected.missing_parameters()
    assert "people" not in collected.missing_parameters()
    for tool in registry.values():
        assert tool.calls
        assert tool.calls[0].company_name == "Acme"


async def test_graph_agent_tool_calls_are_merged() -> None:
    registry = _registry()
    state = await run_research(
        ToolRequest(
            company_name="Acme",
            company_domain="acme.example",
            website_url="https://acme.example",
        ),
        model=OneShotAllToolsModel(),
        registry=registry,
    )
    assert set(state["tools_used"]) == set(TOOL_NAMES)
    collected = CollectedResearch.model_validate(state["collected"])
    assert collected.company.headquarters.value == "Austin"
    assert len(collected.people) == 1

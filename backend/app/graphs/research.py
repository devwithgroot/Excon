from __future__ import annotations

import json
import os
from typing import Annotated, Any, Literal
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from sqlalchemy.orm import sessionmaker
from typing_extensions import TypedDict

from app.application.gap_judge import judge_gaps, retry_decision
from app.application.seller_intel.profile_builder import domain_from_url, minimal_profile
from app.config import get_settings
from app.domain.collected_research import CollectedResearch
from app.domain.gap import GapDecision, GapVerdict
from app.domain.merge import merge_research
from app.domain.seller_profile import SellerProfile
from app.domain.tool_contract import ToolRequest
from app.infrastructure.repositories.research import ResearchStore
from app.tools import TOOL_NAMES, research_tools

os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

MAX_LLM_CALLS = 8

SYSTEM = """You are the Excon research orchestrator.
You NEVER invent company facts, emails, phones, funding, or dates.
You only call LangChain tools. Tools return evidence-backed fields or leave them missing.

Company: {company_name}
Domain: {company_domain}
Website: {website_url}
Already used tools: {used}
Still missing: {missing}

Rules:
- Call unused tools that can fill missing fields.
- Each first-pass tool at most once.
- After the tools have run, stop. Do not fill gaps yourself.
- If a tool found nothing, that field stays missing.
"""

GAP_FOR = {
    "signals": "signals.",
    "news": "news",
    "website_docs": "company.",
    "people": "people",
}


class ResearchState(TypedDict):
    messages: Annotated[list, add_messages]
    run_id: str | None
    seller_id: str | None
    lead_id: str | None
    company_name: str
    company_domain: str | None
    website_url: str | None
    seller_input: dict | None
    seller_profile: dict | None
    collected: dict
    missing: list[str]
    tools_used: list[str]
    targeted_attempts: dict
    gap_decisions: list[dict]
    llm_calls: int
    status: str
    error: str | None


def research_llm():
    settings = get_settings()
    return ChatOpenAI(
        base_url=f"{settings.mlx_base_url.rstrip('/')}/v1",
        api_key="mlx",
        model=settings.mlx_model,
        temperature=0,
    )


def next_gap_tool(missing: list[str], used: list[str]) -> str | None:
    for name in TOOL_NAMES:
        if name in used:
            continue
        needle = GAP_FOR[name]
        if any(item == needle or item.startswith(needle) for item in missing):
            return name
    for name in TOOL_NAMES:
        if name not in used:
            return name
    return None


def _tool_args(call: Any) -> tuple[str, dict, str]:
    name = call["name"] if isinstance(call, dict) else call["name"]
    args = call["args"] if isinstance(call, dict) else call["args"]
    call_id = call["id"] if isinstance(call, dict) else call["id"]
    return name, args or {}, call_id


def _lead_args(state: ResearchState, focus: str = "") -> dict:
    return {
        "company_name": state["company_name"],
        "company_domain": state.get("company_domain") or "",
        "website_url": state.get("website_url") or "",
        "focus": focus,
    }


def build_research_graph(
    model: Any | None = None,
    registry: dict | None = None,
    session_factory: sessionmaker | None = None,
    classify: Any | None = None,
    mlx: Any | None = None,
):
    tools = research_tools(registry)
    tools_by_name = {tool.name: tool for tool in tools}
    llm = model or research_llm()
    bound = llm.bind_tools(tools)

    def _open_store() -> tuple[Any, ResearchStore] | tuple[None, None]:
        if session_factory is None:
            return None, None
        session = session_factory()
        return session, ResearchStore(session)

    def create_run(state: ResearchState) -> dict:
        if session_factory is None:
            return {"run_id": state.get("run_id") or str(uuid4()), "status": "running"}
        session, store = _open_store()
        assert store is not None
        try:
            seller = None
            seller_input = state.get("seller_input") or {}
            if seller_input.get("seller_id"):
                seller = store.get_seller(seller_input["seller_id"])
            elif seller_input.get("company_name"):
                seller = store.create_seller(
                    company_name=seller_input["company_name"],
                    name=seller_input.get("name"),
                    website_url=seller_input.get("website_url"),
                )
                profile = seller_input.get("approved_profile") or minimal_profile(seller_input).model_dump(mode="json")
                seller.profile = profile
            lead = store.create_lead(
                company_name=state["company_name"],
                domain=state.get("company_domain"),
                website_url=state.get("website_url"),
            )
            run = store.create_run(
                lead=lead,
                seller=seller,
                collected=state.get("collected"),
            )
            session.commit()
            return {
                "run_id": run.id,
                "seller_id": seller.id if seller else None,
                "lead_id": lead.id,
                "status": "running",
            }
        except Exception as exc:
            session.rollback()
            return {"status": "failed", "error": str(exc), "run_id": state.get("run_id") or str(uuid4())}
        finally:
            session.close()

    async def seller_profile(state: ResearchState) -> dict:
        seller_input = state.get("seller_input") or {}
        if seller_input.get("approved_profile"):
            approved = SellerProfile.model_validate(seller_input["approved_profile"])
            dumped = approved.model_dump(mode="json")
            return {"seller_profile": dumped}
        if not seller_input.get("company_name"):
            return {"seller_profile": None}
        return {"seller_profile": minimal_profile(seller_input).model_dump(mode="json")}

    async def plan_or_llm(state: ResearchState) -> dict:
        collected = CollectedResearch.model_validate(state["collected"])
        system = SystemMessage(
            content=SYSTEM.format(
                company_name=state["company_name"],
                company_domain=state.get("company_domain") or "",
                website_url=state.get("website_url") or "",
                used=", ".join(state.get("tools_used") or []) or "(none)",
                missing=", ".join(collected.missing_parameters()) or "(none)",
            )
        )
        response = await bound.ainvoke([system, *state["messages"]])
        return {"messages": [response], "llm_calls": state.get("llm_calls", 0) + 1}

    async def tool_node(state: ResearchState) -> dict:
        last = state["messages"][-1]
        collected = CollectedResearch.model_validate(state["collected"])
        used = list(state.get("tools_used") or [])
        messages: list[ToolMessage] = []
        for call in getattr(last, "tool_calls", []) or []:
            name, args, call_id = _tool_args(call)
            if name in used or name not in tools_by_name:
                messages.append(
                    ToolMessage(
                        content=json.dumps({"skipped": True, "reason": "already_used_or_unknown"}),
                        tool_call_id=call_id,
                    )
                )
                continue
            raw = await tools_by_name[name].ainvoke(args)
            payload = json.loads(raw) if isinstance(raw, str) else raw
            patch = CollectedResearch.model_validate(payload.get("patch") or {})
            collected = merge_research(collected, patch)
            used.append(name)
            messages.append(
                ToolMessage(
                    content=json.dumps(payload.get("summary") or {"success": payload.get("success")}),
                    tool_call_id=call_id,
                )
            )
        return {
            "messages": messages,
            "collected": collected.model_dump(mode="json"),
            "missing": collected.missing_parameters(),
            "tools_used": used,
        }

    def first_pass_router(state: ResearchState) -> dict:
        nxt = next_gap_tool(state.get("missing") or [], state.get("tools_used") or [])
        if not nxt:
            return {}
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": nxt,
                            "args": _lead_args(state),
                            "id": f"gap-{nxt}",
                            "type": "tool_call",
                        }
                    ],
                )
            ]
        }

    async def gap_judge(state: ResearchState) -> dict:
        collected = CollectedResearch.model_validate(state["collected"])
        decisions = await judge_gaps(
            collected,
            company_name=state.get("company_name"),
            website_url=state.get("website_url"),
            targeted_attempts=state.get("targeted_attempts") or {},
            classify=classify,
            mlx=mlx,
        )
        return {"gap_decisions": [item.model_dump(mode="json") for item in decisions]}

    async def targeted_tool(state: ResearchState) -> dict:
        collected = CollectedResearch.model_validate(state["collected"])
        decisions = [GapDecision.model_validate(item) for item in state.get("gap_decisions") or []]
        chosen = retry_decision(decisions)
        attempts = dict(state.get("targeted_attempts") or {})
        if chosen is None or not chosen.tool_name or chosen.tool_name not in tools_by_name:
            return {
                "gap_decisions": [item.model_dump(mode="json") for item in decisions],
                "targeted_attempts": attempts,
            }
        raw = await tools_by_name[chosen.tool_name].ainvoke(
            _lead_args(state, focus=chosen.focus or "")
        )
        payload = json.loads(raw) if isinstance(raw, str) else raw
        patch = CollectedResearch.model_validate((payload or {}).get("patch") or {})
        collected = merge_research(collected, patch)
        attempts[chosen.field] = attempts.get(chosen.field, 0) + 1
        still_missing = chosen.field in collected.missing_parameters()
        updated: list[GapDecision] = []
        for decision in decisions:
            if decision.field != chosen.field:
                updated.append(decision)
                continue
            updated.append(
                decision.model_copy(
                    update={
                        "retried": True,
                        "left_missing": still_missing,
                        "reason": (
                            "Retried; still empty."
                            if still_missing
                            else "Retried; the targeted tool found supporting evidence."
                        ),
                        "verdict": GapVerdict.leave if still_missing else decision.verdict,
                    }
                )
            )
        return {
            "collected": collected.model_dump(mode="json"),
            "missing": collected.missing_parameters(),
            "targeted_attempts": attempts,
            "gap_decisions": [item.model_dump(mode="json") for item in updated],
        }

    def persist(state: ResearchState) -> dict:
        collected = CollectedResearch.model_validate(state["collected"])
        missing = collected.missing_parameters()
        status = state.get("status") or "running"
        if status != "failed":
            status = "complete" if not missing else "partial"
        if session_factory is None or not state.get("run_id"):
            return {"status": status, "missing": missing}
        session, store = _open_store()
        assert store is not None
        try:
            store.persist_run(
                state["run_id"],
                status=status,
                collected=collected,
                tools_used=list(state.get("tools_used") or []),
                gap_decisions=list(state.get("gap_decisions") or []),
                targeted_attempts=dict(state.get("targeted_attempts") or {}),
                seller_profile=state.get("seller_profile"),
                error=state.get("error"),
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            return {"status": "failed", "error": str(exc), "missing": missing}
        finally:
            session.close()
        return {"status": status, "missing": missing}

    def after_create(state: ResearchState) -> Literal["seller_profile", "persist"]:
        if state.get("status") == "failed":
            return "persist"
        return "seller_profile"

    def after_plan(state: ResearchState) -> Literal["tool_node", "first_pass_router", "gap_judge"]:
        if state.get("llm_calls", 0) >= MAX_LLM_CALLS:
            unused = [name for name in TOOL_NAMES if name not in (state.get("tools_used") or [])]
            if unused and state.get("missing"):
                return "first_pass_router"
            return "gap_judge"
        last = state["messages"][-1] if state.get("messages") else None
        if last is not None and getattr(last, "tool_calls", None):
            return "tool_node"
        unused = [name for name in TOOL_NAMES if name not in (state.get("tools_used") or [])]
        if unused and state.get("missing"):
            return "first_pass_router"
        return "gap_judge"

    def after_judge(state: ResearchState) -> Literal["targeted_tool", "persist"]:
        decisions = [GapDecision.model_validate(item) for item in state.get("gap_decisions") or []]
        if retry_decision(decisions):
            return "targeted_tool"
        return "persist"

    graph = StateGraph(ResearchState)
    graph.add_node("create_run", create_run)
    graph.add_node("seller_profile", seller_profile)
    graph.add_node("plan_or_llm", plan_or_llm)
    graph.add_node("tool_node", tool_node)
    graph.add_node("first_pass_router", first_pass_router)
    graph.add_node("gap_judge", gap_judge)
    graph.add_node("targeted_tool", targeted_tool)
    graph.add_node("persist", persist)
    graph.add_edge(START, "create_run")
    graph.add_conditional_edges(
        "create_run",
        after_create,
        {"seller_profile": "seller_profile", "persist": "persist"},
    )
    graph.add_edge("seller_profile", "plan_or_llm")
    graph.add_conditional_edges(
        "plan_or_llm",
        after_plan,
        {
            "tool_node": "tool_node",
            "first_pass_router": "first_pass_router",
            "gap_judge": "gap_judge",
        },
    )
    graph.add_edge("tool_node", "plan_or_llm")
    graph.add_edge("first_pass_router", "tool_node")
    graph.add_conditional_edges(
        "gap_judge",
        after_judge,
        {"targeted_tool": "targeted_tool", "persist": "persist"},
    )
    graph.add_edge("targeted_tool", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


def _initial_state(
    request: ToolRequest,
    seller_input: dict | None = None,
) -> ResearchState:
    empty = CollectedResearch()
    domain = request.company_domain or domain_from_url(request.website_url)
    return {
        "messages": [
            HumanMessage(
                content=(
                    f"Research {request.company_name}. "
                    f"Domain: {domain or 'unknown'}. "
                    f"Website: {request.website_url or 'unknown'}."
                )
            )
        ],
        "run_id": None,
        "seller_id": None,
        "lead_id": None,
        "company_name": request.company_name,
        "company_domain": domain,
        "website_url": request.website_url,
        "seller_input": seller_input,
        "seller_profile": None,
        "collected": empty.model_dump(mode="json"),
        "missing": empty.missing_parameters(),
        "tools_used": [],
        "targeted_attempts": {},
        "gap_decisions": [],
        "llm_calls": 0,
        "status": "running",
        "error": None,
    }


async def run_research(
    request: ToolRequest,
    *,
    model: Any | None = None,
    registry: dict | None = None,
    seller_input: dict | None = None,
    session_factory: sessionmaker | None = None,
    classify: Any | None = None,
    mlx: Any | None = None,
) -> ResearchState:
    graph = build_research_graph(
        model=model,
        registry=registry,
        session_factory=session_factory,
        classify=classify,
        mlx=mlx,
    )
    return await graph.ainvoke(_initial_state(request, seller_input=seller_input))

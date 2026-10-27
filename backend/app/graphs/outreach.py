from __future__ import annotations

from typing import Any
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import sessionmaker
from typing_extensions import TypedDict

from app.application.outreach import compose_batch
from app.domain.collected_research import CollectedResearch
from app.domain.outreach import OutreachBatch, OutreachDraft
from app.domain.report import LeadReportBody
from app.domain.seller_profile import SellerProfile
from app.infrastructure.repositories.research import ResearchStore


class OutreachState(TypedDict):
    run_id: str
    seller_id: str | None
    contact_name: str | None
    lead_name: str | None
    seller: dict | None
    collected: dict
    report: dict | None
    drafts: list[dict]
    skipped: list[dict]
    status: str
    error: str | None


def build_outreach_graph(session_factory: sessionmaker | None = None):
    """LangGraph agent: pick people, write grounded drafts, validate, persist."""

    def _open_store() -> tuple[Any, ResearchStore] | tuple[None, None]:
        if session_factory is None:
            return None, None
        session = session_factory()
        return session, ResearchStore(session)

    def select_and_compose(state: OutreachState) -> dict:
        collected = CollectedResearch.model_validate(state.get("collected") or {})
        seller = (
            SellerProfile.model_validate(state["seller"]) if state.get("seller") else None
        )
        report = (
            LeadReportBody.model_validate(state["report"]) if state.get("report") else None
        )
        if not collected.people:
            return {
                "drafts": [],
                "skipped": [],
                "status": "no_recipients",
                "error": "No decision-makers were found on this run, so there is no one to write to.",
            }
        drafts, skipped = compose_batch(
            run_id=state["run_id"],
            collected=collected,
            seller=seller,
            seller_id=state.get("seller_id"),
            report=report,
            contact_name=state.get("contact_name"),
            lead_name=state.get("lead_name"),
        )
        return {
            "drafts": [item.model_dump(mode="json") for item in drafts],
            "skipped": skipped,
            "status": "composed" if drafts else "no_recipients",
            "error": None
            if drafts
            else "People were found, but no usable drafts could be validated.",
        }

    def persist(state: OutreachState) -> dict:
        drafts = [OutreachDraft.model_validate(item) for item in state.get("drafts") or []]
        status = state.get("status") or "composed"
        if status == "no_recipients":
            return {"status": status}
        if session_factory is None or not state.get("run_id"):
            return {"status": "ready", "drafts": [item.model_dump(mode="json") for item in drafts]}
        session, store = _open_store()
        assert store is not None
        try:
            stored: list[dict] = []
            for draft in drafts:
                row = store.upsert_draft(draft)
                payload = dict(row.body or draft.model_dump(mode="json"))
                payload["draft_id"] = row.id
                payload["status"] = row.status
                payload["version"] = row.version
                stored.append(payload)
            session.commit()
            return {"status": "ready", "drafts": stored}
        except Exception as exc:
            session.rollback()
            return {"status": "failed", "error": str(exc)}
        finally:
            session.close()

    graph = StateGraph(OutreachState)
    graph.add_node("select_and_compose", select_and_compose)
    graph.add_node("persist", persist)
    graph.add_edge(START, "select_and_compose")
    graph.add_edge("select_and_compose", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


def _initial_state(
    *,
    run_id: str,
    collected: CollectedResearch,
    seller: SellerProfile | None,
    seller_id: str | None,
    report: LeadReportBody | None,
    contact_name: str | None,
    lead_name: str | None,
) -> OutreachState:
    return {
        "run_id": run_id,
        "seller_id": seller_id,
        "contact_name": contact_name,
        "lead_name": lead_name,
        "seller": seller.model_dump(mode="json") if seller else None,
        "collected": collected.model_dump(mode="json"),
        "report": report.model_dump(mode="json") if report else None,
        "drafts": [],
        "skipped": [],
        "status": "running",
        "error": None,
    }


async def run_outreach(
    *,
    run_id: str,
    collected: CollectedResearch,
    seller: SellerProfile | None = None,
    seller_id: str | None = None,
    report: LeadReportBody | None = None,
    contact_name: str | None = None,
    lead_name: str | None = None,
    session_factory: sessionmaker | None = None,
) -> OutreachBatch:
    graph = build_outreach_graph(session_factory=session_factory)
    state = await graph.ainvoke(
        _initial_state(
            run_id=run_id or str(uuid4()),
            collected=collected,
            seller=seller,
            seller_id=seller_id,
            report=report,
            contact_name=contact_name,
            lead_name=lead_name,
        )
    )
    drafts = [OutreachDraft.model_validate(item) for item in state.get("drafts") or []]
    return OutreachBatch(
        run_id=state.get("run_id") or run_id,
        status=state.get("status") or "ready",
        drafts=drafts,
        skipped=list(state.get("skipped") or []),
        error=state.get("error"),
    )

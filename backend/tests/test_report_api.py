from fastapi.testclient import TestClient

from app.domain.collected_research import (
    CollectedResearch,
    CompanyBlock,
    FieldValue,
    ParameterStatus,
    SignalsBlock,
)
from app.domain.report import LeadReportBody, LeadScores, ScoreBreakdown
from app.domain.seller_profile import SellerProfile
from app.infrastructure.models.research import Lead, ResearchRun, Seller
from app.main import app
from tests.conftest import sqlite_session_factory


def _score() -> LeadScores:
    block = ScoreBreakdown(key="x", label="X", score=70, reasons=["ok"])
    return LeadScores(
        completeness=block,
        evidence_quality=block,
        qualification=block.model_copy(update={"key": "qualification", "label": "Lead qualification"}),
        fit=block.model_copy(update={"key": "fit", "label": "Seller–lead fit"}),
        contact_relevance=block.model_copy(update={"key": "contact_relevance", "label": "Contact relevance"}),
        overall=68,
        recommendation="pursue",
        recommendation_reason="Fit and motion are strong.",
    )


def test_report_is_persisted_for_a_run(monkeypatch) -> None:
    factory = sqlite_session_factory()
    session = factory()
    seller = Seller(
        company_name="Excon Seller Co",
        name="Alex",
        profile={"company_name": "Excon Seller Co", "products": "payments"},
        approved_profile=SellerProfile(
            company_name="Excon Seller Co",
            products="payments billing",
            status="approved",
            version=1,
        ).model_dump(mode="json"),
        approved_version=1,
        status="approved",
    )
    lead = Lead(company_name="Stripe", domain="stripe.com")
    session.add_all([seller, lead])
    session.flush()
    run = ResearchRun(
        seller_id=seller.id,
        lead_id=lead.id,
        status="partial",
        collected=CollectedResearch(
            company=CompanyBlock(
                name=FieldValue(value="Stripe", status=ParameterStatus.supported, evidence_ids=["e1"])
            ),
            signals=SignalsBlock(
                hiring=FieldValue(value="hiring", status=ParameterStatus.supported, evidence_ids=["e2"])
            ),
        ).model_dump(mode="json"),
        missing=["company.size"],
        tools_used=["signals"],
        gap_decisions=[],
        targeted_attempts={},
        seller_profile=seller.approved_profile,
    )
    session.add(run)
    session.commit()
    run_id = run.id
    session.close()

    async def fake_report(collected, seller_profile, **kwargs):
        return LeadReportBody(
            report_id="rep-1",
            run_id=kwargs["run_id"],
            seller_id=kwargs.get("seller_id"),
            seller_version=1,
            scores=_score(),
            overview="Stripe is worth time.",
            why_fit=["Payments overlap"],
            why_not=["Size unknown"],
            recommended_action="Call the CEO about billing.",
            conversation_angle="Lead with payments.",
            gaps=["company.size"],
        )

    monkeypatch.setattr("app.api.routes.reports.build_lead_report", fake_report)

    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    from app.infrastructure.database import get_db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    try:
        created = client.post(f"/research/runs/{run_id}/report")
        assert created.status_code == 200
        assert created.json()["scores"]["recommendation"] == "pursue"
        assert created.json()["why_fit"]
        fetched = client.get(f"/research/runs/{run_id}/report")
        assert fetched.status_code == 200
        assert fetched.json()["overview"] == "Stripe is worth time."
    finally:
        app.dependency_overrides.clear()

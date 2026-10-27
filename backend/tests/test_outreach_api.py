from fastapi.testclient import TestClient

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
from app.infrastructure.models.research import Lead, ResearchRun, Seller
from app.main import app
from tests.conftest import sqlite_session_factory


def _supported(value: str) -> FieldValue:
    return FieldValue(value=value, status=ParameterStatus.supported, evidence_ids=["e1"])


def test_generate_edit_and_approve_drafts(monkeypatch) -> None:
    factory = sqlite_session_factory()
    session = factory()
    seller = Seller(
        company_name="Tezbytes",
        name="Alex",
        approved_profile=SellerProfile(
            company_name="Tezbytes",
            contact_name="Alex",
            products="FieldAXIS",
            status="approved",
            version=1,
        ).model_dump(mode="json"),
        approved_version=1,
        status="approved",
    )
    lead = Lead(company_name="Acme Logistics")
    session.add_all([seller, lead])
    session.flush()
    run = ResearchRun(
        seller_id=seller.id,
        lead_id=lead.id,
        status="partial",
        collected=CollectedResearch(
            company=CompanyBlock(
                name=_supported("Acme Logistics"),
                description=_supported("Field technicians across depots."),
            ),
            signals=SignalsBlock(hiring=_supported("Hiring field engineers")),
            news=[NewsItem(title="Acme depot news", url="https://n.example", evidence_id="n1")],
            people=[PersonRecord(name="Priya Shah", title="Head of Operations", evidence_id="p1")],
        ).model_dump(mode="json"),
        missing=[],
        tools_used=["people"],
        gap_decisions=[],
        targeted_attempts={},
        seller_profile=seller.approved_profile,
    )
    session.add(run)
    session.commit()
    run_id = run.id
    session.close()

    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    from app.infrastructure.database import get_db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("app.api.routes.drafts.get_session_factory", lambda: factory)
    client = TestClient(app)
    try:
        created = client.post(f"/research/runs/{run_id}/drafts")
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["drafts"]
        draft = body["drafts"][0]
        assert draft["person_name"] == "Priya Shah"
        assert "Priya" in draft["linkedin_connect"]
        assert draft["whatsapp"]
        listed = client.get(f"/research/runs/{run_id}/drafts")
        assert listed.status_code == 200
        assert listed.json()["drafts"][0]["draft_id"] == draft["draft_id"]
        patched = client.patch(
            f"/drafts/{draft['draft_id']}",
            json={
                "linkedin_connect": "Hi Priya — edited connect.",
                "linkedin_message": "Edited longer note.",
                "whatsapp": "Hi Priya — edited wa.",
            },
        )
        assert patched.status_code == 200
        assert patched.json()["linkedin_connect"] == "Hi Priya — edited connect."
        assert patched.json()["version"] >= 2
        approved = client.post(f"/drafts/{draft['draft_id']}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
    finally:
        app.dependency_overrides.clear()

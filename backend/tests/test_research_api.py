from fastapi.testclient import TestClient

from app.domain.collected_research import CollectedResearch
from app.domain.seller_profile import SellerProfile
from app.infrastructure.models.research import Seller
from app.main import app
from tests.conftest import sqlite_session_factory


def _override(factory):
    def override_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    from app.infrastructure.database import get_db

    app.dependency_overrides[get_db] = override_db


def test_create_and_get_research_run(monkeypatch) -> None:
    factory = sqlite_session_factory()

    async def fake_run(request, **kwargs):
        from app.graphs.research import run_research
        from tests.test_orchestrator import SilentModel, _base_registry

        return await run_research(
            request,
            model=SilentModel(),
            registry=_base_registry(),
            seller_input=kwargs.get("seller_input"),
            session_factory=factory,
        )

    monkeypatch.setattr("app.api.routes.research.run_research", fake_run)
    monkeypatch.setattr("app.api.routes.research.get_session_factory", lambda: factory)
    _override(factory)
    client = TestClient(app)
    try:
        response = client.post(
            "/research/runs",
            json={
                "lead": {"company_name": "Acme", "company_domain": "acme.example"},
                "seller": {"company_name": "Excon Seller Co", "name": "Alex"},
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["run_id"]
        assert body["status"] in {"partial", "complete"}
        assert body["lead"]["company_name"] == "Acme"
        collected = CollectedResearch.model_validate(body["collected"])
        assert collected.company.name.value == "Acme"
        fetched = client.get(f"/research/runs/{body['run_id']}")
        assert fetched.status_code == 200
        assert fetched.json()["run_id"] == body["run_id"]
        assert fetched.json()["tools_used"]
    finally:
        app.dependency_overrides.clear()


def test_seller_id_requires_approved_profile(monkeypatch) -> None:
    factory = sqlite_session_factory()
    session = factory()
    draft = Seller(
        company_name="Draft Co",
        name="Alex",
        profile={"company_name": "Draft Co", "status": "draft"},
        status="draft",
    )
    approved = Seller(
        company_name="Approved Co",
        name="Alex",
        profile={"company_name": "Approved Co", "products": [{"name": "CRM"}], "status": "approved", "version": 1},
        approved_profile=SellerProfile(
            company_name="Approved Co",
            products="CRM",
            status="approved",
            version=1,
        ).model_dump(mode="json"),
        approved_version=1,
        status="approved",
    )
    session.add_all([draft, approved])
    session.commit()
    draft_id, approved_id = draft.id, approved.id
    session.close()

    captured: dict = {}

    async def fake_run(request, **kwargs):
        captured["seller_input"] = kwargs.get("seller_input")
        from app.graphs.research import run_research
        from tests.test_orchestrator import SilentModel, _base_registry

        return await run_research(
            request,
            model=SilentModel(),
            registry=_base_registry(),
            seller_input=kwargs.get("seller_input"),
            session_factory=factory,
        )

    monkeypatch.setattr("app.api.routes.research.run_research", fake_run)
    monkeypatch.setattr("app.api.routes.research.get_session_factory", lambda: factory)
    _override(factory)
    client = TestClient(app)
    try:
        missing = client.post(
            "/research/runs",
            json={"lead": {"company_name": "Acme"}, "seller_id": "does-not-exist"},
        )
        assert missing.status_code == 404

        blocked = client.post(
            "/research/runs",
            json={"lead": {"company_name": "Acme"}, "seller_id": draft_id},
        )
        assert blocked.status_code == 409
        assert "Approve" in blocked.json()["detail"]

        ok = client.post(
            "/research/runs",
            json={"lead": {"company_name": "Acme", "website_url": "https://acme.example"}, "seller_id": approved_id},
        )
        assert ok.status_code == 200, ok.text
        assert captured["seller_input"]["seller_id"] == approved_id
        assert captured["seller_input"]["approved_profile"]["company_name"] == "Approved Co"
        assert [item["name"] for item in ok.json()["seller_profile"]["products"]] == ["CRM"]
        assert ok.json()["lead"]["company_domain"] == "acme.example"
    finally:
        app.dependency_overrides.clear()


def test_get_missing_run_is_404(monkeypatch) -> None:
    factory = sqlite_session_factory()
    _override(factory)
    client = TestClient(app)
    try:
        response = client.get("/research/runs/does-not-exist")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()

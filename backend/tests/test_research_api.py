from fastapi.testclient import TestClient

from app.domain.collected_research import CollectedResearch
from app.main import app
from tests.conftest import sqlite_session_factory


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


def test_get_missing_run_is_404(monkeypatch) -> None:
    factory = sqlite_session_factory()

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
        response = client.get("/research/runs/does-not-exist")
        assert response.status_code == 404
    finally:
        app.dependency_overrides.clear()

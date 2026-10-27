from fastapi.testclient import TestClient

from app.domain.seller_profile import SellerProfile
from app.main import app
from tests.conftest import sqlite_session_factory


def test_extract_patch_approve_does_not_auto_approve(monkeypatch) -> None:
    factory = sqlite_session_factory()

    async def fake_extract(seller_input, **kwargs):
        return SellerProfile(
            company_name=seller_input["company_name"],
            products="Freight CRM",
            description="We sell a CRM for brokers",
            status="draft",
        )

    monkeypatch.setattr("app.api.routes.sellers.extract_seller_profile", fake_extract)
    monkeypatch.setattr("app.api.routes.sellers.get_session_factory", lambda: factory)

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
        created = client.post(
            "/sellers/extract",
            json={"name": "Alex", "company_name": "Excon Seller Co", "website_url": "https://seller.example"},
        )
        assert created.status_code == 200
        body = created.json()
        assert body["status"] == "draft"
        assert body["approved"] is None
        assert body["draft"]["products"] == "Freight CRM"
        seller_id = body["seller_id"]

        draft = body["draft"]
        draft["products"] = "Freight CRM and dispatch"
        draft["icp"]["target_industries"] = "logistics"
        patched = client.patch(f"/sellers/{seller_id}/draft", json={"profile": draft})
        assert patched.status_code == 200
        assert patched.json()["draft"]["products"] == "Freight CRM and dispatch"
        assert patched.json()["status"] == "draft"

        approved = client.post(f"/sellers/{seller_id}/approve")
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        assert approved.json()["approved_version"] == 1
        assert approved.json()["approved"]["products"] == "Freight CRM and dispatch"
        assert approved.json()["approved"]["icp"]["target_industries"] == "logistics"

        fetched = client.get(f"/sellers/{seller_id}")
        assert fetched.json()["approved"]["products"] == "Freight CRM and dispatch"

        created = client.post(
            "/sellers",
            json={
                "name": "Alex",
                "company_name": "Quick Seller Co",
                "website_url": "https://quick.example",
                "profile": {
                    "company_name": "Quick Seller Co",
                    "products": "Yard cameras",
                    "icp": {"target_industries": "warehousing"},
                    "status": "draft",
                    "version": 0,
                },
            },
        )
        assert created.status_code == 200
        assert created.json()["status"] == "draft"
        assert created.json()["draft"]["products"] == "Yard cameras"
        assert created.json()["approved"] is None
    finally:
        app.dependency_overrides.clear()

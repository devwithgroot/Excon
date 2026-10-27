from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_live() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_providers_does_not_leak_secrets() -> None:
    response = client.get("/health/providers")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"mlx_configured", "tavily_configured", "prospeo_configured"}
    assert all(isinstance(value, bool) for value in body.values())
    dumped = response.text.lower()
    assert "api_key" not in dumped
    assert "tvly-" not in dumped
    assert "pk_" not in dumped

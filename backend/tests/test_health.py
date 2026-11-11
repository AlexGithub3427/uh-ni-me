from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_f001_health_returns_ok() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_f001_health_is_only_served_under_api_prefix() -> None:
    assert client.get("/health").status_code == 404

"""Tests for routers/health.py."""


class TestHealthEndpoints:
    def test_root(self, client):
        response = client.get("/api/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "AI Recruiter API"
        assert data["status"] == "ok"

    def test_health(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

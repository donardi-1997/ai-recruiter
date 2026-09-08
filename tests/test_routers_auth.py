"""Tests for routers/auth.py."""

from unittest.mock import patch


class TestAuthEndpoints:
    def test_register(self, client):
        with patch("routers.auth.create_user") as mock:
            mock.return_value = {"message": "Usuario creado", "user_sub": "abc"}
            response = client.post(
                "/api/auth/register",
                params={"email": "test@example.com", "password": "Pass123!"},
            )
        assert response.status_code == 200
        data = response.json()
        assert "message" in data

    def test_login_success(self, client):
        with patch("routers.auth.login_user") as mock:
            mock.return_value = {
                "access_token": "at",
                "id_token": "it",
                "refresh_token": "rt",
                "expires_in": 3600,
            }
            response = client.post(
                "/api/auth/login",
                json={"email": "test@example.com", "password": "Pass123!"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "at"

    def test_login_sets_refresh_cookie(self, client):
        with patch("routers.auth.login_user") as mock:
            mock.return_value = {
                "access_token": "at",
                "id_token": "it",
                "refresh_token": "rt",
                "expires_in": 3600,
            }
            response = client.post(
                "/api/auth/login",
                json={"email": "test@example.com", "password": "Pass123!"},
            )
        assert "ai_recruiter_refresh" in response.cookies

    def test_login_failure(self, client):
        with patch("routers.auth.login_user") as mock:
            mock.return_value = {"error": "Credenciales incorrectas"}
            response = client.post(
                "/api/auth/login",
                json={"email": "bad@example.com", "password": "wrong"},
            )
        assert response.status_code == 401

    def test_refresh_no_cookie(self, client):
        response = client.post("/api/auth/refresh")
        assert response.status_code == 401

    def test_refresh_success(self, client):
        with patch("routers.auth.refresh_user") as mock:
            mock.return_value = {"access_token": "new-at", "expires_in": 3600}
            response = client.post(
                "/api/auth/refresh",
                cookies={"ai_recruiter_refresh": "valid-refresh-token"},
            )
        assert response.status_code == 200
        assert response.json()["access_token"] == "new-at"

    def test_logout(self, client):
        response = client.post("/api/auth/logout")
        assert response.status_code == 200
        assert response.json()["logged_out"] is True

    def test_me_authenticated(self, client, mock_current_user):
        response = client.get("/api/auth/me")
        assert response.status_code == 200
        data = response.json()
        assert data["authenticated"] is True
        assert data["user"]["sub"] == mock_current_user["sub"]

    def test_confirm_success(self, client):
        with patch("routers.auth.confirm_user") as mock:
            mock.return_value = {"message": "Confirmado"}
            response = client.post(
                "/api/auth/confirm",
                params={
                    "email": "test@example.com",
                    "confirmation_code": "123456",
                },
            )
        assert response.status_code == 200

    def test_confirm_failure(self, client):
        with patch("routers.auth.confirm_user") as mock:
            mock.return_value = {"error": "Código inválido"}
            response = client.post(
                "/api/auth/confirm",
                params={
                    "email": "test@example.com",
                    "confirmation_code": "bad",
                },
            )
        assert response.status_code == 400

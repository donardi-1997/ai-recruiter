"""Tests for core/auth.py - JWT validation."""

from unittest.mock import patch, MagicMock
import pytest


class TestGetCurrentUser:
    @patch("core.auth.get_cognito_jwks")
    @patch("core.auth.jwt")
    def test_valid_token_returns_payload(self, mock_jwt, mock_jwks):
        from core.auth import get_current_user

        mock_jwks.return_value = {
            "keys": [{"kid": "test-kid", "kty": "RSA"}]
        }
        mock_jwt.get_unverified_header.return_value = {"kid": "test-kid"}
        mock_jwt.decode.return_value = {
            "sub": "user-123",
            "token_use": "access",
            "client_id": "test-client-id",
            "username": "testuser",
        }

        mock_credentials = MagicMock()
        mock_credentials.credentials = "valid-token"

        with patch("core.auth.COGNITO_CLIENT_ID", "test-client-id"):
            result = get_current_user(mock_credentials)

        assert result["sub"] == "user-123"
        assert result["token_use"] == "access"

    @patch("core.auth.get_cognito_jwks")
    @patch("core.auth.jwt")
    def test_missing_kid_raises_401(self, mock_jwt, mock_jwks):
        from core.auth import get_current_user
        from fastapi import HTTPException

        mock_jwks.return_value = {"keys": []}
        mock_jwt.get_unverified_header.return_value = {}

        mock_credentials = MagicMock()
        mock_credentials.credentials = "bad-token"

        with pytest.raises(HTTPException) as exc_info:
            get_current_user(mock_credentials)
        assert exc_info.value.status_code == 401

    @patch("core.auth.get_cognito_jwks")
    @patch("core.auth.jwt")
    def test_wrong_token_use_raises_401(self, mock_jwt, mock_jwks):
        from core.auth import get_current_user
        from fastapi import HTTPException

        mock_jwks.return_value = {
            "keys": [{"kid": "test-kid", "kty": "RSA"}]
        }
        mock_jwt.get_unverified_header.return_value = {"kid": "test-kid"}
        mock_jwt.decode.return_value = {
            "sub": "user-123",
            "token_use": "id",
            "client_id": "test-client-id",
        }

        mock_credentials = MagicMock()
        mock_credentials.credentials = "id-token"

        with patch("core.auth.COGNITO_CLIENT_ID", "test-client-id"):
            with pytest.raises(HTTPException) as exc_info:
                get_current_user(mock_credentials)
        assert exc_info.value.status_code == 401
        assert "Access Token" in exc_info.value.detail

    @patch("core.auth.get_cognito_jwks")
    @patch("core.auth.jwt")
    def test_wrong_client_id_raises_401(self, mock_jwt, mock_jwks):
        from core.auth import get_current_user
        from fastapi import HTTPException

        mock_jwks.return_value = {
            "keys": [{"kid": "test-kid", "kty": "RSA"}]
        }
        mock_jwt.get_unverified_header.return_value = {"kid": "test-kid"}
        mock_jwt.decode.return_value = {
            "sub": "user-123",
            "token_use": "access",
            "client_id": "wrong-client-id",
        }

        mock_credentials = MagicMock()
        mock_credentials.credentials = "token"

        with patch("core.auth.COGNITO_CLIENT_ID", "test-client-id"):
            with pytest.raises(HTTPException) as exc_info:
                get_current_user(mock_credentials)
        assert exc_info.value.status_code == 401
        assert "no pertenece" in exc_info.value.detail


class TestGetCurrentOwnerId:
    def test_returns_sub(self):
        from core.auth import get_current_owner_id

        result = get_current_owner_id(current_user={"sub": "user-123"})
        assert result == "user-123"

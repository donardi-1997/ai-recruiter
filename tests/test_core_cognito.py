"""Tests for core/cognito.py - Cognito auth functions."""

from unittest.mock import patch, MagicMock
import pytest


class TestCreateUser:
    def test_success(self, mock_cognito_client):
        from core.cognito import create_user

        with patch("core.cognito.cognito_client", mock_cognito_client):
            result = create_user("test@example.com", "Password123!")

        assert result["user_sub"] == "test-user-sub"
        assert result["confirmed"] is False
        assert "message" in result

    def test_client_error(self, mock_cognito_client):
        from core.cognito import create_user
        from botocore.exceptions import ClientError

        mock_cognito_client.sign_up.side_effect = ClientError(
            {"Error": {"Message": "Username exists"}},
            "SignUp",
        )

        with patch("core.cognito.cognito_client", mock_cognito_client):
            result = create_user("test@example.com", "Password123!")

        assert "error" in result
        assert "Username exists" in result["error"]


class TestLoginUser:
    def test_success(self, mock_cognito_client):
        from core.cognito import login_user

        with patch("core.cognito.cognito_client", mock_cognito_client):
            result = login_user("test@example.com", "Password123!")

        assert result["access_token"] == "test-access-token"
        assert result["id_token"] == "test-id-token"
        assert result["refresh_token"] == "test-refresh-token"

    def test_wrong_credentials(self, mock_cognito_client):
        from core.cognito import login_user
        from botocore.exceptions import ClientError

        mock_cognito_client.initiate_auth.side_effect = ClientError(
            {"Error": {"Code": "NotAuthorizedException", "Message": "Bad"}},
            "InitiateAuth",
        )

        with patch("core.cognito.cognito_client", mock_cognito_client):
            result = login_user("test@example.com", "wrong")

        assert "error" in result
        assert "incorrectos" in result["error"]

    def test_unconfirmed_user(self, mock_cognito_client):
        from core.cognito import login_user
        from botocore.exceptions import ClientError

        mock_cognito_client.initiate_auth.side_effect = ClientError(
            {"Error": {"Code": "UserNotConfirmedException", "Message": "No"}},
            "InitiateAuth",
        )

        with patch("core.cognito.cognito_client", mock_cognito_client):
            result = login_user("test@example.com", "Password123!")

        assert "error" in result
        assert "confirmada" in result["error"]


class TestRefreshUser:
    def test_success(self, mock_cognito_client):
        from core.cognito import refresh_user

        with patch("core.cognito.cognito_client", mock_cognito_client):
            result = refresh_user("test-refresh-token")

        assert result["access_token"] == "test-access-token"

    def test_expired_token(self, mock_cognito_client):
        from core.cognito import refresh_user
        from botocore.exceptions import ClientError

        mock_cognito_client.initiate_auth.side_effect = ClientError(
            {"Error": {"Message": "Expired"}},
            "InitiateAuth",
        )

        with patch("core.cognito.cognito_client", mock_cognito_client):
            result = refresh_user("expired-token")

        assert "error" in result


class TestConfirmUser:
    def test_success(self, mock_cognito_client):
        from core.cognito import confirm_user

        with patch("core.cognito.cognito_client", mock_cognito_client):
            result = confirm_user("test@example.com", "123456")

        assert "message" in result

    def test_invalid_code(self, mock_cognito_client):
        from core.cognito import confirm_user
        from botocore.exceptions import ClientError

        mock_cognito_client.confirm_sign_up.side_effect = ClientError(
            {"Error": {"Message": "Invalid code"}},
            "ConfirmSignUp",
        )

        with patch("core.cognito.cognito_client", mock_cognito_client):
            result = confirm_user("test@example.com", "bad")

        assert "error" in result

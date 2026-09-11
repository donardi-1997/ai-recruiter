"""Authentication infrastructure exports."""

from app.infrastructure.auth.cognito import (
    CognitoAuthenticationError,
    get_cognito_client,
    validate_access_token,
)

__all__ = [
    "CognitoAuthenticationError",
    "get_cognito_client",
    "validate_access_token",
]

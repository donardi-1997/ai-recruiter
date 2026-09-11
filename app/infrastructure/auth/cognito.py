"""AWS Cognito access-token validation infrastructure."""

import logging
import os

import boto3

logger = logging.getLogger(__name__)


class CognitoAuthenticationError(Exception):
    """Raised when Cognito cannot validate an access token."""


_cognito_client = None


def get_cognito_client():
    """Return the cached Cognito IDP client."""
    global _cognito_client
    if _cognito_client is None:
        _cognito_client = boto3.client(
            "cognito-idp",
            region_name=os.getenv("AWS_REGION", "us-east-2"),
        )
    return _cognito_client


def validate_access_token(token: str) -> dict[str, str | None]:
    """Validate an access token and normalize the existing user payload."""
    try:
        response = get_cognito_client().get_user(AccessToken=token)
        attrs = {a["Name"]: a["Value"] for a in response.get("UserAttributes", [])}
        return {
            "sub": attrs.get("sub") or response.get("Username"),
            "email": attrs.get("email"),
        }
    except Exception as exc:
        logger.warning("Auth validation failed: %s", exc)
        raise CognitoAuthenticationError() from exc

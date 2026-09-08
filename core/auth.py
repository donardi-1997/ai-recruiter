import requests

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt

from core.config import COGNITO_JWKS_URL, COGNITO_ISSUER, COGNITO_CLIENT_ID, logger

security = HTTPBearer()
_cognito_jwks = None


def get_cognito_jwks():
    global _cognito_jwks
    if _cognito_jwks is None:
        response = requests.get(COGNITO_JWKS_URL, timeout=10)
        response.raise_for_status()
        _cognito_jwks = response.json()
    return _cognito_jwks


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials

    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        if not kid:
            raise HTTPException(status_code=401, detail="JWT sin kid.")

        jwks = get_cognito_jwks()
        key = next(
            (key for key in jwks["keys"] if key["kid"] == kid), None
        )

        if not key:
            raise HTTPException(
                status_code=401, detail="Clave JWT no encontrada."
            )

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=COGNITO_ISSUER,
            options={"verify_aud": False},
        )

        token_use = payload.get("token_use")
        if token_use != "access":
            raise HTTPException(
                status_code=401,
                detail="Se requiere un Cognito Access Token.",
            )

        token_client_id = payload.get("client_id")
        if token_client_id != COGNITO_CLIENT_ID:
            raise HTTPException(
                status_code=401,
                detail="El token no pertenece a esta aplicación.",
            )

        if not payload.get("sub"):
            raise HTTPException(
                status_code=401,
                detail="JWT sin identificador de usuario.",
            )

        return payload

    except HTTPException:
        raise
    except Exception as e:
        logger.error("JWT VALIDATION ERROR: %s", str(e))
        raise HTTPException(
            status_code=401, detail="Token inválido o expirado."
        )


def get_current_owner_id(
    current_user: dict = Depends(get_current_user),
):
    return current_user["sub"]

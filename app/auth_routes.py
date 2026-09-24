"""Auth routes — Cognito login, register, refresh, logout, me."""

import os
import logging

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.deps import get_current_principal
from app.infrastructure.bedrock.session import get_cached_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")

AWS_REGION = os.getenv("AWS_REGION", "us-east-2")
COGNITO_USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID")
COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID")

cognito_client = boto3.client(
    "cognito-idp",
    region_name=AWS_REGION,
)


def get_admin_cognito_client():
    """Return a signed Cognito client using the runtime Roles Anywhere session."""
    return get_cached_session().client("cognito-idp", region_name=AWS_REGION)


class CredentialsRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized.count("@") != 1:
            raise ValueError("invalid email")
        local, domain = normalized.split("@", 1)
        if not local or not domain or "." not in domain:
            raise ValueError("invalid email")
        return normalized


class LoginRequest(CredentialsRequest):
    pass


class RegisterRequest(CredentialsRequest):
    password: str = Field(min_length=8, max_length=256)


def public_registration_enabled() -> bool:
    """Return whether self-service account creation is explicitly enabled."""
    return os.getenv("ALLOW_PUBLIC_REGISTRATION", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@router.post("/login")
def login(body: LoginRequest):
    try:
        response = cognito_client.initiate_auth(
            ClientId=COGNITO_CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": body.email,
                "PASSWORD": body.password,
            },
        )
        auth = response.get("AuthenticationResult", {})
        access_token = auth.get("AccessToken")
        if not access_token:
            challenge = str(response.get("ChallengeName") or "").strip()
            logger.warning("Cognito login did not return an access token; challenge=%s", challenge)
            raise HTTPException(
                status_code=403,
                detail="El inicio de sesion requiere un paso adicional no soportado.",
            )
        resp = JSONResponse({
            "access_token": access_token,
            "expires_in": auth.get("ExpiresIn"),
        })
        if auth.get("RefreshToken"):
            resp.set_cookie(
                "ai_recruiter_refresh",
                auth["RefreshToken"],
                httponly=True,
                secure=True,
                samesite="lax",
                max_age=86400 * 30,
                path="/",
            )
        return resp
    except ClientError as e:
        error_code = e.response["Error"].get("Code", "")
        logger.warning("Cognito login error: %s", error_code)
        if error_code in ("NotAuthorizedException", "UserNotFoundException"):
            raise HTTPException(status_code=401, detail="Correo o contrasena incorrectos.")
        if error_code == "UserNotConfirmedException":
            raise HTTPException(status_code=403, detail="Tu cuenta todavia no ha sido confirmada.")
        raise HTTPException(status_code=500, detail="No fue posible iniciar sesion.")


@router.post("/register")
def register(body: RegisterRequest):
    if not public_registration_enabled():
        raise HTTPException(
            status_code=403,
            detail="El registro publico esta deshabilitado. Solicita acceso a un administrador.",
        )

    email = body.email
    password = body.password
    if not COGNITO_USER_POOL_ID:
        logger.error("COGNITO_USER_POOL_ID is required for automatic registration confirmation")
        raise HTTPException(status_code=500, detail="No fue posible crear la cuenta.")

    try:
        response = cognito_client.sign_up(
            ClientId=COGNITO_CLIENT_ID,
            Username=email,
            Password=password,
            UserAttributes=[{"Name": "email", "Value": email}],
        )
        get_admin_cognito_client().admin_confirm_sign_up(
            UserPoolId=COGNITO_USER_POOL_ID,
            Username=email,
        )
        return {
            "message": "Usuario creado correctamente. Ya puedes iniciar sesion.",
            "user_sub": response.get("UserSub"),
        }
    except ClientError as e:
        error = e.response.get("Error", {})
        error_code = str(error.get("Code") or "")
        logger.warning("Cognito registration error: %s", error_code)
        if error_code == "UsernameExistsException":
            raise HTTPException(
                status_code=409,
                detail="Ya existe una cuenta con este correo.",
            ) from e
        if error_code == "InvalidPasswordException":
            raise HTTPException(
                status_code=400,
                detail="La contrasena no cumple los requisitos de seguridad.",
            ) from e
        if error_code in {"InvalidParameterException", "InvalidLambdaResponseException"}:
            raise HTTPException(
                status_code=400,
                detail="Los datos de registro no son validos.",
            ) from e
        if error_code in {"TooManyRequestsException", "LimitExceededException"}:
            raise HTTPException(
                status_code=429,
                detail="Hay demasiados intentos. Intenta nuevamente mas tarde.",
            ) from e
        raise HTTPException(
            status_code=500,
            detail="No fue posible crear la cuenta.",
        ) from e


@router.post("/refresh")
def refresh(request: Request):
    refresh_token = request.cookies.get("ai_recruiter_refresh")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token.")
    try:
        response = cognito_client.initiate_auth(
            ClientId=COGNITO_CLIENT_ID,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={"REFRESH_TOKEN": refresh_token},
        )
        auth = response.get("AuthenticationResult", {})
        access_token = auth.get("AccessToken")
        if not access_token:
            raise HTTPException(
                status_code=401,
                detail="La sesion expiro. Inicia sesion nuevamente.",
            )
        resp = JSONResponse({
            "access_token": access_token,
            "expires_in": auth.get("ExpiresIn"),
        })
        if auth.get("RefreshToken"):
            resp.set_cookie(
                "ai_recruiter_refresh",
                auth["RefreshToken"],
                httponly=True,
                secure=True,
                samesite="lax",
                max_age=86400 * 30,
            )
        return resp
    except ClientError:
        raise HTTPException(status_code=401, detail="La sesion expiro. Inicia sesion nuevamente.")


@router.post("/logout")
def logout():
    resp = JSONResponse({"message": "Sesion cerrada."})
    resp.delete_cookie("ai_recruiter_refresh")
    return resp


@router.get("/me")
def me(principal: dict = Depends(get_current_principal)):
    """Return the authenticated user enriched with internal roles and permissions."""
    return principal

"""Auth routes — Cognito login, register, refresh, logout, me."""

import os
import logging

import boto3
from botocore.exceptions import ClientError
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")

cognito_client = boto3.client(
    "cognito-idp",
    region_name=os.getenv("AWS_REGION", "us-east-2"),
)

COGNITO_CLIENT_ID = os.getenv("COGNITO_CLIENT_ID")


class LoginRequest(BaseModel):
    email: str
    password: str


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
        return {
            "access_token": auth.get("AccessToken"),
            "id_token": auth.get("IdToken"),
            "refresh_token": auth.get("RefreshToken"),
            "expires_in": auth.get("ExpiresIn"),
        }
    except ClientError as e:
        error_code = e.response["Error"].get("Code", "")
        logger.warning("Cognito login error: %s %s", error_code, e.response["Error"].get("Message"))
        if error_code in ("NotAuthorizedException", "UserNotFoundException"):
            raise HTTPException(status_code=401, detail="Correo o contrasena incorrectos.")
        if error_code == "UserNotConfirmedException":
            raise HTTPException(status_code=403, detail="Tu cuenta todavia no ha sido confirmada.")
        raise HTTPException(status_code=500, detail="No fue posible iniciar sesion.")


@router.post("/register")
def register(email: str = Query(...), password: str = Query(...)):
    try:
        response = cognito_client.sign_up(
            ClientId=COGNITO_CLIENT_ID,
            Username=email,
            Password=password,
            UserAttributes=[{"Name": "email", "Value": email}],
        )
        return {
            "message": "Usuario creado correctamente. Revisa tu correo para confirmar la cuenta.",
            "user_sub": response.get("UserSub"),
        }
    except ClientError as e:
        raise HTTPException(status_code=400, detail=e.response["Error"]["Message"])


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
        resp = JSONResponse({
            "access_token": auth.get("AccessToken"),
            "id_token": auth.get("IdToken"),
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
def me(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No token provided.")
    token = auth_header[7:]
    try:
        response = cognito_client.get_user(AccessToken=token)
        attrs = {a["Name"]: a["Value"] for a in response.get("UserAttributes", [])}
        return {
            "sub": response.get("Username"),
            "email": attrs.get("email"),
            "email_verified": attrs.get("email_verified"),
        }
    except ClientError:
        raise HTTPException(status_code=401, detail="Token invalido o expirado.")

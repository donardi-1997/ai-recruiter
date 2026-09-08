from fastapi import APIRouter, Depends, HTTPException, Response, Cookie

from core.cognito import create_user, login_user, refresh_user, confirm_user
from core.auth import get_current_user
from core.models import LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
def register_user(email: str, password: str):
    return create_user(email, password)


@router.post("/login")
def login(data: LoginRequest, response: Response):
    result = login_user(data.email, data.password)
    if result.get("error"):
        raise HTTPException(status_code=401, detail=result["error"])
    refresh_token = result.pop("refresh_token", None)
    if refresh_token:
        response.set_cookie(
            "ai_recruiter_refresh",
            refresh_token,
            max_age=30 * 24 * 60 * 60,
            httponly=True,
            secure=True,
            samesite="lax",
            path="/api",
        )
    return result


@router.post("/refresh")
def refresh_session(
    refresh_token: str | None = Cookie(default=None, alias="ai_recruiter_refresh"),
):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Sesión no disponible.")
    result = refresh_user(refresh_token)
    if result.get("error"):
        raise HTTPException(status_code=401, detail=result["error"])
    return result


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("ai_recruiter_refresh", path="/api")
    return {"logged_out": True}


@router.get("/me")
def get_current_user_info(
    current_user: dict = Depends(get_current_user),
):
    return {"authenticated": True, "user": current_user}


@router.post("/confirm")
def confirm_registration(email: str, confirmation_code: str):
    result = confirm_user(email, confirmation_code)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result

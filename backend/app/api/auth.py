"""Endpoints de autenticación: login, refresco y cierre de sesión."""

import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_session
from app.security.auth import (
    ACCESS_TTL,
    REFRESH_TTL,
    AuthError,
    LoginThrottle,
    create_access_token,
    create_refresh_token,
    get_current_user,
    get_throttle,
    login,
    user_from_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["autenticación"])

REFRESH_COOKIE = "chatiapp_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"


class LoginRequest(BaseModel):
    email: str
    password: str


class UserInfo(BaseModel):
    id: uuid.UUID
    email: str
    is_admin: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserInfo


def _user_info(user: User) -> UserInfo:
    return UserInfo(id=user.id, email=user.email, is_admin=user.is_admin)


def _set_refresh_cookie(response: Response, token: str) -> None:
    secure = os.environ.get("CHATIAPP_COOKIE_SECURE", "true").lower() not in ("0", "false", "no")
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=int(REFRESH_TTL.total_seconds()),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=secure,
        samesite="strict",
    )


def _token_response(user: User, access_token: str) -> TokenResponse:
    return TokenResponse(
        access_token=access_token,
        expires_in=int(ACCESS_TTL.total_seconds()),
        user=_user_info(user),
    )


@router.post("/login", summary="Correo y contraseña → JWT y cookie de refresco")
def login_endpoint(
    body: LoginRequest,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    throttle: Annotated[LoginThrottle, Depends(get_throttle)],
) -> TokenResponse:
    result = login(session, throttle, body.email, body.password)
    _set_refresh_cookie(response, result.refresh_token)
    return _token_response(result.user, result.access_token)


@router.post("/refresh", summary="Renueva el JWT con la cookie de refresco")
def refresh_endpoint(
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    refresh_token: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
) -> TokenResponse:
    if not refresh_token:
        raise AuthError(401, "not_authenticated", "No hay sesión activa.")
    user = user_from_refresh_token(session, refresh_token)
    _set_refresh_cookie(response, create_refresh_token(user.id))
    return _token_response(user, create_access_token(user.id))


@router.post("/logout", status_code=204, summary="Cierra la sesión borrando la cookie")
def logout_endpoint(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)


@router.get("/me", summary="Usuario autenticado")
def me_endpoint(user: Annotated[User, Depends(get_current_user)]) -> UserInfo:
    return _user_info(user)

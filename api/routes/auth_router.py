"""Auth routes — /api/auth/login."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from api.auth import create_token, is_admin, verify_login

log = logging.getLogger(__name__)
router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str
    is_admin: bool


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest) -> LoginResponse:
    username = (body.username or "").strip()
    if not username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="username is required",
        )

    if not verify_login(username, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    token = create_token(username)
    log.info("User %r logged in successfully", username)
    return LoginResponse(
        token=token,
        username=username.lower(),
        is_admin=is_admin(username),
    )

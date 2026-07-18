"""FastAPI auth module — in-memory token store, no Streamlit dependency."""
from __future__ import annotations

import logging
import os
import secrets
import time
from typing import Annotated

from fastapi import Header, HTTPException, status

log = logging.getLogger(__name__)

# Token sống 2 giờ — hết hạn buộc đăng nhập lại (đổi qua env TOKEN_TTL_SECONDS)
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", str(2 * 3600)))

# token → (username, expires_at epoch seconds)
_TOKEN_STORE: dict[str, tuple[str, float]] = {}


def _allowed_users() -> set[str]:
    raw = os.getenv("ALLOWED_USERS", "")
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


def verify_login(username: str, password: str) -> bool:
    """Return True if username+password are valid."""
    expected_password = os.getenv("APP_PASSWORD", "")
    if not expected_password:
        # No password configured — accept anyone
        return True

    clean = (username or "").strip().lower()
    allowed = _allowed_users()
    if allowed and clean not in allowed:
        log.warning("Login rejected: username %r not in ALLOWED_USERS", clean)
        return False

    if password != expected_password:
        log.warning("Login rejected: wrong password for user %r", clean)
        return False

    return True


def create_token(username: str) -> str:
    token = secrets.token_hex(32)
    _TOKEN_STORE[token] = (username.strip().lower(), time.time() + TOKEN_TTL_SECONDS)
    log.info("Token created for user %r (TTL %ds)", username, TOKEN_TTL_SECONDS)
    return token


def is_admin(username: str) -> bool:
    raw = os.getenv("ADMIN_USERS", "admin")
    admins = {u.strip().lower() for u in raw.split(",") if u.strip()}
    return username.strip().lower() in admins


def get_current_user(authorization: Annotated[str | None, Header()] = None) -> str:
    """FastAPI dependency — extract and validate Bearer token."""
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected: Bearer <token>",
        )
    token = parts[1].strip()
    record = _TOKEN_STORE.get(token)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    username, expires_at = record
    if time.time() >= expires_at:
        _TOKEN_STORE.pop(token, None)
        log.info("Token expired for user %r", username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return username

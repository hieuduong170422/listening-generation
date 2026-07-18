"""FastAPI auth module — token store trong SQLite.

Dùng SQLite thay vì dict in-memory vì:
- Production chạy uvicorn --workers 2: mỗi worker một process, dict riêng
  → login ở worker A, request sau rơi vào worker B là 401 ngẫu nhiên.
- Restart/deploy không làm mất phiên đăng nhập (volume audivy_history).
Chỉ lưu SHA-256 hash của token, không lưu token thô.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Annotated

from fastapi import Header, HTTPException, status

log = logging.getLogger(__name__)

# Token sống 2 giờ — hết hạn buộc đăng nhập lại (đổi qua env TOKEN_TTL_SECONDS)
TOKEN_TTL_SECONDS = int(os.getenv("TOKEN_TTL_SECONDS", str(2 * 3600)))

DB_PATH = Path(__file__).resolve().parent.parent / "history" / "auth_tokens.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tokens (
            token_hash TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    return conn


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
    now = time.time()
    with _conn() as conn:
        conn.execute("DELETE FROM tokens WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO tokens (token_hash, username, expires_at) VALUES (?, ?, ?)",
            (_hash_token(token), username.strip().lower(), now + TOKEN_TTL_SECONDS),
        )
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
    token_hash = _hash_token(token)
    with _conn() as conn:
        row = conn.execute(
            "SELECT username, expires_at FROM tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    username, expires_at = row
    if time.time() >= expires_at:
        with _conn() as conn:
            conn.execute("DELETE FROM tokens WHERE token_hash = ?", (token_hash,))
        log.info("Token expired for user %r", username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return username

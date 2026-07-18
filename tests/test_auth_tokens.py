"""Tests cho token TTL trong api/auth.py."""
import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import auth  # noqa: E402


@pytest.fixture(autouse=True)
def clean_store():
    auth._TOKEN_STORE.clear()
    yield
    auth._TOKEN_STORE.clear()


class TestTokenLifecycle:
    def test_valid_token_returns_username(self):
        token = auth.create_token("Alice")
        assert auth.get_current_user(f"Bearer {token}") == "alice"

    def test_unknown_token_401(self):
        with pytest.raises(HTTPException) as exc:
            auth.get_current_user("Bearer khong-ton-tai")
        assert exc.value.status_code == 401

    def test_missing_header_401(self):
        with pytest.raises(HTTPException) as exc:
            auth.get_current_user(None)
        assert exc.value.status_code == 401

    def test_bad_format_401(self):
        with pytest.raises(HTTPException) as exc:
            auth.get_current_user("Token abc")
        assert exc.value.status_code == 401


class TestTokenExpiry:
    def test_token_expires_after_ttl(self, monkeypatch):
        token = auth.create_token("bob")
        real_time = time.time
        # 2 giờ 1 giây sau
        monkeypatch.setattr(time, "time", lambda: real_time() + auth.TOKEN_TTL_SECONDS + 1)
        with pytest.raises(HTTPException) as exc:
            auth.get_current_user(f"Bearer {token}")
        assert exc.value.status_code == 401
        # Token hết hạn bị dọn khỏi store
        assert token not in auth._TOKEN_STORE

    def test_token_still_valid_before_ttl(self, monkeypatch):
        token = auth.create_token("bob")
        real_time = time.time
        # 1 giờ 59 phút sau
        monkeypatch.setattr(time, "time", lambda: real_time() + auth.TOKEN_TTL_SECONDS - 60)
        assert auth.get_current_user(f"Bearer {token}") == "bob"

    def test_default_ttl_is_two_hours(self):
        assert auth.TOKEN_TTL_SECONDS == 2 * 3600

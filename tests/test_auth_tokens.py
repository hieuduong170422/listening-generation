"""Tests cho token store SQLite + TTL trong api/auth.py."""
import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import auth  # noqa: E402


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "DB_PATH", tmp_path / "auth_tokens.db")


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

    def test_raw_token_not_stored(self):
        """DB chỉ chứa hash, không chứa token thô."""
        token = auth.create_token("alice")
        raw = auth.DB_PATH.read_bytes()
        assert token.encode() not in raw

    def test_survives_across_connections(self):
        """Mô phỏng 2 worker: mỗi lần gọi là 1 connection SQLite riêng."""
        token = auth.create_token("alice")
        # get_current_user mở connection mới — như worker khác đọc
        assert auth.get_current_user(f"Bearer {token}") == "alice"
        assert auth.get_current_user(f"Bearer {token}") == "alice"


class TestTokenExpiry:
    def test_token_expires_after_ttl(self, monkeypatch):
        token = auth.create_token("bob")
        real_time = time.time
        # 2 giờ 1 giây sau
        monkeypatch.setattr(time, "time", lambda: real_time() + auth.TOKEN_TTL_SECONDS + 1)
        with pytest.raises(HTTPException) as exc:
            auth.get_current_user(f"Bearer {token}")
        assert exc.value.status_code == 401
        # Gọi lại vẫn 401 (token đã bị xoá khỏi DB)
        with pytest.raises(HTTPException):
            auth.get_current_user(f"Bearer {token}")

    def test_token_still_valid_before_ttl(self, monkeypatch):
        token = auth.create_token("bob")
        real_time = time.time
        # 1 giờ 59 phút sau
        monkeypatch.setattr(time, "time", lambda: real_time() + auth.TOKEN_TTL_SECONDS - 60)
        assert auth.get_current_user(f"Bearer {token}") == "bob"

    def test_expired_tokens_pruned_on_create(self, monkeypatch):
        auth.create_token("old-user")
        real_time = time.time
        monkeypatch.setattr(time, "time", lambda: real_time() + auth.TOKEN_TTL_SECONDS + 10)
        auth.create_token("new-user")
        import sqlite3
        with sqlite3.connect(auth.DB_PATH) as conn:
            usernames = [r[0] for r in conn.execute("SELECT username FROM tokens").fetchall()]
        assert usernames == ["new-user"]

    def test_default_ttl_is_two_hours(self):
        assert auth.TOKEN_TTL_SECONDS == 2 * 3600

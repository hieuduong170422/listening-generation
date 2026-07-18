"""Tests cho api/outline_store.py — per-user, admin thấy hết, retention 7 ngày."""
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from api import outline_store  # noqa: E402


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(outline_store, "DB_PATH", tmp_path / "outline_history.db")


PAYLOAD = {
    "config": {"topic": "t"},
    "outline": {"topic": "t", "total_minutes": 3, "parts": [{"index": 1, "title": "P1"}]},
    "scripts": {"1": "Speaker1: hi"},
    "audio_ids": {},
}


class TestUpsertAndList:
    def test_insert_then_list_own(self):
        outline_store.upsert_entry("alice", "id-1", PAYLOAD)
        entries = outline_store.list_entries("alice")
        assert len(entries) == 1
        assert entries[0]["id"] == "id-1"
        assert entries[0]["username"] == "alice"
        assert entries[0]["outline"]["parts"][0]["title"] == "P1"

    def test_update_keeps_created_at(self):
        outline_store.upsert_entry("alice", "id-1", PAYLOAD)
        created = outline_store.list_entries("alice")[0]["created_at"]
        outline_store.upsert_entry("alice", "id-1", {**PAYLOAD, "scripts": {"1": "x", "2": "y"}})
        entries = outline_store.list_entries("alice")
        assert len(entries) == 1
        assert entries[0]["created_at"] == created
        assert len(entries[0]["scripts"]) == 2

    def test_user_isolation(self):
        outline_store.upsert_entry("alice", "id-a", PAYLOAD)
        outline_store.upsert_entry("bob", "id-b", PAYLOAD)
        assert [e["id"] for e in outline_store.list_entries("alice")] == ["id-a"]
        assert [e["id"] for e in outline_store.list_entries("bob")] == ["id-b"]

    def test_admin_sees_all(self):
        outline_store.upsert_entry("alice", "id-a", PAYLOAD)
        outline_store.upsert_entry("bob", "id-b", PAYLOAD)
        all_entries = outline_store.list_entries("admin", include_all=True)
        assert {e["username"] for e in all_entries} == {"alice", "bob"}

    def test_upsert_other_users_entry_denied(self):
        outline_store.upsert_entry("alice", "id-1", PAYLOAD)
        with pytest.raises(PermissionError):
            outline_store.upsert_entry("bob", "id-1", PAYLOAD)

    def test_oversized_payload_rejected(self):
        big = {**PAYLOAD, "scripts": {"1": "x" * 3_000_000}}
        with pytest.raises(ValueError):
            outline_store.upsert_entry("alice", "id-big", big)


class TestDelete:
    def test_delete_own(self):
        outline_store.upsert_entry("alice", "id-1", PAYLOAD)
        assert outline_store.delete_entry("id-1", "alice", is_admin=False) is True
        assert outline_store.list_entries("alice") == []

    def test_delete_missing_returns_false(self):
        assert outline_store.delete_entry("nope", "alice", is_admin=False) is False

    def test_delete_others_denied_unless_admin(self):
        outline_store.upsert_entry("alice", "id-1", PAYLOAD)
        with pytest.raises(PermissionError):
            outline_store.delete_entry("id-1", "bob", is_admin=False)
        assert outline_store.delete_entry("id-1", "bob", is_admin=True) is True


class TestRetention:
    def test_old_entries_pruned(self, monkeypatch):
        outline_store.upsert_entry("alice", "id-old", PAYLOAD)
        # Giả lập 8 ngày sau
        real_time = time.time
        monkeypatch.setattr(time, "time", lambda: real_time() + 8 * 24 * 3600)
        outline_store.upsert_entry("alice", "id-new", PAYLOAD)
        entries = outline_store.list_entries("alice")
        assert [e["id"] for e in entries] == ["id-new"]

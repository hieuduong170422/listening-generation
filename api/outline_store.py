"""SQLite store cho lịch sử dàn ý theo user — giữ 7 ngày."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "history" / "outline_history.db"
RETENTION_SECONDS = 7 * 24 * 3600
MAX_PAYLOAD_BYTES = 2_000_000  # ~2MB / entry — chặn payload bất thường


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS outline_history (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_outline_user ON outline_history (username, updated_at)"
    )
    return conn


def _prune(conn: sqlite3.Connection) -> None:
    cutoff = int(time.time()) - RETENTION_SECONDS
    conn.execute("DELETE FROM outline_history WHERE updated_at < ?", (cutoff,))


def upsert_entry(username: str, entry_id: str, payload: dict) -> None:
    """Thêm mới hoặc cập nhật entry; giữ nguyên created_at và chủ sở hữu cũ."""
    raw = json.dumps(payload, ensure_ascii=False)
    if len(raw.encode()) > MAX_PAYLOAD_BYTES:
        raise ValueError("Payload quá lớn")
    now = int(time.time())
    with _conn() as conn:
        _prune(conn)
        row = conn.execute(
            "SELECT username, created_at FROM outline_history WHERE id = ?", (entry_id,)
        ).fetchone()
        if row:
            owner, created_at = row
            if owner != username:
                raise PermissionError("Entry thuộc user khác")
            conn.execute(
                "UPDATE outline_history SET updated_at = ?, payload = ? WHERE id = ?",
                (now, raw, entry_id),
            )
        else:
            conn.execute(
                "INSERT INTO outline_history (id, username, created_at, updated_at, payload) "
                "VALUES (?, ?, ?, ?, ?)",
                (entry_id, username, now, now, raw),
            )


def list_entries(username: str, include_all: bool = False) -> list[dict]:
    """Entries của user (hoặc tất cả nếu admin), mới nhất trước."""
    with _conn() as conn:
        _prune(conn)
        if include_all:
            rows = conn.execute(
                "SELECT id, username, created_at, updated_at, payload "
                "FROM outline_history ORDER BY updated_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, username, created_at, updated_at, payload "
                "FROM outline_history WHERE username = ? ORDER BY updated_at DESC",
                (username,),
            ).fetchall()
    entries: list[dict] = []
    for entry_id, owner, created_at, updated_at, raw in rows:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue  # bỏ qua row hỏng thay vì crash cả list
        entries.append(
            {
                "id": entry_id,
                "username": owner,
                "created_at": created_at,
                "updated_at": updated_at,
                **payload,
            }
        )
    return entries


def delete_entry(entry_id: str, username: str, is_admin: bool) -> bool:
    """Xoá entry của mình (admin xoá được của bất kỳ ai). Trả False nếu không có."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT username FROM outline_history WHERE id = ?", (entry_id,)
        ).fetchone()
        if not row:
            return False
        if row[0] != username and not is_admin:
            raise PermissionError("Không có quyền xoá entry này")
        conn.execute("DELETE FROM outline_history WHERE id = ?", (entry_id,))
        return True

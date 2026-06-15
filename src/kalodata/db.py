"""SQLite storage for kalodata snapshots + product rows.

Each fetch creates a `snapshots` row + N `products` rows. Compare
snapshots over time to detect trending products.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = os.environ.get("KALODATA_DB_PATH", str(_ROOT / "kalodata.db"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    country         TEXT NOT NULL,
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    sort_field      TEXT NOT NULL,
    sort_type       TEXT NOT NULL,
    fetched_at      TEXT NOT NULL,
    total_products  INTEGER NOT NULL DEFAULT 0,
    notes           TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id     INTEGER NOT NULL,
    rank            INTEGER,
    product_id      TEXT,
    product_name    TEXT,
    image_url       TEXT,
    image_urls      TEXT,     -- JSON array of all CDN image URLs
    video_urls      TEXT,     -- JSON array of video objects
    category        TEXT,
    revenue         REAL,
    sales           REAL,
    views           REAL,
    price           REAL,
    rating          REAL,
    raw_json        TEXT NOT NULL,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_products_snapshot
    ON products(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_products_lookup
    ON products(snapshot_id, product_id);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(_SCHEMA)
        # Idempotent migrations for pre-existing DBs.
        for col, type_ in (
            ("image_urls", "TEXT"),
            ("video_urls", "TEXT"),
            ("creator_num", "INTEGER"),
            ("commission_pct", "REAL"),
            ("launch_date", "TEXT"),
        ):
            try:
                conn.execute(f"ALTER TABLE products ADD COLUMN {col} {type_}")
            except sqlite3.OperationalError:
                pass  # already exists
        conn.commit()
    finally:
        conn.close()


def reset_db() -> None:
    """Drop everything — use with care."""
    conn = get_connection()
    try:
        conn.executescript(
            "DROP TABLE IF EXISTS products; DROP TABLE IF EXISTS snapshots;"
        )
        conn.commit()
    finally:
        conn.close()
    init_db()

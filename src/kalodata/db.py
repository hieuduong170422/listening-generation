"""SQLite storage for kalodata snapshots + product rows.

Each fetch creates a `snapshots` row + N `products` rows. Compare
snapshots over time to detect trending products.

Backed by either:
  • local sqlite3 (default, file at kalodata.db) — for local dev / cron
  • Turso (libsql) — when TURSO_DATABASE_URL + TURSO_AUTH_TOKEN are set;
    used by Streamlit Cloud since Cloudflare IP-binds the kalodata
    cookie so Cloud cannot fetch live, but it CAN read the snapshots
    that the local cron wrote into Turso.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
DATABASE_PATH = os.environ.get("KALODATA_DB_PATH", str(_ROOT / "kalodata.db"))

# ── Optional libsql (Turso) shim ───────────────────────────────────────────
try:
    import libsql as _libsql
    _HAS_TURSO = True
except ImportError:
    try:
        import libsql_experimental as _libsql  # noqa: F401  deprecation fallback
        _HAS_TURSO = True
    except ImportError:
        _HAS_TURSO = False


class _TursoRow(dict):
    """Lookup row by both column name and positional index."""
    __slots__ = ("_keys",)

    def __init__(self, keys, values):
        self._keys = keys
        super().__init__(zip(keys, values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return super().__getitem__(self._keys[key])
        return dict.__getitem__(self, key)


class _TursoResult:
    def __init__(self, result, columns):
        self._result = result
        self._columns = columns
        self.lastrowid = None

    def fetchone(self):
        row = self._result.fetchone()
        return _TursoRow(self._columns, row) if row else None

    def fetchall(self):
        return [_TursoRow(self._columns, r) for r in self._result.fetchall()]


class _TursoConnection:
    def __init__(self, url, token):
        self._conn = _libsql.connect(database=url, auth_token=token)
        self._lastrowid = None

    def execute(self, sql, params=None):
        result = self._conn.execute(sql, params) if params is not None else self._conn.execute(sql)
        if sql.strip().upper().startswith("INSERT"):
            try:
                row = self._conn.execute("SELECT last_insert_rowid()").fetchone()
                self._lastrowid = row[0] if row else None
            except Exception:
                self._lastrowid = None
        columns = []
        if hasattr(result, "description") and result.description:
            columns = [col[0] for col in result.description]
        wrapper = _TursoResult(result, columns)
        wrapper.lastrowid = self._lastrowid
        return wrapper

    def executescript(self, sql_script):
        for statement in sql_script.split(";"):
            stmt = statement.strip()
            if stmt:
                try:
                    self.execute(stmt)
                except Exception as exc:
                    raise RuntimeError(f"executescript error near: {stmt[:60]!r}") from exc

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

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


def get_connection():
    """Return a Turso (if configured) or local SQLite connection.

    Turso is auto-used when both TURSO_DATABASE_URL and TURSO_AUTH_TOKEN
    are present. On Streamlit Cloud this is how the deployed app can see
    the snapshots that the local cron has written.
    """
    turso_url = (os.environ.get("TURSO_DATABASE_URL") or "").strip()
    turso_token = (os.environ.get("TURSO_AUTH_TOKEN") or "").strip()
    if turso_url and turso_token:
        if not _HAS_TURSO:
            raise RuntimeError(
                "TURSO_DATABASE_URL set but `libsql` chưa cài. "
                "Chạy: pip install libsql"
            )
        return _TursoConnection(turso_url, turso_token)

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
            # Catch broadly: sqlite3 raises OperationalError, libsql (Turso)
            # surfaces "duplicate column" as ValueError.
            try:
                conn.execute(f"ALTER TABLE products ADD COLUMN {col} {type_}")
            except Exception:
                pass  # column already exists
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

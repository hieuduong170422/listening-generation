import os
import sqlite3

DATABASE_PATH = os.environ.get("DATABASE_PATH", "templates.db")

# ── Turso helpers ──────────────────────────────────────────────────────────────

try:
    import libsql as _libsql
    _HAS_TURSO = True
except ImportError:
    try:
        import libsql_experimental as _libsql  # deprecation fallback
        _HAS_TURSO = True
    except ImportError:
        _HAS_TURSO = False


class _TursoRow(dict):
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
        if row is None:
            return None
        return _TursoRow(self._columns, row)

    def fetchall(self):
        return [_TursoRow(self._columns, r) for r in self._result.fetchall()]


class _TursoConnection:
    def __init__(self, url, token):
        self._conn = _libsql.connect(database=url, auth_token=token)
        self._lastrowid = None

    def execute(self, sql, params=None):
        if params is not None:
            result = self._conn.execute(sql, params)
        else:
            result = self._conn.execute(sql)

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


# ── Public API ─────────────────────────────────────────────────────────────────

def get_connection():
    """Return a database connection (Turso remote or local SQLite)."""
    turso_url = os.environ.get("TURSO_DATABASE_URL")
    turso_token = os.environ.get("TURSO_AUTH_TOKEN")

    if turso_url and turso_token:
        if not _HAS_TURSO:
            raise RuntimeError(
                "TURSO_DATABASE_URL is set but 'libsql' is not installed.\n"
                "  Run: uv add libsql"
            )
        return _TursoConnection(turso_url, turso_token)

    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            system_prompt TEXT DEFAULT '',
            model TEXT NOT NULL DEFAULT 'gemini-2.5-pro',
            temperature REAL NOT NULL DEFAULT 0.7,
            output_type TEXT NOT NULL DEFAULT 'text',
            sdk TEXT NOT NULL DEFAULT 'Google Gemini',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS template_inputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            label TEXT NOT NULL,
            type TEXT NOT NULL DEFAULT 'TEXT',
            required INTEGER NOT NULL DEFAULT 0,
            placeholder TEXT DEFAULT '',
            select_options TEXT DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS execution_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            template_name TEXT NOT NULL,
            inputs_json TEXT NOT NULL,
            response_type TEXT DEFAULT 'text',
            response_text TEXT,
            response_data TEXT,
            model TEXT NOT NULL,
            temperature REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (template_id) REFERENCES templates(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_template_inputs_template ON template_inputs(template_id);
        CREATE INDEX IF NOT EXISTS idx_history_template ON execution_history(template_id);
        CREATE INDEX IF NOT EXISTS idx_history_created ON execution_history(created_at);

        CREATE TABLE IF NOT EXISTS template_flows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            main_template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
            sub_template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
            output_key TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_flows_main ON template_flows(main_template_id);
        CREATE INDEX IF NOT EXISTS idx_flows_sub ON template_flows(sub_template_id);
    """)
    # Create elevenlabs_voices cache table (individual execute calls for Turso compat)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS elevenlabs_voices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voice_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            labels_json TEXT DEFAULT '',
            category TEXT DEFAULT '',
            description TEXT DEFAULT '',
            gender TEXT DEFAULT '',
            accent TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_elevenlabs_voices_name ON elevenlabs_voices(name)")
    migrate_db(conn)
    conn.close()


def migrate_db(conn):
    try:
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(templates)").fetchall()}
    except Exception:
        return
    if "output_type" not in existing_cols:
        conn.execute("ALTER TABLE templates ADD COLUMN output_type TEXT NOT NULL DEFAULT 'text'")
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(templates)").fetchall()}
    if "is_flow" not in existing_cols:
        conn.execute("ALTER TABLE templates ADD COLUMN is_flow INTEGER NOT NULL DEFAULT 0")
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(templates)").fetchall()}
    if "sdk" not in existing_cols:
        conn.execute("ALTER TABLE templates ADD COLUMN sdk TEXT NOT NULL DEFAULT 'Google Gemini'")

    # Check for elevenlabs_voices table
    try:
        table_check = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='elevenlabs_voices'").fetchone()
        if not table_check:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS elevenlabs_voices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    voice_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    labels_json TEXT DEFAULT '',
                    category TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    gender TEXT DEFAULT '',
                    accent TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_elevenlabs_voices_name ON elevenlabs_voices(name)")
    except Exception:
        pass  # Table creation failure shouldn't block migration

import sqlite3

DATABASE_PATH = "templates.db"


def get_connection():
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
    """)
    conn.close()

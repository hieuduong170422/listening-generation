import json

from prompt_template.database import get_connection


def save_execution(template_id, template_name, inputs_dict, response_text, response_type, response_data, model, temperature):
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO execution_history (template_id, template_name, inputs_json, response_text, response_type, response_data, model, temperature) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (template_id, template_name, json.dumps(inputs_dict), response_text, response_type, response_data, model, temperature)
    )
    entry_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return entry_id


def list_history(limit=50):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM execution_history ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_history_entry(entry_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM execution_history WHERE id = ?",
        (entry_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_history(entry_id):
    conn = get_connection()
    conn.execute("DELETE FROM execution_history WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()

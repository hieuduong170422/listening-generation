from prompt_template.database import get_connection


def create_template(name, description, system_prompt, model, temperature, inputs):
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO templates (name, description, system_prompt, model, temperature) VALUES (?, ?, ?, ?, ?)",
        (name, description, system_prompt, model, temperature),
    )
    template_id = cursor.lastrowid
    for i, inp in enumerate(inputs):
        conn.execute(
            "INSERT INTO template_inputs (template_id, key, label, type, required, placeholder, select_options, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                template_id,
                inp["key"],
                inp["label"],
                inp["type"],
                inp.get("required", 0),
                inp.get("placeholder", ""),
                inp.get("select_options", ""),
                i,
            ),
        )
    conn.commit()
    conn.close()
    return template_id


def get_template(template_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM templates WHERE id = ?", (template_id,)
    ).fetchone()
    if row is None:
        conn.close()
        return None
    template = dict(row)
    input_rows = conn.execute(
        "SELECT * FROM template_inputs WHERE template_id = ? ORDER BY sort_order",
        (template_id,),
    ).fetchall()
    template["inputs"] = [dict(r) for r in input_rows]
    conn.close()
    return template


def list_templates():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, description, model, temperature, created_at, updated_at FROM templates ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_template(template_id, name, description, system_prompt, model, temperature, inputs):
    conn = get_connection()
    conn.execute(
        "UPDATE templates SET name=?, description=?, system_prompt=?, model=?, temperature=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (name, description, system_prompt, model, temperature, template_id),
    )
    conn.execute("DELETE FROM template_inputs WHERE template_id=?", (template_id,))
    for i, inp in enumerate(inputs):
        conn.execute(
            "INSERT INTO template_inputs (template_id, key, label, type, required, placeholder, select_options, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                template_id,
                inp["key"],
                inp["label"],
                inp["type"],
                inp.get("required", 0),
                inp.get("placeholder", ""),
                inp.get("select_options", ""),
                i,
            ),
        )
    conn.commit()
    conn.close()


def delete_template(template_id):
    conn = get_connection()
    conn.execute("DELETE FROM templates WHERE id=?", (template_id,))
    conn.commit()
    conn.close()

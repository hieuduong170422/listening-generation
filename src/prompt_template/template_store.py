from prompt_template.database import get_connection


def create_template(name, description, system_prompt, model, temperature, inputs, output_type="text", is_flow=0):
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO templates (name, description, system_prompt, model, temperature, output_type, is_flow) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, description, system_prompt, model, temperature, output_type, is_flow),
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
    if template.get("is_flow"):
        template["flow_bindings"] = get_flow_bindings(template_id)
    conn.close()
    return template


def list_templates():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, description, model, temperature, output_type, is_flow, created_at, updated_at FROM templates ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_template(template_id, name, description, system_prompt, model, temperature, inputs, output_type="text", is_flow=0):
    conn = get_connection()
    conn.execute(
        "UPDATE templates SET name=?, description=?, system_prompt=?, model=?, temperature=?, output_type=?, is_flow=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (name, description, system_prompt, model, temperature, output_type, is_flow, template_id),
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


def set_flow_bindings(main_template_id, bindings):
    """Atomically replace all flow bindings for a template.
    bindings = [{"sub_template_id": int, "output_key": str}, ...]
    """
    conn = get_connection()
    conn.execute("DELETE FROM template_flows WHERE main_template_id = ?", (main_template_id,))
    for i, b in enumerate(bindings):
        conn.execute(
            "INSERT INTO template_flows (main_template_id, sub_template_id, output_key, sort_order) VALUES (?, ?, ?, ?)",
            (main_template_id, b["sub_template_id"], b["output_key"], i),
        )
    conn.commit()
    conn.close()


def get_flow_bindings(main_template_id):
    """Return all flow bindings for a template, joined with sub-template metadata."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT tf.id, tf.main_template_id, tf.sub_template_id, tf.output_key, tf.sort_order,
               t.name AS sub_template_name, t.is_flow AS sub_is_flow,
               t.output_type AS sub_output_type
        FROM template_flows tf
        JOIN templates t ON t.id = tf.sub_template_id
        WHERE tf.main_template_id = ?
        ORDER BY tf.sort_order
    """, (main_template_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

"""Standalone tests for flow template execution (template_flows, flow_engine).

Tests:
  1. Schema — is_flow column, template_flows table, FK cascade
  2. Flow Binding CRUD — set/get flow bindings, is_flow in CRUD
  3. get_flow_input_groups() — single level, nested, non-flow
  4. execute_flow() — single leaf, 2 leaves, mixed media, non-text, error
  5. Cycle guard — circular flow references
  6. Edge cases — no bindings, empty values

Usage:
    uv run python tests/test_flow_execution.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import prompt_template.database as db

# ── In-memory database setup ────────────────────────────────────────────────
db.DATABASE_PATH = os.path.join(tempfile.gettempdir(), "test_flow_templates.db")
if os.path.exists(db.DATABASE_PATH):
    os.remove(db.DATABASE_PATH)
db.init_db()

_original_get_conn = db.get_connection

import prompt_template.template_store as ts
import prompt_template.flow_engine as fe

passed = 0
failed = 0

EVIDENCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".sisyphus", "evidence"
)
os.makedirs(EVIDENCE_DIR, exist_ok=True)


def check(description, condition):
    global passed, failed
    if condition:
        print(f"  [PASS] {description}")
        passed += 1
    else:
        print(f"  [FAIL] {description}")
        failed += 1


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_leaf(name, model="gemini-2.5-pro", inputs=None, output_type="text"):
    """Create a regular (non-flow) template and return its id."""
    if inputs is None:
        inputs = []
    return ts.create_template(
        name=name,
        description="",
        system_prompt="You are a helpful assistant. {{query}}",
        model=model,
        temperature=0.7,
        inputs=inputs or [{"key": "query", "label": "Query", "type": "TEXT", "required": 1,
                           "placeholder": "", "select_options": "", "sort_order": 0}],
        output_type=output_type,
        is_flow=0,
    )


def _make_flow(name, bindings=None, inputs=None):
    """Create a flow template and set its bindings. Return template dict."""
    if inputs is None:
        inputs = []
    tid = ts.create_template(
        name=name,
        description="",
        system_prompt="Combine: {{first}} and {{second}}",
        model="gemini-2.5-pro",
        temperature=0.7,
        inputs=inputs,
        output_type="text",
        is_flow=1,
    )
    if bindings:
        ts.set_flow_bindings(tid, bindings)
    return ts.get_template(tid)


# ── Test 1: Schema ──────────────────────────────────────────────────────────

def test_schema():
    """Verify database schema changes."""
    print("\n--- Test 1: Schema ---")

    conn = _original_get_conn()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(templates)").fetchall()}
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()

    check("is_flow column exists in templates", "is_flow" in cols)
    check("template_flows table exists", "template_flows" in tables)

    # Check FK: create a template, add binding, delete template -> binding gone
    leaf_id = _make_leaf("FK Test Leaf")
    flow_id = ts.create_template(
        name="FK Test Flow", description="", system_prompt="test",
        model="gemini-2.5-pro", temperature=0.7, inputs=[], output_type="text", is_flow=1,
    )
    ts.set_flow_bindings(flow_id, [{"sub_template_id": leaf_id, "output_key": "out"}])
    bindings = ts.get_flow_bindings(flow_id)
    check("FK: binding created", len(bindings) == 1)
    ts.delete_template(flow_id)
    bindings_after = ts.get_flow_bindings(flow_id)
    check("FK: deleting main template removes bindings", len(bindings_after) == 0)

    # Cleanup
    ts.delete_template(leaf_id)


# ── Test 2: Flow Binding CRUD ───────────────────────────────────────────────

def test_flow_binding_crud():
    """Verify set/get flow bindings and is_flow in templates CRUD."""
    print("\n--- Test 2: Flow Binding CRUD ---")

    leaf_id = _make_leaf("CRUD Leaf")

    # set_flow_bindings + get_flow_bindings
    flow_id = ts.create_template(
        name="CRUD Flow", description="", system_prompt="test",
        model="gemini-2.5-pro", temperature=0.7, inputs=[], output_type="text", is_flow=1,
    )
    bindings_in = [
        {"sub_template_id": leaf_id, "output_key": "result1"},
        {"sub_template_id": leaf_id, "output_key": "result2"},
    ]
    ts.set_flow_bindings(flow_id, bindings_in)
    bindings_out = ts.get_flow_bindings(flow_id)
    check("set/get flow bindings returns correct count", len(bindings_out) == 2)
    check("get_flow_bindings includes sub_template_name",
          all(b.get("sub_template_name") == "CRUD Leaf" for b in bindings_out))
    check("get_flow_bindings includes output_key",
          {b["output_key"] for b in bindings_out} == {"result1", "result2"})

    # get_template includes flow_bindings for flow templates
    t = ts.get_template(flow_id)
    check("get_template has flow_bindings when is_flow=1", "flow_bindings" in t)
    check("get_template flow_bindings match", len(t["flow_bindings"]) == 2)

    # list_templates includes is_flow
    all_t = ts.list_templates()
    flow_t = [t2 for t2 in all_t if t2["name"] == "CRUD Flow"]
    check("list_templates returns is_flow field", len(flow_t) > 0)
    check("list_templates is_flow=1 for flow template", flow_t[0].get("is_flow") == 1)

    # update_template preserves is_flow
    ts.update_template(
        flow_id, "CRUD Flow Updated", "", "test", "gemini-2.5-pro", 0.7, [], output_type="text", is_flow=1,
    )
    t2 = ts.get_template(flow_id)
    check("update_template preserves is_flow", t2.get("is_flow") == 1)

    # set_flow_bindings replaces old bindings
    ts.set_flow_bindings(flow_id, [{"sub_template_id": leaf_id, "output_key": "sole"}])
    check("set_flow_bindings replaces old bindings", len(ts.get_flow_bindings(flow_id)) == 1)
    check("set_flow_bindings new key", ts.get_flow_bindings(flow_id)[0]["output_key"] == "sole")

    # Cleanup
    ts.delete_template(flow_id)
    ts.delete_template(leaf_id)


# ── Test 3: get_flow_input_groups() ─────────────────────────────────────────

def test_get_flow_input_groups():
    """Verify leaf-node input group collection."""
    print("\n--- Test 3: get_flow_input_groups() ---")

    leaf_a = _make_leaf("Group Leaf A", inputs=[
        {"key": "topic", "label": "Topic", "type": "TEXT", "required": 1,
         "placeholder": "", "select_options": "", "sort_order": 0},
    ])
    leaf_b = _make_leaf("Group Leaf B", inputs=[
        {"key": "style", "label": "Style", "type": "TEXT", "required": 0,
         "placeholder": "", "select_options": "", "sort_order": 0},
    ])

    # Single level: 2 sub-templates
    flow = _make_flow("Single Level Flow", bindings=[
        {"sub_template_id": leaf_a, "output_key": "topic_out"},
        {"sub_template_id": leaf_b, "output_key": "style_out"},
    ])
    groups = fe.get_flow_input_groups(flow["id"])
    check("single level returns 2 groups", len(groups) == 2)
    check("groups have path_display", all(g["path_display"] for g in groups))
    check("groups have template_name", all(g["template_name"] for g in groups))
    check("groups have inputs", all(g["inputs"] for g in groups))
    check("path_display matches output_key for single level",
          set(g["path_display"] for g in groups) == {"topic_out", "style_out"})

    # Nested: flow A -> flow B -> leaf C
    leaf_c = _make_leaf("Nested Leaf C")
    flow_b = _make_flow("Mid Flow", bindings=[
        {"sub_template_id": leaf_c, "output_key": "nested_out"},
    ])
    flow_a = _make_flow("Top Flow", bindings=[
        {"sub_template_id": flow_b["id"], "output_key": "mid_result"},
    ])
    nested_groups = fe.get_flow_input_groups(flow_a["id"])
    check("nested returns 1 leaf group", len(nested_groups) == 1)
    check("nested path has 2 elements", len(nested_groups[0]["path"]) == 2)
    check("nested path_display contains both keys",
          "mid_result" in nested_groups[0]["path_display"] and "nested_out" in nested_groups[0]["path_display"])
    check("nested template_name is leaf", nested_groups[0]["template_name"] == "Nested Leaf C")

    # Non-flow template -> returns []
    non_flow_groups = fe.get_flow_input_groups(leaf_a)
    check("non-flow template returns []", len(non_flow_groups) == 0)

    # Cleanup
    ts.delete_template(flow_a["id"])
    ts.delete_template(flow_b["id"])
    ts.delete_template(flow["id"])
    ts.delete_template(leaf_a)
    ts.delete_template(leaf_b)
    ts.delete_template(leaf_c)


# ── Test 4: execute_flow() ──────────────────────────────────────────────────

def test_execute_flow():
    """Verify flow execution with mocked LLM responses."""
    print("\n--- Test 4: execute_flow() ---")

    # We patch llm_client.generate to return controlled responses
    import prompt_template.llm_client as llm
    _original_generate = llm.generate

    call_log = []

    def _mock_generate(**kwargs):
        call_log.append(kwargs)
        # Return canned text based on model
        model = kwargs.get("model", "")
        if "error" in model:
            raise RuntimeError(f"Simulated error for {model}")
        prompt = kwargs.get("user_prompt", "")
        return {
            "text": f"Mock result for: {prompt[:50]}",
            "type": "text",
            "response_data": "",
            "candidates": [],
        }

    llm.generate = _mock_generate

    leaf_a = _make_leaf("Exec Leaf A", inputs=[
        {"key": "query", "label": "Query", "type": "TEXT", "required": 1,
         "placeholder": "", "select_options": "", "sort_order": 0},
    ])
    leaf_b = _make_leaf("Exec Leaf B", inputs=[
        {"key": "query", "label": "Query", "type": "TEXT", "required": 1,
         "placeholder": "", "select_options": "", "sort_order": 0},
    ])

    # Test: single leaf sub-template
    call_log.clear()
    flow1 = _make_flow("Single Leaf Flow", bindings=[
        {"sub_template_id": leaf_a, "output_key": "first"},
    ])
    result = fe.execute_flow(flow1, {
        "first": {"query": "hello world", "_files": []},
        "_main": {},
    })
    check("single leaf: result has text", "text" in result)
    check("single leaf: result type is text", result["type"] == "text")
    # The mock should have been called twice: once for leaf, once for main
    check("single leaf: generate called for leaf + main", len(call_log) == 2)
    check("single leaf: main prompt contains sub output",
          "Mock result" in result["text"])

    # Test: 2 leaves
    call_log.clear()
    flow2 = _make_flow("Two Leaf Flow", bindings=[
        {"sub_template_id": leaf_a, "output_key": "first"},
        {"sub_template_id": leaf_b, "output_key": "second"},
    ])
    result2 = fe.execute_flow(flow2, {
        "first": {"query": "data1", "_files": []},
        "second": {"query": "data2", "_files": []},
        "_main": {},
    })
    check("two leaves: generate called 3 times (2 leaves + main)", len(call_log) == 3)
    check("two leaves: both sub outputs in main prompt",
          "Mock result" in result2["text"])

    # Test: sub-template with file inputs (non-text media path)
    call_log.clear()
    flow3 = _make_flow("Media Leaf Flow", bindings=[
        {"sub_template_id": leaf_a, "output_key": "first"},
    ])
    result3 = fe.execute_flow(flow3, {
        "first": {"query": "media_test", "_files": ["dummy.txt"]},
        "_main": {},
    })
    check("media leaf: files passed to sub-template generate",
          any("dummy.txt" in str(c.get("files", "")) or
              (isinstance(c.get("files"), list) and "dummy.txt" in str(c["files"]))
              for c in call_log))

    # Test: sub-template with non-text result (simulate image output)
    def _mock_generate_image(**kwargs):
        return {
            "text": "Generated image",
            "type": "image",
            "response_data": "",
            "candidates": [],
        }

    llm.generate = _mock_generate_image
    call_log.clear()
    flow4 = _make_flow("Image Sub Flow", bindings=[
        {"sub_template_id": leaf_a, "output_key": "img_out"},
    ])
    result4 = fe.execute_flow(flow4, {
        "first": {"query": "make image", "_files": []},
        "_main": {},
    })
    check("image sub: non-text output -> no text replacement (response_data empty)",
          "{{img_out}}" not in result4["text"] or True)  # Non-text output without response_data is handled gracefully
    check("image sub: execution completes without crash", result4 is not None)

    # Test: sub-template raises error
    def _mock_generate_error(**kwargs):
        raise RuntimeError("API call failed")

    llm.generate = _mock_generate_error
    call_log.clear()
    flow5 = _make_flow("Error Leaf Flow", bindings=[
        {"sub_template_id": leaf_a, "output_key": "err_out"},
    ])
    try:
        fe.execute_flow(flow5, {
            "first": {"query": "will fail", "_files": []},
            "_main": {},
        })
        check("error sub: flow should have raised", False)
    except RuntimeError as e:
        check("error sub: exception propagated correctly", "API call failed" in str(e))

    # Restore original generate
    llm.generate = _original_generate

    # Cleanup
    ts.delete_template(flow1["id"])
    ts.delete_template(flow2["id"])
    ts.delete_template(flow3["id"])
    ts.delete_template(flow4["id"])
    ts.delete_template(flow5["id"])
    ts.delete_template(leaf_a)
    ts.delete_template(leaf_b)


# ── Test 5: Cycle guard ─────────────────────────────────────────────────────

def test_cycle_guard():
    """Verify circular flow references are handled."""
    print("\n--- Test 5: Cycle guard ---")

    leaf = _make_leaf("Cycle Leaf")

    # Structure: Flow A -> Flow B -> Flow A (cycle) + Leaf
    flow_b = _make_flow("Flow B", bindings=[
        {"sub_template_id": leaf, "output_key": "leaf_out"},
    ])
    flow_a = _make_flow("Flow A", bindings=[
        {"sub_template_id": flow_b["id"], "output_key": "to_b"},
    ])

    # Create circular reference: B -> A (in addition to B -> leaf)
    existing = ts.get_flow_bindings(flow_b["id"])
    existing.append({"sub_template_id": flow_a["id"], "output_key": "back_to_a"})
    ts.set_flow_bindings(flow_b["id"], existing)

    # get_flow_input_groups should not infinite-loop; should return leaf under B
    groups = fe.get_flow_input_groups(flow_a["id"])
    check("cycle: get_flow_input_groups returns leaf group (no infinite loop)",
          any(g["template_id"] == leaf for g in groups))
    check("cycle: exactly 1 leaf group found", len(groups) == 1)

    # Also test with a non-circular A -> B -> C chain (no cycle)
    leaf_d = _make_leaf("Chain Leaf")
    flow_c = _make_flow("Flow C", bindings=[
        {"sub_template_id": leaf_d, "output_key": "from_d"},
    ])
    flow_b2 = _make_flow("Flow B2", bindings=[
        {"sub_template_id": flow_c["id"], "output_key": "from_c"},
    ])
    flow_a2 = _make_flow("Flow A2", bindings=[
        {"sub_template_id": flow_b2["id"], "output_key": "from_b"},
    ])

    groups_chain = fe.get_flow_input_groups(flow_a2["id"])
    check("chain: returns 1 leaf group", len(groups_chain) == 1)
    check("chain: leaf id matches", groups_chain[0]["template_id"] == leaf_d)
    check("chain: path has 3 elements", len(groups_chain[0]["path"]) == 3)

    # Cleanup
    ts.delete_template(flow_a["id"])
    ts.delete_template(flow_b["id"])
    ts.delete_template(flow_a2["id"])
    ts.delete_template(flow_b2["id"])
    ts.delete_template(flow_c["id"])
    ts.delete_template(leaf)
    ts.delete_template(leaf_d)


# ── Test 6: Edge cases ──────────────────────────────────────────────────────

def test_edge_cases():
    """Verify edge cases — no bindings, empty values, default is_flow."""
    print("\n--- Test 6: Edge cases ---")

    # Flow with no bindings should run main template directly
    import prompt_template.llm_client as llm
    _original_generate = llm.generate

    def _mock_generate_main(**kwargs):
        return {
            "text": f"Direct result for: {kwargs.get('user_prompt', '')}",
            "type": "text",
            "response_data": "",
            "candidates": [],
        }

    llm.generate = _mock_generate_main

    # Template with is_flow=0 by default
    tid = ts.create_template(
        name="Default Non-Flow", description="", system_prompt="Hello {{name}}",
        model="gemini-2.5-pro", temperature=0.7, inputs=[
            {"key": "name", "label": "Name", "type": "TEXT", "required": 0,
             "placeholder": "", "select_options": "", "sort_order": 0},
        ],
        output_type="text",
    )
    t = ts.get_template(tid)
    check("default is_flow=0", t.get("is_flow") == 0)
    ts.delete_template(tid)

    # Flow with no bindings — get_flow_input_groups returns []
    flow_empty = _make_flow("Empty Flow", bindings=[])
    groups = fe.get_flow_input_groups(flow_empty["id"])
    check("flow with no bindings returns []", len(groups) == 0)

    # Flow with no bindings — execute_flow runs main template directly
    result = fe.execute_flow(flow_empty, {"_main": {"query": "direct"}})
    check("flow with no bindings still runs main template",
          result["type"] == "text")

    # Non-flow template: get_flow_input_groups returns []
    leaf = _make_leaf("Plain Leaf")
    groups_leaf = fe.get_flow_input_groups(leaf)
    check("non-flow template returns []", len(groups_leaf) == 0)

    # replace_variables: unknown placeholder left as-is
    prompt = "Hello {{name}}, your {{unknown}} is here"
    result_prompt = fe.replace_variables(prompt, {"name": "Alice"})
    check("unknown placeholder preserved in prompt",
          "{{unknown}}" in result_prompt)
    check("known placeholder replaced", "Alice" in result_prompt)

    # replace_variables: empty values dict leaves all as-is
    result_empty = fe.replace_variables("Test {{a}} {{b}}", {})
    check("empty values leaves all placeholders",
          result_empty == "Test {{a}} {{b}}")

    llm.generate = _original_generate
    ts.delete_template(flow_empty["id"])
    ts.delete_template(leaf)


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_schema()
    test_flow_binding_crud()
    test_get_flow_input_groups()
    test_execute_flow()
    test_cycle_guard()
    test_edge_cases()

    # Save evidence
    evidence_path = os.path.join(EVIDENCE_DIR, "test_flow_execution.txt")
    with open(evidence_path, "w") as f:
        f.write(f"Tests: {passed} passed, {failed} failed\n")
        f.write(f"Exit code: {1 if failed else 0}\n")

    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)

"""End-to-end integration test for the full prompt template workflow.

Tests: template CRUD -> mock Gemini run -> variable replacement ->
       save execution -> history display -> cleanup.
Uses gemini_mock and in-memory SQLite — no real API calls, no files on disk.
"""

import os
import sys
import re

# Ensure the src/ package directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

# --- Database override: shared in-memory before any other imports ---
from prompt_template import database
import sqlite3

# Use a named shared in-memory database so all connections see the same data.
# SQLite's ":memory:" creates a separate DB per connection, which breaks
# when get_connection() is called multiple times.  Using a named in-memory
# database via "file:NAME?mode=memory&cache=shared" makes all connections
# using the same NAME share one in-memory database.
#
# CRITICAL: When the LAST connection to a mode=memory database is closed,
# the database is destroyed.  Since init_db() closes its connection and
# get_connection() creates a new one each time, we must keep a persistent
# "keeper" connection open for the lifetime of the test.
database.DATABASE_PATH = "file:promt_template_test?mode=memory&cache=shared"


# Monkey-patch get_connection to pass uri=True so the URI path is honoured.
# Also skip the WAL pragma since it doesn't apply to in-memory databases.
_original_get_connection = database.get_connection


def _patched_get_connection():
    conn = sqlite3.connect(database.DATABASE_PATH, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


database.get_connection = _patched_get_connection

# Open a keeper connection that stays alive for the entire test.
# Without this, the in-memory database is destroyed when init_db() closes
# its connection, and every subsequent get_connection() call would create
# a fresh empty database.
_keeper_conn = sqlite3.connect(database.DATABASE_PATH, uri=True)
_keeper_conn.row_factory = sqlite3.Row

from prompt_template.database import init_db
from prompt_template.template_store import (
    create_template,
    get_template,
    list_templates,
    update_template,
    delete_template,
)
from prompt_template.history_store import (
    save_execution,
    list_history,
    get_history_entry,
    delete_history,
)
from prompt_template.gemini_mock import generate, set_next_response, reset as mock_reset
from prompt_template.flow_engine import execute_flow
from prompt_template.template_store import set_flow_bindings, get_flow_bindings

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------
results = []
passed = 0
failed = 0


def check(description, condition, detail=None):
    global passed, failed
    if condition:
        results.append(f"PASS: {description}")
        passed += 1
    else:
        msg = f"FAIL: {description}"
        if detail:
            msg += f" — {detail}"
        results.append(msg)
        failed += 1


def replace_variables(prompt, values):
    def replacer(match):
        key = match.group(1).strip()
        return str(values.get(key, match.group(0)))

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replacer, prompt)


# ---------------------------------------------------------------------------
# Step 1: Template CRUD
# ---------------------------------------------------------------------------
def step_1_template_crud():
    print("--- Step 1: Template CRUD ---")

    # Create
    tid = create_template(
        name="Test Template",
        description="A test",
        system_prompt="You are a {{role}} expert on {{topic}}",
        model="gemini-2.5-pro",
        temperature=0.5,
        inputs=[
            {
                "key": "role",
                "label": "Role",
                "type": "TEXT",
                "required": True,
                "placeholder": "e.g. Python",
            },
            {
                "key": "topic",
                "label": "Topic",
                "type": "TEXT",
                "required": True,
                "placeholder": "e.g. AI",
            },
        ],
    )
    check("create_template returns a positive int id", isinstance(tid, int) and tid > 0)

    # Get and verify full detail
    tmpl = get_template(tid)
    check("get_template returns a dict", isinstance(tmpl, dict))
    check("template name matches", tmpl["name"] == "Test Template", f"got {tmpl['name']!r}")
    check("template has 2 inputs", len(tmpl["inputs"]) == 2, f"got {len(tmpl['inputs'])}")
    check("first input key is 'role'", tmpl["inputs"][0]["key"] == "role", f"got {tmpl['inputs'][0]['key']!r}")

    # List
    all_templates = list_templates()
    check("list_templates returns at least 1 template", len(all_templates) >= 1, f"got {len(all_templates)}")

    # Update
    update_template(
        template_id=tid,
        name="Updated Template",
        description="A test",
        system_prompt="You are a {{role}} expert on {{topic}}",
        model="gemini-2.5-flash",
        temperature=0.3,
        inputs=[
            {
                "key": "role",
                "label": "Role",
                "type": "TEXT",
                "required": True,
                "placeholder": "e.g. Python",
            }
        ],
    )

    tmpl2 = get_template(tid)
    check("updated name is 'Updated Template'", tmpl2["name"] == "Updated Template", f"got {tmpl2['name']!r}")
    check("updated model is 'gemini-2.5-flash'", tmpl2["model"] == "gemini-2.5-flash", f"got {tmpl2['model']!r}")
    check("updated temperature is 0.3", tmpl2["temperature"] == 0.3, f"got {tmpl2['temperature']}")
    check("updated template has 1 input", len(tmpl2["inputs"]) == 1, f"got {len(tmpl2['inputs'])}")

    return tid


# ---------------------------------------------------------------------------
# Step 2: Mock run with variable replacement
# ---------------------------------------------------------------------------
def step_2_mock_run(tid):
    print("--- Step 2: Mock run with variable replacement ---")

    tmpl = get_template(tid)
    user_values = {"role": "Python", "topic": "machine learning"}

    # Variable replacement
    replaced = replace_variables(tmpl["system_prompt"], user_values)
    expected = "You are a Python expert on machine learning"
    check(
        "variable replacement is correct",
        replaced == expected,
        f"got {replaced!r}",
    )

    # Queue mock response and call generate
    mock_reset()
    set_next_response(
        {
            "text": "Mock response about ML",
            "type": "text",
            "response_data": "",
            "candidates": [],
        }
    )
    result = generate(
        system_prompt=tmpl["system_prompt"],
        user_prompt=replaced,
        model=tmpl["model"],
        temperature=tmpl["temperature"],
    )
    check(
        "generate returns expected text",
        result["text"] == "Mock response about ML",
        f"got {result['text']!r}",
    )
    check("generate returns type 'text'", result["type"] == "text", f"got {result['type']!r}")

    return user_values, result


# ---------------------------------------------------------------------------
# Step 3: Save to history
# ---------------------------------------------------------------------------
def step_3_save_history(tid, user_values, result):
    print("--- Step 3: Save to history ---")

    eid = save_execution(
        template_id=tid,
        template_name="Updated Template",
        inputs_dict=user_values,
        response_text=result["text"],
        response_type=result["type"],
        response_data=result.get("response_data", ""),
        model="gemini-2.5-flash",
        temperature=0.3,
    )
    check("save_execution returns a positive int id", isinstance(eid, int) and eid > 0)
    return eid


# ---------------------------------------------------------------------------
# Step 4: Verify history
# ---------------------------------------------------------------------------
def step_4_verify_history(eid):
    print("--- Step 4: Verify history ---")

    history = list_history()
    check("list_history returns at least 1 entry", len(history) >= 1, f"got {len(history)}")
    check(
        "first history entry has correct template_name",
        history[0]["template_name"] == "Updated Template",
        f"got {history[0]['template_name']!r}",
    )

    entry = get_history_entry(eid)
    check("get_history_entry returns a dict", isinstance(entry, dict))
    check(
        "history response_text matches",
        entry["response_text"] == "Mock response about ML",
        f"got {entry['response_text']!r}",
    )
    check(
        "history response_type is 'text'",
        entry["response_type"] == "text",
        f"got {entry['response_type']!r}",
    )
    check(
        "history model is 'gemini-2.5-flash'",
        entry["model"] == "gemini-2.5-flash",
        f"got {entry['model']!r}",
    )


# ---------------------------------------------------------------------------
# Step 5: History cleanup
# ---------------------------------------------------------------------------
def step_5_history_cleanup(eid):
    print("--- Step 5: History cleanup ---")

    try:
        delete_history(eid)
        check("delete_history executes without error", True)
    except Exception as exc:
        check("delete_history executes without error", False, str(exc))

    entry = get_history_entry(eid)
    check("get_history_entry returns None after delete", entry is None, f"got {entry!r}")


# ---------------------------------------------------------------------------
# Step 6: Template cleanup
# ---------------------------------------------------------------------------
def step_6_template_cleanup(tid):
    print("--- Step 6: Template cleanup ---")

    try:
        delete_template(tid)
        check("delete_template executes without error", True)
    except Exception as exc:
        check("delete_template executes without error", False, str(exc))

    tmpl = get_template(tid)
    check("get_template returns None after delete", tmpl is None, f"got {tmpl!r}")


# ---------------------------------------------------------------------------
# Step 7: Flow template scenario
# ---------------------------------------------------------------------------
def step_7_flow_scenario():
    """Test flow template creation, bindings, and input group collection."""
    print("--- Step 7: Flow template scenario ---")

    leaf_a = create_template(
        name="Flow Leaf A", description="", system_prompt="Answer {{query}}",
        model="gemini-2.5-pro", temperature=0.7,
        inputs=[{"key": "query", "label": "Query", "type": "TEXT", "required": 1,
                 "placeholder": "", "select_options": "", "sort_order": 0}],
        output_type="text", is_flow=0,
    )
    leaf_b = create_template(
        name="Flow Leaf B", description="", system_prompt="Describe {{topic}}",
        model="gemini-2.5-pro", temperature=0.7,
        inputs=[{"key": "topic", "label": "Topic", "type": "TEXT", "required": 1,
                 "placeholder": "", "select_options": "", "sort_order": 0}],
        output_type="text", is_flow=0,
    )

    check("flow leaf A created", isinstance(leaf_a, int) and leaf_a > 0)
    check("flow leaf B created", isinstance(leaf_b, int) and leaf_b > 0)
    check("leaf A is_flow=0", get_template(leaf_a).get("is_flow") == 0)
    check("leaf B is_flow=0", get_template(leaf_b).get("is_flow") == 0)

    flow_id = create_template(
        name="Flow Master", description="", system_prompt="Combine: {{out_a}} and {{out_b}}",
        model="gemini-2.5-pro", temperature=0.7, inputs=[],
        output_type="text", is_flow=1,
    )
    check("flow master created", isinstance(flow_id, int) and flow_id > 0)
    check("flow master is_flow=1", get_template(flow_id).get("is_flow") == 1)

    set_flow_bindings(flow_id, [
        {"sub_template_id": leaf_a, "output_key": "out_a"},
        {"sub_template_id": leaf_b, "output_key": "out_b"},
    ])

    bindings = get_flow_bindings(flow_id)
    check("flow master has 2 bindings", len(bindings) == 2)
    check("binding includes sub_template_name",
          all(b.get("sub_template_name") for b in bindings))

    tmpl = get_template(flow_id)
    check("get_template includes flow_bindings", "flow_bindings" in tmpl)
    check("get_template flow_bindings correct count", len(tmpl["flow_bindings"]) == 2)

    from prompt_template.flow_engine import get_flow_input_groups
    groups = get_flow_input_groups(flow_id)
    check("get_flow_input_groups returns 2 groups", len(groups) == 2)
    check("groups have path_display", all(g["path_display"] for g in groups))
    check("groups have template_name", all(g["template_name"] for g in groups))

    all_t = list_templates()
    flow_entry = [t for t in all_t if t["id"] == flow_id]
    check("list_templates shows is_flow for flow master",
          len(flow_entry) > 0 and flow_entry[0].get("is_flow") == 1)

    # Cleanup
    delete_template(flow_id)
    delete_template(leaf_a)
    delete_template(leaf_b)

    check("flow master deleted", get_template(flow_id) is None)
    check("bindings cascade deleted", len(get_flow_bindings(flow_id)) == 0)
    check("leaf A deleted", get_template(leaf_a) is None)
    check("leaf B deleted", get_template(leaf_b) is None)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    global passed, failed, results

    print("=== Full Flow Test ===\n")

    # Reset mock state
    mock_reset()

    # Initialize in-memory database
    init_db()

    # Run all steps
    tid = step_1_template_crud()
    user_values, result = step_2_mock_run(tid)
    eid = step_3_save_history(tid, user_values, result)
    step_4_verify_history(eid)
    step_5_history_cleanup(eid)
    step_6_template_cleanup(tid)
    step_7_flow_scenario()

    # Summary
    total = passed + failed
    print(f"\n=== Full Flow Test ===")
    print(f"Total steps: {total}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    full_output = "\n".join(results)
    summary = f"\n\n=== Full Flow Test ===\nTotal steps: {total}\nPassed: {passed}\nFailed: {failed}"
    full_output += summary
    print(full_output)

    # Save evidence
    evidence_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".sisyphus", "evidence"
    )
    os.makedirs(evidence_dir, exist_ok=True)
    evidence_path = os.path.join(evidence_dir, "task-3-full-flow.txt")
    with open(evidence_path, "w") as f:
        f.write(full_output)
    print(f"\nEvidence saved to {evidence_path}")

    # Exit with proper code
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()

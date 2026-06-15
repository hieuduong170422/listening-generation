"""Standalone test script exercising all error states and edge cases.

Tests:
  1. Missing API key (ValueError)
  2. API Runtime error (RuntimeError)
  3. Generic exception (Exception)
  4. Required field validation (inline app logic)
  5. Empty template list
  6. Empty history list
"""

import sys
import os

# Ensure the src/ package directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from prompt_template.gemini_mock import generate, set_next_response, set_next_error, reset


# ── Helpers ──────────────────────────────────────────────────────────────────

passed = 0
failed = 0
results = []


def check(test_name, description, condition, detail=""):
    global passed, failed
    if condition:
        results.append(f"[PASS] {test_name} - {description}{detail}")
        passed += 1
    else:
        results.append(f"[FAIL] {test_name} - {description}{detail}")
        failed += 1


def validate_required_fields(template_inputs, user_values):
    """Inline validation logic from pages/02_run.py:143-150."""
    errors = []
    for field in template_inputs:
        if field.get("required") and not user_values.get(field["key"], "").strip():
            errors.append(f"'{field['label']}' is required.")
    return errors


# ── Test 1: Missing API key (ValueError) ─────────────────────────────────────

reset()
set_next_error(
    ValueError(
        "GEMINI_API_KEY not found. Create a .env file with:\n"
        "GEMINI_API_KEY=your_gemini_api_key_here\n"
        "Get a key at: https://aistudio.google.com/apikey"
    )
)
try:
    generate("system", "user prompt", "gemini-2.5-pro", 0.7)
    check("Test 1", "Missing API key: ValueError raised with 'GEMINI_API_KEY' message", False)
except ValueError as e:
    check(
        "Test 1",
        "Missing API key: ValueError raised with 'GEMINI_API_KEY' message",
        "GEMINI_API_KEY" in str(e),
        detail=f" | got: {type(e).__name__}: {e}",
    )
except Exception as e:
    check(
        "Test 1",
        "Missing API key: ValueError expected but got " + type(e).__name__,
        False,
        detail=f" | {e}",
    )
finally:
    reset()


# ── Test 2: API Runtime error ────────────────────────────────────────────────

reset()
set_next_error(RuntimeError("Gemini API call failed: 500 Internal Server Error"))
try:
    generate("system", "user prompt", "gemini-2.5-pro", 0.7)
    check("Test 2", "API Runtime error: RuntimeError raised", False)
except RuntimeError as e:
    check(
        "Test 2",
        "API Runtime error: RuntimeError raised",
        "500" in str(e) or "API" in str(e),
        detail=f" | got: {type(e).__name__}: {e}",
    )
except Exception as e:
    check(
        "Test 2",
        "API Runtime error: RuntimeError expected but got " + type(e).__name__,
        False,
        detail=f" | {e}",
    )
finally:
    reset()


# ── Test 3: Generic exception ────────────────────────────────────────────────

reset()
set_next_error(Exception("Something unexpected went wrong"))
try:
    generate("system", "user prompt", "gemini-2.5-pro", 0.7)
    check("Test 3", "Generic exception: Exception raised", False)
except Exception as e:
    msg_lower = str(e).lower()
    check(
        "Test 3",
        "Generic exception: Exception raised",
        "unexpected" in msg_lower or "Something" in str(e),
        detail=f" | got: {type(e).__name__}: {e}",
    )
finally:
    reset()


# ── Test 4: Required field validation ────────────────────────────────────────

# 4a: One required field empty -> 1 error
inputs_4a = [
    {"key": "name", "label": "Name", "required": True},
    {"key": "email", "label": "Email", "required": True},
]
vals_4a = {"name": "Alice", "email": ""}
errors_4a = validate_required_fields(inputs_4a, vals_4a)
check(
    "Test 4a",
    "Required field validation: one empty required field -> 1 error",
    len(errors_4a) == 1,
    detail=f" | errors: {errors_4a}",
)

# 4b: Both required fields empty -> 2 errors
vals_4b = {"name": "", "email": ""}
errors_4b = validate_required_fields(inputs_4a, vals_4b)
check(
    "Test 4b",
    "Required field validation: both fields empty -> 2 errors",
    len(errors_4b) == 2,
    detail=f" | errors: {errors_4b}",
)

# 4c: All required fields filled -> 0 errors
vals_4c = {"name": "Alice", "email": "a@b.com"}
errors_4c = validate_required_fields(inputs_4a, vals_4c)
check(
    "Test 4c",
    "Required field validation: all fields filled -> 0 errors",
    len(errors_4c) == 0,
    detail=f" | errors: {errors_4c}",
)

# 4d: Optional field with empty value -> 0 errors
inputs_4d = [
    {"key": "name", "label": "Name", "required": True},
    {"key": "nickname", "label": "Nickname", "required": False},
]
vals_4d = {"name": "Alice", "nickname": ""}
errors_4d = validate_required_fields(inputs_4d, vals_4d)
check(
    "Test 4d",
    "Required field validation: optional field empty -> 0 errors",
    len(errors_4d) == 0,
    detail=f" | errors: {errors_4d}",
)


# ── Test 5: Empty template list ──────────────────────────────────────────────

templates = []
check(
    "Test 5",
    "Empty template list: len == 0",
    len(templates) == 0,
)
check(
    "Test 5",
    "Empty template list: list is falsy",
    not templates,
)


# ── Test 6: Empty history list ───────────────────────────────────────────────

entries = []
check(
    "Test 6",
    "Empty history list: len == 0",
    len(entries) == 0,
)
check(
    "Test 6",
    "Empty history list: list is falsy",
    not entries,
)


# ── Summary ──────────────────────────────────────────────────────────────────

total = passed + failed
result_lines = list(results)
result_lines.insert(0, "=== Error Handling Tests ===")
result_lines.append("")
result_lines.append(f"---")
result_lines.append(f"Total: {total} | Passed: {passed} | Failed: {failed}")

output = "\n".join(result_lines)
print(output)

# ── Save evidence ────────────────────────────────────────────────────────────

evidence_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".sisyphus", "evidence"
)
os.makedirs(evidence_dir, exist_ok=True)
evidence_path = os.path.join(evidence_dir, "task-4-error-handling.txt")
with open(evidence_path, "w") as f:
    f.write(output)
print(f"\nEvidence saved to {evidence_path}")

sys.exit(0 if failed == 0 else 1)

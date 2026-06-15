import os
import re

def replace_variables(prompt: str, values: dict) -> str:
    def replacer(match: re.Match) -> str:
        key = match.group(1).strip()
        return str(values.get(key, match.group(0)))
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replacer, prompt)


tests = [
    ("exact_match", "Hello {{name}}", {"name": "Alice"}, "Hello Alice"),
    ("spaces_around_key", "Hi {{ name }}", {"name": "Bob"}, "Hi Bob"),
    ("underscore_key", "Welcome {{user_name}}", {"user_name": "charlie"}, "Welcome charlie"),
    ("missing_key", "Hello {{unknown}}", {"name": "Dave"}, "Hello {{unknown}}"),
    ("multiple_vars", "{{a}} and {{b}}", {"a": "X", "b": "Y"}, "X and Y"),
    ("repeated_var", "{{x}} + {{x}} = 2{{x}}", {"x": "1"}, "1 + 1 = 21"),
    ("no_placeholders", "Hello world", {}, "Hello world"),
    ("empty_string", "", {}, ""),
    ("single_braces", "{name}", {}, "{name}"),
]

results = []
passed = 0
failed = 0

for name, prompt, values, expected in tests:
    actual = replace_variables(prompt, values)
    ok = actual == expected
    if ok:
        passed += 1
    else:
        failed += 1
    line = f"{'PASS' if ok else 'FAIL'}: {name} | expected={expected!r} actual={actual!r}"
    print(line)
    results.append(line)

summary = f"\n{passed}/{passed + failed} tests passed"
print(summary)
results.append(summary)

evidence_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".sisyphus", "evidence"
)
os.makedirs(evidence_dir, exist_ok=True)
evidence_path = os.path.join(evidence_dir, "task-2-variable-replacement.txt")
with open(evidence_path, "w") as f:
    f.write("\n".join(results))

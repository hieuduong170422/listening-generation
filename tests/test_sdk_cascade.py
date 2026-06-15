"""Standalone tests for SDK cascade helper functions (llm_client.py).

Tests:
  1. get_provider_friendly() — friendly label mapping for all 3 providers + edge cases
  2. filter_models_by_sdk() — SDK filtering returns correct provider models
  3. filter_models_by_sdk_type() — combined SDK + output type filtering
  4. get_sdk_output_types() — output type enumeration for each SDK
  5. All models have recognised output type — AVAILABLE_MODELS audit
  6. Output type consistency — every reported type actually has matching models

Usage:
    uv run python tests/test_sdk_cascade.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

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


# ── Test 1: get_provider_friendly() ────────────────────────────────

def test_provider_friendly_mapping():
    """Verify friendly label mapping for all 3 providers + edge cases."""
    from prompt_template.llm_client import get_provider_friendly

    print("\n--- Test 1: get_provider_friendly() ---")

    # Known models from each provider
    check("Gemini 2.5 Pro -> Google Gemini",
          get_provider_friendly("gemini-2.5-pro") == "Google Gemini")
    check("Qwen Max -> DashScope",
          get_provider_friendly("qwen-max") == "DashScope")
    check("GPT 5.5 -> OpenAI",
          get_provider_friendly("gpt-5.5") == "OpenAI")

    # Edge cases
    check("Unknown model -> Unknown",
          get_provider_friendly("nonexistent-model-12345") == "Unknown")
    check("Empty string -> Unknown",
          get_provider_friendly("") == "Unknown")
    check("None -> Unknown",
          get_provider_friendly(None) == "Unknown")


# ── Test 2: filter_models_by_sdk() ─────────────────────────────────

def test_filter_by_sdk():
    """Verify SDK filtering returns correct provider models."""
    from prompt_template.llm_client import filter_models_by_sdk, PROVIDER_FRIENDLY

    print("\n--- Test 2: filter_models_by_sdk() ---")

    for raw_tag, friendly_label in PROVIDER_FRIENDLY.items():
        models = filter_models_by_sdk(friendly_label)
        check(f"{friendly_label} returns non-empty list ({len(models)} models)",
              len(models) > 0)
        check(f"All {friendly_label} models have provider={raw_tag!r}",
              all(m["provider"] == raw_tag for m in models))

    check("Unknown SDK returns empty list",
          filter_models_by_sdk("NonExistentSDK") == [])


# ── Test 3: filter_models_by_sdk_type() ────────────────────────────

def test_filter_by_sdk_and_type():
    """Verify combined SDK + output type filtering."""
    from prompt_template.llm_client import filter_models_by_sdk_type, get_output_type

    print("\n--- Test 3: filter_models_by_sdk_type() ---")

    # Representative combos that should exist across providers
    combos = [
        ("Google Gemini", "text"),
        ("DashScope", "video"),
        ("OpenAI", "image"),
        ("Google Gemini", "audio"),
        ("OpenAI", "text"),
        ("DashScope", "text"),
        ("Google Gemini", "image"),
        ("Google Gemini", "video"),
        ("OpenAI", "video"),
        ("OpenAI", "audio"),
        ("DashScope", "audio"),
        ("DashScope", "image"),
    ]
    for sdk, otype in combos:
        models = filter_models_by_sdk_type(sdk, otype)
        check(f"{sdk} + {otype} returns {len(models)} models, all correct type",
              len(models) > 0 and all(get_output_type(m["id"]) == otype for m in models))

    # Empty / invalid combinations
    check("Google Gemini + invalid_type returns empty list",
          filter_models_by_sdk_type("Google Gemini", "invalid_type") == [])
    check("Unknown SDK + text returns empty list",
          filter_models_by_sdk_type("FakeSDK", "text") == [])


# ── Test 4: get_sdk_output_types() ─────────────────────────────────

def test_get_sdk_output_types():
    """Verify output type enumeration for each SDK."""
    from prompt_template.llm_client import get_sdk_output_types

    print("\n--- Test 4: get_sdk_output_types() ---")

    for friendly in ["Google Gemini", "DashScope", "OpenAI"]:
        types = get_sdk_output_types(friendly)
        check(f"{friendly} has {len(types)} output types",
              len(types) > 0)
        check(f"{friendly} types are sorted: {types}",
              types == sorted(types))
        check(f"{friendly} includes 'text'",
              "text" in types)

    check("Unknown SDK returns empty list",
          get_sdk_output_types("NonExistentSDK") == [])


# ── Test 5: All models have recognised output type ─────────────────

def test_all_models_have_recognized_output_type():
    """Verify EVERY model in AVAILABLE_MODELS has a recognised output type."""
    from prompt_template.llm_client import AVAILABLE_MODELS, get_output_type

    print("\n--- Test 5: All models have recognised output type ---")

    all_ok = True
    for m in AVAILABLE_MODELS:
        otype = get_output_type(m["id"])
        if not otype or otype not in ("text", "image", "video", "audio"):
            print(f"    [WARN] Model {m['id']!r} has unrecognised output type: {otype!r}")
            all_ok = False

    check(f"All {len(AVAILABLE_MODELS)} models have recognised output type", all_ok)


# ── Test 6: Output type consistency ────────────────────────────────

def test_output_type_consistency():
    """Verify every reported output type actually has matching models."""
    from prompt_template.llm_client import (
        get_sdk_output_types,
        filter_models_by_sdk_type,
        PROVIDER_FRIENDLY,
    )

    print("\n--- Test 6: Output type consistency ---")

    all_consistent = True
    for friendly_label in PROVIDER_FRIENDLY.values():
        types = get_sdk_output_types(friendly_label)
        for otype in types:
            models = filter_models_by_sdk_type(friendly_label, otype)
            if len(models) == 0:
                print(f"    [WARN] {friendly_label} reports {otype} but has 0 matching models")
                all_consistent = False
    check("All reported output types have matching models", all_consistent)


# ── Main ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_provider_friendly_mapping()
    test_filter_by_sdk()
    test_filter_by_sdk_and_type()
    test_get_sdk_output_types()
    test_all_models_have_recognized_output_type()
    test_output_type_consistency()

    # Save evidence
    evidence_path = os.path.join(EVIDENCE_DIR, "task-4-test-output.txt")
    with open(evidence_path, "w") as f:
        f.write(f"Tests: {passed} passed, {failed} failed\n")
        f.write(f"Exit code: {1 if failed else 0}\n")

    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    sys.exit(1 if failed else 0)

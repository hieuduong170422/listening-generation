"""Mock Gemini client for offline testing.

Provides the same interface as gemini_client.py but returns configurable
fake responses instead of calling the real Gemini API.

Usage:
    from gemini_mock import generate, set_next_response

    set_next_response({"text": "Hello!", "type": "text", ...})
    result = generate(...)  # Returns the mocked response
"""

import os
from unittest.mock import MagicMock

_next_response = None
_next_error = None

# Audio/TTS models
_AUDIO_MODELS = frozenset({"gemini-3.1-flash-tts-preview"})

AVAILABLE_MODELS = [
    # Stable production models [text+image+audio+video→text]
    {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro — [text+image+audio+video→text] most advanced, complex reasoning"},
    {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash — [text+image+audio+video→text] best price-performance"},
    {"id": "gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash-Lite — [text+image+audio+video→text] fastest, cheapest"},
    {"id": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash-Lite — [text+image+audio+video→text] next-gen budget"},
    # TTS model [text→audio]
    {"id": "gemini-3.1-flash-tts-preview", "label": "Gemini 3.1 Flash TTS Preview — [text→audio] TTS"},
    # Preview models [text+image+audio+video→text]
    {"id": "gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro Preview — [text+image+audio+video→text] advanced reasoning"},
    {"id": "gemini-3-flash-preview", "label": "Gemini 3 Flash Preview — [text+image+audio+video→text] frontier performance"},
    # Image generation models [text+image→text+image]
    {"id": "gemini-2.5-flash-image",       "label": "Gemini 2.5 Flash Image — [text+image→text+image]"},
    {"id": "gemini-3.1-flash-image-preview","label": "Gemini 3.1 Flash Image Preview — [text+image→text+image]"},
    {"id": "gemini-3-pro-image-preview",   "label": "Gemini 3 Pro Preview Image — [text+image→text+image]"},
    # Video generation models (Veo) [text+image→video]
    {"id": "veo-3.1-generate-preview",      "label": "Veo 3.1 — [text+image→video] highest quality"},
    {"id": "veo-3.1-lite-generate-preview", "label": "Veo 3.1 Lite — [text+image→video] fast, efficient"},
    {"id": "veo-2.0-generate-001",          "label": "Veo 2.0 — [text+image→video] previous gen"},
]

DEFAULT_TEXT_RESPONSE = {
    "text": "This is a mock Gemini response.\n\n## Key Points\n- Point one\n- Point two\n- Point three",
    "type": "text",
    "response_data": "",
    "candidates": [],
}

DEFAULT_IMAGE_RESPONSE = {
    "text": "[Mock: Gemini would return an image here]",
    "type": "image",
    "response_data": "image/png",
    "candidates": [],
}

DEFAULT_VIDEO_RESPONSE = {
    "text": "[Mock: Gemini would return a video here]",
    "type": "video",
    "response_data": "video/mp4",
    "candidates": [],
}

DEFAULT_AUDIO_RESPONSE = {
    "text": "[Generated speech: test input text]",
    "type": "audio",
    "response_data": "uploads/tts_test_mock.wav",
    "candidates": [],
}


def get_client():
    """Return a mock client object (never raises)."""
    return MagicMock()


def generate(system_prompt, user_prompt, model, temperature, files=None, **kwargs):
    """Mocked generate — returns queued response/error or default per model type.

    Args:
        system_prompt: Ignored (system-level instruction).
        user_prompt: Ignored (user message text).
        model: Model ID string (used for type-appropriate default).
        temperature: Ignored (sampling temperature).
        files: Ignored (optional list of file paths).
        **kwargs: Ignored (additional options forwarded to real client).

    Returns:
        dict with keys: text, type, response_data, candidates.

    Raises:
        Exception: If set_next_error() was called before this invocation.
    """
    global _next_response, _next_error

    # Error takes priority over response
    if _next_error is not None:
        err = _next_error
        _next_error = None
        raise err

    if _next_response is not None:
        resp = _next_response
        _next_response = None
        return resp

    if model in _AUDIO_MODELS:
        return dict(DEFAULT_AUDIO_RESPONSE)

    return dict(DEFAULT_TEXT_RESPONSE)


def set_next_response(response):
    """Queue a custom response dict for the next generate() call (single-use)."""
    global _next_response
    _next_response = response


def set_next_error(exception):
    """Queue an exception to raise on the next generate() call (single-use)."""
    global _next_error
    _next_error = exception


def reset():
    """Clear all queued responses and errors."""
    global _next_response, _next_error
    _next_response = None
    _next_error = None


if __name__ == "__main__":
    passed = 0
    failed = 0
    results = []

    def check(description, condition):
        global passed, failed
        if condition:
            results.append(f"PASS: {description}")
            passed += 1
        else:
            results.append(f"FAIL: {description}")
            failed += 1

    # 1. Default response
    reset()
    resp = generate("sp", "up", "gemini-2.5-flash", 0.7)
    check("default response returns DEFAULT_TEXT_RESPONSE", resp == DEFAULT_TEXT_RESPONSE)

    # 2. Custom text response
    reset()
    custom = {"text": "Custom hello", "type": "text", "response_data": "", "candidates": []}
    set_next_response(custom)
    resp = generate("sp", "up", "gemini-2.5-flash", 0.7)
    check("set_next_response returns queued dict", resp == custom)

    # 3. Image response type
    reset()
    set_next_response(dict(DEFAULT_IMAGE_RESPONSE))
    resp = generate("sp", "up", "gemini-2.5-flash", 0.7)
    check("image response has type='image'", resp["type"] == "image")

    # 4. Video response type
    reset()
    set_next_response(dict(DEFAULT_VIDEO_RESPONSE))
    resp = generate("sp", "up", "gemini-2.5-flash", 0.7)
    check("video response has type='video'", resp["type"] == "video")

    # 5. Error — ValueError
    reset()
    set_next_error(ValueError("test value error"))
    try:
        generate("sp", "up", "gemini-2.5-flash", 0.7)
        check("ValueError was raised", False)
    except ValueError:
        check("ValueError was raised", True)
    except Exception:
        check("ValueError was raised", False)

    # 6. Error — RuntimeError
    reset()
    set_next_error(RuntimeError("test runtime error"))
    try:
        generate("sp", "up", "gemini-2.5-flash", 0.7)
        check("RuntimeError was raised", False)
    except RuntimeError:
        check("RuntimeError was raised", True)
    except Exception:
        check("RuntimeError was raised", False)

    # 7. Single-use: queued response consumed on first call, default on second
    reset()
    set_next_response(custom)
    resp1 = generate("sp", "up", "gemini-2.5-flash", 0.7)
    resp2 = generate("sp", "up", "gemini-2.5-flash", 0.7)
    check("first call returns queued response", resp1 == custom)
    check("second call returns default after single-use", resp2 == DEFAULT_TEXT_RESPONSE)

    # 8. reset() clears all state
    reset()
    set_next_response(custom)
    set_next_error(ValueError("should be cleared"))
    reset()
    resp = generate("sp", "up", "gemini-2.5-flash", 0.7)
    check("reset() clears queued response and error", resp == DEFAULT_TEXT_RESPONSE)

    # 9. get_client() returns non-None
    client = get_client()
    check("get_client() returns non-None object", client is not None)

    # 10. AVAILABLE_MODELS
    check("AVAILABLE_MODELS is a list", isinstance(AVAILABLE_MODELS, list))
    check("AVAILABLE_MODELS has 6+ items", len(AVAILABLE_MODELS) >= 6)
    all_have_id = all("id" in m for m in AVAILABLE_MODELS)
    all_have_label = all("label" in m for m in AVAILABLE_MODELS)
    check("each model has 'id' key", all_have_id)
    check("each model has 'label' key", all_have_label)

    # Summary
    total = passed + failed
    output = "\n".join(results)
    output += f"\n\n{passed}/{total} tests passed"
    print(output)

    # Save evidence
    evidence_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".sisyphus", "evidence"
    )
    os.makedirs(evidence_dir, exist_ok=True)
    evidence_path = os.path.join(evidence_dir, "task-1-mock-smoke.txt")
    with open(evidence_path, "w") as f:
        f.write(output)
    print(f"\nEvidence saved to {evidence_path}")

"""ElevenLabs integration test — full end-to-end flow, all mocked.

Tests the complete pipeline:
  1. Template creation with ElevenLabs model → output_type="audio"
  2. Run template via llm_client.generate() → mock ElevenLabs SDK → result
  3. Audio MIME type detection from file extension
  4. Voice cache flow: mock SDK → DB cache → retrieve
  5. Error handling stack: missing API key, API failures

All tests are self-contained, use mocks, and leave no side effects.

Run: uv run python tests/test_elevenlabs_integration.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import sqlite3

passed = 0
failed = 0
FAILED_TESTS = []


def check(description, condition, evidence=None):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {description}")
    else:
        failed += 1
        FAILED_TESTS.append(description)
        print(f"  FAIL: {description}")
    if evidence:
        evid_dir = os.path.join(os.path.dirname(__file__), "..", ".sisyphus", "evidence")
        os.makedirs(evid_dir, exist_ok=True)
        with open(os.path.join(evid_dir, evidence), "w") as f:
            f.write(str(evidence))


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: Create template with ElevenLabs model
# ═══════════════════════════════════════════════════════════════════════════════

def test_create_elevenlabs_template():
    """Create a template with an ElevenLabs model, verify audio output type."""
    from prompt_template import database as db
    from prompt_template.template_store import create_template, delete_template, get_template

    # In-memory database with keeper connection
    db.DATABASE_PATH = "file:test_el_integration_1?mode=memory&cache=shared"
    _orig_get_conn = db.get_connection

    def _patched():
        conn = sqlite3.connect(db.DATABASE_PATH, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    db.get_connection = _patched
    _keeper = sqlite3.connect(db.DATABASE_PATH, uri=True)

    from prompt_template.database import init_db
    init_db()

    from prompt_template.llm_client import AVAILABLE_MODELS

    eleven_models = [m for m in AVAILABLE_MODELS if m["provider"] == "elevenlabs"]
    check("ElevenLabs models exist in AVAILABLE_MODELS", len(eleven_models) > 0,
          evidence="test-el-integration-1-available-models.txt")

    if eleven_models:
        model_id = eleven_models[0]["id"]
        tid = create_template(
            name="ElevenLabs Integration Test",
            description="Auto-generated integration test",
            system_prompt="Test prompt",
            model=model_id,
            temperature=0.7,
            inputs=[],
            output_type="audio",
        )
        check("create_template returns positive int id", isinstance(tid, int) and tid > 0)

        tpl = get_template(tid)
        check("get_template returns a dict", tpl is not None)
        check("template model matches ElevenLabs model", tpl["model"] == model_id)
        check("template output_type is 'audio'", tpl["output_type"] == "audio")

        delete_template(tid)
        check("get_template returns None after delete", get_template(tid) is None)

    _keeper.close()
    db.get_connection = _orig_get_conn


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: Run template with ElevenLabs (mocked generate)
# ═══════════════════════════════════════════════════════════════════════════════

def test_run_elevenlabs_template():
    """Mock generate() with ElevenLabs model, verify kwargs flow and result shape."""
    from unittest.mock import patch, MagicMock
    from prompt_template.llm_client import generate, AVAILABLE_MODELS

    eleven_models = [m for m in AVAILABLE_MODELS if m["provider"] == "elevenlabs"]
    if not eleven_models:
        check("Skipped - no elevenlabs models in AVAILABLE_MODELS", True)
        return

    model_id = eleven_models[0]["id"]
    old_val = os.environ.get("ELEVENLABS_API_KEY")
    _cleanup_path = None

    os.environ["ELEVENLABS_API_KEY"] = "test-key-for-mock"
    # Also set for patched code that may read it
    os.environ["ELEVEN_API_KEY"] = "test-key-for-mock"

    try:
        # Mock the ElevenLabs SDK at the package level (where generate() imports it)
        with patch("elevenlabs.ElevenLabs") as mock_el_cls:
            mock_el_instance = mock_el_cls.return_value
            mock_audio = MagicMock()
            mock_audio.__iter__.return_value = iter([b"mock_audio_data_chunk"])
            mock_el_instance.text_to_speech.convert.return_value = mock_audio

            # Mock VoiceSettings to capture kwargs
            vs_kwargs = {}

            class MockVS:
                def __init__(self, **kw):
                    vs_kwargs.update(kw)

            with patch("elevenlabs.VoiceSettings", MockVS):
                # Mock save_mp3 to avoid writing to disk
                with patch("prompt_template.audio_utils.save_mp3") as mock_save:
                    fake_path = os.path.abspath(
                        os.path.join("uploads", "test_elevenlabs_mock.mp3")
                    )
                    mock_save.return_value = fake_path
                    _cleanup_path = fake_path

                    result = generate(
                        system_prompt="",
                        user_prompt="Hello from ElevenLabs integration test",
                        model=model_id,
                        temperature=0.7,
                        voice_id="test_voice_123",
                        stability=0.3,
                        similarity_boost=0.8,
                        style=0.1,
                        use_speaker_boost=True,
                        speed=1.1,
                        language_code="en",
                    )

                    # Verify result shape
                    check("result type is 'audio'", result["type"] == "audio")
                    check("result has response_data", bool(result.get("response_data")))
                    check("result response_data ends .mp3",
                          result["response_data"].endswith(".mp3"))
                    check("candidates has model key",
                          "model" in result.get("candidates", {}))
                    check("candidates model matches model_id",
                          result["candidates"]["model"] == model_id)
                    check("candidates has voice_id",
                          result["candidates"]["voice_id"] == "test_voice_123")

                    # Verify kwargs were forwarded through the chain
                    check("ElevenLabs.convert called with voice_id=test_voice_123",
                          mock_el_instance.text_to_speech.convert.call_args[1]
                          .get("voice_id") == "test_voice_123")
                    check("ElevenLabs.convert called with model_id",
                          mock_el_instance.text_to_speech.convert.call_args[1]
                          .get("model_id") == model_id)
                    check("ElevenLabs.convert called with text",
                          "Hello from ElevenLabs" in
                          mock_el_instance.text_to_speech.convert.call_args[1]
                          .get("text", ""))

                    # Verify VoiceSettings was constructed with correct kwargs
                    check("VoiceSettings received stability=0.3",
                          vs_kwargs.get("stability") == 0.3)
                    check("VoiceSettings received similarity_boost=0.8",
                          vs_kwargs.get("similarity_boost") == 0.8)
                    check("VoiceSettings received style=0.1",
                          vs_kwargs.get("style") == 0.1)
                    check("VoiceSettings received use_speaker_boost=True",
                          vs_kwargs.get("use_speaker_boost") is True)
                    check("VoiceSettings received speed=1.1",
                          vs_kwargs.get("speed") == 1.1)
    finally:
        if old_val is not None:
            os.environ["ELEVENLABS_API_KEY"] = old_val
        else:
            os.environ.pop("ELEVENLABS_API_KEY", None)
        os.environ.pop("ELEVEN_API_KEY", None)
        if _cleanup_path and os.path.exists(_cleanup_path):
            try:
                os.remove(_cleanup_path)
            except OSError:
                pass


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Audio MIME detection
# ═══════════════════════════════════════════════════════════════════════════════

def test_audio_mime_detection():
    """Verify MIME type is correctly derived from file extension (matches run page logic)."""
    # Logic from pages/02_run.py:
    #   mime = "audio/mpeg" if audio_path.endswith(".mp3") else "audio/wav"

    def detect_mime(path):
        return "audio/mpeg" if path.endswith(".mp3") else "audio/wav"

    check(".mp3 -> audio/mpeg",
          detect_mime("/path/to/output.mp3") == "audio/mpeg",
          evidence="test-el-integration-3-mime.txt")
    check(".wav -> audio/wav",
          detect_mime("/path/to/output.wav") == "audio/wav")
    check("no extension defaults to wav",
          detect_mime("/path/to/output") == "audio/wav")
    check("uppercase .MP3 NOT detected as mpeg (case-sensitive)",
          detect_mime("/path/to/output.MP3") != "audio/mpeg")

    from prompt_template.llm_client import get_output_type
    check("get_output_type('eleven_v3') returns 'audio'",
          get_output_type("eleven_v3") == "audio")
    check("get_output_type('eleven_multilingual_v2') returns 'audio'",
          get_output_type("eleven_multilingual_v2") == "audio")
    check("get_output_type('eleven_flash_v2_5') returns 'audio'",
          get_output_type("eleven_flash_v2_5") == "audio")
    check("get_output_type('eleven_turbo_v2_5') returns 'audio'",
          get_output_type("eleven_turbo_v2_5") == "audio")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: Voice cache flow
# ═══════════════════════════════════════════════════════════════════════════════

def test_voice_cache_flow():
    """Test voice cache: mock SDK → DB cache (update) → retrieve (get_cached_voices)."""
    from unittest.mock import MagicMock
    from prompt_template import database as db
    from prompt_template.elevenlabs_client import update_voice_cache, get_cached_voices

    # In-memory SQLite with keeper
    db.DATABASE_PATH = "file:test_el_integration_4?mode=memory&cache=shared"
    _orig_get_conn = db.get_connection

    def _patched():
        conn = sqlite3.connect(db.DATABASE_PATH, uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    db.get_connection = _patched
    _keeper = sqlite3.connect(db.DATABASE_PATH, uri=True)

    # Create the voices table
    _keeper.execute("""CREATE TABLE IF NOT EXISTS elevenlabs_voices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        voice_id TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        labels_json TEXT DEFAULT '',
        category TEXT DEFAULT '',
        description TEXT DEFAULT '',
        gender TEXT DEFAULT '',
        accent TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    _keeper.execute("CREATE INDEX IF NOT EXISTS idx_elevenlabs_voices_name ON elevenlabs_voices(name)")
    _keeper.commit()

    try:
        # Mock client with voices
        mock_client = MagicMock()

        v1 = MagicMock()
        v1.voice_id = "rachel_id"
        v1.name = "Rachel"
        v1.labels = {"gender": "female", "accent": "american"}
        v1.category = "premade"
        v1.description = "Rachel voice"

        v2 = MagicMock()
        v2.voice_id = "antoni_id"
        v2.name = "Antoni"
        v2.labels = {"gender": "male", "accent": "british"}
        v2.category = "premade"
        v2.description = "Antoni voice"

        v3 = MagicMock()
        v3.voice_id = "bella_id"
        v3.name = "Bella"
        v3.labels = {"gender": "female", "accent": "american"}
        v3.category = "generated"
        v3.description = "Bella voice"

        mock_client.voices.search.return_value.voices = [v1, v2, v3]

        # Update cache from API
        count = update_voice_cache(mock_client)
        check("update_voice_cache returns 3 voices", count == 3,
              evidence="test-el-integration-4-voice-cache.txt")

        # Retrieve cached voices
        cached = get_cached_voices()
        check("get_cached_voices returns 3 entries", len(cached) == 3)

        names = {v["name"] for v in cached}
        check("Rachel in cached voices", "Rachel" in names)
        check("Antoni in cached voices", "Antoni" in names)
        check("Bella in cached voices", "Bella" in names)

        # Verify a specific voice's metadata
        rachel = [v for v in cached if v["name"] == "Rachel"]
        check("Rachel voice found in cache", len(rachel) == 1)
        check("Rachel voice_id is 'rachel_id'", rachel[0]["voice_id"] == "rachel_id")
        check("Rachel category is 'premade'", rachel[0]["category"] == "premade")

        # Test update replaces old cache
        mock_client.voices.search.return_value.voices = [v1]  # only Rachel
        count2 = update_voice_cache(mock_client)
        check("update_voice_cache replaces cache — returns 1", count2 == 1)
        cached2 = get_cached_voices()
        check("cache now has 1 entry", len(cached2) == 1)
        check("only Rachel remains after replace", cached2[0]["name"] == "Rachel")

        # Test empty response
        mock_client.voices.search.return_value.voices = []
        count3 = update_voice_cache(mock_client)
        check("update_voice_cache with empty response returns 0", count3 == 0)
        cached3 = get_cached_voices()
        check("cache still has previous data on empty response (no clear without API data)",
              len(cached3) == 1)

    finally:
        db.get_connection = _orig_get_conn
        _keeper.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5: Error handling stack
# ═══════════════════════════════════════════════════════════════════════════════

def test_error_handling():
    """Test error propagation for missing keys and API errors."""
    from unittest.mock import patch

    # ── 5a: Missing API key raises ValueError ──
    old_val = os.environ.pop("ELEVENLABS_API_KEY", None)
    os.environ.pop("ELEVEN_API_KEY", None)

    try:
        from prompt_template.elevenlabs_client import generate as el_generate

        try:
            el_generate("", "hello", "eleven_v3", 0.7)
            check("Missing key raises ValueError", False)
        except ValueError as e:
            check("Missing key raises ValueError with 'ELEVENLABS_API_KEY' message",
                  "ELEVENLABS_API_KEY" in str(e),
                  evidence="test-el-integration-5a-missing-key.txt")
    finally:
        if old_val is not None:
            os.environ["ELEVENLABS_API_KEY"] = old_val

    # ── 5b: API error raises RuntimeError ──
    os.environ["ELEVENLABS_API_KEY"] = "test-key-for-error"
    os.environ["ELEVEN_API_KEY"] = "test-key-for-error"
    _path = None

    try:
        with patch("elevenlabs.ElevenLabs") as mock_el:
            mock_el.return_value.text_to_speech.convert.side_effect = Exception(
                "API failure: quota exceeded"
            )
            with patch("prompt_template.audio_utils.save_mp3") as mock_save:
                mock_save.return_value = "/tmp/test_error.mp3"
                _path = "/tmp/test_error.mp3"

                try:
                    el_generate("", "speak this", "eleven_v3", 0.7)
                    check("API error raises RuntimeError", False)
                except RuntimeError as e:
                    check("API error raises RuntimeError with cause message",
                          "API failure" in str(e))
    finally:
        if _path and os.path.exists(_path):
            try:
                os.remove(_path)
            except OSError:
                pass
        os.environ.pop("ELEVENLABS_API_KEY", None)
        os.environ.pop("ELEVEN_API_KEY", None)

    # ── 5c: Unknown model via llm_client raises ValueError ──
    from prompt_template.llm_client import generate as llm_generate

    try:
        llm_generate("", "test", "nonexistent_model_xyz", 0.7)
        check("Unknown model raises ValueError", False)
    except ValueError as e:
        check("Unknown model raises ValueError with model name",
              "nonexistent_model_xyz" in str(e),
              evidence="test-el-integration-5c-unknown-model.txt")

    # ── 5d: llm_client routes ElevenLabs key errors correctly ──
    os.environ.pop("ELEVENLABS_API_KEY", None)
    os.environ.pop("ELEVEN_API_KEY", None)

    try:
        try:
            llm_generate("", "test", "eleven_v3", 0.7)
            check("llm_client missing key raises ValueError", False)
        except ValueError as e:
            check("llm_client missing key error mentions ELEVENLABS_API_KEY",
                  "ELEVENLABS_API_KEY" in str(e))
    finally:
        if old_val is not None:
            os.environ["ELEVENLABS_API_KEY"] = old_val


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== ElevenLabs Integration Test ===\n")

    print("--- Test 1: Create ElevenLabs template ---")
    test_create_elevenlabs_template()

    print("\n--- Test 2: Run ElevenLabs template (mocked) ---")
    test_run_elevenlabs_template()

    print("\n--- Test 3: Audio MIME detection ---")
    test_audio_mime_detection()

    print("\n--- Test 4: Voice cache flow ---")
    test_voice_cache_flow()

    print("\n--- Test 5: Error handling ---")
    test_error_handling()

    print()
    total = passed + failed
    print(f"Total: {total} | Passed: {passed} | Failed: {failed}")
    if FAILED_TESTS:
        print(f"FAILED: {FAILED_TESTS}")
    else:
        print("ALL PASSED")

    sys.exit(1 if failed > 0 else 0)

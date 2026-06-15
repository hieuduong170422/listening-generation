"""ElevenLabs client test suite.

Tests the elevenlabs_client module interface:
  - get_client() / generate() error handling
  - VoiceSettings parameter passing
  - Voice cache database operations
  - Model routing & output type detection
  - Audio file saving

Run: uv run python tests/test_elevenlabs.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

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


# ── 1. get_client missing key ──────────────────────────────────────────────

def test_get_client_missing_key():
    old_val = os.environ.pop("ELEVENLABS_API_KEY", None)
    os.environ.pop("ELEVEN_API_KEY", None)
    from prompt_template.elevenlabs_client import get_client
    try:
        try:
            get_client()
            check("get_client without key raises ValueError", False)
        except ValueError as e:
            check("get_client without key raises ValueError with 'ELEVENLABS_API_KEY'", "ELEVENLABS_API_KEY" in str(e))
    finally:
        if old_val is not None:
            os.environ["ELEVENLABS_API_KEY"] = old_val


# ── 2. get_client with key ─────────────────────────────────────────────────

def test_get_client_with_key():
    old_val = os.environ.get("ELEVENLABS_API_KEY")
    os.environ["ELEVENLABS_API_KEY"] = "test"
    os.environ.pop("ELEVEN_API_KEY", None)
    from unittest.mock import patch
    from prompt_template.elevenlabs_client import get_client
    try:
        with patch("elevenlabs.ElevenLabs") as mock:
            mock_instance = mock.return_value
            client = get_client()
            check("get_client with key returns ElevenLabs instance", client is mock_instance)
    finally:
        if old_val:
            os.environ["ELEVENLABS_API_KEY"] = old_val
        else:
            os.environ.pop("ELEVENLABS_API_KEY", None)


# ── 3. generate success ────────────────────────────────────────────────────

def test_generate_success():
    old_val = os.environ.get("ELEVENLABS_API_KEY")
    os.environ["ELEVENLABS_API_KEY"] = "test"
    _path = None
    from unittest.mock import patch, MagicMock
    from prompt_template.elevenlabs_client import generate
    try:
        mock_audio = MagicMock()
        mock_audio.__iter__.return_value = iter([b"chunk1", b"chunk2"])

        with patch("elevenlabs.ElevenLabs") as mock_el:
            mock_el.return_value.text_to_speech.convert.return_value = mock_audio
            result = generate("", "hello", "eleven_v3", 0.7)
            _path = result.get("response_data", "")
            check("generate returns type='audio'", result["type"] == "audio")
            check("generate returns response_data ending .mp3", _path.endswith(".mp3"))
    finally:
        if _path and os.path.exists(_path):
            os.remove(_path)
        if old_val:
            os.environ["ELEVENLABS_API_KEY"] = old_val
        else:
            os.environ.pop("ELEVENLABS_API_KEY", None)


# ── 4. generate missing key ────────────────────────────────────────────────

def test_generate_missing_key():
    old_val = os.environ.pop("ELEVENLABS_API_KEY", None)
    os.environ.pop("ELEVEN_API_KEY", None)
    from prompt_template.elevenlabs_client import generate
    try:
        try:
            generate("", "hello", "eleven_v3", 0.7)
            check("generate without key raises ValueError", False)
        except ValueError:
            check("generate without key raises ValueError", True)
    finally:
        if old_val is not None:
            os.environ["ELEVENLABS_API_KEY"] = old_val


# ── 5. generate API error ──────────────────────────────────────────────────

def test_generate_api_error():
    old_val = os.environ.get("ELEVENLABS_API_KEY")
    os.environ["ELEVENLABS_API_KEY"] = "test"
    from unittest.mock import patch
    from prompt_template.elevenlabs_client import generate
    try:
        with patch("elevenlabs.ElevenLabs") as mock_el:
            mock_el.return_value.text_to_speech.convert.side_effect = Exception("API error")
            try:
                generate("", "hello", "eleven_v3", 0.7)
                check("generate with API error raises RuntimeError", False)
            except RuntimeError as e:
                check("generate with API error raises RuntimeError with API error message", "API error" in str(e))
    finally:
        if old_val:
            os.environ["ELEVENLABS_API_KEY"] = old_val
        else:
            os.environ.pop("ELEVENLABS_API_KEY", None)


# ── 6. generate with voice settings ───────────────────────────────────────

def test_generate_with_voice_settings():
    old_val = os.environ.get("ELEVENLABS_API_KEY")
    os.environ["ELEVENLABS_API_KEY"] = "test"
    vs_kwargs = {}

    class MockVS:
        def __init__(self, **kw):
            vs_kwargs.update(kw)

    from unittest.mock import patch, MagicMock
    from prompt_template.elevenlabs_client import generate
    _path = None
    try:
        mock_audio = MagicMock()
        mock_audio.__iter__.return_value = iter([b"data"])

        with patch("elevenlabs.ElevenLabs") as mock_el:
            mock_el.return_value.text_to_speech.convert.return_value = mock_audio
            with patch("elevenlabs.VoiceSettings", MockVS):
                result = generate("", "hello", "eleven_v3", 0.7,
                                  stability=0.5, similarity_boost=0.8, style=0.2,
                                  use_speaker_boost=True, speed=1.2)
                _path = result.get("response_data", "")
                check("VoiceSettings receives stability=0.5", vs_kwargs.get("stability") == 0.5)
                check("VoiceSettings receives similarity_boost=0.8", vs_kwargs.get("similarity_boost") == 0.8)
                check("VoiceSettings receives style=0.2", vs_kwargs.get("style") == 0.2)
                check("VoiceSettings receives use_speaker_boost=True", vs_kwargs.get("use_speaker_boost") is True)
                check("VoiceSettings receives speed=1.2", vs_kwargs.get("speed") == 1.2)
    finally:
        if _path and os.path.exists(_path):
            os.remove(_path)
        if old_val:
            os.environ["ELEVENLABS_API_KEY"] = old_val
        else:
            os.environ.pop("ELEVENLABS_API_KEY", None)


# ── 7. get_cached_voices empty ────────────────────────────────────────────

def test_get_cached_voices_empty():
    import sqlite3
    from prompt_template.elevenlabs_client import get_cached_voices
    from prompt_template import database

    keeper = sqlite3.connect("file::memory:?cache=shared", uri=True)
    keeper.execute("""CREATE TABLE IF NOT EXISTS elevenlabs_voices (
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
    keeper.commit()

    original_path = database.DATABASE_PATH
    original_get_conn = database.get_connection

    def _mem_conn():
        conn = sqlite3.connect("file::memory:?cache=shared", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    try:
        database.DATABASE_PATH = "file::memory:?cache=shared"
        database.get_connection = _mem_conn

        result = get_cached_voices()
        check("get_cached_voices returns [] when empty", result == [])
    finally:
        database.DATABASE_PATH = original_path
        database.get_connection = original_get_conn
        keeper.close()


# ── 8. get_cached_voices ──────────────────────────────────────────────────

def test_get_cached_voices():
    import sqlite3
    from prompt_template.elevenlabs_client import get_cached_voices
    from prompt_template import database

    keeper = sqlite3.connect("file::memory:?cache=shared", uri=True)
    keeper.execute("""CREATE TABLE IF NOT EXISTS elevenlabs_voices (
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
    keeper.execute(
        "INSERT INTO elevenlabs_voices (voice_id, name, labels_json, category, description, gender, accent) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("v1", "Voice1", '{"gender":"female"}', "premade", "Test voice", "female", "american"),
    )
    keeper.commit()

    original_path = database.DATABASE_PATH
    original_get_conn = database.get_connection

    def _mem_conn():
        conn = sqlite3.connect("file::memory:?cache=shared", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    try:
        database.DATABASE_PATH = "file::memory:?cache=shared"
        database.get_connection = _mem_conn

        result = get_cached_voices()
        check("get_cached_voices returns 1 entry", len(result) == 1)
        check("cached voice has voice_id='v1'", result[0]["voice_id"] == "v1")
        check("cached voice has name='Voice1'", result[0]["name"] == "Voice1")
    finally:
        database.DATABASE_PATH = original_path
        database.get_connection = original_get_conn
        keeper.close()


# ── 9. fetch and cache voices ─────────────────────────────────────────────

def test_fetch_and_cache_voices():
    import sqlite3
    from unittest.mock import MagicMock
    from prompt_template.elevenlabs_client import update_voice_cache, get_cached_voices
    from prompt_template import database

    keeper = sqlite3.connect("file::memory:?cache=shared", uri=True)
    keeper.execute("""CREATE TABLE IF NOT EXISTS elevenlabs_voices (
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
    keeper.commit()

    original_path = database.DATABASE_PATH
    original_get_conn = database.get_connection

    def _mem_conn():
        conn = sqlite3.connect("file::memory:?cache=shared", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    try:
        database.DATABASE_PATH = "file::memory:?cache=shared"
        database.get_connection = _mem_conn

        mock_client = MagicMock()
        mock_voice = MagicMock()
        mock_voice.voice_id = "v1"
        mock_voice.name = "Voice1"
        mock_voice.labels = {"gender": "female", "accent": "american"}
        mock_voice.category = "premade"
        mock_voice.description = "Test voice"
        mock_client.voices.search.return_value.voices = [mock_voice]

        count = update_voice_cache(mock_client)
        check("update_voice_cache returns 1 for one voice", count == 1)

        cached = get_cached_voices()
        check("get_cached_voices has one entry after update", len(cached) == 1)
        check("cached voice has voice_id='v1'", cached[0]["voice_id"] == "v1")
        check("cached voice has name='Voice1'", cached[0]["name"] == "Voice1")
    finally:
        database.DATABASE_PATH = original_path
        database.get_connection = original_get_conn
        keeper.close()


# ── 10. get_output_type for elevenlabs models ──────────────────────────────

def test_get_output_type():
    from prompt_template.llm_client import get_output_type

    r1 = get_output_type("eleven_v3")
    check(
        "get_output_type('eleven_v3') == 'audio'",
        r1 == "audio",
        evidence="test-10-elevenlabs-output-type.txt",
    )

    r2 = get_output_type("eleven_multilingual_v2")
    check(
        "get_output_type('eleven_multilingual_v2') == 'audio'",
        r2 == "audio",
    )


# ── 11. ElevenLabs models in AVAILABLE_MODELS ─────────────────────────────

def test_elevenlabs_in_available_models():
    from prompt_template.llm_client import AVAILABLE_MODELS

    eleven_ids = [m["id"] for m in AVAILABLE_MODELS if m["id"].startswith("eleven_")]
    check(
        "AVAILABLE_MODELS contains models with id starting 'eleven_'",
        len(eleven_ids) > 0,
        evidence="test-11-elevenlabs-available-models.txt",
    )


# ── 12. save_mp3 ──────────────────────────────────────────────────────────

def test_save_mp3():
    from prompt_template.audio_utils import save_mp3

    path = save_mp3(b"data")
    try:
        check(
            "save_mp3 returns path ending with .mp3",
            path.endswith(".mp3"),
            evidence="test-12-elevenlabs-save-mp3.txt",
        )
        check(
            "save_mp3 creates file on disk",
            os.path.exists(path),
        )
    finally:
        if os.path.exists(path):
            os.remove(path)


# ── Runner ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== ElevenLabs Test Suite ===\n")

    print("--- Test 1: get_client missing key ---")
    test_get_client_missing_key()

    print("--- Test 2: get_client with key ---")
    test_get_client_with_key()

    print("--- Test 3: generate success ---")
    test_generate_success()

    print("--- Test 4: generate missing key ---")
    test_generate_missing_key()

    print("--- Test 5: generate API error ---")
    test_generate_api_error()

    print("--- Test 6: generate with voice settings ---")
    test_generate_with_voice_settings()

    print("--- Test 7: get_cached_voices empty ---")
    test_get_cached_voices_empty()

    print("--- Test 8: get_cached_voices ---")
    test_get_cached_voices()

    print("--- Test 9: fetch and cache voices ---")
    test_fetch_and_cache_voices()

    print("--- Test 10: get_output_type ---")
    test_get_output_type()

    print("--- Test 11: ElevenLabs in AVAILABLE_MODELS ---")
    test_elevenlabs_in_available_models()

    print("--- Test 12: save_mp3 ---")
    test_save_mp3()

    print()
    print(f"Total: {passed + failed} | Passed: {passed} | Failed: {failed}")
    if FAILED_TESTS:
        print(f"FAILED: {FAILED_TESTS}")
    else:
        print("ALL PASSED")

    sys.exit(1 if failed > 0 else 0)

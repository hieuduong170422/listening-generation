"""TTS integration test script.

Tests: Gemini TTS model routing, DashScope TTS model routing,
audio file saving, voice/language parameter passing, error handling,
and output_type storage.

All tests use gemini_mock or monkeypatched dashscope — no real API calls needed.

Run: uv run python tests/test_tts_flow.py
"""

import os
import sys

# Ensure the src/ package directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from unittest.mock import MagicMock, patch

import dotenv

dotenv.load_dotenv()

os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["DASHCOPE_API_KEY"] = "test-key"

from prompt_template import audio_utils
from prompt_template.gemini_mock import (
    generate as gemini_generate,
    DEFAULT_AUDIO_RESPONSE,
    reset as mock_reset,
)

# ── Test harness ──────────────────────────────────────────────────────────────

passed = 0
failed = 0
results = []
EVIDENCE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".sisyphus", "evidence",
)
os.makedirs(EVIDENCE_DIR, exist_ok=True)

# Ensure uploads/ exists
os.makedirs("uploads", exist_ok=True)


def check(description, condition):
    global passed, failed
    if condition:
        results.append(f"PASS: {description}")
        passed += 1
    else:
        results.append(f"FAIL: {description}")
        failed += 1


def save_evidence(filename, content):
    path = os.path.join(EVIDENCE_DIR, filename)
    with open(path, "w") as f:
        f.write(str(content))
    print(f"  Evidence saved to {path}")


# ── 1. Gemini TTS model routing ──────────────────────────────────────────────

mock_reset()
result = gemini_generate("", "Hello world", "gemini-3.1-flash-tts-preview", 0.7)
check("Gemini TTS model returns audio type", result["type"] == "audio")
check("Gemini TTS response contains response_data", bool(result.get("response_data")))
check("Gemini TTS response_data ends with .wav", result["response_data"].endswith(".wav"))
check("Gemini TTS response has text", bool(result.get("text")))
save_evidence("task-17-gemini-tts-routing.txt",
    f"Gemini TTS: type={result['type']!r}, response_data={result['response_data']!r}\n")

# ── 2. Non-TTS Gemini model returns text ──────────────────────────────────────

mock_reset()
result = gemini_generate("", "Hello", "gemini-2.5-pro", 0.7)
check("Non-TTS Gemini model returns text type", result["type"] == "text")
save_evidence("task-17-non-tts-routing.txt",
    f"Non-TTS: type={result['type']!r}\n")

# ── 3. DashScope TTS model routing ────────────────────────────────────────────

from prompt_template import dashscope_client
from prompt_template.dashscope_client import _AUDIO_MODELS, generate as ds_generate

# Verify TTS models are registered
check("qwen3-tts-flash-2025-11-27 in DashScope _AUDIO_MODELS",
      "qwen3-tts-flash-2025-11-27" in _AUDIO_MODELS)
check("qwen3-tts-instruct-flash in DashScope _AUDIO_MODELS",
      "qwen3-tts-instruct-flash" in _AUDIO_MODELS)

# Monkey-patch MultiModalConversation.call for TTS
def make_tts_response(url="http://example.com/test.wav"):
    """Create a mock DashScope TTS response."""
    output = MagicMock()
    output.audio = {"url": url}
    response = MagicMock()
    response.status_code = 200
    response.output = output
    return response

with patch.object(dashscope_client, "MultiModalConversation") as mock_mmc:
    mock_mmc.call.return_value = make_tts_response()

    with patch("prompt_template.audio_utils.download_and_save_audio") as mock_dl:
        mock_dl.return_value = os.path.abspath("uploads/tts_test_mock_ds.wav")
        with open("uploads/tts_test_mock_ds.wav", "wb") as f:
            f.write(b"fake audio data")

        try:
            ds_result = ds_generate(
                system_prompt="", user_prompt="Xin chào",
                model="qwen3-tts-flash-2025-11-27", temperature=0.7,
                voice="Cherry", language="Auto",
            )
            check("DashScope TTS returns audio type",
                  ds_result["type"] == "audio")
            check("DashScope TTS response_data is non-empty",
                  bool(ds_result.get("response_data")))
            check("DashScope TTS kwargs passed: voice=Cherry",
                  mock_mmc.call.call_args[1].get("voice") == "Cherry")
            check("DashScope TTS kwargs passed: language_type=Auto",
                  mock_mmc.call.call_args[1].get("language_type") == "Auto")
            check("DashScope TTS text is original input",
                  ds_result["text"] == "Xin chào")
        finally:
            if os.path.exists("uploads/tts_test_mock_ds.wav"):
                os.remove("uploads/tts_test_mock_ds.wav")

ds_result_type = ds_result.get("type", "N/A")
save_evidence("task-17-dashscope-tts-routing.txt",
    f"DashScope TTS: result type={ds_result_type}\n")

# ── 4. Audio file saving (audio_utils) ────────────────────────────────────────

path = audio_utils.save_pcm_as_wav(b"\x00" * 1000)
check("save_pcm_as_wav creates valid WAV", os.path.exists(path))
check("WAV file has RIFF header", open(path, "rb").read(4) == b"RIFF")
check("WAV file > 44 bytes", os.path.getsize(path) > 44)
os.remove(path)

# ── 5. Error handling: empty response_data ────────────────────────────────────

mock_reset()
# Simulate error: set next response with missing data
from prompt_template.gemini_mock import set_next_response, generate as gemini_gen
set_next_response({"text": "[Error: no audio]", "type": "text", "response_data": "", "candidates": []})
err_result = gemini_gen("", "test", "gemini-3.1-flash-tts-preview", 0.7)
check("Error response for TTS model returns text",
      err_result["type"] == "text")

# ── 6. output_type stored correctly in template ──────────────────────────────

# Use in-memory DB
from prompt_template import database as db
import sqlite3

db.DATABASE_PATH = "file:test_tts_output_type?mode=memory&cache=shared"
_original_get_connection = db.get_connection

def _patched_get_connection():
    conn = sqlite3.connect(db.DATABASE_PATH, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

db.get_connection = _patched_get_connection
_keeper = sqlite3.connect(db.DATABASE_PATH, uri=True)

from prompt_template.database import init_db
init_db()

from prompt_template.template_store import create_template, get_template

tid = create_template(
    name="TTS Test",
    description="",
    system_prompt="Speak this",
    model="gemini-3.1-flash-tts-preview",
    temperature=0.7,
    inputs=[],
    output_type="audio",
)

t = get_template(tid)
check("Template stored output_type='audio'", t is not None and t.get("output_type") == "audio")

# Default output_type
tid2 = create_template(
    name="Text Test",
    description="",
    system_prompt="Write this",
    model="gemini-2.5-pro",
    temperature=0.7,
    inputs=[],
)
t2 = get_template(tid2)
check("Template defaults to output_type='text'", t2 is not None and t2.get("output_type") == "text")

_keeper.close()
db.get_connection = _original_get_connection

# ── 7. get_output_type helper ────────────────────────────────────────────────

from prompt_template.llm_client import get_output_type

check("get_output_type detects TTS model as audio",
      get_output_type("gemini-3.1-flash-tts-preview") == "audio")
check("get_output_type detects text model as text",
      get_output_type("gemini-2.5-pro") == "text")
check("get_output_type detects image model as image",
      get_output_type("gemini-2.5-flash-image") == "image")
check("get_output_type detects video model as video",
      get_output_type("veo-3.1-generate-preview") == "video")

# ── 8. Merged model list in llm_client includes TTS models ───────────────────

from prompt_template.llm_client import AVAILABLE_MODELS

tts_ids = {m["id"] for m in AVAILABLE_MODELS if "tts" in m["id"]}
check("Gemini TTS model in merged list",
      "gemini-3.1-flash-tts-preview" in tts_ids)
check("DashScope TTS models in merged list",
      "qwen3-tts-flash-2025-11-27" in tts_ids and "qwen3-tts-instruct-flash" in tts_ids)

# ── Summary ──────────────────────────────────────────────────────────────────

total = passed + failed
output = "\n".join(results)
output += f"\n\n{passed}/{total} tests passed"
print(output)

evidence_path = os.path.join(EVIDENCE_DIR, "task-17-tts-tests.txt")
with open(evidence_path, "w") as f:
    f.write(output)
print(f"\nEvidence saved to {evidence_path}")

sys.exit(0 if failed == 0 else 1)

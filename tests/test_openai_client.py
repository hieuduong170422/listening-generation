"""Standalone test script for the OpenAI API client wrapper.

Tests openai_client.py directly with monkeypatched API calls.
No real API key or network access needed.

Run: uv run python tests/test_openai_client.py
"""

import os
import sys
import tempfile
import base64
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))


# ── Test harness ──────────────────────────────────────────────────────────────

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


def make_mock_completion(content="Hello!", finish_reason="stop", refusal=None, tool_calls=None):
    choice = MagicMock()
    choice.message = MagicMock()
    choice.message.content = content
    choice.message.refusal = refusal
    choice.message.tool_calls = tool_calls
    choice.finish_reason = finish_reason
    completion = MagicMock()
    completion.choices = [choice]
    return completion


def make_mock_image_response(b64_json=None, url=None):
    data = MagicMock()
    data.b64_json = b64_json
    data.url = url
    resp = MagicMock()
    resp.data = [data] if (b64_json or url) else []
    return resp


def make_mock_tts_response(content=b"\x00\x01\x02"):
    resp = MagicMock()
    resp.content = content
    return resp


def make_mock_video(status="completed", video_id="video_123", error=None):
    video = MagicMock()
    video.status = status
    video.id = video_id
    if error:
        video.error = error
    return video


# Bootstrap the logger early so patches for video/TTS tests
# don't interfere with log handler file operations.
from prompt_template.logger import get_api_logger
get_api_logger()


# ── Import module under test ────────────────────────────────────────────────

from prompt_template.openai_client import (
    get_client,
    generate,
    AVAILABLE_MODELS,
    _TEXT_MODELS,
    _IMAGE_MODELS,
    _AUDIO_MODELS,
    _VIDEO_MODELS,
    _encode_image,
    _build_user_content,
    _convert_size,
    _clamp_duration,
)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 1 — Module-level constants & get_client
# ═══════════════════════════════════════════════════════════════════════════════

check("Test 1", "AVAILABLE_MODELS has 22 entries",
      len(AVAILABLE_MODELS) == 22, detail=f" | count={len(AVAILABLE_MODELS)}")

model_ids = {m["id"] for m in AVAILABLE_MODELS}
check("Test 1b", "AVAILABLE_MODELS includes gpt-4o",
      "gpt-4o" in model_ids)
check("Test 1c", "AVAILABLE_MODELS includes sora-2-pro",
      "sora-2-pro" in model_ids)
check("Test 1d", "_TEXT_MODELS has 10 entries",
      len(_TEXT_MODELS) == 10)
check("Test 1e", "_IMAGE_MODELS has 4 entries",
      len(_IMAGE_MODELS) == 4)
check("Test 1f", "_AUDIO_MODELS has 4 entries",
      len(_AUDIO_MODELS) == 4)
check("Test 1g", "_VIDEO_MODELS has 4 entries",
      len(_VIDEO_MODELS) == 4)


# ── get_client: no API key ────────────────────────────────────────────────────

with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
    try:
        get_client()
        check("Test 2", "get_client without key: should raise ValueError", False)
    except ValueError as e:
        check("Test 2", "get_client without key: ValueError raised with OPENAI_API_KEY",
              "OPENAI_API_KEY" in str(e), detail=f" | {e}")
    except Exception as e:
        check("Test 2", "get_client without key: unexpected exception",
              False, detail=f" | {type(e).__name__}: {e}")


# ── get_client: success with key ──────────────────────────────────────────────

@patch("prompt_template.openai_client.OpenAI")
def test_get_client_success(mock_openai_cls):
    mock_instance = MagicMock()
    mock_openai_cls.return_value = mock_instance
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}):
        client = get_client()
        check("Test 3", "get_client success: returns OpenAI instance",
              client is mock_instance)
        check("Test 3b", "get_client success: called with api_key",
              mock_openai_cls.call_args[1].get("api_key") == "sk-test-key",
              detail=f" | kwargs={mock_openai_cls.call_args[1]}")

test_get_client_success()


# ── get_client: with OPENAI_BASE_URL ──────────────────────────────────────────

@patch("prompt_template.openai_client.OpenAI")
def test_get_client_base_url(mock_openai_cls):
    mock_instance = MagicMock()
    mock_openai_cls.return_value = mock_instance
    with patch.dict(os.environ, {"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "https://custom.api.com"}):
        get_client()
        check("Test 3c", "get_client with OPENAI_BASE_URL: base_url passed to OpenAI",
              mock_openai_cls.call_args[1].get("base_url") == "https://custom.api.com",
              detail=f" | kwargs={mock_openai_cls.call_args[1]}")

test_get_client_base_url()


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 2 — Text generation
# ═══════════════════════════════════════════════════════════════════════════════

@patch("prompt_template.openai_client.get_client")
def test_text_success(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = make_mock_completion(
        content="Hello world!", finish_reason="stop"
    )
    result = generate("Be helpful", "Say hi", "gpt-4o", 0.7)
    check("Test 4", "Text success: type is 'text'",
          result["type"] == "text")
    check("Test 4b", "Text success: text matches content",
          result["text"] == "Hello world!",
          detail=f" | text={result['text']!r}")
    check("Test 4c", "Text success: response_data empty",
          result["response_data"] == "")

test_text_success()


@patch("prompt_template.openai_client.get_client")
def test_text_developer_role(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = make_mock_completion("OK")
    generate("System instruction", "User query", "gpt-4o-mini", 0.5)
    args, kwargs = mock_client.chat.completions.create.call_args
    messages = kwargs["messages"]
    check("Test 5", "Developer role: first message has role 'developer'",
          messages[0]["role"] == "developer",
          detail=f" | role={messages[0]['role']!r}")
    check("Test 5b", "Developer role: second message has role 'user'",
          messages[1]["role"] == "user",
          detail=f" | role={messages[1]['role']!r}")
    check("Test 5c", "Developer role: model passed correctly",
          kwargs["model"] == "gpt-4o-mini",
          detail=f" | model={kwargs['model']!r}")

test_text_developer_role()


@patch("prompt_template.openai_client.get_client")
def test_text_empty_choices(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    completion = make_mock_completion("irrelevant")
    completion.choices = []
    mock_client.chat.completions.create.return_value = completion
    result = generate("s", "u", "gpt-4o", 0.5)
    check("Test 6", "Empty choices: text mentions 'no choices'",
          "no choices" in result["text"].lower(),
          detail=f" | text={result['text']!r}")

test_text_empty_choices()


@patch("prompt_template.openai_client.get_client")
def test_text_refusal(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = make_mock_completion(
        content=None, finish_reason="stop", refusal="I cannot answer that"
    )
    result = generate("s", "u", "gpt-4o", 0.5)
    check("Test 7", "Refusal: text contains 'Content refused'",
          "Content refused" in result["text"],
          detail=f" | text={result['text']!r}")

test_text_refusal()


@patch("prompt_template.openai_client.get_client")
def test_text_content_filter(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = make_mock_completion(
        content="Some text", finish_reason="content_filter"
    )
    result = generate("s", "u", "gpt-4o", 0.5)
    check("Test 8", "Content filter: text mentions 'filtered'",
          "filtered" in result["text"].lower(),
          detail=f" | text={result['text']!r}")

test_text_content_filter()


@patch("prompt_template.openai_client.get_client")
def test_text_length_truncation(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = make_mock_completion(
        content="Partial text", finish_reason="length"
    )
    result = generate("s", "u", "gpt-4o", 0.5)
    check("Test 9", "Length truncation: text includes 'truncated due to token limit'",
          "truncated due to token limit" in result["text"],
          detail=f" | text={result['text']!r}")

test_text_length_truncation()


@patch("prompt_template.openai_client.get_client")
def test_text_tool_calls(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = make_mock_completion(
        content=None, finish_reason="stop", tool_calls=[MagicMock(), MagicMock()]
    )
    result = generate("s", "u", "gpt-4o", 0.5)
    check("Test 10", "Tool calls: text mentions 'tool call(s)'",
          "tool call(s)" in result["text"],
          detail=f" | text={result['text']!r}")

test_text_tool_calls()


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 3 — Image generation
# ═══════════════════════════════════════════════════════════════════════════════

@patch("prompt_template.openai_client.get_client")
def test_image_b64_json(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.images.generate.return_value = make_mock_image_response(
        b64_json="iVBORw0KGgoAAAANSUhEUg=="
    )
    result = generate("Enhance", "A cat", "gpt-image-2", 0.5)
    check("Test 11", "Image b64_json: type is 'image'",
          result["type"] == "image", detail=f" | type={result['type']!r}")
    check("Test 11b", "Image b64_json: response_data is data URI",
          result["response_data"].startswith("data:image/png;base64,"),
          detail=f" | prefix={result['response_data'][:35]!r}")
    check("Test 11c", "Image b64_json: text mentions 'Generated image'",
          "Generated image" in result["text"],
          detail=f" | text={result['text']!r}")

test_image_b64_json()


@patch("prompt_template.openai_client.get_client")
def test_image_kwargs(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.images.generate.return_value = make_mock_image_response(b64_json="x")
    generate("", "Draw", "gpt-image-2", 0.5, size="1024*768")
    args, kwargs = mock_client.images.generate.call_args
    check("Test 12", "Image kwargs: n=1",
          kwargs.get("n") == 1)
    check("Test 12b", "Image kwargs: response_format=b64_json",
          kwargs.get("response_format") == "b64_json")
    check("Test 12c", "Image kwargs: size converted to '1024x768'",
          kwargs.get("size") == "1024x768",
          detail=f" | size={kwargs.get('size')!r}")

test_image_kwargs()


@patch("prompt_template.openai_client.get_client")
def test_image_empty_data(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.images.generate.return_value = make_mock_image_response()
    result = generate("", "Draw", "dall-e-3", 0.5)
    check("Test 13", "Image empty data: type is 'image'",
          result["type"] == "image")
    check("Test 13b", "Image empty data: response_data is empty",
          result["response_data"] == "")
    check("Test 13c", "Image empty data: text mentions 'no data'",
          "no data" in result["text"].lower(),
          detail=f" | text={result['text']!r}")

test_image_empty_data()


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 4 — TTS audio generation
# ═══════════════════════════════════════════════════════════════════════════════

@patch("prompt_template.audio_utils.save_base64_audio")
@patch("prompt_template.openai_client.get_client")
def test_tts_success(mock_get_client, mock_save):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.audio.speech.create.return_value = make_mock_tts_response(b"\x00\x01\x02")
    mock_save.return_value = "uploads/tts_test.wav"
    result = generate("", "Hello world", "gpt-4o-mini-tts", 0.5, voice="nova")
    check("Test 14", "TTS success: type is 'audio'",
          result["type"] == "audio", detail=f" | type={result['type']!r}")
    check("Test 14b", "TTS success: response_data is saved file path",
          result["response_data"] == "uploads/tts_test.wav",
          detail=f" | path={result['response_data']!r}")
    check("Test 14c", "TTS success: text equals user_prompt",
          result["text"] == "Hello world",
          detail=f" | text={result['text']!r}")
    check("Test 14d", "TTS success: candidates has model and voice",
          result["candidates"].get("model") == "gpt-4o-mini-tts",
          detail=f" | candidates={result['candidates']!r}")

test_tts_success()


@patch("prompt_template.audio_utils.save_base64_audio")
@patch("prompt_template.openai_client.get_client")
def test_tts_kwargs(mock_get_client, mock_save):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.audio.speech.create.return_value = make_mock_tts_response(b"\x00")
    mock_save.return_value = ""
    generate("", "Speak", "tts-1-hd", 0.5, voice="echo", speed=1.5)
    args, kwargs = mock_client.audio.speech.create.call_args
    check("Test 15", "TTS kwargs: response_format is 'wav'",
          kwargs.get("response_format") == "wav")
    check("Test 15b", "TTS kwargs: voice forwarded",
          kwargs.get("voice") == "echo", detail=f" | voice={kwargs.get('voice')!r}")
    check("Test 15c", "TTS kwargs: speed forwarded",
          kwargs.get("speed") == 1.5, detail=f" | speed={kwargs.get('speed')!r}")

test_tts_kwargs()


@patch("prompt_template.audio_utils.save_base64_audio")
@patch("prompt_template.openai_client.get_client")
def test_tts_no_instructions_on_tts1(mock_get_client, mock_save):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.audio.speech.create.return_value = make_mock_tts_response(b"\x00")
    mock_save.return_value = ""
    generate("", "Hi", "tts-1", 0.5, instructions="Speak slowly", voice="alloy")
    args, kwargs = mock_client.audio.speech.create.call_args
    check("Test 16", "tts-1: instructions NOT in call kwargs",
          "instructions" not in kwargs,
          detail=f" | kwargs_keys={list(kwargs.keys())}")

test_tts_no_instructions_on_tts1()


@patch("prompt_template.audio_utils.save_base64_audio")
@patch("prompt_template.openai_client.get_client")
def test_tts_with_instructions(mock_get_client, mock_save):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.audio.speech.create.return_value = make_mock_tts_response(b"\x00")
    mock_save.return_value = ""
    generate("", "Hi", "gpt-4o-mini-tts", 0.5, instructions="Speak slowly", voice="alloy")
    args, kwargs = mock_client.audio.speech.create.call_args
    check("Test 16b", "gpt-4o-mini-tts: instructions IS in kwargs",
          kwargs.get("instructions") == "Speak slowly",
          detail=f" | instructions={kwargs.get('instructions')!r}")

test_tts_with_instructions()


@patch("prompt_template.openai_client.get_client")
def test_tts_empty_response(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.audio.speech.create.return_value = make_mock_tts_response(content=b"")
    result = generate("", "Hi", "tts-1", 0.5, voice="alloy")
    check("Test 17", "TTS empty response: type is 'text' (fallback)",
          result["type"] == "text", detail=f" | type={result['type']!r}")
    check("Test 17b", "TTS empty response: text mentions 'empty audio'",
          "empty audio" in result["text"].lower(),
          detail=f" | text={result['text']!r}")

test_tts_empty_response()


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 5 — Video generation (Sora)
# ═══════════════════════════════════════════════════════════════════════════════

@patch("builtins.open", new_callable=mock_open)
@patch("prompt_template.openai_client.os.makedirs")
@patch("prompt_template.openai_client.get_client")
def test_video_success(mock_get_client, mock_makedirs, mock_file):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_video = make_mock_video(status="completed", video_id="vid_001")
    mock_client.videos.create_and_poll.return_value = mock_video
    mock_client.videos.download_content.return_value = b"\x00\x01\x02MP4"
    result = generate("Cinematic", "A dog running", "sora-2", 0.5)
    check("Test 18", "Video success: type is 'video'",
          result["type"] == "video", detail=f" | type={result['type']!r}")

test_video_success()


@patch("builtins.open", new_callable=mock_open)
@patch("prompt_template.openai_client.os.makedirs")
@patch("prompt_template.openai_client.get_client")
def test_video_download_called(mock_get_client, mock_makedirs, mock_file):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_video = make_mock_video(status="completed", video_id="vid_002")
    mock_client.videos.create_and_poll.return_value = mock_video
    mock_client.videos.download_content.return_value = b"\x00" * 100
    generate("", "Run", "sora-2", 0.5)
    call_args = mock_client.videos.download_content.call_args
    check("Test 18b", "Video download: download_content called with video.id",
          call_args is not None and call_args[0][0] == "vid_002",
          detail=f" | call_args={call_args}")

test_video_download_called()


@patch("builtins.open", new_callable=mock_open)
@patch("prompt_template.openai_client.os.makedirs")
@patch("prompt_template.openai_client.get_client")
def test_video_duration_clamping(mock_get_client, mock_makedirs, mock_file):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_video = make_mock_video(status="completed", video_id="v3")
    mock_client.videos.create_and_poll.return_value = mock_video
    mock_client.videos.download_content.return_value = b"\x00" * 100
    generate("", "Fly", "sora-2", 0.5, duration=3)
    args, kwargs = mock_client.videos.create_and_poll.call_args
    check("Test 18c", "Video duration: duration=3 clamped to seconds='4'",
          kwargs.get("seconds") == "4",
          detail=f" | seconds={kwargs.get('seconds')!r}")

test_video_duration_clamping()


@patch("builtins.open", new_callable=mock_open)
@patch("prompt_template.openai_client.os.makedirs")
@patch("prompt_template.openai_client.get_client")
def test_video_size_conversion(mock_get_client, mock_makedirs, mock_file):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_video = make_mock_video(status="completed", video_id="v4")
    mock_client.videos.create_and_poll.return_value = mock_video
    mock_client.videos.download_content.return_value = b"\x00" * 100
    generate("", "Fly", "sora-2-pro", 0.5, size="1280*720")
    args, kwargs = mock_client.videos.create_and_poll.call_args
    check("Test 18d", "Video size: size='1280*720' converted to '1280x720'",
          kwargs.get("size") == "1280x720",
          detail=f" | size={kwargs.get('size')!r}")

test_video_size_conversion()


@patch("prompt_template.openai_client.get_client")
def test_video_failure_status(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_error = MagicMock(message="Content policy violation")
    mock_video = make_mock_video(status="failed", video_id="v5", error=mock_error)
    mock_client.videos.create_and_poll.return_value = mock_video
    result = generate("", "Bad", "sora-2", 0.5)
    check("Test 19", "Video failure: type is 'text' (fallback)",
          result["type"] == "text", detail=f" | type={result['type']!r}")
    check("Test 19b", "Video failure: text mentions 'failed' and 'policy'",
          "failed" in result["text"].lower() and "policy" in result["text"].lower(),
          detail=f" | text={result['text']!r}")

test_video_failure_status()


@patch("prompt_template.openai_client.get_client")
def test_video_download_failure(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_video = make_mock_video(status="completed", video_id="v6")
    mock_client.videos.create_and_poll.return_value = mock_video
    mock_client.videos.download_content.side_effect = Exception("Connection error")
    result = generate("", "OK", "sora-2", 0.5)
    check("Test 20", "Video download failure: type is 'text' (fallback)",
          result["type"] == "text", detail=f" | type={result['type']!r}")
    check("Test 20b", "Video download failure: text mentions 'download failed'",
          "download failed" in result["text"].lower(),
          detail=f" | text={result['text']!r}")

test_video_download_failure()


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 6 — Helper functions
# ═══════════════════════════════════════════════════════════════════════════════

PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
    f.write(PNG_HEADER)
    _img_path = f.name
try:
    data_uri = _encode_image(_img_path)
    check("Test 21", "_encode_image: returns data:image/png;base64,...",
          data_uri.startswith("data:image/png;base64,"),
          detail=f" | prefix={data_uri[:35]!r}")
finally:
    os.unlink(_img_path)


check("Test 22", "_convert_size('1280*720') returns '1280x720'",
      _convert_size("1280*720") == "1280x720")
check("Test 22b", "_convert_size('1024x768') passes through unchanged",
      _convert_size("1024x768") == "1024x768")
check("Test 22c", "_convert_size(None) returns None",
      _convert_size(None) is None)


check("Test 23", "_clamp_duration(1) returns '4'",
      _clamp_duration(1) == "4")
check("Test 23b", "_clamp_duration(3) returns '4'",
      _clamp_duration(3) == "4")
check("Test 23c", "_clamp_duration(6) returns '4'",
      _clamp_duration(6) == "4")
check("Test 23d", "_clamp_duration(10) returns '8'",
      _clamp_duration(10) == "8")
check("Test 23e", "_clamp_duration(20) returns '20'",
      _clamp_duration(20) == "20")
check("Test 23f", "_clamp_duration(30) returns '20'",
      _clamp_duration(30) == "20")


with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
    f.write(PNG_HEADER)
    _png_path = f.name
try:
    parts = _build_user_content("Describe this image", files=[_png_path])
    check("Test 24", "_build_user_content: returns 2 parts (text + image)",
          len(parts) == 2, detail=f" | len={len(parts)}")
    check("Test 24b", "_build_user_content: first part is text",
          parts[0]["type"] == "text" and parts[0]["text"] == "Describe this image",
          detail=f" | type={parts[0].get('type')!r}")
    check("Test 24c", "_build_user_content: second part is image_url",
          parts[1]["type"] == "image_url",
          detail=f" | type={parts[1].get('type')!r}")
finally:
    os.unlink(_png_path)


@patch("prompt_template.openai_client.get_client")
def test_text_with_image_file(mock_get_client):
    mock_client = MagicMock()
    mock_get_client.return_value = mock_client
    mock_client.chat.completions.create.return_value = make_mock_completion("Seen it")
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(PNG_HEADER)
        _img_path = f.name
    try:
        result = generate("Look", "What is this?", "gpt-4o", 0.5, files=[_img_path])
        check("Test 25", "Text with image: type is 'text'",
              result["type"] == "text")
        args, kwargs = mock_client.chat.completions.create.call_args
        user_content = kwargs["messages"][1]["content"]
        has_image_url = any(
            p.get("type") == "image_url" for p in user_content
        )
        check("Test 25b", "Text with image: image_url in user message content",
              has_image_url,
              detail=f" | content_types={[p.get('type') for p in user_content]}")
    finally:
        os.unlink(_img_path)

test_text_with_image_file()


# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════

total = passed + failed
result_lines = list(results)
result_lines.insert(0, "=== OpenAI Client Tests ===")
result_lines.append("")
result_lines.append("---")
result_lines.append(f"Total: {total} | Passed: {passed} | Failed: {failed}")

output = "\n".join(result_lines)
print(output)

evidence_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".sisyphus", "evidence"
)
os.makedirs(evidence_dir, exist_ok=True)
evidence_path = os.path.join(evidence_dir, "task-4-test-results.txt")
with open(evidence_path, "w") as f:
    f.write(output)
print(f"\nEvidence saved to {evidence_path}")

sys.exit(0 if failed == 0 else 1)

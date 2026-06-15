"""Standalone test script for the DashScope native SDK client.

Tests dashscope_client.py directly with monkeypatched API calls.
No real API key or network access needed.

All models use MultiModalConversation.call() — response content is
always a list of dicts: [{"text": "..."}] or [{"image": "..."}].

Run: uv run python tests/test_dashscope_client.py
"""

import os
import sys
from unittest.mock import MagicMock, patch

# Ensure the src/ package directory is on the path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))


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


def make_mm_response(content_list, finish_reason="stop", status_code=200):
    """Create a mock MultiModalConversation.call() response.

    Matches MultiModalConversationResponse DictMixin structure:
        .status_code, .output.choices[].message.content (list of dicts),
        .output.choices[].finish_reason
    """
    msg = MagicMock(spec=["content"])
    msg.content = content_list

    choice = MagicMock(spec=["message", "finish_reason"])
    choice.message = msg
    choice.finish_reason = finish_reason

    output = MagicMock(spec=["choices"])
    output.choices = [choice]

    resp = MagicMock(spec=["status_code", "output", "message", "code"])
    resp.status_code = status_code
    resp.output = output
    resp.message = ""
    resp.code = ""
    return resp


def make_gen_response(text, finish_reason="stop", status_code=200):
    """Create a mock Generation.call() response (string content).

    Matches GenerationResponse DictMixin structure:
        .status_code, .output.choices[].message.content (str),
        .output.choices[].finish_reason
    """
    msg = MagicMock(spec=["content"])
    msg.content = text

    choice = MagicMock(spec=["message", "finish_reason"])
    choice.message = msg
    choice.finish_reason = finish_reason

    output = MagicMock(spec=["choices"])
    output.choices = [choice]

    resp = MagicMock(spec=["status_code", "output", "message", "code"])
    resp.status_code = status_code
    resp.output = output
    resp.message = ""
    resp.code = ""
    return resp


def make_video_response(video_url, task_status="SUCCEEDED", status_code=200, message=""):
    """Create a mock VideoSynthesisResponse.

    Matches VideoSynthesisResponse DictMixin structure:
        .status_code, .output (dict-like with .get()),
        .output.task_status, .output.video_url, .output.message
    """
    output = MagicMock()
    output.get = lambda key, default=None: {
        "task_status": task_status,
        "video_url": video_url,
        "message": message,
    }.get(key, default)

    resp = MagicMock(spec=["status_code", "output", "message", "code"])
    resp.status_code = status_code
    resp.output = output
    resp.message = message
    resp.code = ""
    return resp


# ── Import (after helper defs) ──────────────────────────────────────────────

from prompt_template.dashscope_client import (
    get_client,
    generate,
    AVAILABLE_MODELS,
    _IMAGE_MODELS,
    _TEXT_MODELS,
    _VIDEO_MODELS,
    _encode_image,
    _build_user_content,
    _parse_text_response,
    _parse_multimodal_response,
    _parse_video_response,
    _find_first_image,
)


# ── Test 1: get_client() success ─────────────────────────────────────────────

with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test-key"}, clear=True):
    import dashscope
    dashscope.api_key = None
    result = get_client()
    check(
        "Test 1",
        "get_client success: returns sentinel 'dashscope'",
        result == "dashscope",
        detail=f" | got: {result!r}",
    )
    check(
        "Test 1b",
        "get_client success: dashscope.api_key configured",
        dashscope.api_key == "sk-test-key",
        detail=f" | key={dashscope.api_key!r}",
    )

# ── Test 1c: get_client with DASHCOPE_BASE_URL ────────────────────────────────

with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test-key", "DASHCOPE_BASE_URL": "https://custom.api.com"}, clear=True):
    dashscope.api_key = None
    dashscope.base_http_api_url = None
    get_client()
    check(
        "Test 1c",
        "get_client with DASHCOPE_BASE_URL: dashscope.base_http_api_url configured",
        dashscope.base_http_api_url == "https://custom.api.com",
        detail=f" | url={dashscope.base_http_api_url!r}",
    )

with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test-key"}, clear=True):
    dashscope.api_key = None
    dashscope.base_http_api_url = None
    get_client()
    check(
        "Test 1d",
        "get_client without DASHCOPE_BASE_URL: dashscope.base_http_api_url stays None",
        dashscope.base_http_api_url is None,
        detail=f" | url={dashscope.base_http_api_url!r}",
    )

# ── Test 2: get_client() failure (no API key) ────────────────────────────────

with patch.dict(os.environ, {}, clear=True):
    try:
        get_client()
        check("Test 2", "get_client failure: ValueError raised", False)
    except ValueError as e:
        check(
            "Test 2",
            "get_client failure: ValueError raised with 'DASHCOPE_API_KEY' message",
            "DASHCOPE_API_KEY" in str(e),
            detail=f" | got: {type(e).__name__}: {e}",
        )
    except Exception as e:
        check(
            "Test 2",
            "get_client failure: ValueError expected but got " + type(e).__name__,
            False,
            detail=f" | {e}",
        )


# ── Test 3: Text generation success ──────────────────────────────────────────

@patch("prompt_template.dashscope_client.Generation.call")
def test_text_generation_success(mock_gen):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_gen.return_value = make_gen_response(
            "Hello from Qwen!", finish_reason="stop", status_code=200
        )
        result = generate(
            system_prompt="Be helpful",
            user_prompt="Say hi",
            model="qwen-plus",
            temperature=0.7,
        )
        check(
            "Test 3",
            "Text generation success: returns text response",
            result["text"] == "Hello from Qwen!",
            detail=f" | text={result['text']!r}",
        )
        check(
            "Test 3b",
            "Text generation success: type is 'text'",
            result["type"] == "text",
        )
        check(
            "Test 3c",
            "Text generation success: response_data is empty",
            result["response_data"] == "",
        )
        args, kwargs = mock_gen.call_args
        check(
            "Test 3d",
            "Text generation success: model passed to Generation.call",
            kwargs["model"] == "qwen-plus",
            detail=f" | model={kwargs.get('model')!r}",
        )


test_text_generation_success()


# ── Test 4: Text generation truncated (finish_reason="length") ───────────────

@patch("prompt_template.dashscope_client.Generation.call")
def test_text_generation_truncated(mock_gen):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_gen.return_value = make_gen_response(
            "Partial response", finish_reason="length", status_code=200
        )
        result = generate(
            system_prompt="", user_prompt="Long story", model="qwen-turbo", temperature=0.5
        )
        check(
            "Test 4",
            "Text generation truncated: includes truncation warning",
            "[Response truncated due to token limit]" in result["text"],
            detail=f" | text={result['text']!r}",
        )


test_text_generation_truncated()


# ── Test 5: Text generation empty choices ────────────────────────────────────

@patch("prompt_template.dashscope_client.Generation.call")
def test_text_generation_empty_choices(mock_gen):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        resp = make_gen_response("", status_code=200)
        resp.output.choices = []
        mock_gen.return_value = resp
        result = generate("s", "u", model="qwen-max", temperature=0.5)
        check(
            "Test 5",
            "Text generation empty choices: returns error message",
            "no choices" in result["text"].lower(),
            detail=f" | text={result['text']!r}",
        )


test_text_generation_empty_choices()


# ── Test 6: Text generation null content ─────────────────────────────────────

@patch("prompt_template.dashscope_client.Generation.call")
def test_text_generation_null_content(mock_gen):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_gen.return_value = make_gen_response(None, status_code=200)
        result = generate("s", "u", model="qwen-max", temperature=0.5)
        check(
            "Test 6",
            "Text generation null content: returns error message",
            "null content" in result["text"].lower(),
            detail=f" | text={result['text']!r}",
        )


test_text_generation_null_content()


# ── Test 7: Image generation success (image URL returned) ────────────────────

@patch("prompt_template.dashscope_client.MultiModalConversation.call")
def test_image_generation_success(mock_mm):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        image_url = "https://dashscope.oss-cn-hangzhou.aliyuncs.com/test/image.png"
        mock_mm.return_value = make_mm_response(
            [{"image": image_url}], status_code=200
        )
        result = generate(
            system_prompt="", user_prompt="A cat", model="qwen-image-2.0", temperature=0.5
        )
        check(
            "Test 7",
            "Image generation success: type is 'image'",
            result["type"] == "image",
            detail=f" | type={result['type']!r}",
        )
        check(
            "Test 7b",
            "Image generation success: response_data is image URL",
            result["response_data"] == image_url,
            detail=f" | url={result['response_data']!r}",
        )
        check(
            "Test 7c",
            "Image generation success: text contains 'Generated image'",
            "Generated image" in result["text"],
            detail=f" | text={result['text']!r}",
        )


test_image_generation_success()


# ── Test 8: Image generation returns text (no image in response) ─────────────

@patch("prompt_template.dashscope_client.MultiModalConversation.call")
def test_image_generation_text_response(mock_mm):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_mm.return_value = make_mm_response(
            [{"text": "I cannot generate images with this model."}], status_code=200
        )
        result = generate(
            system_prompt="", user_prompt="Draw", model="qwen-image-2.0", temperature=0.5
        )
        check(
            "Test 8",
            "Image generation text response: type is 'text'",
            result["type"] == "text",
            detail=f" | type={result['type']!r}",
        )
        check(
            "Test 8b",
            "Image generation text response: returns text content",
            "cannot generate" in result["text"],
            detail=f" | text={result['text']!r}",
        )


test_image_generation_text_response()


# ── Test 9: Image generation empty choices ───────────────────────────────────

@patch("prompt_template.dashscope_client.MultiModalConversation.call")
def test_image_generation_empty_choices(mock_mm):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        resp = make_mm_response([], status_code=200)
        resp.output.choices = []
        mock_mm.return_value = resp
        result = generate("", "Draw", model="qwen-image-2.0", temperature=0.5)
        check(
            "Test 9",
            "Image generation empty choices: returns error message",
            "no choices" in result["text"].lower(),
            detail=f" | text={result['text']!r}",
        )


test_image_generation_empty_choices()


# ── Test 9b: Image generation with reference image file ──────────────────────

@patch("prompt_template.dashscope_client.MultiModalConversation.call")
def test_image_generation_with_file(mock_mm):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_mm.return_value = make_mm_response(
            [{"image": "https://dashscope.oss/generated.png"}], status_code=200
        )

        import tempfile
        img_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(img_content)
            tmp_path = f.name

        try:
            result = generate(
                system_prompt="Enhance this style",
                user_prompt="Generate a variation of this image",
                model="qwen-image-2.0-pro",
                temperature=0.5,
                files=[tmp_path],
            )
            check(
                "Test 9b",
                "Image generation with file: returns image response",
                result["type"] == "image",
                detail=f" | type={result['type']!r}",
            )
            args, kwargs = mock_mm.call_args
            messages = kwargs["messages"]
            check(
                "Test 9c",
                "Image generation with file: single user message (no system role)",
                len(messages) == 1 and messages[0]["role"] == "user",
                detail=f" | roles={[m['role'] for m in messages]}",
            )
            content = messages[0]["content"]
            check(
                "Test 9d",
                "Image generation with file: content has text + image parts",
                len(content) == 2,
                detail=f" | content_len={len(content)}",
            )
            check(
                "Test 9e",
                "Image generation with file: first part is text with combined prompts",
                content[0]["text"].startswith("Enhance this style"),
                detail=f" | text={content[0]['text'][:50]!r}",
            )
            check(
                "Test 9f",
                "Image generation with file: second part is image data URI",
                content[1]["image"].startswith("data:image/png;base64,"),
                detail=f" | image_prefix={content[1]['image'][:30]!r}",
            )
        finally:
            os.unlink(tmp_path)


test_image_generation_with_file()


# ── Test 10: API error (non-200 status) ──────────────────────────────────────

@patch("prompt_template.dashscope_client.Generation.call")
def test_api_error(mock_gen):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_gen.return_value = make_gen_response(
            "", status_code=400
        )
        mock_gen.return_value.message = "Bad Request"
        result = generate("s", "u", model="qwen-plus", temperature=0.5)
        check(
            "Test 10",
            "API error: returns error message with status info",
            "DashScope API error" in result["text"],
            detail=f" | text={result['text']!r}",
        )


test_api_error()


# ── Test 11: API call exception (network error) ─────────────────────────────

@patch("prompt_template.dashscope_client.Generation.call")
def test_api_exception(mock_gen):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_gen.side_effect = ConnectionError("Connection refused")
        try:
            generate("s", "u", model="qwen-plus", temperature=0.5)
            check("Test 11", "API exception: RuntimeError raised", False)
        except RuntimeError as e:
            check(
                "Test 11",
                "API exception: RuntimeError raised with connection info",
                "Connection refused" in str(e) or "failed" in str(e).lower(),
                detail=f" | got: {type(e).__name__}: {e}",
            )
        except Exception as e:
            check(
                "Test 11",
                "API exception: RuntimeError expected but got " + type(e).__name__,
                False,
                detail=f" | {e}",
            )


test_api_exception()


# ── Test 12: Text generation with files ──────────────────────────────────────

@patch("prompt_template.dashscope_client.Generation.call")
def test_text_generation_with_files(mock_gen):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_gen.return_value = make_gen_response(
            "File content processed", finish_reason="stop", status_code=200
        )

        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello from temp file")
            tmp_path = f.name

        try:
            result = generate(
                system_prompt="Analyze",
                user_prompt="What is in the file?",
                model="qwen-plus",
                temperature=0.5,
                files=[tmp_path],
            )
            check(
                "Test 12",
                "Text generation with files: returns response text",
                "File content processed" in result["text"],
                detail=f" | text={result['text']!r}",
            )
            args, kwargs = mock_gen.call_args
            user_msg = kwargs["messages"][1]["content"]
            check(
                "Test 12b",
                "Text generation with files: file content in user message string",
                "hello from temp file" in user_msg,
                detail=f" | content excerpt: {user_msg[-60:]!r}",
            )
        finally:
            os.unlink(tmp_path)


test_text_generation_with_files()


# ── Test 13: Model list includes image and text models ───────────────────────

model_ids = {m["id"] for m in AVAILABLE_MODELS}
check(
    "Test 13",
    "Model list: contains qwen-plus (text)",
    "qwen-plus" in model_ids,
)
check(
    "Test 13b",
    "Model list: contains qwen-image-2.0 (image)",
    "qwen-image-2.0" in model_ids,
)
check(
    "Test 13c",
    "Model list: contains qwen-image-2.0-pro (image)",
    "qwen-image-2.0-pro" in model_ids,
)
check(
    "Test 13d",
    "Model list: contains qwen3.6-max-preview (multimodal)",
    "qwen3.6-max-preview" in model_ids,
)
check(
    "Test 13e",
    "Model list: contains deepseek-v4-pro (third-party text)",
    "deepseek-v4-pro" in model_ids,
)
check(
    "Test 13f",
    "Model list: contains deepseek-v4-flash (third-party text)",
    "deepseek-v4-flash" in model_ids,
)
check(
    "Test 13g",
    "Model list: contains kimi-k2.6 (third-party text)",
    "kimi-k2.6" in model_ids,
)
check(
    "Test 13h",
    "Model list: contains glm-5.1 (third-party text)",
    "glm-5.1" in model_ids,
)
check(
    "Test 13i",
    "Model list: contains MiniMax-M2.5 (third-party text)",
    "MiniMax-M2.5" in model_ids,
)
check(
    "Test 13j",
    "Model list: contains wan2.7-image-pro (image generation)",
    "wan2.7-image-pro" in model_ids,
)
check(
    "Test 13k",
    "Model list: _IMAGE_MODELS matches image model ids",
    _IMAGE_MODELS == {"qwen-image-2.0", "qwen-image-2.0-pro", "wan2.7-image-pro"},
)
check(
    "Test 13l",
    "Model list: _TEXT_MODELS includes third-party models",
    all(m in _TEXT_MODELS for m in ["deepseek-v4-pro", "deepseek-v4-flash", "kimi-k2.6", "glm-5.1", "MiniMax-M2.5"]),
)


# ── Test 14: Third-party text model routes to Generation.call ─────────────────

@patch("prompt_template.dashscope_client.Generation.call")
def test_third_party_text_model_routing(mock_gen):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_gen.return_value = make_gen_response(
            "Hello from DeepSeek!", finish_reason="stop", status_code=200
        )
        result = generate(
            system_prompt="Be helpful",
            user_prompt="Hi",
            model="deepseek-v4-pro",
            temperature=0.7,
        )
        check(
            "Test 14",
            "Third-party text model: returns text response via Generation.call",
            result["text"] == "Hello from DeepSeek!",
            detail=f" | text={result['text']!r}",
        )
        args, kwargs = mock_gen.call_args
        check(
            "Test 14b",
            "Third-party text model: Generation.call called with model",
            kwargs["model"] == "deepseek-v4-pro",
            detail=f" | model={kwargs.get('model')!r}",
        )


test_third_party_text_model_routing()


# ── Test 15: wan2.7-image-pro routes to MultiModalConversation (image gen) ───

@patch("prompt_template.dashscope_client.MultiModalConversation.call")
def test_wan_image_pro_routing(mock_mm):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_mm.return_value = make_mm_response(
            [{"image": "https://dashscope.oss/wan.png"}], status_code=200
        )
        result = generate(
            system_prompt="", user_prompt="A landscape", model="wan2.7-image-pro", temperature=0.5
        )
        check(
            "Test 15",
            "wan2.7-image-pro: type is 'image' via MultiModalConversation",
            result["type"] == "image",
            detail=f" | type={result['type']!r}",
        )
        args, kwargs = mock_mm.call_args
        check(
            "Test 15b",
            "wan2.7-image-pro: MultiModalConversation.call called with model",
            kwargs["model"] == "wan2.7-image-pro",
            detail=f" | model={kwargs.get('model')!r}",
        )


test_wan_image_pro_routing()


# ── Test 16: Multimodal model (qwen3.6-max-preview) routes to MultiModalConversation ──

@patch("prompt_template.dashscope_client.MultiModalConversation.call")
def test_multimodal_model_routing(mock_mm):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_mm.return_value = make_mm_response(
            [{"text": "I can see the image."}], status_code=200
        )
        result = generate(
            system_prompt="You are a helpful assistant.",
            user_prompt="What is in this image?",
            model="qwen3.6-max-preview",
            temperature=0.7,
        )
        check(
            "Test 16",
            "Multimodal model: returns text response via MultiModalConversation",
            result["text"] == "I can see the image.",
            detail=f" | text={result['text']!r}",
        )
        args, kwargs = mock_mm.call_args
        check(
            "Test 16b",
            "Multimodal model: MultiModalConversation.call called with model",
            kwargs["model"] == "qwen3.6-max-preview",
            detail=f" | model={kwargs.get('model')!r}",
        )
        messages = kwargs["messages"]
        check(
            "Test 16c",
            "Multimodal model: single user message (no system role)",
            len(messages) == 1 and messages[0]["role"] == "user",
            detail=f" | roles={[m['role'] for m in messages]}",
        )
        content = messages[0]["content"]
        check(
            "Test 16d",
            "Multimodal model: text part includes combined system prompt",
            content[0]["text"].startswith("You are a helpful assistant."),
            detail=f" | text={content[0]['text'][:50]!r}",
        )


test_multimodal_model_routing()


# ── Test 17: _encode_image produces valid data URI ───────────────────────────

import tempfile
img_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
    f.write(img_content)
    img_path = f.name
try:
    data_uri = _encode_image(img_path)
    check(
        "Test 14",
        "_encode_image: produces data URI starting with data:image",
        data_uri.startswith("data:image/png;base64,"),
        detail=f" | prefix={data_uri[:25]!r}",
    )
finally:
    os.unlink(img_path)


# ── Test 15: _parse_multimodal_response with missing message ─────────────────

bad_resp = MagicMock()
bad_resp.output.choices = [MagicMock(message=None)]
text, rtype, data = _parse_multimodal_response(bad_resp, is_image=False)
check(
    "Test 15",
    "_parse_multimodal_response missing message: returns error",
    "Failed to parse" in text,
    detail=f" | text={text!r}",
)

# Test 15b: empty content list
empty_resp = make_mm_response([], status_code=200)
text, rtype, data = _parse_multimodal_response(empty_resp, is_image=False)
check(
    "Test 15b",
    "_parse_multimodal_response empty content list: returns str of list",
    text == "[]",
    detail=f" | text={text!r}",
)


# ── Test 17: Model list includes video models ──────────────────────────────

model_ids = {m["id"] for m in AVAILABLE_MODELS}
check(
    "Test 17",
    "Model list: contains wan2.6-t2v (video)",
    "wan2.6-t2v" in model_ids,
)
check(
    "Test 17b",
    "Model list: contains wan2.6-i2v-flash (video)",
    "wan2.6-i2v-flash" in model_ids,
)
check(
    "Test 17c",
    "Model list: _VIDEO_MODELS matches all video model ids",
    _VIDEO_MODELS == {
        "wan2.6-t2v", "wan2.5-t2v-preview", "wan2.2-t2v-plus",
        "wan2.1-t2v-plus", "wan2.1-t2v-turbo",
        "wan2.6-i2v-flash", "wan2.2-i2v-plus",
        "wan2.1-i2v-plus", "wan2.1-i2v-turbo",
    },
)


# ── Test 18: T2V video model routes to VideoSynthesis.call ─────────────────

@patch("prompt_template.dashscope_client.VideoSynthesis.call")
def test_t2v_video_routing(mock_vs):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_vs.return_value = make_video_response(
            video_url="https://dashscope.oss/video.mp4",
            task_status="SUCCEEDED",
            status_code=200,
        )
        result = generate(
            system_prompt="Cinematic style",
            user_prompt="A dog running on the beach",
            model="wan2.6-t2v",
            temperature=0.5,
        )
        check(
            "Test 18",
            "T2V video: type is 'video'",
            result["type"] == "video",
            detail=f" | type={result['type']!r}",
        )
        check(
            "Test 18b",
            "T2V video: response_data contains video URL",
            "dashscope.oss/video.mp4" in result["response_data"],
            detail=f" | data={result['response_data']!r}",
        )
        args, kwargs = mock_vs.call_args
        check(
            "Test 18c",
            "T2V video: VideoSynthesis.call called with model",
            kwargs["model"] == "wan2.6-t2v",
            detail=f" | model={kwargs.get('model')!r}",
        )
        check(
            "Test 18d",
            "T2V video: prompt includes system_prompt + user_prompt",
            "Cinematic style" in kwargs["prompt"],
            detail=f" | prompt={kwargs['prompt'][:60]!r}",
        )
        check(
            "Test 18e",
            "T2V video: img_url is None (no image file)",
            kwargs.get("img_url") is None,
            detail=f" | img_url={kwargs.get('img_url')!r}",
        )


test_t2v_video_routing()


# ── Test 19: I2V video model routes to VideoSynthesis.call with img_url ────

@patch("prompt_template.dashscope_client.VideoSynthesis.call")
def test_i2v_video_routing(mock_vs):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_vs.return_value = make_video_response(
            video_url="https://dashscope.oss/generated.mp4",
            task_status="SUCCEEDED",
            status_code=200,
        )

        import tempfile
        img_content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(img_content)
            tmp_path = f.name

        try:
            result = generate(
                system_prompt="Animate this",
                user_prompt="Make it move",
                model="wan2.6-i2v-flash",
                temperature=0.5,
                files=[tmp_path],
            )
            check(
                "Test 19",
                "I2V video: type is 'video'",
                result["type"] == "video",
                detail=f" | type={result['type']!r}",
            )
            args, kwargs = mock_vs.call_args
            check(
                "Test 19b",
                "I2V video: img_url is set to image path",
                kwargs.get("img_url") is not None,
                detail=f" | img_url={kwargs.get('img_url')!r}",
            )
            check(
                "Test 19c",
                "I2V video: img_url ends with .png",
                kwargs.get("img_url", "").endswith(".png"),
                detail=f" | img_url={kwargs.get('img_url')!r}",
            )
        finally:
            os.unlink(tmp_path)


test_i2v_video_routing()


# ── Test 20: Video generation task failed ──────────────────────────────────

@patch("prompt_template.dashscope_client.VideoSynthesis.call")
def test_video_generation_failed(mock_vs):
    with patch.dict(os.environ, {"DASHCOPE_API_KEY": "sk-test"}, clear=True):
        mock_vs.return_value = make_video_response(
            video_url="",
            task_status="FAILED",
            status_code=200,
            message="Content violates policy",
        )
        result = generate(
            system_prompt="", user_prompt="Bad content", model="wan2.6-t2v", temperature=0.5
        )
        check(
            "Test 20",
            "Video generation failed: type is 'text' (fallback)",
            result["type"] == "text",
            detail=f" | type={result['type']!r}",
        )
        check(
            "Test 20b",
            "Video generation failed: text contains error message",
            "Video generation failed" in result["text"],
            detail=f" | text={result['text']!r}",
        )


test_video_generation_failed()


# ── Test 21: _parse_video_response error handling ──────────────────────────

text, rtype, data = _parse_video_response(make_video_response("", "UNKNOWN", 200))
check(
    "Test 21",
    "_parse_video_response with no video_url: returns error",
    "Video generation failed" in text,
    detail=f" | text={text!r}",
)

# Null output (missing .output attribute)
bad_resp = MagicMock(spec=["status_code"])
del bad_resp.output
text, rtype, data = _parse_video_response(bad_resp)
check(
    "Test 21b",
    "_parse_video_response with missing output: returns error gracefully",
    "Failed to parse video response" in text,
    detail=f" | text={text!r}",
)


# ── Test 22: _find_first_image returns image path ──────────────────────────

no_img = _find_first_image(["readme.txt", "data.csv"])
check(
    "Test 22",
    "_find_first_image with no image files: returns None",
    no_img is None,
    detail=f" | got={no_img!r}",
)

import tempfile
_img = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
    f.write(_img)
    _png_path = f.name
try:
    found = _find_first_image(["readme.txt", _png_path, "data.csv"])
    check(
        "Test 22b",
        "_find_first_image with image file: returns image path",
        found == _png_path,
        detail=f" | got={found!r}",
    )
finally:
    os.unlink(_png_path)

with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
    f.write(b"hello")
    _txt_path = f.name
try:
    found = _find_first_image([_txt_path])
    check(
        "Test 22c",
        "_find_first_image with only text file: returns None",
        found is None,
        detail=f" | got={found!r}",
    )
finally:
    os.unlink(_txt_path)


# ── Summary ──────────────────────────────────────────────────────────────────

total = passed + failed
result_lines = list(results)
result_lines.insert(0, "=== DashScope Client Tests ===")
result_lines.append("")
result_lines.append("---")
result_lines.append(f"Total: {total} | Passed: {passed} | Failed: {failed}")

output = "\n".join(result_lines)
print(output)

# ── Save evidence ────────────────────────────────────────────────────────────

evidence_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".sisyphus", "evidence"
)
os.makedirs(evidence_dir, exist_ok=True)
evidence_path = os.path.join(evidence_dir, "task-dashscope-client.txt")
with open(evidence_path, "w") as f:
    f.write(output)
print(f"\nEvidence saved to {evidence_path}")

sys.exit(0 if failed == 0 else 1)

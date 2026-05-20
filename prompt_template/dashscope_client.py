"""DashScope native SDK client wrapper for prompt-template.

Model-to-endpoint routing:
  Text models  (qwen-max, qwen-plus, etc.) → Generation.call()
  Image models (qwen-image-2.0, etc.)      → MultiModalConversation.call()
  Multimodal   (qwen3.6-*, qwen3-vl-*, etc.) → MultiModalConversation.call()

DashScope enforces strict model-to-endpoint matching — using the wrong
endpoint produces "url error, please check url!".
"""

import base64
import mimetypes
import os
import time
from http import HTTPStatus

import dashscope
import dotenv
from dashscope import Generation, MultiModalConversation

from prompt_template.logger import get_api_logger

dotenv.load_dotenv()

AVAILABLE_MODELS = [
    # Latest generation — multimodal (MultiModalConversation)
    {"id": "qwen3.6-max-preview", "label": "Qwen 3.6 Max Preview — latest multimodal flagship"},
    {"id": "qwen3.6-plus",        "label": "Qwen 3.6 Plus — latest generation flagship"},
    {"id": "qwen3.6-flash",       "label": "Qwen 3.6 Flash — latest, fast & efficient"},
    {"id": "qwen3.5-omni-plus",   "label": "Qwen 3.5 Omni Plus — multimodal vision & audio"},
    # Stable generation — plain text (Generation.call)
    {"id": "qwen-max",            "label": "Qwen Max — most capable stable model"},
    {"id": "qwen-plus",           "label": "Qwen Plus — balanced quality and speed"},
    {"id": "qwen-flash",          "label": "Qwen Flash — fast, cost-efficient"},
    {"id": "qwen-turbo",          "label": "Qwen Turbo — fastest inference"},
    {"id": "qwq-plus",            "label": "QWQ Plus — reasoning model"},
    # Third-party text models (Generation.call)
    {"id": "deepseek-v4-pro",     "label": "DeepSeek V4 Pro — powerful third-party text model"},
    {"id": "deepseek-v4-flash",   "label": "DeepSeek V4 Flash — fast third-party text model"},
    {"id": "kimi-k2.6",           "label": "Kimi K2.6 — third-party text model"},
    {"id": "glm-5.1",             "label": "GLM 5.1 — third-party text model"},
    {"id": "MiniMax-M2.5",        "label": "MiniMax M2.5 — third-party text model"},
    # Image generation (MultiModalConversation)
    {"id": "qwen-image-2.0",      "label": "Qwen Image 2.0 — text-to-image generation"},
    {"id": "qwen-image-2.0-pro",  "label": "Qwen Image 2.0 Pro — enhanced quality"},
    {"id": "wan2.7-image-pro",    "label": "Wan 2.7 Image Pro — text-to-image generation"},
    # Vision-language (MultiModalConversation)
    {"id": "qwen3-vl-flash",      "label": "qwen3-vl-flash"},
]

# Models that MUST use Generation.call() — plain text endpoint
_TEXT_MODELS = frozenset({
    "qwen-max", "qwen-plus", "qwen-flash", "qwen-turbo", "qwq-plus",
    "deepseek-v4-pro", "deepseek-v4-flash",
    "kimi-k2.6", "glm-5.1", "MiniMax-M2.5",
})
# Models that MUST use MultiModalConversation.call() — image generation
_IMAGE_MODELS = frozenset({
    "qwen-image-2.0", "qwen-image-2.0-pro", "wan2.7-image-pro",
})
# Everything else (qwen3.6-*, qwen3-vl-*) → MultiModalConversation.call()


def get_client():
    """Configure the DashScope global API key.

    Reads API_KEY from environment (via python-dotenv).
    DashScope authenticates with the same sk-... key used for the
    OpenAI-compatible endpoint.

    Returns:
        str: "dashscope" sentinel value.

    Raises:
        ValueError: If API_KEY is not set.
    """
    api_key = os.getenv("API_KEY")
    if not api_key:
        raise ValueError(
            "API_KEY not found. Create a .env file with:\n"
            "API_KEY=your_api_key_here\n\n"
            "Set SDK=dashscope in .env to use the DashScope native SDK."
        )
    dashscope.api_key = api_key
    base_url = os.getenv("BASE_URL")
    if base_url:
        dashscope.base_http_api_url = base_url.rstrip("/")
    return "dashscope"


def _encode_image(file_path):
    """Read an image file and return a base64 data URI string."""
    with open(file_path, "rb") as f:
        data = f.read()
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "image/png"
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime_type};base64,{b64}"


def _build_user_content(user_prompt, files=None):
    """Embed file contents into the user prompt string (for Generation.call).

    Generation.call() uses simple string content — files are inlined
    as text rather than sent via content parts.
    """
    if not files:
        return user_prompt

    parts = [user_prompt]
    for file_path in files:
        file_path = str(file_path)
        if file_path.lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        ):
            data_uri = _encode_image(file_path)
            parts.append(f"\n\n[Attached image: {os.path.basename(file_path)}]\n{data_uri[:80]}...")
        else:
            try:
                with open(file_path, "rb") as f:
                    raw = f.read()
                text = raw.decode("utf-8")
                parts.append(
                    f"\n\n[Attached file: {os.path.basename(file_path)}]\n"
                    f"```\n{text}\n```"
                )
            except UnicodeDecodeError:
                parts.append(
                    f"\n\n[Attached file: {os.path.basename(file_path)}"
                    f" (binary, could not embed as text)]"
                )

    return "\n".join(parts)


def _parse_text_response(response):
    """Extract text from a Generation.call() response (string content).

    Returns:
        str: Extracted text, or an error/diagnostic message.
    """
    try:
        choices = response.output.choices
        if not choices:
            return "[Model returned no choices]"

        choice = choices[0]
        content = getattr(choice, "message", None)
        if content is None:
            return "[Model returned a response without message content]"

        text = getattr(content, "content", None)
        if text is None:
            return "[Model returned null content]"

        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason == "length":
            text += "\n\n[Response truncated due to token limit]"

        return str(text) if text is not None else ""

    except (AttributeError, IndexError, TypeError) as e:
        return f"[Failed to parse text response: {e}]"


def _parse_multimodal_response(response, is_image):
    """Parse a MultiModalConversation response into (text, type, data).

    Response content is always a list of dicts when non-empty:
      text:  [{"text": "..."}]
      image: [{"image": "https://..."}]

    Returns:
        tuple: (response_text, response_type, response_data)
    """
    try:
        choices = response.output.choices
        if not choices:
            msg = "[Image model returned no choices]" if is_image else "[Model returned no choices]"
            return msg, "text", ""

        choice = choices[0]
        content_list = choice.message.content
        if content_list is None:
            return "[Model returned null content]", "text", ""
        if not isinstance(content_list, list):
            content_list = [content_list]

        response_text = ""
        for item in content_list:
            if isinstance(item, dict):
                if "image" in item:
                    img_url = item["image"]
                    if img_url:
                        display = f"[Generated image: {img_url[:80]}...]"
                        return display, "image", img_url
                if "text" in item and item["text"]:
                    response_text = item["text"]

        if not is_image:
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason == "length" and response_text:
                response_text += "\n\n[Response truncated due to token limit]"

        if not response_text:
            return str(content_list), "text", ""
        return response_text, "text", ""

    except (AttributeError, IndexError, TypeError) as e:
        prefix = "image" if is_image else "text"
        return f"[Failed to parse {prefix} response: {e}]", "text", ""


def generate(system_prompt, user_prompt, model, temperature, files=None):
    """Generate content using the DashScope native SDK.

    Routes text models to Generation.call() and multimodal/image models
    to MultiModalConversation.call() to match DashScope's strict
    model-to-endpoint requirements.

    Args:
        system_prompt: System-level instruction for the model.
        user_prompt: User message text.
        model: Model ID string (from AVAILABLE_MODELS).
        temperature: Sampling temperature (0.0-2.0).
        files: Optional list of file paths (strings or Path objects).

    Returns:
        dict with keys:
            - text: Generated response text (or display message).
            - type: Response content type ("text" or "image").
            - response_data: Image URL if type is "image", else "".
            - candidates: Raw response output from the API.

    Raises:
        ValueError: If API_KEY is not set.
        RuntimeError: If the API call fails.
    """
    get_client()

    log = get_api_logger()
    file_count = len(files) if files else 0
    log.info(
        "DashScope generate() | model=%s | temp=%s | prompt_len=%s | files=%s",
        model, temperature, len(user_prompt), file_count,
    )

    is_text = model in _TEXT_MODELS
    is_image = model in _IMAGE_MODELS
    t0 = time.time()

    try:
        if is_text:
            user_content = _build_user_content(user_prompt, files)
            messages = [
                {
                    "role": "system",
                    "content": system_prompt or "You are a helpful assistant.",
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ]
            response = Generation.call(
                model=model,
                messages=messages,
                result_format="message",
                temperature=temperature,
            )
        else:
            # All multimodal / image-generation models use a single user
            # message with content parts — no separate system role.
            combined = (
                f"{system_prompt}\n\n---\n\n{user_prompt}"
                if system_prompt
                else user_prompt
            )
            user_parts = [{"text": combined}]
            if files:
                for file_path in files:
                    file_path = str(file_path)
                    if file_path.lower().endswith(
                        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
                    ):
                        user_parts.append({"image": _encode_image(file_path)})
                    else:
                        try:
                            with open(file_path, "rb") as f:
                                raw = f.read()
                            text_content = raw.decode("utf-8")
                            user_parts.append({
                                "text": (
                                    f"\n[Attached file: {os.path.basename(file_path)}]\n"
                                    f"```\n{text_content}\n```"
                                ),
                            })
                        except UnicodeDecodeError:
                            user_parts.append({
                                "text": (
                                    f"\n[Attached file: {os.path.basename(file_path)}"
                                    f" (binary, could not embed as text)]"
                                ),
                            })

            messages = [{"role": "user", "content": user_parts}]

            response = MultiModalConversation.call(
                model=model,
                messages=messages,
                temperature=temperature,
            )
    except Exception as e:
        elapsed = time.time() - t0
        log.error(
            "DashScope generate() FAILED | model=%s | elapsed=%.2fs | error=%s",
            model, elapsed, e,
        )
        raise RuntimeError(f"DashScope API call failed: {e}") from e

    elapsed = time.time() - t0

    response_text = ""
    response_type = "text"
    response_data = ""

    if response.status_code != HTTPStatus.OK:
        error_msg = (
            getattr(response, "message", None)
            or getattr(response, "code", "Unknown error")
        )
        response_text = f"[DashScope API error: {error_msg}]"
        log.error(
            "DashScope API error | model=%s | status=%s | message=%s",
            model, response.status_code, error_msg,
        )
    else:
        if is_text:
            response_text = _parse_text_response(response)
        else:
            response_text, response_type, response_data = _parse_multimodal_response(response, is_image)

    log.info(
        "DashScope generate() OK | model=%s | elapsed=%.2fs | "
        "response_len=%s | type=%s",
        model, elapsed, len(response_text), response_type,
    )
    log.debug("DashScope full response:\n%s", response_text)

    return {
        "text": response_text,
        "type": response_type,
        "response_data": response_data,
        "candidates": getattr(response, "output", {}),
    }

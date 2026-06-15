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
from dashscope.aigc.video_synthesis import VideoSynthesis

from prompt_template.logger import get_api_logger

dotenv.load_dotenv()

AVAILABLE_MODELS = [
    # Latest generation — multimodal (MultiModalConversation) [text+image+video→text]
    {"id": "qwen3.6-max-preview", "label": "Qwen 3.6 Max Preview — [text+image+video→text] multimodal flagship"},
    {"id": "qwen3.6-plus",        "label": "Qwen 3.6 Plus — [text+image+video→text] latest generation flagship"},
    {"id": "qwen3.6-flash",       "label": "Qwen 3.6 Flash — [text+image+video→text] fast & efficient"},
    {"id": "qwen3.5-omni-plus",   "label": "Qwen 3.5 Omni Plus — [text+image+audio+video→text+audio] multimodal"},
    # Stable generation — plain text (Generation.call) [text→text]
    {"id": "qwen-max",            "label": "Qwen Max — [text→text] most capable stable"},
    {"id": "qwen-plus",           "label": "Qwen Plus — [text→text] balanced quality and speed"},
    {"id": "qwen-flash",          "label": "Qwen Flash — [text→text] fast, cost-efficient"},
    {"id": "qwen-turbo",          "label": "Qwen Turbo — [text→text] fastest inference"},
    {"id": "qwq-plus",            "label": "QWQ Plus — [text→text] reasoning model"},
    # Third-party text models (Generation.call) [text→text]
    {"id": "deepseek-v4-pro",     "label": "DeepSeek V4 Pro — [text→text] powerful third-party"},
    {"id": "deepseek-v4-flash",   "label": "DeepSeek V4 Flash — [text→text] fast third-party"},
    {"id": "kimi-k2.6",           "label": "Kimi K2.6 — [text→text] third-party"},
    {"id": "glm-5.1",             "label": "GLM 5.1 — [text→text] third-party"},
    {"id": "MiniMax-M2.5",        "label": "MiniMax M2.5 — [text→text] third-party"},
    # Image generation (MultiModalConversation) [text+image→image]
    {"id": "qwen-image-2.0",      "label": "Qwen Image 2.0 — [text+image→image] generation & editing"},
    {"id": "qwen-image-2.0-pro",  "label": "Qwen Image 2.0 Pro — [text+image→image] enhanced quality"},
    {"id": "wan2.7-image-pro",    "label": "Wan 2.7 Image Pro — [text+image→image] 4K generation & editing"},
    # Vision-language (MultiModalConversation) [text+image+video→text]
    {"id": "qwen3-vl-flash",      "label": "qwen3-vl-flash — [text+image+video→text] vision-language"},
    # Video generation — VideoSynthesis API [text→video] or [text+image→video]
    {"id": "wan2.6-t2v",         "label": "Wan 2.6 T2V — [text→video] latest generation"},
    {"id": "wan2.5-t2v-preview", "label": "Wan 2.5 T2V Preview — [text→video] enhanced quality"},
    {"id": "wan2.2-t2v-plus",    "label": "Wan 2.2 T2V Plus — [text→video] balanced"},
    {"id": "wan2.1-t2v-plus",    "label": "Wan 2.1 T2V Plus — [text→video] quality"},
    {"id": "wan2.1-t2v-turbo",   "label": "Wan 2.1 T2V Turbo — [text→video] fast"},
    {"id": "wan2.6-i2v-flash",   "label": "Wan 2.6 I2V Flash — [text+image→video] latest fast"},
    {"id": "wan2.2-i2v-plus",    "label": "Wan 2.2 I2V Plus — [text+image→video] balanced"},
    {"id": "wan2.1-i2v-plus",    "label": "Wan 2.1 I2V Plus — [text+image→video] quality"},
    {"id": "wan2.1-i2v-turbo",   "label": "Wan 2.1 I2V Turbo — [text+image→video] fast"},
    # TTS models (MultiModalConversation.call) [text→audio]
    {"id": "qwen3-tts-flash-2025-11-27",         "label": "Qwen 3 TTS Flash — [text→audio] fast speech synthesis"},
    {"id": "qwen3-tts-instruct-flash", "label": "Qwen 3 TTS Instruct Flash — [text→audio] with instruction control"},
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
# Models that MUST use VideoSynthesis.call() — video generation (async submit + poll)
_VIDEO_MODELS = frozenset({
    "wan2.6-t2v", "wan2.5-t2v-preview", "wan2.2-t2v-plus",
    "wan2.1-t2v-plus", "wan2.1-t2v-turbo",
    "wan2.6-i2v-flash", "wan2.2-i2v-plus",
    "wan2.1-i2v-plus", "wan2.1-i2v-turbo",
})

# Models that MUST use MultiModalConversation.call() — TTS (text→audio)
_AUDIO_MODELS = frozenset({
    "qwen3-tts-flash-2025-11-27",
    "qwen3-tts-instruct-flash",
})


def get_client():
    """Configure the DashScope global API key.

    Reads DASHCOPE_API_KEY from environment (via python-dotenv).
    DashScope authenticates with the same sk-... key used for the
    OpenAI-compatible endpoint.

    Returns:
        str: "dashscope" sentinel value.

    Raises:
        ValueError: If DASHCOPE_API_KEY is not set.
    """
    # Canonical name is DASHSCOPE_API_KEY (shared with Podcast Studio);
    # keep DASHCOPE_API_KEY as a backward-compatible fallback.
    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("DASHCOPE_API_KEY")
    if not api_key:
        raise ValueError(
            "DASHSCOPE_API_KEY not found. Create a .env file with:\n"
            "DASHSCOPE_API_KEY=your_dashscope_api_key_here\n\n"
            "Get a key at: https://dashscope.aliyun.com"
        )
    dashscope.api_key = api_key
    base_url = os.getenv("DASHSCOPE_BASE_URL") or os.getenv("DASHCOPE_BASE_URL")
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


def _find_first_image(files):
    """Return the first image file path from files list, or None."""
    if not files:
        return None
    for file_path in files:
        file_path = str(file_path)
        if file_path.lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        ):
            return file_path
    return None


def _parse_video_response(response):
    """Parse a VideoSynthesisResponse into (display_text, type, video_url)."""
    try:
        task_status = response.output.get("task_status")
        video_url = response.output.get("video_url")

        if task_status == "SUCCEEDED" and video_url:
            display = f"[Generated video: {video_url[:80]}...]"
            return display, "video", video_url

        error_msg = (
            response.output.get("message")
            or response.output.get("code", "Unknown error")
        )
        return f"[Video generation failed: {error_msg}]", "text", ""

    except (AttributeError, TypeError) as e:
        return f"[Failed to parse video response: {e}]", "text", ""


def _parse_tts_response(response, original_text):
    """Parse a TTS MultiModalConversation response into (text, type, data).

    The response may contain ``output.audio.url`` (WAV URL, valid ~24h) or
    ``output.audio.data`` (base64-encoded audio). We download/save the audio
    locally for persistent access.

    Returns:
        tuple: (response_text, response_type, response_data)
            response_text = original input text (transcript)
            response_type = "audio"
            response_data = local file path to saved WAV
    """
    from prompt_template.audio_utils import download_and_save_audio, save_base64_audio

    try:
        output = response.output
        audio = getattr(output, "audio", None) if hasattr(output, "audio") else output.get("audio")
        if not audio:
            return "[TTS returned no audio data]", "text", ""

        url = None
        b64_data = None

        if isinstance(audio, dict):
            url = audio.get("url") or audio.get("audio_url")
            b64_data = audio.get("data")
        elif isinstance(audio, str):
            if audio.startswith("http"):
                url = audio
            else:
                b64_data = audio

        if url:
            path = download_and_save_audio(url)
            return original_text, "audio", path
        if b64_data:
            path = save_base64_audio(b64_data, "audio/wav")
            return original_text, "audio", path

        return "[TTS audio format not recognised]", "text", ""

    except (AttributeError, TypeError, ValueError) as e:
        return f"[Failed to parse TTS response: {e}]", "text", ""


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


def generate(system_prompt, user_prompt, model, temperature, files=None,
             size="1280*720", duration=5, **kwargs):
    """Generate content using the DashScope native SDK.

    Routes text models to Generation.call(), multimodal/image models
    to MultiModalConversation.call(), and TTS models to
    MultiModalConversation.call() with speech parameters.

    Args:
        system_prompt: System-level instruction for the model.
        user_prompt: User message text.
        model: Model ID string (from AVAILABLE_MODELS).
        temperature: Sampling temperature (0.0-2.0).
        files: Optional list of file paths (strings or Path objects).
        size: Output video size (width*height). Only used for video models.
              Defaults to "1280*720".
        duration: Video duration in seconds. Only used for video models.
                  Defaults to 5.
        **kwargs: Additional options.
            voice (str): Voice name for TTS models (default "Cherry").
            language (str): Language for TTS models (default "Auto").

    Returns:
        dict with keys:
            - text: Generated response text (or input text for TTS).
            - type: Response content type ("text", "image", "video", or "audio").
            - response_data: Image/video URL or saved audio file path.
            - candidates: Raw response output from the API.

    Raises:
        ValueError: If DASHCOPE_API_KEY is not set.
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
    is_video = model in _VIDEO_MODELS
    is_tts = model in _AUDIO_MODELS
    t0 = time.time()

    try:
        if is_video:
            combined = (
                f"{system_prompt}\n\n---\n\n{user_prompt}"
                if system_prompt
                else user_prompt
            )
            img_path = _find_first_image(files)
            response = VideoSynthesis.call(
                model=model,
                prompt=combined,
                img_url=img_path,
                size=size,
                duration=duration,
            )
        elif is_tts:
            voice = kwargs.get("voice", "Cherry")
            language = kwargs.get("language", "Auto")
            response = MultiModalConversation.call(
                model=model,
                text=user_prompt,
                voice=voice,
                language_type=language,
                stream=False,
            )
        elif is_text:
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
        if is_tts:
            response_text, response_type, response_data = _parse_tts_response(response, user_prompt)
        elif is_text:
            response_text = _parse_text_response(response)
        elif is_video:
            response_text, response_type, response_data = _parse_video_response(response)
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

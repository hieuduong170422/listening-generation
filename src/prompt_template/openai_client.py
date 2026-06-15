"""OpenAI API client wrapper for prompt-template.

Provides:
- get_client(): Returns a configured OpenAI client
- AVAILABLE_MODELS: List of supported OpenAI models
- generate(): Generate content with text, image, video, and audio outputs

Routes to four API families:
  Text chat    → client.chat.completions.create()
  Image gen    → client.images.generate()
  TTS audio    → client.audio.speech.create()
  Video gen    → client.videos.create_and_poll()  (Sora, async with sync polling)
"""

import base64
import mimetypes
import os
import time
import uuid
from pathlib import Path

import dotenv
from openai import OpenAI

from prompt_template.logger import get_api_logger

dotenv.load_dotenv()

AVAILABLE_MODELS = [
    # Text (chat) models
    {"id": "gpt-5.5", "label": "GPT-5.5 — [text+image\u2192text] flagship reasoning model"},
    {"id": "gpt-5.4-mini", "label": "GPT-5.4 Mini — [text+image\u2192text] fast reasoning"},
    {"id": "gpt-5.4-nano", "label": "GPT-5.4 Nano — [text+image\u2192text] fastest reasoning"},
    {"id": "gpt-4o", "label": "GPT-4o — [text+image\u2192text] previous flagship"},
    {"id": "gpt-4o-mini", "label": "GPT-4o Mini — [text+image\u2192text] cost-efficient"},
    {"id": "o3", "label": "o3 — [text+image\u2192text] advanced reasoning"},
    {"id": "o4-mini", "label": "o4-mini — [text+image\u2192text] fast reasoning"},
    {"id": "gpt-4.1", "label": "GPT-4.1 — [text+image\u2192text] latest gen"},
    {"id": "gpt-4.1-nano", "label": "GPT-4.1 Nano — [text+image\u2192text] fastest latest"},
    {"id": "gpt-4.1-mini", "label": "GPT-4.1 Mini — [text+image\u2192text] balanced latest"},
    # Image generation models
    {"id": "gpt-image-2", "label": "GPT Image 2 — [text+image\u2192image] state-of-the-art image gen"},
    {"id": "gpt-image-2-2026-04-21", "label": "GPT Image 2 (2026-04-21) — [text+image\u2192image] snapshot"},
    {"id": "dall-e-3", "label": "DALL-E 3 — [text\u2192image] previous gen"},
    {"id": "gpt-image-1.5", "label": "GPT Image 1.5 — [text+image\u2192image] previous gen"},
    # TTS models
    {"id": "gpt-4o-mini-tts", "label": "GPT-4o Mini TTS — [text\u2192audio] latest TTS"},
    {"id": "gpt-4o-mini-tts-2025-12-15", "label": "GPT-4o Mini TTS (2025-12-15) — [text\u2192audio] snapshot"},
    {"id": "tts-1", "label": "TTS-1 — [text\u2192audio] low-latency"},
    {"id": "tts-1-hd", "label": "TTS-1 HD — [text\u2192audio] high quality"},
    # Video generation models (Sora)
    {"id": "sora-2", "label": "Sora 2 — [text+image\u2192video] flagship video gen"},
    {"id": "sora-2-pro", "label": "Sora 2 Pro — [text+image\u2192video] high quality"},
    {"id": "sora-2-2025-12-08", "label": "Sora 2 (2025-12-08) — [text+image\u2192video] snapshot"},
    {"id": "sora-2-2025-10-06", "label": "Sora 2 (2025-10-06) — [text+image\u2192video] snapshot"},
]

_TEXT_MODELS = frozenset({
    "gpt-5.5", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-4o", "gpt-4o-mini",
    "o3", "o4-mini", "gpt-4.1", "gpt-4.1-nano", "gpt-4.1-mini",
})

_IMAGE_MODELS = frozenset({
    "gpt-image-2", "gpt-image-2-2026-04-21", "dall-e-3", "gpt-image-1.5",
})

_AUDIO_MODELS = frozenset({
    "gpt-4o-mini-tts", "gpt-4o-mini-tts-2025-12-15", "tts-1", "tts-1-hd",
})

_VIDEO_MODELS = frozenset({
    "sora-2", "sora-2-pro", "sora-2-2025-12-08", "sora-2-2025-10-06",
})


def get_client():
    """Create and return an OpenAI API client.

    Reads OPENAI_API_KEY from environment (via python-dotenv).
    Optionally reads OPENAI_BASE_URL for custom API endpoints (OpenAI-compatible).

    Returns:
        OpenAI: Configured OpenAI client.

    Raises:
        ValueError: If OPENAI_API_KEY is not set.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY not found. Create a .env file with:\n"
            "OPENAI_API_KEY=your_openai_api_key_here\n"
            "Get a key at: https://platform.openai.com/api-keys"
        )
    kwargs = {"api_key": api_key}
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


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
    """Build the user message content array, optionally including file attachments.

    Always returns a list of content parts for maximum API compatibility.

    Args:
        user_prompt: The user message text.
        files: Optional list of file paths (strings or Path objects).

    Returns:
        list: Content parts for the OpenAI user message.
    """
    parts = [{"type": "text", "text": user_prompt}]

    if files:
        for file_path in files:
            file_path = str(file_path)
            if file_path.lower().endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
            ):
                data_uri = _encode_image(file_path)
                parts.append(
                    {"type": "image_url", "image_url": {"url": data_uri}}
                )
            else:
                try:
                    with open(file_path, "rb") as f:
                        raw = f.read()
                    text_content = raw.decode("utf-8")
                    parts.append(
                        {
                            "type": "text",
                            "text": f"\n[Attached file: {Path(file_path).name}]\n```\n{text_content}\n```",
                        }
                    )
                except UnicodeDecodeError:
                    parts.append(
                        {
                            "type": "text",
                            "text": f"\n[Attached file: {Path(file_path).name} (binary, could not embed as text)]",
                        }
                    )

    return parts


def _convert_size(size):
    """Convert 'W*H' to 'WxH' for OpenAI format. Accept both."""
    if size and "*" in size:
        return size.replace("*", "x")
    return size


def _clamp_duration(duration):
    """Clamp int to nearest valid Sora seconds value [4, 8, 12, 16, 20].

    Midpoints between valid values:
      6  (boundary between 4 and 8)
     10  (boundary between 8 and 12)
     14  (boundary between 12 and 16)
     18  (boundary between 16 and 20)
    """
    if duration <= 6:
        return "4"
    if duration <= 10:
        return "8"
    if duration <= 14:
        return "12"
    if duration <= 18:
        return "16"
    return "20"


def _generate_text(client, system_prompt, user_prompt, model, temperature, files, log, t0):
    """Generate text via chat completions.

    Uses ``developer`` role for system prompt to match the o-series model
    convention. Files are embedded via ``_build_user_content`` as image_url
    or text parts.

    Returns:
        dict with keys: text, type, response_data, candidates.
    """
    messages = []
    if system_prompt:
        messages.append({"role": "developer", "content": system_prompt})
    user_content = _build_user_content(user_prompt, files)
    messages.append({"role": "user", "content": user_content})

    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
    except Exception as e:
        elapsed = time.time() - t0
        log.error(
            "OpenAI text FAILED | model=%s | elapsed=%.2fs | error=%s",
            model, elapsed, e,
        )
        raise RuntimeError(f"OpenAI text API call failed: {e}") from e

    elapsed = time.time() - t0

    # ── Safely extract response text ──────────────────────────────────────
    response_text = ""
    response_type = "text"
    response_data = ""
    finish_detail = ""

    if not response.choices:
        response_text = (
            "[API returned no choices \u2014 the model may have been filtered]"
        )
    else:
        choice = response.choices[0]
        message = choice.message
        finish_reason = getattr(choice, "finish_reason", None)

        # Check for safety refusal
        if hasattr(message, "refusal") and message.refusal:
            response_text = (
                f"[Content refused by model: {message.refusal}]"
            )

        # Standard text content (may be str or list from vision endpoints)
        elif message.content is not None:
            if isinstance(message.content, list):
                for part in message.content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        response_text = part.get("text", "")
                        break
                if not response_text:
                    response_text = str(message.content)
                for part in message.content:
                    if isinstance(part, dict):
                        ptype = part.get("type", "")
                        if ptype == "image_url" and "image_url" in part:
                            response_type = "image"
                            url_or_data = (
                                part["image_url"].get("url", "")
                                if isinstance(part["image_url"], dict)
                                else ""
                            )
                            if url_or_data:
                                response_data = url_or_data
                            break
            else:
                response_text = message.content
                if isinstance(response_text, str):
                    stripped = response_text.strip()
                    if stripped.startswith("data:image/"):
                        response_type = "image"
                        response_data = stripped
                    elif stripped.startswith("http") and any(
                        ext in stripped.lower()
                        for ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]
                    ):
                        response_type = "image"
                        response_data = stripped

        # Tool / function calls
        elif hasattr(message, "tool_calls") and message.tool_calls:
            response_text = (
                f"[Model returned {len(message.tool_calls)} tool call(s) "
                f"\u2014 not supported in this app]"
            )

        # Null content but successful response (image gen models that
        # returned content through chat completions)
        if not response_text and finish_reason == "stop":
            try:
                raw = response.model_dump()
                choice_raw = raw.get("choices", [{}])[0]
                msg_raw = choice_raw.get("message", {})
                img_url = (
                    msg_raw.get("image_url")
                    or msg_raw.get("data", {}).get("url")
                    or msg_raw.get("url")
                )
                if img_url:
                    response_text = (
                        f"[Generated image: {img_url[:80]}...]"
                    )
                    response_type = "image"
                    response_data = img_url
                else:
                    response_text = (
                        "[Model generated a response (non-text content)]"
                    )
                    log.debug(
                        "Null-content response dump:\n%s", raw,
                    )
            except Exception:
                response_text = (
                    "[Model returned a non-text response]"
                )

        # Finish-reason diagnostics
        if finish_reason == "content_filter":
            finish_detail = " (filtered by content moderation)"
            if not response_text:
                response_text = (
                    f"[Response filtered{finish_detail}]"
                )
        elif finish_reason == "length":
            finish_detail = " (truncated by token limit)"
            response_text = (response_text or "") + (
                "\n\n[Response truncated due to token limit]"
            )

    display_text = response_text + finish_detail

    log.info(
        "OpenAI text OK | model=%s | elapsed=%.2fs | "
        "response_len=%s | type=%s",
        model, elapsed, len(display_text), response_type,
    )
    log.debug("OpenAI text response:\n%s", display_text)

    return {
        "text": display_text,
        "type": response_type,
        "response_data": response_data,
        "candidates": getattr(response, "choices", []),
    }


def _generate_image(client, system_prompt, user_prompt, model, temperature, log, t0, **kwargs):
    """Generate an image via the Images API.

    Combines system_prompt and user_prompt into a single prompt string.
    Supports response_format=b64_json, quality, and size parameters.

    Returns:
        dict with keys: text, type="image", response_data (data URI), candidates.
    """
    combined = (
        f"{system_prompt}\n\n---\n\n{user_prompt}"
        if system_prompt
        else user_prompt
    )

    gen_kwargs = {
        "model": model,
        "prompt": combined,
        "n": 1,
        "response_format": "b64_json",
    }

    size = kwargs.get("size")
    if size:
        gen_kwargs["size"] = _convert_size(size)

    quality = kwargs.get("quality")
    if quality:
        gen_kwargs["quality"] = quality

    try:
        response = client.images.generate(**gen_kwargs)
    except Exception as e:
        elapsed = time.time() - t0
        log.error(
            "OpenAI image FAILED | model=%s | elapsed=%.2fs | error=%s",
            model, elapsed, e,
        )
        raise RuntimeError(f"OpenAI image generation failed: {e}") from e

    elapsed = time.time() - t0

    # Extract base64 image from response
    response_data = ""
    if response.data and len(response.data) > 0:
        img_data = response.data[0]
        if hasattr(img_data, "b64_json") and img_data.b64_json:
            response_data = f"data:image/png;base64,{img_data.b64_json}"
            display_text = "[Generated image]"
        elif hasattr(img_data, "url") and img_data.url:
            response_data = img_data.url
            display_text = f"[Generated image: {img_data.url[:80]}...]"
        else:
            display_text = "[Image generated but no data returned]"
    else:
        display_text = "[Image generation returned no data]"

    log.info(
        "OpenAI image OK | model=%s | elapsed=%.2fs | has_data=%s",
        model, elapsed, bool(response_data),
    )

    return {
        "text": display_text,
        "type": "image",
        "response_data": response_data,
        "candidates": getattr(response, "data", []),
    }


def _generate_audio(client, system_prompt, user_prompt, model, temperature, log, t0, **kwargs):
    """Generate speech audio via the TTS API.

    OpenAI TTS returns WAV format (response_format="wav"). The raw bytes
    are saved directly to ``uploads/tts_*.wav``.

    Note: tts-1 and tts-1-hd do NOT support the ``instructions`` parameter.

    Returns:
        dict with keys: text, type="audio", response_data (local file path), candidates.
    """
    voice = kwargs.get("voice", "alloy")
    instructions = kwargs.get("instructions")

    speech_kwargs = {
        "model": model,
        "input": user_prompt,
        "voice": voice,
        "response_format": "wav",
    }

    speed = kwargs.get("speed")
    if speed:
        speech_kwargs["speed"] = speed

    # tts-1 and tts-1-hd do NOT support instructions
    if instructions and model not in ("tts-1", "tts-1-hd"):
        speech_kwargs["instructions"] = instructions

    try:
        response = client.audio.speech.create(**speech_kwargs)
    except Exception as e:
        elapsed = time.time() - t0
        log.error(
            "OpenAI TTS FAILED | model=%s | elapsed=%.2fs | error=%s",
            model, elapsed, e,
        )
        raise RuntimeError(f"OpenAI TTS failed: {e}") from e

    elapsed = time.time() - t0

    # Save the WAV bytes to a local file
    from prompt_template.audio_utils import save_base64_audio

    raw_bytes = response.content
    if not raw_bytes:
        return {
            "text": "[TTS returned empty audio data]",
            "type": "text",
            "response_data": "",
            "candidates": {},
        }

    # Encode bytes as base64 and reuse save_base64_audio for consistency
    b64_str = base64.b64encode(raw_bytes).decode("utf-8")
    file_path = save_base64_audio(b64_str, "audio/wav")

    log.info(
        "OpenAI TTS OK | model=%s | elapsed=%.2fs | voice=%s | file=%s",
        model, elapsed, voice, file_path,
    )

    return {
        "text": user_prompt,
        "type": "audio",
        "response_data": file_path,
        "candidates": {"model": model, "voice": voice},
    }


def _generate_video(client, system_prompt, user_prompt, model, temperature, files, log, t0, **kwargs):
    """Generate a video via the Sora API (create_and_poll).

    Combines system_prompt and user_prompt. If an image file is provided,
    it is sent as an ``input_reference`` for image-to-video generation.
    Duration is clamped to the nearest valid Sora value.

    Uses ``client.videos.create_and_poll()`` (built-in sync polling) and
    ``client.videos.download_content()`` to retrieve the MP4.

    Returns:
        dict with keys: text, type="video", response_data (local file path), candidates.
    """
    combined = (
        f"{system_prompt}\n\n---\n\n{user_prompt}"
        if system_prompt
        else user_prompt
    )

    video_kwargs = {
        "model": model,
        "prompt": combined,
    }

    size = kwargs.get("size")
    if size:
        video_kwargs["size"] = _convert_size(size)

    duration = kwargs.get("duration", 5)
    video_kwargs["seconds"] = _clamp_duration(duration)

    # If files contain an image, use as input_reference
    if files:
        for fp in files:
            fp_str = str(fp)
            if fp_str.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                img_b64 = _encode_image(fp_str)
                video_kwargs["input_reference"] = {"image_url": img_b64}
                break

    try:
        video = client.videos.create_and_poll(**video_kwargs)
    except Exception as e:
        elapsed = time.time() - t0
        log.error(
            "OpenAI video FAILED | model=%s | elapsed=%.2fs | error=%s",
            model, elapsed, e,
        )
        raise RuntimeError(f"OpenAI video generation failed: {e}") from e

    elapsed = time.time() - t0

    # Check for failure
    status = getattr(video, "status", None)
    if status != "completed":
        error_msg = "Unknown error"
        if hasattr(video, "error") and video.error:
            error_msg = getattr(video.error, "message", None) or str(video.error)
        elif not status:
            error_msg = "No status returned"
        else:
            error_msg = f"Status: {status}"
        log.error(
            "OpenAI video not completed | model=%s | elapsed=%.2fs | status=%s",
            model, elapsed, status,
        )
        return {
            "text": f"[Video generation failed: {error_msg}]",
            "type": "text",
            "response_data": "",
            "candidates": video,
        }

    # Download MP4 content
    try:
        mp4_bytes = client.videos.download_content(video.id)
    except Exception as e:
        elapsed = time.time() - t0
        log.error(
            "OpenAI video download FAILED | model=%s | elapsed=%.2fs | error=%s",
            model, elapsed, e,
        )
        return {
            "text": f"[Video generated but download failed: {e}]",
            "type": "text",
            "response_data": "",
            "candidates": video,
        }

    # Save to uploads/video_{timestamp}_{uuid8}.mp4
    os.makedirs("uploads", exist_ok=True)
    timestamp = int(time.time() * 1000)
    suffix = uuid.uuid4().hex[:8]
    file_path = os.path.abspath(
        os.path.join("uploads", f"video_{timestamp}_{suffix}.mp4")
    )
    with open(file_path, "wb") as f:
        f.write(mp4_bytes)

    log.info(
        "OpenAI video OK | model=%s | elapsed=%.2fs | file=%s",
        model, elapsed, file_path,
    )

    return {
        "text": f"[Generated video: {file_path}]",
        "type": "video",
        "response_data": file_path,
        "candidates": video,
    }


def generate(system_prompt, user_prompt, model, temperature, files=None,
             size=None, duration=5, **kwargs):
    """Generate content using the OpenAI API.

    Routes to the correct API based on model frozenset membership:
      Text   → chat completions
      Image  → images.generate()
      Audio  → audio.speech.create() (TTS)
      Video  → videos.create_and_poll() (Sora)

    Args:
        system_prompt: System-level instruction for the model.
        user_prompt: User message text.
        model: Model ID string (from AVAILABLE_MODELS).
        temperature: Sampling temperature (0.0-2.0).
        files: Optional list of file paths (strings or Path objects).
        size: Output size (e.g. "1024x1024" or "1280*720"). Used for
              image and video generation.
        duration: Video duration in seconds. Only used for Sora video models.
                  Defaults to 5.
        **kwargs: Additional options forwarded to the specific handler.
            voice (str): Voice for TTS models (default "alloy").
            instructions (str): TTS instruction text (not supported by tts-1/tts-1-hd).
            speed (float): TTS speech speed.
            quality (str): Image quality ("standard" or "hd" for DALL-E 3).

    Returns:
        dict with keys:
            - text: Generated response text (or input text for TTS).
            - type: Response content type ("text", "image", "video", or "audio").
            - response_data: Data URI, URL, or local file path.
            - candidates: Raw response data from the API.

    Raises:
        ValueError: If OPENAI_API_KEY is not set.
        RuntimeError: If the API call fails.
    """
    client = get_client()

    log = get_api_logger()
    file_count = len(files) if files else 0
    log.info(
        "OpenAI generate() | model=%s | temp=%s | prompt_len=%s | files=%s",
        model, temperature, len(user_prompt), file_count,
    )

    t0 = time.time()

    try:
        if model in _VIDEO_MODELS:
            return _generate_video(
                client=client,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                temperature=temperature,
                files=files,
                log=log,
                t0=t0,
                size=size,
                duration=duration,
                **kwargs,
            )
        elif model in _AUDIO_MODELS:
            return _generate_audio(
                client=client,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                temperature=temperature,
                log=log,
                t0=t0,
                **kwargs,
            )
        elif model in _IMAGE_MODELS:
            return _generate_image(
                client=client,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                temperature=temperature,
                log=log,
                t0=t0,
                size=size,
                **kwargs,
            )
        else:
            return _generate_text(
                client=client,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                temperature=temperature,
                files=files,
                log=log,
                t0=t0,
            )
    except (ValueError, RuntimeError):
        raise
    except Exception as e:
        elapsed = time.time() - t0
        log.error(
            "OpenAI generate() FAILED | model=%s | elapsed=%.2fs | error=%s",
            model, elapsed, e,
        )
        raise RuntimeError(f"OpenAI API call failed: {e}") from e

"""Gemini API client wrapper for prompt-template.

Provides:
- get_client(): Returns a configured genai.Client
- AVAILABLE_MODELS: List of supported Gemini models
- generate(): Generate content with text, image, and file inputs
"""
import base64
import mimetypes
import os
import sys
import time
from pathlib import Path

import dotenv
from PIL import Image
from google import genai
from google.genai import types

from prompt_template.logger import get_api_logger

# Maximum time to wait for Veo video generation (in seconds)
_VEO_POLL_TIMEOUT = 600
# Poll interval for Veo video generation (in seconds)
_VEO_POLL_INTERVAL = 10

dotenv.load_dotenv()

AVAILABLE_MODELS = [
    # Stable production models [text+image+audio+video→text]
    {"id": "gemini-2.5-pro",       "label": "Gemini 2.5 Pro — [text+image+audio+video→text] most advanced, complex reasoning"},
    {"id": "gemini-2.5-flash",     "label": "Gemini 2.5 Flash — [text+image+audio+video→text] best price-performance"},
    {"id": "gemini-2.5-flash-lite","label": "Gemini 2.5 Flash-Lite — [text+image+audio+video→text] fastest, cheapest"},
    {"id": "gemini-3.1-flash-lite","label": "Gemini 3.1 Flash-Lite — [text+image+audio+video→text] next-gen budget"},
    # Preview models
    {"id": "gemini-3.1-flash-image-preview", "label": "gemini-3.1-flash-image-preview — [text+image→text+image] image gen"},
    {"id": "gemini-2.5-flash-image", "label": "gemini-2.5-flash-image — [text+image→text+image] image gen"},
    {"id": "gemini-3.1-flash-tts-preview", "label": "Gemini 3.1 Flash TTS Preview — [text→audio] TTS"},
    {"id": "gemini-3.1-pro-preview","label": "Gemini 3.1 Pro Preview — [text+image+audio+video→text] advanced reasoning"},
    {"id": "gemini-3-flash-preview","label": "Gemini 3 Flash Preview — [text+image+audio+video→text] frontier performance"},
    # Video generation — Veo models (long-running async, sync polling wrapper)
    {"id": "veo-3.1-generate-preview",      "label": "Veo 3.1 — [text+image→video] highest quality"},
    {"id": "veo-3.1-lite-generate-preview", "label": "Veo 3.1 Lite — [text+image→video] fast, efficient"},
    {"id": "veo-2.0-generate-001",          "label": "Veo 2.0 — [text+image→video] previous gen"},
]

# Models that generate images (require response_modalities config)
_IMAGE_MODELS = frozenset({
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview",
})

# Models that generate video via Veo API (client.models.generate_videos, async polling)
_VIDEO_MODELS = frozenset({
    "veo-3.1-generate-preview",
    "veo-3.1-lite-generate-preview",
    "veo-2.0-generate-001",
})

# Models that generate audio via TTS (response_modalities=["AUDIO"])
_AUDIO_MODELS = frozenset({
    "gemini-3.1-flash-tts-preview",
})


def get_client():
    """Create and return a Gemini API client.

    Reads GEMINI_API_KEY from environment (via python-dotenv).

    Returns:
        genai.Client: Configured Gemini client.

    Raises:
        ValueError: If GEMINI_API_KEY is not set.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY not found. Create a .env file with:\n"
            "GEMINI_API_KEY=your_gemini_api_key_here\n"
            "Get a key at: https://aistudio.google.com/apikey"
        )
    return genai.Client(api_key=api_key)


def _generate_video(client, system_prompt, user_prompt, model, files, log, t0,
                    size=None, duration=5):
    """Generate video using Veo API (long-running async with sync polling).

    Calls client.models.generate_videos() and polls until completion
    or timeout. Returns the same dict shape as generate().
    """
    combined = (
        f"{system_prompt}\n\n---\n\n{user_prompt}"
        if system_prompt
        else user_prompt
    )

    # Build the source — optionally include an image
    source_kwargs = {"prompt": combined}
    if files:
        for file_path in files:
            file_path = str(file_path)
            if file_path.lower().endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
            ):
                img = Image.open(file_path)
                source_kwargs["image"] = types.Image(
                    image_bytes=img.tobytes(),
                    mime_type=f"image/{img.format.lower()}" if img.format else "image/png",
                )
                break

    source = types.GenerateVideosSource(**source_kwargs)
    config = types.GenerateVideosConfig(
        duration_seconds=duration,
        aspect_ratio="16:9",
    )

    try:
        operation = client.models.generate_videos(
            model=model,
            source=source,
            config=config,
        )
    except Exception as e:
        elapsed = time.time() - t0
        log.error(
            "Veo generate_videos() FAILED | model=%s | elapsed=%.2fs | error=%s",
            model, elapsed, e,
        )
        raise RuntimeError(f"Veo video generation failed: {e}") from e

    # Poll until done or timeout
    deadline = time.time() + _VEO_POLL_TIMEOUT
    while not operation.done and time.time() < deadline:
        time.sleep(_VEO_POLL_INTERVAL)
        try:
            operation = client.operations.get(operation)
        except Exception as e:
            elapsed = time.time() - t0
            log.error(
                "Veo poll() FAILED | model=%s | elapsed=%.2fs | error=%s",
                model, elapsed, e,
            )
            raise RuntimeError(f"Veo polling failed: {e}") from e

    elapsed = time.time() - t0

    if not operation.done:
        log.error(
            "Veo timeout | model=%s | elapsed=%.2fs", model, elapsed,
        )
        return {
            "text": f"[Video generation timed out after {_VEO_POLL_TIMEOUT}s]",
            "type": "text",
            "response_data": "",
            "candidates": {},
        }

    if operation.error:
        error_msg = operation.error.message or str(operation.error)
        log.error(
            "Veo failed | model=%s | elapsed=%.2fs | error=%s",
            model, elapsed, error_msg,
        )
        return {
            "text": f"[Video generation failed: {error_msg}]",
            "type": "text",
            "response_data": "",
            "candidates": {},
        }

    # Success — extract video URL/data
    result = operation.result
    if not result.generated_videos:
        return {
            "text": "[Video generation returned no videos]",
            "type": "text",
            "response_data": "",
            "candidates": result,
        }

    video = result.generated_videos[0].video
    video_url = video.uri or ""
    response_data = video_url
    text_display = f"[Generated video: {video_url[:80]}...]" if video_url else "[Generated video]"

    # Prefer inline video bytes as data URI when available
    if video.video_bytes:
        mime = video.mime_type or "video/mp4"
        b64 = base64.b64encode(video.video_bytes).decode("utf-8")
        response_data = f"data:{mime};base64,{b64}"

    log.info(
        "Veo generate_videos() OK | model=%s | elapsed=%.2fs | video_url=%s",
        model, elapsed, video_url[:80] if video_url else "N/A",
    )

    return {
        "text": text_display,
        "type": "video",
        "response_data": response_data,
        "candidates": result,
    }


def generate(system_prompt, user_prompt, model, temperature, files=None,
             size=None, duration=5, **kwargs):
    """Generate content using the Gemini API.

    Supports text prompts, image uploads (via PIL), arbitrary file types
    (via bytes with MIME type detection), and TTS (audio output).

    Args:
        system_prompt: System-level instruction for the model.
        user_prompt: User message text.
        model: Model ID string (from AVAILABLE_MODELS).
        temperature: Sampling temperature (0.0-2.0).
        files: Optional list of file paths (strings or Path objects).
        size: Not used by Gemini/Veo (for interface consistency with DashScope).
        duration: Video duration in seconds. Only used for video models.
                  Defaults to 5.
        **kwargs: Additional options.
            voice_name (str): Voice name for TTS models (default "Puck").

    Returns:
        dict with keys:
            - text: Generated response text (or input text for TTS).
            - type: Response content type ("text", "image", "video", or "audio").
            - response_data: MIME type for image/video, saved file path for audio.
            - candidates: Raw response candidates from the API.

    Raises:
        ValueError: If GEMINI_API_KEY is not set.
        RuntimeError: If the API call fails.
    """
    client = get_client()

    log = get_api_logger()
    file_count = len(files) if files else 0
    log.info(
        "Gemini generate() | model=%s | temp=%s | prompt_len=%s | files=%s",
        model, temperature, len(user_prompt), file_count,
    )

    is_video = model in _VIDEO_MODELS
    is_tts = model in _AUDIO_MODELS

    t0 = time.time()

    # ── Veo video generation path (separate async API with polling) ────────
    if is_video:
        return _generate_video(
            client=client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            files=files,
            log=log,
            t0=t0,
            size=size,
            duration=duration,
        )

    # ── Standard Gemini generate_content path ──────────────────────────────
    # Build contents as a flat list — SDK auto-wraps into Content/Part objects.
    contents = [user_prompt]

    if files:
        for file_path in files:
            file_path = str(file_path)
            if file_path.lower().endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
            ):
                img = Image.open(file_path)
                contents.append(img)
            else:
                mime_type, _ = mimetypes.guess_type(file_path)
                if not mime_type:
                    mime_type = "application/octet-stream"
                with open(file_path, "rb") as f:
                    contents.append(
                        types.Part.from_bytes(
                            data=f.read(),
                            mime_type=mime_type,
                        )
                    )

    try:
        config_kwargs = {
            "system_instruction": system_prompt,
            "temperature": temperature,
        }
        if model in _IMAGE_MODELS:
            config_kwargs["response_modalities"] = ["TEXT", "IMAGE"]
        if is_tts:
            voice_name = kwargs.get("voice_name", "Puck")
            config_kwargs["response_modalities"] = ["AUDIO"]
            config_kwargs["speech_config"] = types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            )

        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
    except Exception as e:
        elapsed = time.time() - t0
        log.error(
            "Gemini generate() FAILED | model=%s | elapsed=%.2fs | error=%s",
            model, elapsed, e,
        )
        raise RuntimeError(f"Gemini API call failed: {e}") from e

    elapsed = time.time() - t0

    # ── Safely extract response text ──────────────────────────────────────
    response_text = ""
    block_reason = None
    try:
        response_text = response.text
    except (ValueError, AttributeError):
        if response.prompt_feedback:
            block_reason = response.prompt_feedback.block_reason
        if response.candidates:
            for candidate in response.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, "text") and part.text:
                            response_text = part.text
                            break
                    if response_text:
                        break

    if block_reason and not response_text:
        response_text = f"[Response blocked: {block_reason}]"

    # ── Detect response type (text / image / video / audio) ───────────────
    response_type = "text"
    response_data = ""

    if response.candidates:
        for candidate in response.candidates:
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if part.inline_data and part.inline_data.mime_type:
                        mt = part.inline_data.mime_type
                        if mt.startswith("image/"):
                            response_type = "image"
                            raw = part.inline_data.data
                            if isinstance(raw, bytes):
                                b64 = base64.b64encode(raw).decode("utf-8")
                                response_data = f"data:{mt};base64,{b64}"
                            else:
                                response_data = str(mt)
                            break
                        elif mt.startswith("video/"):
                            response_type = "video"
                            raw = part.inline_data.data
                            if isinstance(raw, bytes):
                                b64 = base64.b64encode(raw).decode("utf-8")
                                response_data = f"data:{mt};base64,{b64}"
                            else:
                                response_data = str(mt)
                            break
                        elif mt.startswith("audio/"):
                            response_type = "audio"
                            raw = part.inline_data.data
                            if isinstance(raw, bytes):
                                from prompt_template.audio_utils import save_pcm_as_wav
                                response_data = save_pcm_as_wav(raw)
                            else:
                                response_data = str(mt)
                            break
                if response_type != "text":
                    break

    # For TTS models, use the input prompt as the transcript if no text returned
    if is_tts and not response_text:
        response_text = user_prompt

    log.info(
        "Gemini generate() OK | model=%s | elapsed=%.2fs | "
        "response_len=%s | type=%s",
        model, elapsed, len(response_text), response_type,
    )
    log.debug("Gemini full response:\n%s", response_text)

    return {
        "text": response_text,
        "type": response_type,
        "response_data": response_data,
        "candidates": response.candidates,
    }

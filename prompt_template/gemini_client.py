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

dotenv.load_dotenv()

AVAILABLE_MODELS = [
    # Stable production models
    {"id": "gemini-2.5-pro",       "label": "Gemini 2.5 Pro — most advanced, complex reasoning (Stable)"},
    {"id": "gemini-2.5-flash",     "label": "Gemini 2.5 Flash — best price-performance (Stable)"},
    {"id": "gemini-2.5-flash-lite","label": "Gemini 2.5 Flash-Lite — fastest, cheapest (Stable)"},
    {"id": "gemini-3.1-flash-lite","label": "Gemini 3.1 Flash-Lite — next-gen budget (Stable)"},
    # Preview models
    {"id": "gemini-3.1-flash-image-preview", "label": "gemini-3.1-flash-image-preview"},
    {"id": "gemini-2.5-flash-image", "label": "gemini-2.5-flash-image"},
    {"id": "gemini-3.1-flash-tts-preview", "label": "gemini-3.1-flash-tts-preview"},
    {"id": "gemini-3.1-pro-preview","label": "Gemini 3.1 Pro Preview — next-gen advanced reasoning"},
    {"id": "gemini-3-flash-preview","label": "Gemini 3 Flash Preview — next-gen frontier performance"},
]

# Models that generate images (require response_modalities config)
_IMAGE_MODELS = frozenset({
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview",
})


def get_client():
    """Create and return a Gemini API client.

    Reads API_KEY from environment (via python-dotenv).

    Returns:
        genai.Client: Configured Gemini client.

    Raises:
        ValueError: If API_KEY is not set.
    """
    api_key = os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError(
            "API_KEY / GEMINI_API_KEY not found. Create a .env file with:\n"
            "GEMINI_API_KEY=your_api_key_here\n"
            "Get a key at: https://aistudio.google.com/apikey"
        )
    return genai.Client(api_key=api_key)


def generate(system_prompt, user_prompt, model, temperature, files=None):
    """Generate content using the Gemini API.

    Supports text prompts, image uploads (via PIL), and arbitrary file types
    (via bytes with MIME type detection).

    Args:
        system_prompt: System-level instruction for the model.
        user_prompt: User message text.
        model: Model ID string (from AVAILABLE_MODELS).
        temperature: Sampling temperature (0.0-2.0).
        files: Optional list of file paths (strings or Path objects).

    Returns:
        dict with keys:
            - text: Generated response text.
            - type: Response content type ("text", "image", or "video").
            - response_data: MIME type if image/video, else "".
            - candidates: Raw response candidates from the API.

    Raises:
        ValueError: If API_KEY is not set.
        RuntimeError: If the API call fails.
    """
    client = get_client()

    # Build contents as a flat list — SDK auto-wraps into Content/Part objects.
    # Do NOT manually construct types.Content() — that requires strict Part types.
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

    log = get_api_logger()
    file_count = len(files) if files else 0
    log.info(
        "Gemini generate() | model=%s | temp=%s | prompt_len=%s | files=%s",
        model, temperature, len(user_prompt), file_count,
    )

    t0 = time.time()
    try:
        config_kwargs = {
            "system_instruction": system_prompt,
            "temperature": temperature,
        }
        if model in _IMAGE_MODELS:
            config_kwargs["response_modalities"] = ["TEXT", "IMAGE"]

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
    # response.text raises ValueError if content was blocked by safety filters.
    # Fall back to extracting text from the first available part.
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
                            response_data = mt
                            break
                        elif mt.startswith("audio/"):
                            response_type = "audio"
                            response_data = mt
                            break
                if response_type != "text":
                    break

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

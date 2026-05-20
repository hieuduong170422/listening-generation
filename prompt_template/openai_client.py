"""OpenAI API client wrapper for prompt-template.

Provides:
- get_client(): Returns a configured OpenAI client
- AVAILABLE_MODELS: List of supported OpenAI models
- generate(): Generate content with text and image inputs
"""

import base64
import mimetypes
import os
import time
from pathlib import Path

import dotenv
from openai import OpenAI

from prompt_template.logger import get_api_logger

dotenv.load_dotenv()

AVAILABLE_MODELS = [
    {"id": "qwen-image-2.0", "label": "qwen-image-2.0"},
]


def get_client():
    """Create and return an OpenAI API client.

    Reads API_KEY from environment (via python-dotenv).
    Optionally reads BASE_URL for custom API endpoints (OpenAI-compatible).

    Returns:
        OpenAI: Configured OpenAI client.

    Raises:
        ValueError: If API_KEY is not set.
    """
    api_key = os.getenv("API_KEY")
    if not api_key:
        raise ValueError(
            "API_KEY not found. Create a .env file with:\n"
            "API_KEY=your_api_key_here\n"
            "Get a key at: https://platform.openai.com/api-keys"
        )
    kwargs = {"api_key": api_key}
    base_url = os.getenv("BASE_URL")
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


def generate(system_prompt, user_prompt, model, temperature, files=None):
    """Generate content using the OpenAI API.

    Supports text prompts, image uploads (via base64 data URIs), and
    text file attachments.

    Args:
        system_prompt: System-level instruction for the model.
        user_prompt: User message text.
        model: Model ID string (from AVAILABLE_MODELS).
        temperature: Sampling temperature (0.0-2.0).
        files: Optional list of file paths (strings or Path objects).

    Returns:
        dict with keys:
            - text: Generated response text.
            - type: Response content type (always "text" for OpenAI).
            - response_data: Empty string (OpenAI returns text only).
            - candidates: Raw response choices from the API.

    Raises:
        ValueError: If API_KEY is not set.
        RuntimeError: If the API call fails.
    """
    client = get_client()

    # Merge system prompt into user message for maximum compatibility.
    # Many OpenAI-compatible endpoints reject the "system" role.
    combined_text = (
        f"{system_prompt}\n\n---\n\n{user_prompt}"
        if system_prompt
        else user_prompt
    )
    messages = [
        {"role": "user", "content": _build_user_content(combined_text, files)},
    ]

    log = get_api_logger()
    file_count = len(files) if files else 0
    log.info(
        "OpenAI generate() | model=%s | temp=%s | prompt_len=%s | files=%s",
        model, temperature, len(user_prompt), file_count,
    )

    t0 = time.time()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
    except Exception as e:
        elapsed = time.time() - t0
        log.error(
            "OpenAI generate() FAILED | model=%s | elapsed=%.2fs | error=%s",
            model, elapsed, e,
        )
        raise RuntimeError(f"OpenAI API call failed: {e}") from e

    elapsed = time.time() - t0

    # ── Safely extract response text ──────────────────────────────────────
    # Handle: empty choices, refusals, null content, tool calls, filters.
    response_text = ""
    response_type = "text"
    response_data = ""
    finish_detail = ""

    if not response.choices:
        response_text = (
            "[API returned no choices — the model may have been filtered]"
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

        # Standard text content (may be str or list from image/vision endpoints)
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
                f"— not supported in this app]"
            )

        # ── Null content but successful response ──────────────────────────
        # Image-generation models (e.g. qwen-image-2.0) may return null
        # content with the generated image in other response fields.
        if not response_text and finish_reason == "stop":
            try:
                raw = response.model_dump()
                choice_raw = raw.get("choices", [{}])[0]
                msg_raw = choice_raw.get("message", {})
                # Some APIs put the image URL in a custom field
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
                        "[Model generated a response "
                        "(non-text content)]"
                    )
                    log.debug(
                        "Null-content response dump:\n%s", raw
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
        "OpenAI generate() OK | model=%s | elapsed=%.2fs | "
        "response_len=%s | type=%s",
        model, elapsed, len(display_text), response_type,
    )
    log.debug("OpenAI full response:\n%s", display_text)

    return {
        "text": display_text,
        "type": response_type,
        "response_data": response_data,
        "candidates": getattr(response, "choices", []),
    }

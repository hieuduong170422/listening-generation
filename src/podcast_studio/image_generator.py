from __future__ import annotations

from pathlib import Path

from google import genai
from google.genai import types

from podcast_studio.api_utils import call_with_retry, track_response

IMAGE_MODEL = "gemini-2.5-flash-image"


def build_image_prompt(topic: str, part_title: str, part_summary: str) -> str:
    return (
        "Create a clean, modern 16:9 widescreen illustration to use as the background "
        "of a YouTube video for an English-learning podcast.\n"
        f"Overall topic: {topic}\n"
        f"This section: {part_title} — {part_summary}\n"
        "Style: warm, friendly, minimal, soft colors, podcast-cover aesthetic. "
        "NO text, NO words, NO letters anywhere in the image. "
        "Simple, not cluttered, pleasant to look at for a few minutes."
    )


def _extract_image_bytes(response) -> bytes:
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for p in parts:
            inline = getattr(p, "inline_data", None)
            if inline and getattr(inline, "data", None):
                return inline.data
    raise RuntimeError("Model không trả về ảnh — thử lại hoặc đổi prompt.")


def generate_part_image(
    client: genai.Client,
    topic: str,
    part_title: str,
    part_summary: str,
    out_path: Path,
    usage_store: list | None = None,
) -> Path:
    prompt = build_image_prompt(topic, part_title, part_summary)
    response = call_with_retry(
        client.models.generate_content,
        model=IMAGE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
    )
    track_response(usage_store, response, "image")
    data = _extract_image_bytes(response)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    return out_path

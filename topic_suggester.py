from __future__ import annotations

import json
import re

from google import genai
from google.genai import types

from api_utils import call_with_retry, track_response
from config import AUDIENCE_LEVELS, DEFAULT_AUDIENCE, DEFAULT_LANGUAGE, LANGUAGES, TEXT_MODEL

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


def _parse_topics(raw: str) -> list[str]:
    candidates: list[str] = [raw]
    match = _JSON_BLOCK_RE.search(raw)
    if match:
        candidates.append(match.group(1))
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(raw[start : end + 1])

    for c in candidates:
        try:
            data = json.loads(c)
            items = data.get("topics", []) if isinstance(data, dict) else []
            cleaned = [str(t).strip() for t in items if str(t).strip()]
            if cleaned:
                return cleaned
        except Exception:
            continue
    return []


def suggest_topics(
    client: genai.Client,
    audience_level: str = DEFAULT_AUDIENCE,
    count: int = 8,
    text_model: str = TEXT_MODEL,
    seed_hint: str = "",
    tone: str = "",
    language: str = DEFAULT_LANGUAGE,
    usage_store: list | None = None,
) -> list[str]:
    audience_desc = AUDIENCE_LEVELS.get(audience_level, AUDIENCE_LEVELS[DEFAULT_AUDIENCE])
    lang = LANGUAGES.get(language, LANGUAGES[DEFAULT_LANGUAGE])
    seed_block = (
        f"\nUSER HINT (steer toward this if useful): {seed_hint}\n" if seed_hint.strip() else ""
    )
    tone_block = f"\nDesired tone of the show: {tone}\n" if tone.strip() else ""
    prompt = (
        f"Suggest fresh, engaging podcast topics for a long-form {lang['label']}-listening series "
        f"(20-30 minute episodes between two hosts) aimed at learners of {lang['label']}.\n"
        f"Audience: {audience_desc}\n"
        f"{tone_block}"
        f"{seed_block}"
        "\nGuidelines:\n"
        f"- Practical and useful for learners of {lang['label']}.\n"
        "- Generates natural 2-way conversation (avoid pure how-to or list articles).\n"
        "- Mix everyday life, career, communication skills, culture, self-improvement, "
        "learning psychology, real-world scenarios.\n"
        "- Vary the angle: no two suggestions should feel like the same idea reworded.\n"
        f"- Each topic title MUST be written in {lang['label']} ({lang['native']}), under ~12 words.\n"
        "- Be specific and intriguing — no generic \"Improve your X\" titles.\n\n"
        f'Return ONLY valid JSON: {{"topics": ["...", "..."]}} with EXACTLY {count} items, '
        f"each in {lang['label']}."
    )

    response = call_with_retry(
        client.models.generate_content,
        model=text_model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    track_response(usage_store, response, "text")
    raw = (response.text or "").strip()
    topics = _parse_topics(raw)
    if not topics:
        raise ValueError(f"Không parse được topic suggestions. Raw:\n{raw[:500]}")
    return topics

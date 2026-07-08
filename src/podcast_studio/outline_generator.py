from __future__ import annotations

import json
import re
from dataclasses import dataclass
from google import genai
from google.genai import types

from podcast_studio.api_utils import call_with_retry, track_response
from podcast_studio.config import (
    AUDIENCE_LEVELS,
    DEFAULT_AUDIENCE,
    DEFAULT_LANGUAGE,
    DEFAULT_TONE,
    LANGUAGES,
    TEXT_MODEL,
    TONES,
)


@dataclass(frozen=True)
class PartBrief:
    index: int
    title: str
    summary: str
    key_points: tuple[str, ...]


@dataclass(frozen=True)
class Outline:
    topic: str
    total_minutes: int
    parts: tuple[PartBrief, ...]

    def to_readable(self) -> str:
        lines = [f"Topic: {self.topic}", f"Total: ~{self.total_minutes} min", ""]
        for p in self.parts:
            lines.append(f"Part {p.index}: {p.title}")
            lines.append(f"  Summary: {p.summary}")
            for kp in p.key_points:
                lines.append(f"  - {kp}")
            lines.append("")
        return "\n".join(lines)


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _extract_json(raw: str) -> str:
    match = _JSON_BLOCK_RE.search(raw)
    if match:
        return match.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Không tìm được JSON trong phản hồi outline.")
    return raw[start : end + 1]


def _normalize_quotes(s: str) -> str:
    return (
        s.replace("“", '"').replace("”", '"')
         .replace("‘", "'").replace("’", "'")
    )


def _repair_truncated_json(s: str) -> str:
    """Đóng ngoặc còn thiếu khi Gemini cắt JSON giữa chừng."""
    s = s.rstrip()

    # Xóa string chưa đóng ở cuối (VD: "key": "abc)
    if re.search(r':\s*"[^"]*$', s):
        s = re.sub(r':\s*"[^"]*$', '', s)

    # Xóa key chưa có value ở cuối (VD: , "title")
    if re.search(r',\s*"[^"]*"\s*$', s):
        s = re.sub(r',\s*"[^"]*"\s*$', '', s)

    # Xóa trailing comma
    s = re.sub(r',\s*$', '', s.rstrip())

    # Đóng ngoặc còn thiếu theo stack
    stack = []
    in_str = False
    esc = False
    for ch in s:
        if esc:
            esc = False
            continue
        if ch == '\\' and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in '{[':
            stack.append('}' if ch == '{' else ']')
        elif ch in '}]' and stack:
            stack.pop()

    return s + ''.join(reversed(stack))


def _safe_load_json(raw: str) -> dict:
    attempts: list[str] = [raw]
    try:
        attempts.append(_extract_json(raw))
    except ValueError:
        pass
    attempts.append(_TRAILING_COMMA_RE.sub(r"\1", _normalize_quotes(raw)))
    if len(attempts) > 1:
        attempts.append(_TRAILING_COMMA_RE.sub(r"\1", _normalize_quotes(attempts[1])))
    # Fallback: thử repair JSON bị truncate
    attempts.append(_repair_truncated_json(raw))
    try:
        attempts.append(_repair_truncated_json(_extract_json(raw)))
    except ValueError:
        pass

    last_err: Exception | None = None
    for candidate in attempts:
        try:
            return json.loads(candidate)
        except Exception as e:
            last_err = e
    raise ValueError(
        f"Không parse được JSON outline. Raw đầu phản hồi:\n{raw[:600]}"
    ) from last_err


def generate_outline(
    client: genai.Client,
    topic: str,
    num_parts: int,
    minutes_per_part: int,
    text_model: str = TEXT_MODEL,
    audience_level: str = DEFAULT_AUDIENCE,
    tone: str = DEFAULT_TONE,
    continuous: bool = True,
    show_name: str = "",
    channel_name: str = "",
    language: str = DEFAULT_LANGUAGE,
    usage_store: list | None = None,
) -> Outline:
    total_minutes = num_parts * minutes_per_part
    audience_desc = AUDIENCE_LEVELS.get(audience_level, AUDIENCE_LEVELS[DEFAULT_AUDIENCE])
    tone_desc = TONES.get(tone, TONES[DEFAULT_TONE])
    lang = LANGUAGES.get(language, LANGUAGES[DEFAULT_LANGUAGE])
    continuity_note = (
        "This will be ONE continuous conversation between two hosts, split into parts only for production. "
        "Each part flows directly into the next — there is NO welcome/sign-off between parts. "
        "Design the parts so they form a single arc, not standalone episodes.\n\n"
        if continuous
        else "Each part may be a standalone episode with its own intro and outro.\n\n"
    )
    branding_note = ""
    if show_name or channel_name:
        bits = []
        if show_name:
            bits.append(f'show "{show_name}"')
        if channel_name:
            bits.append(f'YouTube channel "{channel_name}"')
        branding_note = f"This series belongs to the {' on '.join(bits)}.\n\n"
    prompt = (
        f"You are planning a long-form language-learning podcast for a YouTube series. "
        f"TARGET LANGUAGE: {lang['label']} — the final spoken dialogue will be in {lang['label']}. "
        "Plan the outline accordingly so each part is appropriate for that language and culture.\n"
        f"{branding_note}"
        f"Audience: {audience_desc}\n"
        f"Tone: {tone_desc}\n"
        f"Topic: {topic}\n"
        f"Total runtime: ~{total_minutes} minutes split into {num_parts} parts, "
        f"each part ~{minutes_per_part} minutes.\n\n"
        f"{continuity_note}"
        "Design an outline so each part covers a distinct sub-topic, building progressively "
        "from framing to deeper practical advice. The whole series should feel like a coherent journey, "
        "not repetitive.\n\n"
        "Return ONLY valid JSON. No markdown, no prose, no fences. Schema:\n"
        '{"parts":[{"title":"<short>","summary":"<1 sentence>","key_points":["<short>","<short>","<short>"]}]}\n'
        f'The "parts" array MUST have EXACTLY {num_parts} items.\n'
        'CONSTRAINTS to keep response short and valid:\n'
        '- "title": ≤10 words, no quotes inside.\n'
        '- "summary": exactly ONE sentence, ≤25 words.\n'
        '- "key_points": EXACTLY 3 bullets, each ≤12 words.\n'
        'Keep the entire JSON under 2000 characters. Do NOT use smart quotes or trailing commas.'
    )

    response = call_with_retry(
        client.models.generate_content,
        model=text_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=2048,
            temperature=0.7,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    track_response(usage_store, response, "text")
    raw = (response.text or "").strip()
    try:
        payload = _safe_load_json(raw)
    except ValueError as e:
        finish_reason = None
        try:
            finish_reason = response.candidates[0].finish_reason
        except Exception:
            pass
        hint = ""
        if finish_reason and "MAX_TOKENS" in str(finish_reason).upper():
            hint = " (Gemini cắt giữa chừng do max_output_tokens. Giảm num_parts hoặc thử lại.)"
        elif finish_reason:
            hint = f" (finish_reason={finish_reason})"
        raise ValueError(str(e) + hint) from e

    # Lọc bỏ các item không hợp lệ (thiếu title — thường do JSON bị truncate)
    items = [it for it in payload.get("parts", []) if it.get("title")]
    if len(items) < max(1, num_parts - 1):
        raise ValueError(
            f"Outline chỉ trả về {len(items)} part hợp lệ, mong đợi {num_parts}. Raw:\n{raw}"
        )

    parts = tuple(
        PartBrief(
            index=i + 1,
            title=str(item["title"]).strip(),
            summary=str(item.get("summary") or "").strip(),
            key_points=tuple(str(kp).strip() for kp in item.get("key_points", [])),
        )
        for i, item in enumerate(items)
    )
    return Outline(topic=topic, total_minutes=total_minutes, parts=parts)

import json
import re
from dataclasses import dataclass
from google import genai

from config import (
    AUDIENCE_LEVELS,
    DEFAULT_AUDIENCE,
    DEFAULT_TONE,
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


def _extract_json(raw: str) -> str:
    match = _JSON_BLOCK_RE.search(raw)
    if match:
        return match.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Không tìm được JSON trong phản hồi outline.")
    return raw[start : end + 1]


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
) -> Outline:
    total_minutes = num_parts * minutes_per_part
    audience_desc = AUDIENCE_LEVELS.get(audience_level, AUDIENCE_LEVELS[DEFAULT_AUDIENCE])
    tone_desc = TONES.get(tone, TONES[DEFAULT_TONE])
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
        "You are planning a long-form English-learning podcast for a YouTube series. "
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
        "Return ONLY valid JSON in this exact shape (no prose, no markdown fences):\n"
        "{\n"
        '  "parts": [\n'
        '    {"title": "...", "summary": "...", "key_points": ["...", "...", "..."]}\n'
        "  ]\n"
        "}\n"
        f'The "parts" array MUST have exactly {num_parts} items. '
        'Each "summary" is 1-2 sentences. Each "key_points" array has 3-5 short bullets.'
    )

    response = client.models.generate_content(model=text_model, contents=prompt)
    raw = (response.text or "").strip()
    payload = json.loads(_extract_json(raw))

    items = payload.get("parts", [])
    if len(items) != num_parts:
        raise ValueError(
            f"Outline trả về {len(items)} part, mong đợi {num_parts}. Raw:\n{raw}"
        )

    parts = tuple(
        PartBrief(
            index=i + 1,
            title=str(item["title"]).strip(),
            summary=str(item["summary"]).strip(),
            key_points=tuple(str(kp).strip() for kp in item.get("key_points", [])),
        )
        for i, item in enumerate(items)
    )
    return Outline(topic=topic, total_minutes=total_minutes, parts=parts)

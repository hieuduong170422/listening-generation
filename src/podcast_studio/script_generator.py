from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from google import genai

from podcast_studio.api_utils import call_with_retry, track_response
from podcast_studio.config import (
    AUDIENCE_LEVELS,
    DEFAULT_AUDIENCE,
    DEFAULT_LANGUAGE,
    DEFAULT_PACE,
    DEFAULT_TONE,
    LANGUAGES,
    SPEECH_PACES,
    STYLES,
    TEXT_MODEL,
    TONES,
)


@dataclass(frozen=True)
class DialogueLine:
    speaker: str
    text: str


@dataclass(frozen=True)
class Script:
    topic: str
    style: str
    lines: tuple[DialogueLine, ...]

    def to_tts_prompt(self, pace: str = DEFAULT_PACE) -> str:
        header = SPEECH_PACES.get(pace, SPEECH_PACES[DEFAULT_PACE]) + "\n"
        body = "\n".join(f"{line.speaker}: {line.text}" for line in self.lines)
        return header + body

    def to_readable(self) -> str:
        return "\n".join(f"{line.speaker}: {line.text}" for line in self.lines)


log = logging.getLogger(__name__)

# Chịu được các biến thể model hay trả về: "**Speaker1:**", "- Speaker 2:",
# "> Speaker1：" (full-width colon), "**Speaker1**: ..."
_LINE_RE = re.compile(
    r"^\s*[>#\-*_\s]*(?:Speaker|Host)\s*([1-9])\s*[*_]*\s*[:：]\s*[*_]*\s*(.*\S)\s*$",
    re.IGNORECASE,
)
_FENCE_RE = re.compile(r"^```[a-zA-Z0-9]*\s*$")


def _strip_fences(raw: str) -> str:
    return "\n".join(l for l in raw.splitlines() if not _FENCE_RE.match(l.strip()))


def _parse_by_names(text: str, speaker_names: tuple[str, ...]) -> list[DialogueLine]:
    """Fallback: model dùng tên host thật (vd "Linh:") thay vì SpeakerN."""
    name_to_speaker = {
        name.strip().lower(): f"Speaker{i + 1}"
        for i, name in enumerate(speaker_names)
        if name.strip()
    }
    if not name_to_speaker:
        return []
    alternation = "|".join(re.escape(n) for n in name_to_speaker)
    name_re = re.compile(
        rf"^\s*[>#\-*_\s]*({alternation})\s*[*_]*\s*[:：]\s*[*_]*\s*(.*\S)\s*$",
        re.IGNORECASE,
    )
    parsed: list[DialogueLine] = []
    for line in text.splitlines():
        match = name_re.match(line)
        if match:
            speaker = name_to_speaker[match.group(1).strip().lower()]
            parsed.append(DialogueLine(speaker=speaker, text=match.group(2).strip()))
    return parsed


def _parse_lines(
    raw: str, speaker_names: tuple[str, ...] = ()
) -> tuple[DialogueLine, ...]:
    text = _strip_fences(raw)
    parsed: list[DialogueLine] = []
    for line in text.splitlines():
        match = _LINE_RE.match(line)
        if not match:
            continue
        num, content = match.groups()
        parsed.append(DialogueLine(speaker=f"Speaker{num}", text=content.strip()))
    if not parsed and speaker_names:
        parsed = _parse_by_names(text, speaker_names)
    if not parsed:
        snippet = " ".join(raw.split())[:200]
        log.error("Script parse thất bại. Raw đầu phản hồi: %r", raw[:1000])
        raise ValueError(
            "Không parse được kịch bản — model không trả về định dạng SpeakerN. "
            f"Đầu phản hồi: {snippet!r}"
        )
    return tuple(parsed)


def parse_script_text(topic: str, style_key: str, raw_text: str) -> Script:
    lines = _parse_lines(raw_text)
    return Script(topic=topic, style=style_key, lines=lines)


def extract_tail_lines(raw_text: str, n: int = 6) -> tuple[str, ...]:
    try:
        lines = _parse_lines(raw_text)
    except ValueError:
        return ()
    tail = lines[-n:]
    return tuple(f"{l.speaker}: {l.text}" for l in tail)


def generate_script(client: genai.Client, topic: str, style_key: str, text_model: str = TEXT_MODEL) -> Script:
    if style_key not in STYLES:
        raise ValueError(f"Style không hợp lệ: {style_key}. Chọn 1 trong {list(STYLES)}")

    style = STYLES[style_key]
    prompt = (
        f"{style.instruction}\n\n"
        f"CHỦ ĐỀ: {topic}\n\n"
        "ĐỊNH DẠNG OUTPUT (BẮT BUỘC):\n"
        "Mỗi dòng bắt đầu bằng `Speaker1:` hoặc `Speaker2:` rồi đến nội dung thoại.\n"
        "KHÔNG thêm tiêu đề, KHÔNG thêm nhãn, KHÔNG markdown.\n"
        "VÍ DỤ:\n"
        "Speaker1: Chào mọi người, hôm nay chúng ta nói về...\n"
        "Speaker2: Đúng rồi, mình rất hào hứng với chủ đề này.\n"
    )

    response = call_with_retry(
        client.models.generate_content, model=text_model, contents=prompt
    )
    track_response(None, response, "text")
    raw = (response.text or "").strip()
    lines = _parse_lines(raw)
    return Script(topic=topic, style=style_key, lines=lines)


def generate_part_script(
    client: genai.Client,
    topic: str,
    style_key: str,
    part_index: int,
    total_parts: int,
    target_minutes: int,
    part_title: str,
    part_summary: str,
    key_points: tuple[str, ...],
    previous_part_titles: tuple[str, ...] = (),
    previous_tail_lines: tuple[str, ...] = (),
    text_model: str = TEXT_MODEL,
    audience_level: str = DEFAULT_AUDIENCE,
    tone: str = DEFAULT_TONE,
    continuous: bool = True,
    show_name: str = "",
    channel_name: str = "",
    num_speakers: int = 2,
    host_names: tuple[str, ...] = (),
    language: str = DEFAULT_LANGUAGE,
    usage_store: list | None = None,
) -> Script:
    if style_key not in STYLES:
        raise ValueError(f"Style không hợp lệ: {style_key}. Chọn 1 trong {list(STYLES)}")

    style = STYLES[style_key]
    # ~150 spoken words ≈ 1 minute of audio. Aim at the target, allow ±15%.
    target_words = target_minutes * 150
    min_words = round(target_words * 0.85)
    max_words = round(target_words * 1.15)
    target_lines_low = max(6, round(target_minutes * 9))
    target_lines_high = max(target_lines_low + 3, round(target_minutes * 14))

    bullets = "\n".join(f"- {kp}" for kp in key_points)
    prev_recap = (
        "\n".join(f"  Part {i + 1}: {t}" for i, t in enumerate(previous_part_titles))
        if previous_part_titles
        else "  (none — this is the opening part)"
    )

    audience_desc = AUDIENCE_LEVELS.get(audience_level, AUDIENCE_LEVELS[DEFAULT_AUDIENCE])
    tone_desc = TONES.get(tone, TONES[DEFAULT_TONE])
    lang = LANGUAGES.get(language, LANGUAGES[DEFAULT_LANGUAGE])
    language_label = lang["label"]
    language_instruction = lang["instruction"]

    is_first = part_index == 1
    is_last = part_index == total_parts

    if continuous:
        if is_first:
            intro_rule = (
                "This is the OPENING of the series. Open with ONE warm intro that welcomes the audience "
                "and hooks them on the OVERALL TOPIC (not just this sub-topic). Keep the intro short (2-3 turns)."
            )
            outro_rule = (
                "End MID-CONVERSATION transitioning naturally into the next sub-topic. "
                "Do NOT include any sign-off. Do NOT say 'see you next time', 'bye for now', "
                "'thanks for listening', or 'in the next part'. The conversation should feel like it just "
                "naturally continues — the listener should feel curious, not concluded."
            )
        elif is_last:
            intro_rule = (
                "Pick up the conversation directly as if no break happened. The very first line MUST sound "
                "like a natural next sentence after the previous tail lines provided. "
                "Do NOT say 'welcome back', 'glad you joined us', 'in this part', 'in our last part', "
                "'as we discussed before', or anything that resets the conversation. "
                "Do NOT re-introduce the hosts or the show."
            )
            outro_rule = (
                "This is the FINAL part. Close with ONE strong final takeaway covering the whole topic, "
                "and ONE friendly sign-off thanking the audience and inviting them to subscribe. "
                "Keep the sign-off short (2-3 turns)."
            )
        else:
            intro_rule = (
                "Pick up the conversation directly as if no break happened. The very first line MUST sound "
                "like a natural next sentence after the previous tail lines provided. "
                "Do NOT say 'welcome back', 'glad you joined us', 'in this part', 'in our last part', "
                "'as we discussed before', or anything that resets the conversation. "
                "Do NOT re-introduce the hosts or the show."
            )
            outro_rule = (
                "End MID-CONVERSATION transitioning naturally into the next sub-topic. "
                "Do NOT include any sign-off. Do NOT say 'see you next time', 'bye for now', "
                "'thanks for listening', or 'in the next part'. Conversation just keeps flowing."
            )
    else:
        intro_rule = (
            "Open with a warm welcome to the series and a quick hook for this whole topic."
            if is_first
            else "Open by briefly tying back to the previous part (1 sentence), then dive in."
        )
        outro_rule = (
            "Close with a strong final takeaway and a friendly sign-off thanking the audience."
            if is_last
            else f"Close with a 1-2 sentence recap of THIS part and a teaser for Part {part_index + 1}."
        )

    if continuous and previous_tail_lines:
        tail_block = (
            "THE PREVIOUS PART ENDED LIKE THIS (the conversation continues directly from the last line below — "
            "your VERY FIRST line must flow as a natural next response, NOT a greeting or recap):\n"
            + "\n".join(previous_tail_lines)
            + "\n"
        )
    elif continuous and not is_first:
        tail_block = (
            "(No verbatim tail provided. Still: the conversation is ongoing — start mid-flow as if responding "
            "to a previous remark. Do NOT greet, do NOT recap.)\n"
        )
    else:
        tail_block = ""

    continuity_banner = (
        "IMPORTANT — CONTINUITY MODE:\n"
        "This is ONE long continuous conversation split into multiple files for production reasons. "
        "Treat the whole thing as a single ~"
        f"{total_parts * target_minutes}-minute conversation. The listener will hear all parts "
        "back-to-back as one piece. Therefore:\n"
        "- Only Part 1 has an intro. Only the final part has a sign-off.\n"
        "- Middle parts must NOT greet, recap, sign-off, or tease. They are just the middle of one long talk.\n"
        if continuous else ""
    )

    n = max(1, min(num_speakers, 9))
    if n == 1:
        speakers_block = (
            "SPEAKERS: This is a SOLO MONOLOGUE. There is ONLY ONE host narrating directly to the audience. "
            "Every single line MUST start with `Speaker1:`. Do NOT use Speaker2, Speaker3, or any back-and-forth. "
            "Make it feel like a confident solo host explaining to listeners — no questions to a co-host, "
            "no 'what do you think?' Just a clean, engaging narration.\n\n"
        )
    else:
        names_listing = ""
        if host_names:
            named = [f"Speaker{i + 1} = {host_names[i]}" for i in range(min(n, len(host_names))) if host_names[i]]
            if named:
                names_listing = " (" + ", ".join(named) + ")"
        speakers_block = (
            f"SPEAKERS: This is a {n}-way conversation between {n} hosts: "
            + ", ".join(f"Speaker{i + 1}" for i in range(n))
            + f"{names_listing}. "
            "Every line must start with one of these prefixes. Distribute turns relatively evenly — "
            "no single host should dominate. Hosts react to each other naturally.\n\n"
        )

    branding_block = ""
    if show_name or channel_name:
        lines = ["BRANDING:"]
        if show_name:
            lines.append(f'- Show name: "{show_name}"')
        if channel_name:
            lines.append(f'- YouTube channel: "{channel_name}"')
        if is_first and show_name:
            lines.append(
                f'- In the very first opening line, welcome listeners to "{show_name}" by name '
                "(e.g. \"Welcome to {0}, I'm ...\"). Do this only once, only in this opening.".format(show_name)
            )
        if is_last and channel_name:
            lines.append(
                f'- In the final sign-off, thank listeners and invite them to subscribe to "{channel_name}" '
                "on YouTube. Do this only once, only at the very end."
            )
        if not is_first and not is_last:
            lines.append(
                "- This is a middle part: do NOT mention the show name or channel name. "
                "The audience already heard it in Part 1."
            )
        branding_block = "\n".join(lines) + "\n\n"

    prompt = (
        f"⚠️ TARGET LANGUAGE — HARD OVERRIDE: Every single dialogue line MUST be written in "
        f"{language_label}: {language_instruction}\n"
        "This overrides any other language hint mentioned elsewhere in this prompt.\n\n"
        f"{style.instruction}\n\n"
        f"AUDIENCE: {audience_desc}\n"
        f"TONE: {tone_desc}\n\n"
        f"{speakers_block}"
        f"{branding_block}"
        f"OVERALL TOPIC: {topic}\n"
        f"This is Part {part_index} of {total_parts}.\n\n"
        "LENGTH (IMPORTANT — HIT THE TARGET, DO NOT OVERSHOOT):\n"
        f"- Target audio length: ~{target_minutes} minute(s) of speech.\n"
        f"- TARGET word count: about {target_words} spoken words total.\n"
        f"- ACCEPTABLE RANGE: {min_words}–{max_words} words. Do NOT go above {max_words}.\n"
        f"- Aim for {target_lines_low}-{target_lines_high} dialogue turns total.\n"
        "- Count your words as you write. Stop once you have covered the key points within the word range — "
        "do NOT pad with filler, and do NOT cut the conversation off abruptly. End naturally near the target.\n"
        "- For very short targets (1-2 minutes) keep it tight: a quick intro, the key points, a quick close.\n\n"
        f"{continuity_banner}"
        f"PART {part_index} TITLE: {part_title}\n"
        f"PART SUMMARY: {part_summary}\n"
        "KEY POINTS this part MUST cover:\n"
        f"{bullets}\n\n"
        "CONTEXT — previous parts already covered:\n"
        f"{prev_recap}\n\n"
        f"{tail_block}"
        "STRUCTURE:\n"
        f"- {intro_rule}\n"
        "- For each key point: explain → give 2 concrete examples or sample phrases → react/banter → next point.\n"
        "- Keep turns short (1-3 sentences). Do not let one host monologue.\n"
        f"- {outro_rule}\n"
        "- Do NOT repeat material already covered in previous parts.\n\n"
        "NATURAL CONVERSATION CUES (IMPORTANT for audio realism):\n"
        "Sprinkle these to make the dialogue feel alive. Write them as actual SPOKEN words inside the line, "
        "NOT as stage directions in brackets/asterisks. The TTS will pronounce them naturally:\n"
        "- Laughter: 'Ha ha!', 'Haha, yeah.', 'Hehe.'\n"
        "- Thinking / pause: 'Hmm...', 'Uh...', 'Well...', 'Let me think...'\n"
        "- Surprise: 'Oh!', 'Wow.', 'Whoa, really?', 'No way.'\n"
        "- Agreement: 'Mm-hmm.', 'Right, right.', 'Yeah, exactly.'\n"
        "- Sigh / breath out: 'Phew.', 'Ahh.', 'Oof.'\n"
        "- Trailing thought: use '...' (three dots) for natural pauses inside or at end of a sentence.\n"
        "- Genuine reactions when the other host says something good or surprising.\n"
        "DO NOT use bracketed stage directions like (laughs), [sighs], *chuckles* — those get stripped and waste tokens.\n\n"
        "OUTPUT LANGUAGE (HARD RULE — REPEAT):\n"
        f"Every line MUST be 100% in {language_label}. Do NOT mix in any other language anywhere — "
        "not even greetings, names of concepts, or filler words. The host names provided are written "
        "for the speaker tag only; the spoken dialogue itself is in the target language.\n\n"
        "OUTPUT FORMAT (STRICT):\n"
        "Each line starts with `Speaker1:` or `Speaker2:` followed by the dialogue text in the target language.\n"
        "No headings, no labels, no markdown, no stage directions.\n"
    )

    response = call_with_retry(
        client.models.generate_content, model=text_model, contents=prompt
    )
    track_response(usage_store, response, "text")
    raw = (response.text or "").strip()
    try:
        lines = _parse_lines(raw, speaker_names=host_names)
    except ValueError:
        # Model trả sai định dạng — thử lại 1 lần với nhắc nhở nghiêm hơn
        log.warning(
            "Parse thất bại lần 1 (part %d), retry với nhắc định dạng", part_index
        )
        reminder = (
            "\n\nYOUR PREVIOUS ATTEMPT FAILED THE FORMAT CHECK. "
            "Output ONLY dialogue lines. Every single line MUST start with "
            "`Speaker1:` or `Speaker2:` (plain text, no bold, no markdown, "
            "no code fences, no headings). Nothing else."
        )
        response = call_with_retry(
            client.models.generate_content, model=text_model, contents=prompt + reminder
        )
        track_response(usage_store, response, "text")
        raw = (response.text or "").strip()
        lines = _parse_lines(raw, speaker_names=host_names)
    return Script(topic=f"{topic} — Part {part_index}: {part_title}", style=style_key, lines=lines)

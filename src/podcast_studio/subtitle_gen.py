"""Generate SRT subtitles from TTS-rendered audio using Gemini Audio.

We have BOTH the audio (ElevenLabs render) and the exact script that
produced it, so we use guided ASR: tell Gemini the full script and ask
it only to find each line's start/end timestamps in the audio. This
beats blind transcription on accuracy — there are zero word-level
errors because the text is already known.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from google import genai
from google.genai import types

log = logging.getLogger(__name__)

# Per Google docs, gemini-2.5-pro handles long audio with timestamps best.
_DEFAULT_MODEL = "gemini-2.5-pro"

_LINE_RE = re.compile(r"^\s*Speaker\s*([1-9])\s*[::]\s*(.+)$", re.IGNORECASE)


def _parse_script_lines(script_text: str) -> list[dict]:
    """Pull 'SpeakerN: text' rows out of the same format the TTS used."""
    out: list[dict] = []
    for line in script_text.splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        out.append({
            "speaker": f"Speaker{m.group(1)}",
            "text": m.group(2).strip(),
        })
    return out


def _seconds_to_srt_time(t: float) -> str:
    """`12.345` → `00:00:12,345` (SRT format)."""
    if t < 0:
        t = 0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms >= 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _lines_to_srt(items: list[dict]) -> str:
    """items = [{start, end, text}], all start/end in seconds (float)."""
    blocks = []
    for i, it in enumerate(items, start=1):
        blocks.append(
            f"{i}\n"
            f"{_seconds_to_srt_time(it['start'])} --> {_seconds_to_srt_time(it['end'])}\n"
            f"{it['text']}\n"
        )
    return "\n".join(blocks)


def _build_prompt(script_lines: list[dict]) -> str:
    script_block = "\n".join(
        f'{i + 1}. ({ln["speaker"]}) "{ln["text"]}"'
        for i, ln in enumerate(script_lines)
    )
    return (
        "You are an expert audio subtitle aligner.\n\n"
        "I am providing an audio recording and the EXACT script that was used "
        "to generate it via text-to-speech. Your job is to find the precise "
        "start and end timestamp (in seconds, as a float) of each script line "
        "within the audio.\n\n"
        "SCRIPT (numbered):\n"
        f"{script_block}\n\n"
        "Return ONLY a valid JSON array with one entry per script line in the "
        "same order. Each entry shape:\n"
        '  {"start": <float seconds>, "end": <float seconds>, "text": "<the line text without the speaker tag>"}\n\n'
        "Rules:\n"
        "- start/end are seconds from the beginning of the audio, e.g. 12.43.\n"
        "- The text field must match the script line text VERBATIM (do not paraphrase).\n"
        "- Cover the full audio with no gaps between consecutive lines (end of "
        "  line N ≈ start of line N+1).\n"
        "- No prose, no markdown fences, just the JSON array."
    )


def _parse_response_json(raw: str) -> list[dict]:
    raw = raw.strip()
    # Strip optional ```json fences.
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    # Take the first balanced [...] block.
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"Không tìm được JSON array trong response:\n{raw[:300]}")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("Response không phải JSON array")
    out: list[dict] = []
    for item in data:
        try:
            out.append({
                "start": float(item["start"]),
                "end": float(item["end"]),
                "text": str(item["text"]).strip(),
            })
        except (KeyError, ValueError, TypeError) as e:
            raise ValueError(f"Item sai format: {item} ({e})")
    return out


def generate_srt(
    audio_path: Path | str,
    script_text: str,
    output_path: Path | str | None = None,
    model: str = _DEFAULT_MODEL,
    api_key: str | None = None,
) -> Path:
    """Generate an .srt file aligned to the audio.

    Args:
        audio_path: TTS-rendered .wav / .mp3.
        script_text: Same script used to generate the audio (Speaker1: … / Speaker2: …).
        output_path: Where to write the .srt. Defaults to audio_path.with_suffix('.srt').
        model: Gemini model ID (defaults to gemini-2.5-pro for best audio).
        api_key: Override; otherwise reads GEMINI_API_KEY from env.

    Returns:
        Path to the saved .srt file.
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio không tồn tại: {audio_path}")
    if output_path is None:
        output_path = audio_path.with_suffix(".srt")
    output_path = Path(output_path)

    script_lines = _parse_script_lines(script_text)
    if not script_lines:
        raise ValueError(
            "Script không có dòng 'Speaker1:'/'Speaker2:' nào — không align được."
        )

    key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY chưa set — không gọi được Gemini Audio.")

    client = genai.Client(api_key=key, vertexai=False)

    log.info("subtitle_gen | audio=%s lines=%d model=%s", audio_path.name, len(script_lines), model)
    uploaded = client.files.upload(file=str(audio_path))

    # Wait for the file to be ACTIVE before we send the prompt (large files
    # take a few seconds to ingest).
    for _ in range(30):
        info = client.files.get(name=uploaded.name)
        state = getattr(info, "state", None)
        state_name = getattr(state, "name", str(state))
        if state_name == "ACTIVE":
            break
        if state_name == "FAILED":
            raise RuntimeError("Gemini không xử lý được file audio (FAILED).")
        time.sleep(1)

    prompt = _build_prompt(script_lines)
    response = client.models.generate_content(
        model=model,
        contents=[uploaded, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
        ),
    )

    try:
        client.files.delete(name=uploaded.name)
    except Exception:
        pass

    raw = (response.text or "").strip()
    items = _parse_response_json(raw)

    # Sanity guard: if Gemini returned a wildly different count, fall back to
    # the script lines we know about.
    if len(items) != len(script_lines):
        log.warning(
            "subtitle_gen | Gemini trả %d items, script có %d — align theo cái nhỏ hơn",
            len(items), len(script_lines),
        )

    srt = _lines_to_srt(items)
    output_path.write_text(srt, encoding="utf-8")
    return output_path

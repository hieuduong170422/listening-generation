"""Unified podcast generation — Script (Gemini) → Audio (ElevenLabs) → Subtitles (Whisper).

Single pipeline thay cho việc chuyển đi chuyển lại các tab/service.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from google import genai

from podcast_studio.config import DEFAULT_AUDIENCE, DEFAULT_TONE
from podcast_studio.elevenlabs_tts import render_multi_speaker, render_single_voice
from podcast_studio.multi_part import (
    PartResult,
    _write_outline,
    _write_part_transcript,
)
from podcast_studio.outline_generator import Outline, generate_outline
from podcast_studio.script_generator import Script, generate_part_script
from podcast_studio.tts_settings import get_elevenlabs_config
from podcast_studio.whisper_transcribe import transcribe, transcript_to_srt, write_json_outputs


@dataclass(frozen=True)
class UnifiedPodcastResult:
    """Kết quả tạo podcast: tất cả part + outline + đã có subtitle hay chưa."""

    outline: Outline
    parts: tuple[PartResult, ...]
    outline_path: Path
    has_subtitles: bool


def run_unified_podcast(
    client: genai.Client,
    topic: str,
    style_key: str,
    speaker1: str,
    speaker2: str,
    num_parts: int,
    minutes_per_part: int,
    output_dir: Path,
    base_slug: str,
    generate_subtitles: bool = False,
    only_parts: tuple[int, ...] = (),
    existing_outline: Outline | None = None,
    audience_level: str = DEFAULT_AUDIENCE,
    tone: str = DEFAULT_TONE,
    continuous: bool = True,
    show_name: str = "",
    channel_name: str = "",
    num_speakers: int = 2,
    progress_callback=None,
) -> UnifiedPodcastResult:
    """Tạo podcast hoàn chỉnh: script → audio → subtitle (tuỳ chọn).

    Args:
        client: Gemini API client (dùng cho script generation)
        topic: Chủ đề podcast
        style_key: Kiểu kịch bản (podcast, interview, debate, etc.)
        speaker1, speaker2: Tên các diễn viên (dùng cho ElevenLabs voice mapping)
        num_parts: Số phần (default 10)
        minutes_per_part: Phút mỗi phần
        output_dir: Thư mục lưu output
        base_slug: Prefix tên file (vd: "topic_20250707_123456")
        generate_subtitles: Có tạo phụ đề Whisper không? (default False)
        only_parts: Chỉ tạo 1 số part, vd: (2, 4) — cần existing_outline
        existing_outline: Outline có sẵn (để regen part mà không gen lại outline)
        audience_level: Trình độ khán giả
        tone: Tone giọng
        continuous: Có continuity giữa các part không?
        show_name, channel_name: Branding metadata
        num_speakers: Số speaker (1 hoặc 2, dùng cho ElevenLabs)
        progress_callback: fn(stage, message) để tracking progress

    Returns:
        UnifiedPodcastResult với tất cả part + outline.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    outline_path = output_dir / f"{base_slug}_outline.json"

    def _progress(stage: str, message: str = ""):
        if progress_callback:
            progress_callback(stage, message)

    _progress("outline", f"Generating outline ({num_parts} parts × {minutes_per_part} min)...")

    if existing_outline is not None:
        outline = existing_outline
    else:
        outline = generate_outline(
            client,
            topic,
            num_parts,
            minutes_per_part,
            audience_level=audience_level,
            tone=tone,
            continuous=continuous,
            show_name=show_name,
            channel_name=channel_name,
        )
        _write_outline(outline_path, outline)
        print(f"✓ Outline saved: {outline_path}")
        print("\n--- OUTLINE ---")
        print(outline.to_readable())
        print("--- END OUTLINE ---\n")

    selected = set(only_parts) if only_parts else None
    results: list[PartResult] = []
    previous_titles: list[str] = []
    previous_tail: tuple[str, ...] = ()

    # Load ElevenLabs config once (dùng chung cho tất cả part)
    el_config = get_elevenlabs_config()
    el_voice_ids = el_config.get("voices", ["", ""])[:num_speakers]

    for part in outline.parts:
        previous_titles_snapshot = tuple(previous_titles)
        previous_titles.append(part.title)

        if selected is not None and part.index not in selected:
            print(f"⏭  Skip Part {part.index} (not in --only)")
            continue

        _progress("script", f"Generating script for Part {part.index}: {part.title}")
        print(f"\n→ [Part {part.index}/{num_parts}] Generating script: {part.title!r}")

        script = generate_part_script(
            client=client,
            topic=topic,
            style_key=style_key,
            part_index=part.index,
            total_parts=num_parts,
            target_minutes=minutes_per_part,
            part_title=part.title,
            part_summary=part.summary,
            key_points=part.key_points,
            previous_part_titles=previous_titles_snapshot,
            previous_tail_lines=previous_tail,
            audience_level=audience_level,
            tone=tone,
            continuous=continuous,
            show_name=show_name,
            channel_name=channel_name,
        )
        previous_tail = tuple(f"{l.speaker}: {l.text}" for l in script.lines[-6:])
        print(f"✓ {len(script.lines)} dialogue turns")

        wav_path = output_dir / f"{base_slug}_part{part.index}.wav"
        txt_path = output_dir / f"{base_slug}_part{part.index}.txt"

        _write_part_transcript(
            txt_path=txt_path,
            topic=topic,
            style=style_key,
            speaker1=speaker1,
            speaker2=speaker2,
            part_index=part.index,
            total_parts=num_parts,
            part_title=part.title,
            part_summary=part.summary,
            script=script,
        )
        print(f"✓ Transcript: {txt_path}")

        _progress("audio", f"Rendering audio for Part {part.index}")
        print(f"→ [Part {part.index}/{num_parts}] Rendering audio via ElevenLabs...")

        # Use ElevenLabs multi-speaker rendering
        if num_speakers == 1:
            render_single_voice(script, wav_path, el_voice_ids[0], el_config)
        else:
            render_multi_speaker(script, wav_path, el_voice_ids, el_config)

        print(f"✓ Audio: {wav_path}")

        results.append(
            PartResult(
                index=part.index,
                title=part.title,
                script=script,
                wav_path=wav_path,
                txt_path=txt_path,
            )
        )

    # Tạo phụ đề nếu cần
    has_subtitles = False
    if generate_subtitles and results:
        _progress("subtitles", "Generating subtitles via Whisper...")
        print(f"\n→ Generating subtitles for all parts via Whisper...")

        for result in results:
            try:
                _progress("subtitles", f"Processing Part {result.index}...")
                srt_path = result.wav_path.with_suffix(".srt")
                base_path = result.wav_path.with_suffix("")

                # Chạy Whisper (local, không cần API key)
                transcript = transcribe(result.wav_path, language="vi", model_size="medium")
                srt_path.write_text(transcript_to_srt(transcript), encoding="utf-8")
                write_json_outputs(transcript, base_path)

                print(f"✓ Subtitles Part {result.index}: {srt_path}")
                has_subtitles = True
            except Exception as e:
                print(f"⚠ Failed to generate subtitles for Part {result.index}: {e}")

    _progress("done", f"Generated {len(results)} part(s)")
    print(f"\n✓ Done! Generated {len(results)} part(s).")
    if has_subtitles:
        print(f"✓ Subtitles generated (.srt, .json, .words.json)")

    return UnifiedPodcastResult(
        outline=outline,
        parts=tuple(results),
        outline_path=outline_path,
        has_subtitles=has_subtitles,
    )

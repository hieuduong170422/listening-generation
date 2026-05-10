import json
from dataclasses import dataclass
from pathlib import Path
from google import genai

from config import DEFAULT_AUDIENCE, DEFAULT_TONE
from outline_generator import Outline, generate_outline
from script_generator import Script, generate_part_script
from tts_renderer import render_script


@dataclass(frozen=True)
class PartResult:
    index: int
    title: str
    script: Script
    wav_path: Path
    txt_path: Path


@dataclass(frozen=True)
class MultiPartResult:
    outline: Outline
    parts: tuple[PartResult, ...]
    outline_path: Path


def _write_part_transcript(
    txt_path: Path,
    topic: str,
    style: str,
    speaker1: str,
    speaker2: str,
    part_index: int,
    total_parts: int,
    part_title: str,
    part_summary: str,
    script: Script,
) -> None:
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        f"Topic: {topic}\n"
        f"Part: {part_index}/{total_parts} — {part_title}\n"
        f"Summary: {part_summary}\n"
        f"Style: {style}\n"
        f"Speaker1 ({speaker1}) / Speaker2 ({speaker2})\n\n"
    )
    txt_path.write_text(header + script.to_readable(), encoding="utf-8")


def _write_outline(outline_path: Path, outline: Outline) -> None:
    outline_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "topic": outline.topic,
        "total_minutes": outline.total_minutes,
        "parts": [
            {
                "index": p.index,
                "title": p.title,
                "summary": p.summary,
                "key_points": list(p.key_points),
            }
            for p in outline.parts
        ],
    }
    outline_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run_multi_part(
    client: genai.Client,
    topic: str,
    style_key: str,
    speaker1: str,
    speaker2: str,
    num_parts: int,
    minutes_per_part: int,
    output_dir: Path,
    base_slug: str,
    only_parts: tuple[int, ...] = (),
    existing_outline: Outline | None = None,
    audience_level: str = DEFAULT_AUDIENCE,
    tone: str = DEFAULT_TONE,
    continuous: bool = True,
    show_name: str = "",
    channel_name: str = "",
) -> MultiPartResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    outline_path = output_dir / f"{base_slug}_outline.json"

    if existing_outline is not None:
        outline = existing_outline
    else:
        print(f"→ Generating outline ({num_parts} parts × {minutes_per_part} min)...")
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

    for part in outline.parts:
        previous_titles_snapshot = tuple(previous_titles)
        previous_titles.append(part.title)

        if selected is not None and part.index not in selected:
            print(f"⏭  Skip Part {part.index} (not in --only)")
            continue

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
        previous_tail = tuple(
            f"{l.speaker}: {l.text}" for l in script.lines[-6:]
        )
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

        print(f"→ [Part {part.index}/{num_parts}] Rendering audio...")
        render_script(client, script, wav_path, speaker1, speaker2)
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

    return MultiPartResult(outline=outline, parts=tuple(results), outline_path=outline_path)


def load_outline(outline_path: Path) -> Outline:
    from outline_generator import PartBrief

    payload = json.loads(outline_path.read_text(encoding="utf-8"))
    parts = tuple(
        PartBrief(
            index=int(p["index"]),
            title=str(p["title"]),
            summary=str(p["summary"]),
            key_points=tuple(str(kp) for kp in p.get("key_points", [])),
        )
        for p in payload["parts"]
    )
    return Outline(
        topic=str(payload["topic"]),
        total_minutes=int(payload["total_minutes"]),
        parts=parts,
    )

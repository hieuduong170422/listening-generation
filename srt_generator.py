import wave
from pathlib import Path

from config import PACE_WPM
from script_generator import Script


def _format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hh = total_ms // 3_600_000
    mm = (total_ms % 3_600_000) // 60_000
    ss = (total_ms % 60_000) // 1000
    ms = total_ms % 1000
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def _estimate_duration_seconds(text: str, wpm: int, min_seconds: float = 1.2) -> float:
    word_count = max(1, len(text.split()))
    raw = word_count * 60.0 / wpm
    return max(min_seconds, raw)


def build_srt(
    script: Script,
    speaker1_name: str,
    speaker2_name: str,
    pace: str,
    start_offset_seconds: float = 0.0,
    inter_line_gap_seconds: float = 0.15,
) -> tuple[str, float]:
    wpm = PACE_WPM.get(pace, PACE_WPM["normal"])
    entries: list[str] = []
    cursor = start_offset_seconds

    for index, line in enumerate(script.lines, start=1):
        name = speaker1_name if line.speaker == "Speaker1" else speaker2_name
        display_name = name.strip() or line.speaker
        body = f"{display_name}: {line.text}".strip()

        duration = _estimate_duration_seconds(line.text, wpm)
        start = cursor
        end = cursor + duration
        cursor = end + inter_line_gap_seconds

        entries.append(
            f"{index}\n"
            f"{_format_timestamp(start)} --> {_format_timestamp(end)}\n"
            f"{body}\n"
        )

    return "\n".join(entries), cursor


def write_srt(
    script: Script,
    out_path: Path,
    speaker1_name: str,
    speaker2_name: str,
    pace: str,
    start_offset_seconds: float = 0.0,
) -> float:
    text, end_cursor = build_srt(
        script=script,
        speaker1_name=speaker1_name,
        speaker2_name=speaker2_name,
        pace=pace,
        start_offset_seconds=start_offset_seconds,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return end_cursor


def _wav_duration_seconds(wav_path: Path) -> float:
    with wave.open(str(wav_path), "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
        return frames / float(rate) if rate else 0.0


def _resolve_name(speaker: str, host_names: list[str]) -> str:
    try:
        idx = int(speaker.replace("Speaker", "")) - 1
    except ValueError:
        return speaker
    if 0 <= idx < len(host_names):
        candidate = (host_names[idx] or "").strip()
        if candidate:
            return candidate
    return speaker


def _build_part_entries_scaled(
    script: Script,
    host_names: list[str],
    pace: str,
    actual_duration: float,
    start_offset: float,
    next_index: int,
    inter_line_gap: float = 0.15,
) -> tuple[list[str], int, float]:
    wpm = PACE_WPM.get(pace, PACE_WPM["normal"])
    raw_durations = [
        _estimate_duration_seconds(line.text, wpm) for line in script.lines
    ]
    total_raw = sum(raw_durations) + inter_line_gap * max(0, len(script.lines) - 1)
    if total_raw <= 0 or actual_duration <= 0:
        scale = 1.0
    else:
        total_raw_lines = sum(raw_durations) or 1.0
        scale = max(0.0, actual_duration - inter_line_gap * max(0, len(script.lines) - 1)) / total_raw_lines

    entries: list[str] = []
    cursor = start_offset
    idx = next_index
    for raw_dur, line in zip(raw_durations, script.lines):
        display = _resolve_name(line.speaker, host_names)
        scaled = max(0.6, raw_dur * scale)
        start = cursor
        end = cursor + scaled
        entries.append(
            f"{idx}\n"
            f"{_format_timestamp(start)} --> {_format_timestamp(end)}\n"
            f"{display}: {line.text}\n"
        )
        cursor = end + inter_line_gap
        idx += 1
    return entries, idx, start_offset + (actual_duration if actual_duration > 0 else cursor - start_offset)


def build_full_srt(
    parts: list[tuple[Script, Path]],
    host_names: list[str],
    pace: str,
    inter_part_gap: float = 0.5,
) -> str:
    all_entries: list[str] = []
    next_index = 1
    cursor = 0.0
    for script, wav_path in parts:
        try:
            duration = _wav_duration_seconds(wav_path)
        except Exception:
            duration = 0.0
        entries, next_index, cursor = _build_part_entries_scaled(
            script=script,
            host_names=host_names,
            pace=pace,
            actual_duration=duration,
            start_offset=cursor,
            next_index=next_index,
        )
        all_entries.extend(entries)
        cursor += inter_part_gap
    return "\n".join(all_entries)


def write_full_srt(
    parts: list[tuple[Script, Path]],
    out_path: Path,
    host_names: list[str],
    pace: str,
) -> Path:
    text = build_full_srt(parts, host_names, pace)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return out_path

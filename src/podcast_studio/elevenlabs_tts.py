"""ElevenLabs TTS renderer — single voice + multi-speaker.

Multi-speaker works by rendering each dialogue line separately with the
configured voice, then stitching the segments together via pydub (ffmpeg).
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

import requests
from pydub import AudioSegment

from podcast_studio.script_generator import Script
from podcast_studio.tts_settings import get_elevenlabs_api_key

log = logging.getLogger(__name__)

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
_REQUEST_TIMEOUT = 120
_VOICE_SETTING_KEYS = (
    "stability",
    "similarity_boost",
    "style",
    "use_speaker_boost",
    "speed",
)


class ElevenLabsError(RuntimeError):
    pass


def _require_api_key() -> str:
    key = get_elevenlabs_api_key()
    if not key:
        raise ElevenLabsError(
            "ELEVENLABS_API_KEY chưa được set trong .env. "
            "Thêm dòng `ELEVENLABS_API_KEY=sk_...` rồi restart app."
        )
    return key


def list_voices() -> list[dict]:
    key = _require_api_key()
    resp = requests.get(
        f"{ELEVENLABS_BASE}/voices",
        headers={"xi-api-key": key},
        timeout=30,
    )
    if resp.status_code != 200:
        raise ElevenLabsError(f"GET /voices failed [{resp.status_code}]: {resp.text[:300]}")
    voices = resp.json().get("voices", [])
    return [
        {
            "voice_id": v.get("voice_id", ""),
            "name": v.get("name", "(unnamed)"),
            "category": v.get("category", ""),
            "labels": v.get("labels", {}),
            "preview_url": v.get("preview_url", ""),
            "high_quality_base_model_ids": v.get("high_quality_base_model_ids", []) or [],
            "fine_tuning_states": (v.get("fine_tuning") or {}).get("state", {}) or {},
        }
        for v in voices
    ]


def voice_supports_model(voice: dict, model_id: str) -> bool:
    """Return True if `voice` is known to work with `model_id`.

    Sources of truth (any one is sufficient):
      • voice.high_quality_base_model_ids  — official supported list
      • voice.fine_tuning_states[model_id] == "fine_tuned" — fine-tuned
    """
    if not model_id:
        return True
    if model_id in (voice.get("high_quality_base_model_ids") or []):
        return True
    state = (voice.get("fine_tuning_states") or {}).get(model_id, "")
    return state == "fine_tuned"


def synthesize_preview(text: str, voice_id: str, config: dict) -> bytes:
    """Render a short sample with current voice settings — for UI preview."""
    if not voice_id:
        raise ElevenLabsError("Chưa chọn voice.")
    return _tts_request(text, voice_id, config)


def _parse_format(fmt: str) -> tuple[str, int, int | None]:
    """Return (container, sample_rate, bitrate_kbps_or_None)."""
    parts = fmt.split("_")
    container = parts[0]
    sr = int(parts[1]) if len(parts) > 1 else 44100
    bitrate = int(parts[2]) if len(parts) > 2 else None
    return container, sr, bitrate


def _bytes_to_segment(audio_bytes: bytes, fmt: str) -> AudioSegment:
    container, sr, _ = _parse_format(fmt)
    if container == "mp3":
        return AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
    if container == "pcm":
        return AudioSegment.from_raw(
            io.BytesIO(audio_bytes), sample_width=2, frame_rate=sr, channels=1,
        )
    if container == "ulaw":
        return AudioSegment.from_file(
            io.BytesIO(audio_bytes), format="mulaw", frame_rate=sr, channels=1,
        )
    raise ElevenLabsError(f"Định dạng không hỗ trợ: {fmt}")


def _export_segment(segment: AudioSegment, path: Path, fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    container, _, bitrate = _parse_format(fmt)
    if container == "mp3":
        segment.export(str(path), format="mp3", bitrate=f"{bitrate or 128}k")
    elif container in ("pcm", "ulaw"):
        segment.export(str(path), format="wav")
    else:
        segment.export(str(path), format="mp3", bitrate="128k")


def _output_extension(fmt: str) -> str:
    container, _, _ = _parse_format(fmt)
    return ".mp3" if container == "mp3" else ".wav"


def _voice_settings(config: dict) -> dict:
    return {k: config[k] for k in _VOICE_SETTING_KEYS if k in config}


def _tts_request(text: str, voice_id: str, config: dict) -> bytes:
    api_key = _require_api_key()
    fmt = config.get("output_format", "mp3_44100_128")
    payload = {
        "text": text,
        "model_id": config.get("model_id", "eleven_flash_v2_5"),
        "voice_settings": _voice_settings(config),
    }
    url = f"{ELEVENLABS_BASE}/text-to-speech/{voice_id}?output_format={fmt}"
    log.info("ElevenLabs TTS | voice=%s | model=%s | len=%d", voice_id, payload["model_id"], len(text))
    resp = requests.post(
        url,
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=_REQUEST_TIMEOUT,
    )
    if resp.status_code != 200:
        raise ElevenLabsError(
            f"ElevenLabs TTS failed [{resp.status_code}]: {resp.text[:400]}"
        )
    return resp.content


def _resolve_output_path(output_path: Path, fmt: str) -> Path:
    return output_path.with_suffix(_output_extension(fmt))


def render_single_voice(
    script: Script,
    output_path: Path,
    voice_id: str,
    config: dict,
) -> Path:
    if not voice_id:
        raise ElevenLabsError("Chưa chọn voice ở Settings tab.")
    fmt = config.get("output_format", "mp3_44100_128")
    final_path = _resolve_output_path(output_path, fmt)
    text = "\n\n".join(line.text for line in script.lines if line.text.strip())
    if not text:
        raise ElevenLabsError("Script trống — không có gì để render.")
    audio = _tts_request(text, voice_id, config)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    if fmt.startswith("pcm") or fmt.startswith("ulaw"):
        segment = _bytes_to_segment(audio, fmt)
        _export_segment(segment, final_path, fmt)
    else:
        final_path.write_bytes(audio)
    return final_path


def render_multi_speaker(
    script: Script,
    output_path: Path,
    voice_ids: list[str],
    config: dict,
    progress_callback=None,
) -> Path:
    if not voice_ids or all(not v for v in voice_ids):
        raise ElevenLabsError("Chưa chọn voice cho các speaker ở Settings tab.")
    fmt = config.get("output_format", "mp3_44100_128")
    final_path = _resolve_output_path(output_path, fmt)
    segments: list[AudioSegment] = []
    total = len(script.lines)
    for idx, line in enumerate(script.lines):
        if not line.text.strip():
            continue
        speaker_idx = _speaker_index(line.speaker)
        voice = voice_ids[speaker_idx] if 0 <= speaker_idx < len(voice_ids) else voice_ids[0]
        if not voice:
            raise ElevenLabsError(
                f"Speaker{speaker_idx + 1} chưa được gán voice ở Settings."
            )
        if progress_callback is not None:
            progress_callback(idx, total, line.speaker)
        audio = _tts_request(line.text, voice, config)
        segments.append(_bytes_to_segment(audio, fmt))
    if not segments:
        raise ElevenLabsError("Script trống — không có gì để render.")
    combined = segments[0]
    for seg in segments[1:]:
        combined += seg
    _export_segment(combined, final_path, fmt)
    return final_path


def _speaker_index(speaker: str) -> int:
    """Map 'Speaker1' -> 0, 'Speaker2' -> 1, ..., fallback to 0."""
    try:
        return int("".join(c for c in speaker if c.isdigit())) - 1
    except (ValueError, TypeError):
        return 0

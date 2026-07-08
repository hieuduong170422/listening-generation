"""vclip.io TTS renderer — single voice + multi-speaker.

API flow:
  1. POST /json-rpc  method=ttsLongText  → projectExportId
  2. Poll  /json-rpc  method=getExportStatus  every 2s → state=="completed" → url
  3. GET url → audio bytes (MP3)
"""
from __future__ import annotations

import io
import logging
import os
import time
from pathlib import Path

import requests
from pydub import AudioSegment

from podcast_studio.script_generator import Script

log = logging.getLogger(__name__)

VCLIP_BASE = "https://api-tts.vclip.io/json-rpc"
_TIMEOUT = 30
_POLL_INTERVAL = 2.5   # seconds between status polls
_MAX_WAIT = 300        # bail out after 5 minutes


class VclipError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.getenv("VCLIP_API_KEY", "").strip()
    if not key:
        raise VclipError(
            "VCLIP_API_KEY chưa được set trong .env. "
            "Thêm dòng `VCLIP_API_KEY=sk_live_...` rồi restart app."
        )
    return key


def _post(method: str, payload: dict, api_key: str) -> dict:
    resp = requests.post(
        VCLIP_BASE,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"method": method, "input": payload},
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        raise VclipError(f"vclip [{method}] HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if "error" in data:
        raise VclipError(f"vclip [{method}] error: {data['error']}")
    return data


def _synthesize_text(text: str, voice_id: str, speed: float = 1.0) -> bytes:
    """Render một đoạn text → MP3 bytes."""
    api_key = _api_key()
    resp = _post("ttsLongText", {"text": text, "userVoiceId": voice_id, "speed": speed}, api_key)

    export_id = (resp.get("result") or resp.get("data") or resp).get("projectExportId")
    if not export_id:
        export_id = resp.get("projectExportId")
    if not export_id:
        raise VclipError(f"Không tìm được projectExportId trong response: {resp}")

    log.info("vclip TTS | voice=%s | export_id=%s | len=%d", voice_id, export_id, len(text))

    deadline = time.time() + _MAX_WAIT
    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL)
        status = _post("getExportStatus", {"projectExportId": export_id}, api_key)
        result = (status.get("result") or status.get("data") or status)
        state = result.get("state", "")
        if state == "completed":
            url = result.get("url") or result.get("audioUrl") or result.get("downloadUrl")
            if not url:
                raise VclipError(f"state=completed nhưng không có url. Response: {result}")
            audio_resp = requests.get(url, timeout=60)
            if audio_resp.status_code != 200:
                raise VclipError(f"Tải audio thất bại [{audio_resp.status_code}]: {url}")
            return audio_resp.content
        if state in ("failed", "error", "cancelled"):
            raise VclipError(f"vclip export thất bại: state={state}, detail={result}")

    raise VclipError(f"Timeout sau {_MAX_WAIT}s chờ export {export_id}")


def render_single_voice(
    script: Script,
    output_path: Path,
    voice_id: str,
    speed: float = 1.0,
) -> Path:
    """Render toàn bộ script bằng 1 giọng → WAV."""
    if not voice_id:
        raise VclipError("Chưa nhập Voice ID cho vclip.io.")
    text = "\n\n".join(line.text for line in script.lines if line.text.strip())
    if not text:
        raise VclipError("Script trống — không có gì để render.")
    audio_bytes = _synthesize_text(text, voice_id, speed)
    final_path = output_path.with_suffix(".wav")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
    seg.export(str(final_path), format="wav")
    return final_path


def render_multi_speaker(
    script: Script,
    output_path: Path,
    voice_ids: list[str],
    speed: float = 1.0,
    progress_callback=None,
) -> Path:
    """Render từng line theo speaker → ghép lại → WAV."""
    if not voice_ids or all(not v for v in voice_ids):
        raise VclipError("Chưa nhập Voice ID cho các speaker vclip.io.")

    final_path = output_path.with_suffix(".wav")
    segments: list[AudioSegment] = []
    total = len(script.lines)

    for idx, line in enumerate(script.lines):
        if not line.text.strip():
            continue
        speaker_idx = _speaker_index(line.speaker)
        voice = voice_ids[speaker_idx] if 0 <= speaker_idx < len(voice_ids) else voice_ids[0]
        if not voice:
            raise VclipError(f"Speaker{speaker_idx + 1} chưa được gán Voice ID.")
        if progress_callback:
            progress_callback(idx, total, line.speaker)
        audio_bytes = _synthesize_text(line.text, voice, speed)
        segments.append(AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3"))

    if not segments:
        raise VclipError("Script trống — không có gì để render.")

    combined = segments[0]
    for seg in segments[1:]:
        combined += seg
    final_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(final_path), format="wav")
    return final_path


def _speaker_index(speaker: str) -> int:
    try:
        return int("".join(c for c in speaker if c.isdigit())) - 1
    except (ValueError, TypeError):
        return 0

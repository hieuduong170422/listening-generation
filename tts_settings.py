"""Persistent TTS provider settings (provider, voices, voice tuning, output format).

Stored as JSON at project root so changes survive Streamlit reruns.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SETTINGS_PATH = Path(__file__).parent / "tts_settings.json"

PROVIDER_GEMINI = "gemini"
PROVIDER_ELEVENLABS = "elevenlabs"
VALID_PROVIDERS = {PROVIDER_GEMINI, PROVIDER_ELEVENLABS}

ELEVEN_OUTPUT_FORMATS = [
    "mp3_22050_32",
    "mp3_44100_32",
    "mp3_44100_64",
    "mp3_44100_96",
    "mp3_44100_128",
    "mp3_44100_192",
    "pcm_16000",
    "pcm_22050",
    "pcm_24000",
    "pcm_44100",
    "ulaw_8000",
]

ELEVEN_MODELS = [
    "eleven_flash_v2_5",
    "eleven_flash_v2",
    "eleven_turbo_v2_5",
    "eleven_multilingual_v2",
    "eleven_v3",
]

_DEFAULTS = {
    "tts_provider": PROVIDER_GEMINI,
    "elevenlabs": {
        "num_speakers": 2,
        "voices": ["", "", "", ""],
        "model_id": "eleven_flash_v2_5",
        "stability": 0.5,
        "similarity_boost": 0.75,
        "style": 0.0,
        "use_speaker_boost": True,
        "speed": 1.0,
        "output_format": "mp3_44100_128",
    },
}


def _deep_merge(base: dict, overrides: dict) -> dict:
    out = {**base}
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings() -> dict:
    if not SETTINGS_PATH.exists():
        return json.loads(json.dumps(_DEFAULTS))
    try:
        loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return _deep_merge(json.loads(json.dumps(_DEFAULTS)), loaded)
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(_DEFAULTS))


def save_settings(settings: dict) -> None:
    merged = _deep_merge(json.loads(json.dumps(_DEFAULTS)), settings)
    SETTINGS_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")


def get_provider() -> str:
    return load_settings().get("tts_provider", PROVIDER_GEMINI)


def get_elevenlabs_config() -> dict:
    return load_settings().get("elevenlabs", _DEFAULTS["elevenlabs"])


def get_elevenlabs_api_key() -> str:
    return os.getenv("ELEVENLABS_API_KEY", "").strip()

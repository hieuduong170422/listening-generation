from __future__ import annotations

import re
import wave
from pathlib import Path
from google import genai
from google.genai import types

from api_utils import call_with_retry, track_response
from config import DEFAULT_PACE, SPEECH_PACES, TTS_MODEL
from script_generator import DialogueLine, Script

_STAGE_DIRECTION_RE = re.compile(r"[*\[(](?:laughs?|chuckles?|sighs?|pause|smiles?|giggles?|coughs?|claps?|gasps?)[*\])]", re.IGNORECASE)
_MULTI_SPACE_RE = re.compile(r"\s+")
_MULTI_DOT_RE = re.compile(r"\.{4,}")
_TRAILING_PUNCT_RE = re.compile(r"\s+([,.!?;:])")


def _sanitize_text(text: str) -> str:
    s = text
    s = s.replace("—", ", ").replace("–", ", ")
    s = s.replace("“", '"').replace("”", '"')
    s = s.replace("‘", "'").replace("’", "'")
    s = s.replace("…", "...")
    s = s.replace("•", "")
    s = _STAGE_DIRECTION_RE.sub("", s)
    s = _MULTI_DOT_RE.sub("...", s)
    s = _TRAILING_PUNCT_RE.sub(r"\1", s)
    s = _MULTI_SPACE_RE.sub(" ", s)
    return s.strip()


def _sanitize_script(script: Script) -> Script:
    cleaned_lines = tuple(
        DialogueLine(speaker=line.speaker, text=_sanitize_text(line.text))
        for line in script.lines
        if _sanitize_text(line.text)
    )
    return Script(topic=script.topic, style=script.style, lines=cleaned_lines)

_SAMPLE_RATE = 24000
_CHANNELS = 1
_SAMPLE_WIDTH = 2


def _save_wav(path: Path, audio_bytes: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(_CHANNELS)
        wf.setsampwidth(_SAMPLE_WIDTH)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(audio_bytes)


def _extract_audio_bytes(response) -> bytes:
    parts = response.candidates[0].content.parts
    audio_part = next((p for p in parts if getattr(p, "inline_data", None)), None)
    if audio_part is None:
        raise RuntimeError("Model không trả về audio. Kiểm tra lại API key + quota.")
    return audio_part.inline_data.data


def _render_single_voice(
    client: genai.Client,
    script: Script,
    output_path: Path,
    voice: str,
    pace: str,
    usage_store: list | None = None,
) -> Path:
    response = call_with_retry(
        client.models.generate_content,
        model=TTS_MODEL,
        contents=script.to_tts_prompt(pace=pace),
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice),
                ),
            ),
        ),
    )
    track_response(usage_store, response, "tts")
    _save_wav(output_path, _extract_audio_bytes(response))
    return output_path


def _build_two_speaker_config(voice1: str, voice2: str) -> types.SpeechConfig:
    return types.SpeechConfig(
        multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
            speaker_voice_configs=[
                types.SpeakerVoiceConfig(
                    speaker="Speaker1",
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice1),
                    ),
                ),
                types.SpeakerVoiceConfig(
                    speaker="Speaker2",
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice2),
                    ),
                ),
            ],
        ),
    )


def _render_two_speakers(
    client: genai.Client,
    script: Script,
    output_path: Path,
    voice1: str,
    voice2: str,
    pace: str,
    usage_store: list | None = None,
) -> Path:
    response = call_with_retry(
        client.models.generate_content,
        model=TTS_MODEL,
        contents=script.to_tts_prompt(pace=pace),
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=_build_two_speaker_config(voice1, voice2),
        ),
    )
    track_response(usage_store, response, "tts")
    _save_wav(output_path, _extract_audio_bytes(response))
    return output_path


def _render_line_with_voice(
    client: genai.Client,
    line_text: str,
    voice: str,
    pace_prefix: str,
    usage_store: list | None = None,
) -> bytes:
    prompt = f"{pace_prefix}\n{line_text}"
    response = call_with_retry(
        client.models.generate_content,
        model=TTS_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice),
                ),
            ),
        ),
    )
    track_response(usage_store, response, "tts")
    return _extract_audio_bytes(response)


def _render_n_speakers_per_line(
    client: genai.Client,
    script: Script,
    output_path: Path,
    voices: list[str],
    pace: str,
    progress_callback=None,
    usage_store: list | None = None,
) -> Path:
    pace_prefix = SPEECH_PACES.get(pace, SPEECH_PACES[DEFAULT_PACE])
    total = len(script.lines)
    audio_chunks: list[bytes] = []
    for idx, line in enumerate(script.lines):
        if progress_callback is not None:
            progress_callback(idx, total, line.speaker)
        speaker_idx = int(line.speaker.replace("Speaker", "")) - 1
        voice = voices[speaker_idx] if 0 <= speaker_idx < len(voices) else voices[0]
        chunk = _render_line_with_voice(
            client, line.text, voice, pace_prefix, usage_store=usage_store
        )
        audio_chunks.append(chunk)
    _save_wav(output_path, b"".join(audio_chunks))
    return output_path


def render_script(
    client: genai.Client,
    script: Script,
    output_path: Path,
    speaker_1_voice: str,
    speaker_2_voice: str,
    pace: str = DEFAULT_PACE,
) -> Path:
    return _render_two_speakers(
        client, script, output_path, speaker_1_voice, speaker_2_voice, pace
    )


def render_script_with_voices(
    client: genai.Client,
    script: Script,
    output_path: Path,
    voices: list[str],
    pace: str = DEFAULT_PACE,
    progress_callback=None,
    usage_store: list | None = None,
) -> Path:
    script = _sanitize_script(script)
    if not script.lines:
        raise ValueError("Script trống sau khi sanitize.")
    n = len(voices)
    if n == 0:
        raise ValueError("Cần ít nhất 1 voice.")

    from tts_settings import get_provider, get_elevenlabs_config, PROVIDER_ELEVENLABS
    if get_provider() == PROVIDER_ELEVENLABS:
        from elevenlabs_tts import render_single_voice as el_single, render_multi_speaker as el_multi
        cfg = get_elevenlabs_config()
        el_voices = cfg.get("voices", [])
        if n == 1:
            return el_single(script, output_path, el_voices[0] if el_voices else "", cfg)
        return el_multi(
            script, output_path, el_voices[:n], cfg,
            progress_callback=progress_callback,
        )

    if n == 1:
        return _render_single_voice(
            client, script, output_path, voices[0], pace, usage_store=usage_store
        )
    if n == 2:
        return _render_two_speakers(
            client, script, output_path, voices[0], voices[1], pace,
            usage_store=usage_store,
        )
    return _render_n_speakers_per_line(
        client, script, output_path, voices, pace,
        progress_callback=progress_callback, usage_store=usage_store,
    )

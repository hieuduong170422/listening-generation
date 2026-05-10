import wave
from pathlib import Path
from google import genai
from google.genai import types

from config import DEFAULT_PACE, SPEECH_PACES, TTS_MODEL
from script_generator import DialogueLine, Script

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
) -> Path:
    response = client.models.generate_content(
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
) -> Path:
    response = client.models.generate_content(
        model=TTS_MODEL,
        contents=script.to_tts_prompt(pace=pace),
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=_build_two_speaker_config(voice1, voice2),
        ),
    )
    _save_wav(output_path, _extract_audio_bytes(response))
    return output_path


def _render_line_with_voice(
    client: genai.Client,
    line_text: str,
    voice: str,
    pace_prefix: str,
) -> bytes:
    prompt = f"{pace_prefix}\n{line_text}"
    response = client.models.generate_content(
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
    return _extract_audio_bytes(response)


def _render_n_speakers_per_line(
    client: genai.Client,
    script: Script,
    output_path: Path,
    voices: list[str],
    pace: str,
    progress_callback=None,
) -> Path:
    pace_prefix = SPEECH_PACES.get(pace, SPEECH_PACES[DEFAULT_PACE])
    total = len(script.lines)
    audio_chunks: list[bytes] = []
    for idx, line in enumerate(script.lines):
        if progress_callback is not None:
            progress_callback(idx, total, line.speaker)
        speaker_idx = int(line.speaker.replace("Speaker", "")) - 1
        voice = voices[speaker_idx] if 0 <= speaker_idx < len(voices) else voices[0]
        chunk = _render_line_with_voice(client, line.text, voice, pace_prefix)
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
) -> Path:
    n = len(voices)
    if n == 0:
        raise ValueError("Cần ít nhất 1 voice.")
    if n == 1:
        return _render_single_voice(client, script, output_path, voices[0], pace)
    if n == 2:
        return _render_two_speakers(
            client, script, output_path, voices[0], voices[1], pace
        )
    return _render_n_speakers_per_line(
        client, script, output_path, voices, pace, progress_callback=progress_callback
    )

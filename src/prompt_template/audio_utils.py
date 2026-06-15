"""Audio file save/load helpers.

Provides PCM→WAV conversion, URL download, base64 decode, and unique
filename generation — all using stdlib + ``requests``.
"""

import base64
import os
import time
import uuid
import wave

import requests

UPLOADS_DIR = "uploads"


def _generate_filename(prefix="tts", ext=".wav"):
    """Generate a unique audio filename: {prefix}_{timestamp}_{uuid8}{ext}"""
    timestamp = int(time.time() * 1000)
    suffix = uuid.uuid4().hex[:8]
    return os.path.join(UPLOADS_DIR, f"{prefix}_{timestamp}_{suffix}{ext}")


def save_pcm_as_wav(pcm_bytes, sample_rate=24000, channels=1, sample_width=2):
    """Save raw PCM audio bytes as a WAV file.

    Args:
        pcm_bytes: Raw PCM audio data.
        sample_rate: Sample rate in Hz (default 24000 for Gemini TTS).
        channels: Number of audio channels (default 1 for mono).
        sample_width: Bytes per sample (default 2 for 16-bit).

    Returns:
        str: Absolute path to the saved WAV file.
    """
    path = _generate_filename()
    with wave.open(path, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return os.path.abspath(path)


def download_and_save_audio(url, timeout=30):
    """Download audio from a URL and save as a WAV file.

    Args:
        url: HTTP/HTTPS URL pointing to the audio file.
        timeout: Request timeout in seconds.

    Returns:
        str: Absolute path to the saved file.
    """
    resp = requests.get(url, stream=True, timeout=timeout)
    resp.raise_for_status()
    data = resp.content
    if not data:
        raise ValueError(f"Downloaded audio from {url} is empty")
    path = _generate_filename()
    with open(path, "wb") as f:
        f.write(data)
    return os.path.abspath(path)


def save_base64_audio(base64_data, mime_type):
    """Decode base64-encoded audio and save to a file.

    Args:
        base64_data: Base64-encoded audio string (may include data URI prefix).
        mime_type: MIME type hint for the audio data (used for extension).

    Returns:
        str: Absolute path to the saved file.
    """
    if base64_data.startswith("data:"):
        _, encoded = base64_data.split(",", 1)
    else:
        encoded = base64_data
    data = base64.b64decode(encoded)
    if not data:
        raise ValueError("Decoded base64 audio data is empty")
    path = _generate_filename()
    with open(path, "wb") as f:
        f.write(data)
    return os.path.abspath(path)


def save_mp3(mp3_bytes, prefix="tts"):
    """Save raw MP3 bytes to a file.

    Args:
        mp3_bytes: Raw MP3 audio data (complete format, no conversion needed).
        prefix: Filename prefix.

    Returns:
        str: Absolute path to the saved MP3 file.
    """
    path = _generate_filename(prefix, ".mp3")
    with open(path, "wb") as f:
        f.write(mp3_bytes)
    return os.path.abspath(path)


def get_audio_bytes(file_path):
    """Read an audio file and return its raw bytes.

    Args:
        file_path: Path to the audio file.

    Returns:
        bytes: Raw file contents.
    """
    with open(file_path, "rb") as f:
        return f.read()

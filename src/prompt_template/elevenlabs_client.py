"""ElevenLabs TTS client — text-to-speech via ElevenLabs SDK.

Provides:
- get_client(): Returns a configured ElevenLabs client
- AVAILABLE_MODELS: List of supported ElevenLabs TTS models
- generate(): Generate speech audio from text

All model IDs start with ``eleven_`` prefix.
"""

import os

import dotenv

from prompt_template.logger import get_api_logger

dotenv.load_dotenv()

AVAILABLE_MODELS = [
    {"id": "eleven_v3", "label": "Eleven v3 — [text->audio] dramatic delivery, 70+ languages"},
    {"id": "eleven_multilingual_v2", "label": "Eleven Multilingual v2 — [text->audio] stability, 29 languages"},
    {"id": "eleven_flash_v2_5", "label": "Eleven Flash v2.5 — [text->audio] ultra-low latency, 32 languages"},
    {"id": "eleven_turbo_v2_5", "label": "Eleven Turbo v2.5 — [text->audio] balance quality/latency"},
]

_ELEVEN_MODELS = frozenset({m["id"] for m in AVAILABLE_MODELS})


def get_client():
    """Create and return an ElevenLabs API client.

    Reads ELEVENLABS_API_KEY from environment (via python-dotenv).

    Returns:
        ElevenLabs: Configured ElevenLabs client.

    Raises:
        ValueError: If ELEVENLABS_API_KEY is not set.
    """
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError(
            "ELEVENLABS_API_KEY not found. Create a .env file with:\n"
            "  ELEVENLABS_API_KEY=your_elevenlabs_api_key_here\n"
            "Get a key at: https://elevenlabs.io/app/settings/api-keys"
        )
    # Lazy import — avoid importing elevenlabs at module level
    from elevenlabs import ElevenLabs

    # Also set the SDK's expected env var for internal compatibility
    os.environ["ELEVEN_API_KEY"] = api_key
    return ElevenLabs(api_key=api_key)


def generate(system_prompt, user_prompt, model, temperature, files=None, **kwargs):
    """Generate speech audio via ElevenLabs TTS API.

    Converts the user prompt text to speech using the specified model and voice.
    The output MP3 is saved locally via ``save_mp3()``.

    Args:
        system_prompt: System-level instruction (ignored for TTS).
        user_prompt: Text to synthesize.
        model: Model ID string (from ``AVAILABLE_MODELS``).
        temperature: Sampling temperature (ignored for ElevenLabs TTS).
        files: Ignored (ElevenLabs TTS does not accept file inputs).
        **kwargs: Additional options.
            voice_id (str): Voice ID (default "JBFqnCBsd6RMkjVDRZzb").
            stability (float): Voice stability (0.0–1.0).
            similarity_boost (float): Similarity boost (0.0–1.0).
            style (float): Style exaggeration (0.0–1.0).
            use_speaker_boost (bool): Speaker boost flag.
            speed (float): Speed multiplier.
            language_code (str): Language code (e.g. "en").
            model_id (str): Deprecated — use ``model`` parameter.

    Returns:
        dict with keys:
            - text: The input prompt text (transcript).
            - type: "audio"
            - response_data: Local path to the saved MP3 file.
            - candidates: Dict with model and voice_id metadata.

    Raises:
        ValueError: If ELEVENLABS_API_KEY is not set.
        RuntimeError: If the API call fails.
    """
    logger = get_api_logger()

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError(
            "ELEVENLABS_API_KEY not found. Create a .env file with:\n"
            "  ELEVENLABS_API_KEY=your_elevenlabs_api_key_here\n"
            "Get a key at: https://elevenlabs.io/app/settings/api-keys"
        )

    # Lazy import
    from elevenlabs import ElevenLabs, VoiceSettings

    client = ElevenLabs(api_key=api_key)
    os.environ["ELEVEN_API_KEY"] = api_key

    # Extract VoiceSettings from kwargs
    stability = kwargs.pop("stability", None)
    similarity_boost = kwargs.pop("similarity_boost", None)
    style = kwargs.pop("style", None)
    use_speaker_boost = kwargs.pop("use_speaker_boost", None)
    speed = kwargs.pop("speed", None)

    voice_settings = None
    if any(x is not None for x in [stability, similarity_boost, style, use_speaker_boost, speed]):
        voice_settings = VoiceSettings(
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            use_speaker_boost=use_speaker_boost,
            speed=speed,
        )

    voice_id = kwargs.get("voice_id", "JBFqnCBsd6RMkjVDRZzb")
    language_code = kwargs.get("language_code", None)

    logger.info("ElevenLabs TTS: model=%s voice=%s", model, voice_id)

    try:
        audio_iterator = client.text_to_speech.convert(
            voice_id=voice_id,
            text=user_prompt,
            model_id=model,
            output_format="mp3_44100_128",
            voice_settings=voice_settings,
            language_code=language_code,
        )
        audio_bytes = b"".join(audio_iterator)
    except Exception as e:
        logger.error("ElevenLabs TTS failed: %s", str(e))
        raise RuntimeError(f"ElevenLabs TTS API call failed: {e}") from e

    # Save MP3
    from prompt_template.audio_utils import save_mp3

    path = save_mp3(audio_bytes)

    return {
        "text": user_prompt,
        "type": "audio",
        "response_data": path,
        "candidates": {"model": model, "voice_id": voice_id},
    }


def _voice_to_row(v):
    """Convert a voice SDK object to a DB insert tuple."""
    labels = getattr(v, "labels", {}) or {}
    return (
        v.voice_id,
        v.name,
        str(labels),
        getattr(v, "category", ""),
        getattr(v, "description", ""),
        labels.get("gender", ""),
        labels.get("accent", ""),
    )


def fetch_voices_from_api(client):
    """Fetch available voices from ElevenLabs API (read-only, no write side effects).

    Args:
        client: ElevenLabs client instance.

    Returns:
        list: Voice objects from SDK.
    """
    response = client.voices.search()
    return list(response.voices) if response and hasattr(response, "voices") else []


def get_cached_voices():
    """Return cached voice list from local database.

    Returns:
        list: List of dicts with keys: voice_id, name, labels_json, category,
              description, gender, accent. Empty list if cache empty or table
              doesn't exist.
    """
    from prompt_template.database import get_connection

    conn = None
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT voice_id, name, labels_json, category, description, gender, accent "
            "FROM elevenlabs_voices ORDER BY name"
        ).fetchall()
        result = [dict(r) for r in rows]
        conn.commit()
        return result
    except Exception:
        return []
    finally:
        if conn:
            conn.close()


def update_voice_cache(client):
    """Fetch voices from ElevenLabs API and replace the local cache.

    Clears all existing cached voices and batch-inserts fresh data from the API.

    Args:
        client: ElevenLabs client instance.

    Returns:
        int: Number of voices cached.
    """
    from prompt_template.database import get_connection

    voices = fetch_voices_from_api(client)
    if not voices:
        return 0

    conn = None
    try:
        conn = get_connection()
        # Clear existing cache
        conn.execute("DELETE FROM elevenlabs_voices")
        # Batch insert
        for v in voices:
            conn.execute(
                "INSERT OR IGNORE INTO elevenlabs_voices "
                "(voice_id, name, labels_json, category, description, gender, accent) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                _voice_to_row(v),
            )
        conn.commit()
        return len(voices)
    except Exception:
        return 0
    finally:
        if conn:
            conn.close()

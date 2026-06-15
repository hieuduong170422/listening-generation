"""Unified LLM client facade — routes to google-genai, dashscope, or openai based on model provider tag.

Usage:
    from prompt_template.llm_client import generate, AVAILABLE_MODELS

    result = generate(system_prompt="...", user_prompt="...", model="...", temperature=0.7)
"""
import dotenv

dotenv.load_dotenv()

SDK_GOOGLE = "google-genai"
SDK_OPENAI = "openai"
SDK_DASHSCOPE = "dashscope"
SDK_ELEVENLABS = "elevenlabs"

# ── Friendly SDK labels for UI display ────────────────────────────
PROVIDER_FRIENDLY = {
    "google-genai": "Google Gemini",
    "dashscope": "DashScope",
    "openai": "OpenAI",
    "elevenlabs": "ElevenLabs",
}

# ── Merged model list from all providers ──────────────────────────────────
from prompt_template.gemini_client import AVAILABLE_MODELS as _GEMINI_MODELS
from prompt_template.dashscope_client import AVAILABLE_MODELS as _DASHSCOPE_MODELS
from prompt_template.openai_client import AVAILABLE_MODELS as _OPENAI_MODELS
from prompt_template.elevenlabs_client import AVAILABLE_MODELS as _ELEVENLABS_MODELS


def _tag_models(models, provider):
    return [{**m, "provider": provider} for m in models]


AVAILABLE_MODELS = (
    _tag_models(_GEMINI_MODELS, SDK_GOOGLE)
    + _tag_models(_DASHSCOPE_MODELS, SDK_DASHSCOPE)
    + _tag_models(_OPENAI_MODELS, SDK_OPENAI)
    + _tag_models(_ELEVENLABS_MODELS, SDK_ELEVENLABS)
)


def _get_provider(model_id):
    """Look up the provider tag for a model ID from the merged model list."""
    for m in AVAILABLE_MODELS:
        if m["id"] == model_id:
            return m.get("provider")
    return None


def get_client(model):
    """Return a configured client for a model's provider.

    The model is looked up in the merged model list to determine the provider,
    then the corresponding provider's client is returned.

    Raises:
        ValueError: If *model* is not found in the merged model list.
    """
    provider = _get_provider(model)
    if not provider:
        raise ValueError(f"Unknown model: {model}. Cannot determine provider.")
    if provider == SDK_OPENAI:
        from prompt_template.openai_client import get_client as _get_client

        return _get_client()
    if provider == SDK_DASHSCOPE:
        from prompt_template.dashscope_client import get_client as _get_client

        return _get_client()
    if provider == SDK_ELEVENLABS:
        from prompt_template.elevenlabs_client import get_client as _get_client

        return _get_client()
    from prompt_template.gemini_client import get_client as _get_client

    return _get_client()


def generate(
    system_prompt,
    user_prompt,
    model,
    temperature,
    files=None,
    size="1280*720",
    duration=5,
    **kwargs,
):
    """Generate content using the appropriate provider based on the model.

    The model is looked up in the merged model list to determine the provider,
    then routed to the corresponding provider's ``generate()``.

    Args, return value, and exceptions match the individual client modules.

        size: Output video size (width*height). Only used for video models.
              Defaults to "1280*720".
        duration: Video duration in seconds. Only used for video models.
                  Defaults to 5.
        **kwargs: Additional arguments forwarded to the provider's generate()
                  (e.g. voice, language for TTS models).

    Returns:
        dict with keys: text, type, response_data, candidates.

    Raises:
        ValueError: If *model* is not found in the merged model list,
                    or if the required API key is not set.
        RuntimeError: If the API call fails.
    """
    provider = _get_provider(model)
    if not provider:
        raise ValueError(f"Unknown model: {model}. Cannot determine provider.")

    if provider == SDK_OPENAI:
        from prompt_template.openai_client import generate as _generate

        return _generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
            files=files,
            size=size,
            duration=duration,
            **kwargs,
        )
    if provider == SDK_DASHSCOPE:
        from prompt_template.dashscope_client import generate as _generate

        return _generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
            files=files,
            size=size,
            duration=duration,
            **kwargs,
        )
    if provider == SDK_ELEVENLABS:
        from prompt_template.elevenlabs_client import generate as _generate

        return _generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
            files=files,
            size=size,
            duration=duration,
            **kwargs,
        )
    from prompt_template.gemini_client import generate as _generate

    return _generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        temperature=temperature,
        files=files,
        size=size,
        duration=duration,
        **kwargs,
    )


def get_output_type(model_id):
    """Detect the output content type (text/audio/image/video) from a model ID."""
    mid = model_id.lower()
    if "tts" in mid or mid.startswith("eleven_"):
        return "audio"
    if "image" in mid or mid.startswith("wan2.7-image") or mid.startswith("dall-e"):
        return "image"
    if mid.startswith("sora"):
        return "video"
    if mid.startswith(("veo", "wan")) and any(
        x in mid for x in ("t2v", "i2v", "generate")
    ):
        return "video"
    return "text"


def get_provider_friendly(model_id):
    """Return a friendly display label for a model's provider.

    Looks up the model in the merged model list, then maps the raw
    provider tag to a human-readable label via PROVIDER_FRIENDLY.

    Args:
        model_id: The model identifier string.

    Returns:
        Friendly provider label (e.g. "Google Gemini") or "Unknown"
        if the model or provider is not recognised.
    """
    raw = _get_provider(model_id)
    if not raw:
        return "Unknown"
    return PROVIDER_FRIENDLY.get(raw, "Unknown")


def filter_models_by_sdk(sdk_friendly):
    """Return all models belonging to a provider by its friendly label.

    Builds a reverse lookup from PROVIDER_FRIENDLY, then collects every
    entry in AVAILABLE_MODELS whose provider matches.

    Args:
        sdk_friendly: Friendly provider label (e.g. "Google Gemini").

    Returns:
        List of model dicts for the matching provider, or [] if the
        label is not recognised.
    """
    reverse = {v: k for k, v in PROVIDER_FRIENDLY.items()}
    raw_provider = reverse.get(sdk_friendly)
    if not raw_provider:
        return []
    return [m for m in AVAILABLE_MODELS if m["provider"] == raw_provider]


def filter_models_by_sdk_type(sdk_friendly, output_type):
    """Return models matching both a provider and an output type.

    Delegates to filter_models_by_sdk() first, then narrows by
    get_output_type().

    Args:
        sdk_friendly: Friendly provider label (e.g. "Google Gemini").
        output_type:  Output content type (text/audio/image/video).

    Returns:
        List of model dicts satisfying both filters, or [] if either
        filter yields no results.
    """
    by_sdk = filter_models_by_sdk(sdk_friendly)
    if not by_sdk:
        return []
    return [m for m in by_sdk if get_output_type(m["id"]) == output_type]


def get_sdk_output_types(sdk_friendly):
    """Return the unique output types available for a provider.

    Collects output types by calling get_output_type() on every model
    belonging to the given provider.

    Args:
        sdk_friendly: Friendly provider label (e.g. "Google Gemini").

    Returns:
        Sorted list of unique output type strings, or [] if the
        provider is not recognised.
    """
    by_sdk = filter_models_by_sdk(sdk_friendly)
    if not by_sdk:
        return []
    types = {get_output_type(m["id"]) for m in by_sdk}
    return sorted(types)

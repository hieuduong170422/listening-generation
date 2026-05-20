"""Unified LLM client facade — routes to google-genai or openai based on SDK env var.

Usage:
    from prompt_template.llm_client import generate, AVAILABLE_MODELS

    result = generate(system_prompt="...", user_prompt="...", model="...", temperature=0.7)
"""
import os

import dotenv

dotenv.load_dotenv()

SDK_GOOGLE = "google-genai"
SDK_OPENAI = "openai"
SDK_DASHSCOPE = "dashscope"

_VALID_SDKS = {SDK_GOOGLE, SDK_OPENAI, SDK_DASHSCOPE}


def _resolve_sdk():
    sdk = os.getenv("SDK", SDK_GOOGLE).strip().lower()
    if sdk not in _VALID_SDKS:
        raise ValueError(
            f"Invalid SDK '{sdk}' in .env. Must be one of: {', '.join(sorted(_VALID_SDKS))}"
        )
    return sdk


def get_client():
    """Return a configured client for the active SDK."""
    sdk = _resolve_sdk()
    if sdk == SDK_OPENAI:
        from prompt_template.openai_client import get_client as _get_client

        return _get_client()
    if sdk == SDK_DASHSCOPE:
        from prompt_template.dashscope_client import get_client as _get_client

        return _get_client()
    from prompt_template.gemini_client import get_client as _get_client

    return _get_client()


def generate(system_prompt, user_prompt, model, temperature, files=None):
    """Generate content using the active SDK.

    Args, return value, and exceptions match the individual client modules.

    Returns:
        dict with keys: text, type, response_data, candidates.

    Raises:
        ValueError: If the required API key is not set.
        RuntimeError: If the API call fails.
    """
    sdk = _resolve_sdk()
    if sdk == SDK_OPENAI:
        from prompt_template.openai_client import generate as _generate

        return _generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
            files=files,
        )
    if sdk == SDK_DASHSCOPE:
        from prompt_template.dashscope_client import generate as _generate

        return _generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            temperature=temperature,
            files=files,
        )
    from prompt_template.gemini_client import generate as _generate

    return _generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        temperature=temperature,
        files=files,
    )


def _get_models():
    sdk = _resolve_sdk()
    if sdk == SDK_OPENAI:
        from prompt_template.openai_client import AVAILABLE_MODELS as _models

        return _models
    if sdk == SDK_DASHSCOPE:
        from prompt_template.dashscope_client import AVAILABLE_MODELS as _models

        return _models
    from prompt_template.gemini_client import AVAILABLE_MODELS as _models

    return _models


AVAILABLE_MODELS = _get_models()

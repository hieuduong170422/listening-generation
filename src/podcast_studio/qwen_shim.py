"""DashScope/Qwen client shim that quacks like google.genai.Client.

Lets existing text-gen modules (topic_suggester, outline_generator, script_generator)
work transparently with Qwen via `client.models.generate_content(...)`,
without modifying their source.

Usage:
    from podcast_studio.qwen_shim import QwenClient
    client = QwenClient()      # picks up API_KEY (DashScope) from env
    response = client.models.generate_content(
        model="ignored",
        contents="Hello",
        config=GenerateContentConfig(response_mime_type="application/json"),
    )
    print(response.text)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import dashscope
from dashscope import Generation

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "qwen-plus"


def _get_qwen_model() -> str:
    return os.getenv("QWEN_TEXT_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def _require_api_key() -> str:
    key = (os.getenv("API_KEY") or os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError(
            "API_KEY (DashScope) chưa được set trong .env. "
            "Thêm dòng `API_KEY=sk-...` rồi restart app."
        )
    return key


def _configure_dashscope_base_url() -> None:
    base = (os.getenv("BASE_URL") or "").strip()
    if base:
        dashscope.base_http_api_url = base.rstrip("/")


@dataclass
class _UsageMeta:
    prompt_token_count: int = 0
    candidates_token_count: int = 0


@dataclass
class _CandidateContentPart:
    text: str = ""
    inline_data: Any = None


@dataclass
class _CandidateContent:
    parts: list = field(default_factory=list)


@dataclass
class _Candidate:
    finish_reason: str = "STOP"
    content: _CandidateContent = field(default_factory=_CandidateContent)


@dataclass
class _Response:
    text: str
    usage_metadata: _UsageMeta
    candidates: list


def _read_attr(obj: Any, name: str, default=0) -> int:
    try:
        val = getattr(obj, name, default)
        if val is None:
            return default
        return int(val)
    except (TypeError, ValueError):
        return default


def _extract_json_hint(config: Any) -> bool:
    if config is None:
        return False
    return getattr(config, "response_mime_type", None) == "application/json"


def _extract_temperature(config: Any, fallback: float = 0.7) -> float:
    if config is None:
        return fallback
    val = getattr(config, "temperature", None)
    if val is None:
        return fallback
    try:
        return float(val)
    except (TypeError, ValueError):
        return fallback


def _extract_max_tokens(config: Any) -> int | None:
    if config is None:
        return None
    val = getattr(config, "max_output_tokens", None)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _prompt_text(contents: Any) -> str:
    if contents is None:
        return ""
    if isinstance(contents, str):
        return contents
    return str(contents)


class _ModelsShim:
    def generate_content(
        self,
        *,
        model: str | None = None,
        contents: Any = None,
        config: Any = None,
    ) -> _Response:
        api_key = _require_api_key()
        dashscope.api_key = api_key
        _configure_dashscope_base_url()

        qwen_model = _get_qwen_model()
        prompt = _prompt_text(contents)
        expect_json = _extract_json_hint(config)
        temperature = _extract_temperature(config)
        max_tokens = _extract_max_tokens(config)

        if expect_json:
            prompt += (
                "\n\nReturn ONLY a valid JSON object. "
                "No prose, no markdown fences, no commentary."
            )

        messages = [
            {
                "role": "system",
                "content": "You are a helpful content generation assistant.",
            },
            {"role": "user", "content": prompt},
        ]

        kwargs: dict = {
            "model": qwen_model,
            "messages": messages,
            "result_format": "message",
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if expect_json:
            kwargs["response_format"] = {"type": "json_object"}

        log.info(
            "Qwen shim | model=%s | json=%s | prompt_len=%d",
            qwen_model, expect_json, len(prompt),
        )

        try:
            resp = Generation.call(**kwargs)
        except TypeError:
            # Some SDK versions reject `response_format` — retry without it.
            kwargs.pop("response_format", None)
            resp = Generation.call(**kwargs)

        status = getattr(resp, "status_code", 200)
        if status != 200:
            msg = getattr(resp, "message", "") or getattr(resp, "code", "")
            raise RuntimeError(f"DashScope error [{status}]: {msg}")

        try:
            text = resp.output.choices[0].message.content
            if isinstance(text, list):
                text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
        except (AttributeError, IndexError, KeyError) as e:
            raise RuntimeError(f"Không parse được response DashScope: {e}")

        usage = getattr(resp, "usage", None)
        prompt_tokens = (
            _read_attr(usage, "input_tokens")
            or _read_attr(usage, "prompt_tokens")
        )
        output_tokens = (
            _read_attr(usage, "output_tokens")
            or _read_attr(usage, "completion_tokens")
        )

        return _Response(
            text=text or "",
            usage_metadata=_UsageMeta(
                prompt_token_count=prompt_tokens,
                candidates_token_count=output_tokens,
            ),
            candidates=[_Candidate()],
        )


class QwenClient:
    """Drop-in replacement for genai.Client (text generation only)."""

    def __init__(self):
        _require_api_key()
        self.models = _ModelsShim()

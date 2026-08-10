"""ElevenLabs proxy routes — voices, subscription, history."""
from __future__ import annotations

import logging

import requests
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from podcast_studio.tts_settings import get_elevenlabs_api_key

log = logging.getLogger(__name__)
router = APIRouter()

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
_TIMEOUT = 30


def _api_key() -> str:
    key = get_elevenlabs_api_key()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ELEVENLABS_API_KEY is not configured",
        )
    return key


def _el_headers(key: str) -> dict[str, str]:
    return {"xi-api-key": key}


@router.get("/voices")
def get_voices() -> dict:
    key = _api_key()
    resp = requests.get(
        f"{ELEVENLABS_BASE}/voices",
        headers=_el_headers(key),
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        log.error("ElevenLabs GET /voices failed [%d]: %s", resp.status_code, resp.text[:300])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ElevenLabs error [{resp.status_code}]: {resp.text[:200]}",
        )
    raw_voices = resp.json().get("voices", [])
    voices = [
        {
            "voice_id": v.get("voice_id", ""),
            "name": v.get("name", "(unnamed)"),
            "category": v.get("category", ""),
            "labels": v.get("labels", {}),
            "preview_url": v.get("preview_url", ""),
            "high_quality_base_model_ids": v.get("high_quality_base_model_ids") or [],
            "fine_tuning_states": (v.get("fine_tuning") or {}).get("state", {}) or {},
        }
        for v in raw_voices
    ]
    return {"voices": voices}


@router.get("/subscription")
def get_subscription() -> dict:
    key = _api_key()
    resp = requests.get(
        f"{ELEVENLABS_BASE}/user/subscription",
        headers=_el_headers(key),
        timeout=_TIMEOUT,
    )
    if resp.status_code == 401:
        # Key restricted (missing user_read permission) — trả về fallback thay vì crash
        detail = resp.json().get("detail", {})
        if isinstance(detail, dict) and detail.get("status") == "missing_permissions":
            log.warning("ElevenLabs subscription: key thiếu quyền user_read — trả fallback")
            return {"character_count": None, "character_limit": None, "tier": "restricted"}
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ElevenLabs API key không hợp lệ",
        )
    if resp.status_code != 200:
        log.error(
            "ElevenLabs GET /user/subscription failed [%d]: %s",
            resp.status_code,
            resp.text[:300],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ElevenLabs error [{resp.status_code}]: {resp.text[:200]}",
        )
    data = resp.json()
    return {
        "character_count": data.get("character_count"),
        "character_limit": data.get("character_limit"),
        "tier": data.get("tier"),
    }


@router.get("/history")
def get_history(
    page_size: int = Query(default=100, ge=1, le=1000),
    voice_id: str = Query(default=""),
) -> dict:
    key = _api_key()
    params: dict[str, str | int] = {"page_size": page_size}
    if voice_id:
        params["voice_id"] = voice_id

    resp = requests.get(
        f"{ELEVENLABS_BASE}/history",
        headers=_el_headers(key),
        params=params,
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        log.error(
            "ElevenLabs GET /history failed [%d]: %s", resp.status_code, resp.text[:300]
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ElevenLabs error [{resp.status_code}]: {resp.text[:200]}",
        )
    return {"history": resp.json().get("history", [])}


@router.get("/history/{item_id}/audio")
def get_history_audio(item_id: str) -> StreamingResponse:
    key = _api_key()
    resp = requests.get(
        f"{ELEVENLABS_BASE}/history/{item_id}/audio",
        headers=_el_headers(key),
        timeout=_TIMEOUT,
        stream=True,
    )
    if resp.status_code != 200:
        log.error(
            "ElevenLabs GET /history/%s/audio failed [%d]: %s",
            item_id,
            resp.status_code,
            resp.text[:300],
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ElevenLabs error [{resp.status_code}]",
        )

    def _iter_content():
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                yield chunk

    return StreamingResponse(
        _iter_content(),
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'inline; filename="{item_id}.mp3"'},
    )

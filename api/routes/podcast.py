"""Podcast routes — outline, script, audio generation."""
from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter()

# In-memory map: audio_id → absolute Path of the rendered file (sufficient for MVP)
_AUDIO_STORE: dict[str, Path] = {}


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class OutlineRequest(BaseModel):
    topic: str
    num_parts: int = Field(default=3, ge=1, le=20)
    minutes_per_part: int = Field(default=10, ge=1, le=60)
    text_model: str = "gemini-2.5-flash"
    audience_level: str = "intermediate"
    tone: str = "conversational"
    continuous: bool = True
    show_name: str = ""
    channel_name: str = ""
    language: str = "en"


class PartBriefOut(BaseModel):
    index: int
    title: str
    summary: str
    key_points: list[str]


class OutlineOut(BaseModel):
    topic: str
    total_minutes: int
    parts: list[PartBriefOut]


class OutlineResponse(BaseModel):
    outline: OutlineOut


class ScriptRequest(BaseModel):
    outline: dict  # serialised Outline dict from a previous /outline call
    part_index: int = Field(ge=1)
    style: str = "podcast"
    text_model: str = "gemini-2.5-flash"
    audience_level: str = "intermediate"
    tone: str = "conversational"
    continuous: bool = True
    show_name: str = ""
    channel_name: str = ""
    num_speakers: int = Field(default=2, ge=1, le=9)
    host_names: list[str] = []
    language: str = "en"
    # Keys are part indices as strings; values are the readable script text
    previous_scripts: dict[str, str] = {}


class ScriptResponse(BaseModel):
    text: str


class ElevenLabsConfig(BaseModel):
    model_id: str = "eleven_flash_v2_5"
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0
    speed: float = 1.0
    use_speaker_boost: bool = True
    output_format: str = "mp3_44100_128"


class AudioRequest(BaseModel):
    part_index: int = Field(ge=1)
    script_text: str
    style: str = "podcast"
    topic: str = ""
    # For multi-speaker: one voice_id per speaker slot; single-speaker: list of one
    voices: list[str]
    el_config: ElevenLabsConfig = ElevenLabsConfig()


class AudioResponse(BaseModel):
    audio_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audio_dir() -> Path:
    from paths import HISTORY_DIR  # type: ignore[import]

    d = HISTORY_DIR / "api_audio"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _outline_dict_to_obj(data: dict):
    """Convert the serialised outline dict back to an Outline dataclass."""
    from podcast_studio.outline_generator import Outline, PartBrief

    parts = tuple(
        PartBrief(
            index=p["index"],
            title=p["title"],
            summary=p.get("summary", ""),
            key_points=tuple(p.get("key_points", [])),
        )
        for p in data.get("parts", [])
    )
    return Outline(
        topic=data.get("topic", ""),
        total_minutes=int(data.get("total_minutes", 0)),
        parts=parts,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/outline", response_model=OutlineResponse)
async def generate_outline(
    body: OutlineRequest,
    request: Request,
    current_user: Annotated[str, Depends(get_current_user)],
) -> OutlineResponse:
    from podcast_studio.outline_generator import generate_outline as _gen_outline

    genai_client = request.app.state.genai_client

    loop = asyncio.get_event_loop()
    try:
        outline = await loop.run_in_executor(
            None,
            lambda: _gen_outline(
                client=genai_client,
                topic=body.topic,
                num_parts=body.num_parts,
                minutes_per_part=body.minutes_per_part,
                text_model=body.text_model,
                audience_level=body.audience_level,
                tone=body.tone,
                continuous=body.continuous,
                show_name=body.show_name,
                channel_name=body.channel_name,
                language=body.language,
                usage_store=None,
            ),
        )
    except Exception as exc:
        log.exception("generate_outline failed for user %r, topic=%r", current_user, body.topic)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Outline generation failed: {exc}",
        ) from exc

    return OutlineResponse(
        outline=OutlineOut(
            topic=outline.topic,
            total_minutes=outline.total_minutes,
            parts=[
                PartBriefOut(
                    index=p.index,
                    title=p.title,
                    summary=p.summary,
                    key_points=list(p.key_points),
                )
                for p in outline.parts
            ],
        )
    )


@router.post("/script", response_model=ScriptResponse)
async def generate_script(
    body: ScriptRequest,
    request: Request,
    current_user: Annotated[str, Depends(get_current_user)],
) -> ScriptResponse:
    from podcast_studio.script_generator import (
        extract_tail_lines,
        generate_part_script,
    )

    genai_client = request.app.state.genai_client
    outline = _outline_dict_to_obj(body.outline)

    # Validate part_index
    if body.part_index < 1 or body.part_index > len(outline.parts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"part_index {body.part_index} out of range "
                f"(outline has {len(outline.parts)} parts)"
            ),
        )

    part = outline.parts[body.part_index - 1]
    total_parts = len(outline.parts)

    # Build previous context from previous_scripts
    previous_part_titles = tuple(
        outline.parts[i].title
        for i in range(body.part_index - 1)
    )
    previous_tail_lines: tuple[str, ...] = ()
    if body.previous_scripts:
        # Find the immediately preceding part's script text
        prev_key = str(body.part_index - 1)
        prev_text = body.previous_scripts.get(prev_key, "")
        if prev_text:
            previous_tail_lines = extract_tail_lines(prev_text, n=8)

    # Part kế tiếp (nếu có) — để câu chuyển cảnh hướng đúng chủ đề
    next_part = (
        outline.parts[body.part_index] if body.part_index < total_parts else None
    )

    minutes_per_part = (
        outline.total_minutes // total_parts if total_parts else outline.total_minutes
    )

    loop = asyncio.get_event_loop()
    try:
        script = await loop.run_in_executor(
            None,
            lambda: generate_part_script(
                client=genai_client,
                topic=outline.topic,
                style_key=body.style,
                part_index=body.part_index,
                total_parts=total_parts,
                target_minutes=minutes_per_part,
                part_title=part.title,
                part_summary=part.summary,
                key_points=part.key_points,
                previous_part_titles=previous_part_titles,
                previous_tail_lines=previous_tail_lines,
                next_part_title=next_part.title if next_part else "",
                next_part_summary=next_part.summary if next_part else "",
                text_model=body.text_model,
                audience_level=body.audience_level,
                tone=body.tone,
                continuous=body.continuous,
                show_name=body.show_name,
                channel_name=body.channel_name,
                num_speakers=body.num_speakers,
                host_names=tuple(body.host_names),
                language=body.language,
                usage_store=None,
            ),
        )
    except Exception as exc:
        log.exception(
            "generate_part_script failed for user %r, topic=%r, part=%d",
            current_user,
            outline.topic,
            body.part_index,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Script generation failed: {exc}",
        ) from exc

    return ScriptResponse(text=script.to_readable())


@router.post("/audio", response_model=AudioResponse)
async def render_audio(
    body: AudioRequest,
    request: Request,
    current_user: Annotated[str, Depends(get_current_user)],
) -> AudioResponse:
    from podcast_studio.script_generator import parse_script_text

    if not body.voices or all(not v for v in body.voices):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one voice_id must be provided in `voices`",
        )

    audio_id = str(uuid.uuid4())
    out_path = _audio_dir() / f"{audio_id}.wav"
    el_config = body.el_config.model_dump()

    loop = asyncio.get_event_loop()
    try:
        script = parse_script_text(body.topic, body.style, body.script_text)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse script text: {exc}",
        ) from exc

    try:
        if len(body.voices) == 1:
            from podcast_studio.elevenlabs_tts import render_single_voice

            rendered_path: Path = await loop.run_in_executor(
                None,
                lambda: render_single_voice(
                    script=script,
                    output_path=out_path,
                    voice_id=body.voices[0],
                    config=el_config,
                ),
            )
        else:
            from podcast_studio.elevenlabs_tts import render_multi_speaker

            rendered_path = await loop.run_in_executor(
                None,
                lambda: render_multi_speaker(
                    script=script,
                    output_path=out_path,
                    voice_ids=body.voices,
                    config=el_config,
                    progress_callback=None,
                ),
            )
    except Exception as exc:
        log.exception(
            "Audio render failed for user %r, audio_id=%s", current_user, audio_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Audio render failed: {exc}",
        ) from exc

    _AUDIO_STORE[audio_id] = rendered_path
    log.info(
        "Audio rendered: id=%s path=%s user=%r", audio_id, rendered_path, current_user
    )
    return AudioResponse(audio_id=audio_id)


@router.get("/audio/{audio_id}")
def get_audio(
    audio_id: str,
    current_user: Annotated[str, Depends(get_current_user)],
) -> FileResponse:
    path = _AUDIO_STORE.get(audio_id)
    if path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audio {audio_id!r} not found. It may have been lost after a server restart.",
        )
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Audio file for {audio_id!r} no longer exists on disk.",
        )

    # Determine media type from extension
    suffix = path.suffix.lower()
    media_type = "audio/mpeg" if suffix == ".mp3" else "audio/wav"
    return FileResponse(
        path=str(path),
        media_type=media_type,
        filename=f"podcast_part_{audio_id}{suffix}",
    )

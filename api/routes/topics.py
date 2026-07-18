"""Topics routes — /api/topics/suggest."""
from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter()


class SuggestRequest(BaseModel):
    topic: str = ""
    language: str = "en"
    count: int = Field(default=8, ge=1, le=30)
    text_model: str = "gemini-2.5-flash"
    audience_level: str = "intermediate"
    tone: str = ""


class SuggestResponse(BaseModel):
    suggestions: list[str]


@router.post("/suggest", response_model=SuggestResponse)
async def suggest_topics(
    body: SuggestRequest,
    request: Request,
    current_user: Annotated[str, Depends(get_current_user)],
) -> SuggestResponse:
    from podcast_studio.topic_suggester import suggest_topics as _suggest

    genai_client = request.app.state.genai_client

    loop = asyncio.get_event_loop()
    try:
        topics: list[str] = await loop.run_in_executor(
            None,
            lambda: _suggest(
                client=genai_client,
                audience_level=body.audience_level,
                count=body.count,
                text_model=body.text_model,
                seed_hint=body.topic,
                tone=body.tone,
                language=body.language,
                usage_store=None,
            ),
        )
    except Exception as exc:
        log.exception("suggest_topics failed for user %r", current_user)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Topic suggestion failed: {exc}",
        ) from exc

    return SuggestResponse(suggestions=topics)

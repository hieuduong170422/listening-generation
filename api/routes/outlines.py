"""Routes lịch sử dàn ý — lưu server-side theo user, giữ 7 ngày.

- GET    /api/podcast/outlines        → entries của user (admin: tất cả user)
- POST   /api/podcast/outlines        → upsert entry của user hiện tại
- DELETE /api/podcast/outlines/{id}   → xoá entry (admin xoá được của mọi người)
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import get_current_user, is_admin
from api import outline_store

log = logging.getLogger(__name__)
router = APIRouter()


class OutlineEntryIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    config: dict
    outline: dict
    scripts: dict[str, str] = {}
    audio_ids: dict[str, str] = {}


class OutlineListResponse(BaseModel):
    entries: list[dict]
    is_admin: bool


@router.get("/outlines", response_model=OutlineListResponse)
def list_outlines(
    current_user: Annotated[str, Depends(get_current_user)],
) -> OutlineListResponse:
    admin = is_admin(current_user)
    try:
        entries = outline_store.list_entries(current_user, include_all=admin)
    except Exception:
        log.exception("list_entries failed for user %r", current_user)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không đọc được lịch sử dàn ý",
        )
    return OutlineListResponse(entries=entries, is_admin=admin)


@router.post("/outlines")
def upsert_outline(
    body: OutlineEntryIn,
    current_user: Annotated[str, Depends(get_current_user)],
) -> dict:
    if not isinstance(body.outline.get("parts"), list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="outline.parts phải là mảng",
        )
    try:
        outline_store.upsert_entry(
            username=current_user,
            entry_id=body.id,
            payload={
                "config": body.config,
                "outline": body.outline,
                "scripts": body.scripts,
                "audio_ids": body.audio_ids,
            },
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Entry này thuộc user khác",
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        log.exception("upsert_entry failed for user %r, id=%s", current_user, body.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không lưu được lịch sử dàn ý",
        )
    return {"ok": True}


@router.delete("/outlines/{entry_id}")
def delete_outline(
    entry_id: str,
    current_user: Annotated[str, Depends(get_current_user)],
) -> dict:
    try:
        found = outline_store.delete_entry(
            entry_id, username=current_user, is_admin=is_admin(current_user)
        )
    except PermissionError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Không có quyền xoá entry này",
        )
    except Exception:
        log.exception("delete_entry failed for user %r, id=%s", current_user, entry_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Không xoá được entry",
        )
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy entry")
    return {"ok": True}

"""Affiliate (UGC video) routes — storyboard generation, clip rendering, final stitch."""
from __future__ import annotations

import asyncio
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from api.auth import get_current_user

log = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# In-memory job store + thread pool
# ---------------------------------------------------------------------------

_JOBS: dict[str, dict] = {}
_executor = ThreadPoolExecutor(max_workers=4)

_SESSION_BASE = Path("/tmp/affiliate_sessions")


# ---------------------------------------------------------------------------
# Pydantic models for JSON-body endpoints
# ---------------------------------------------------------------------------


class ClipRequest(BaseModel):
    session_id: str
    clip_index: int = Field(ge=0)


class StitchRequest(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Session / disk helpers
# ---------------------------------------------------------------------------


def _session_dir(session_id: str) -> Path:
    d = _SESSION_BASE / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _find_session_result(session_id: str) -> dict | None:
    """Search _JOBS for the completed storyboard result that owns session_id."""
    for job in _JOBS.values():
        if job.get("type") != "storyboard":
            continue
        result = job.get("result")
        if result and result.get("session_id") == session_id:
            return result
    return None


def _load_product_images(session_id: str) -> list[tuple[bytes, str]]:
    """Load all saved product images from disk, sorted by filename."""
    prod_dir = _SESSION_BASE / session_id / "product_images"
    if not prod_dir.exists():
        return []
    return [
        (path.read_bytes(), "image/png")
        for path in sorted(prod_dir.glob("product_*.png"))
    ]


def _load_frames(session_id: str, clip_index: int) -> list[bytes]:
    """Load frame images for a given clip from disk."""
    sess_dir = _SESSION_BASE / session_id
    frames: list[bytes] = []
    frame_idx = 0
    while True:
        path = sess_dir / f"frame_{clip_index}_{frame_idx}.png"
        if not path.exists():
            break
        frames.append(path.read_bytes())
        frame_idx += 1
    return frames


# ---------------------------------------------------------------------------
# Background functions (run inside the thread pool)
# ---------------------------------------------------------------------------


def _bg_storyboard(
    job_id: str,
    session_id: str,
    product_images: list[tuple[bytes, str]],
    idea: str,
    directions: str,
    clips: int,
    beats_per_clip: int,
    client,
) -> None:
    from podcast_studio.affiliate import generate_storyboard_set

    _JOBS[job_id]["status"] = "running"
    _JOBS[job_id]["message"] = "Planning scenes..."

    try:
        sess_dir = _session_dir(session_id)

        # Persist product images so clip/stitch jobs can reload them later
        prod_dir = sess_dir / "product_images"
        prod_dir.mkdir(parents=True, exist_ok=True)
        for i, (data, _) in enumerate(product_images):
            (prod_dir / f"product_{i}.png").write_bytes(data)

        _JOBS[job_id]["progress"] = 0.05

        result = generate_storyboard_set(
            client,
            product_images=product_images,
            scene_images=[],
            idea=idea,
            clips=clips,
            beats_per_clip=beats_per_clip,
            directions=directions,
        )

        product: str = result["product"]
        (sess_dir / "product.txt").write_text(product, encoding="utf-8")

        raw_items: list[dict] = result.get("items") or []
        n = max(len(raw_items), 1)
        items_out: list[dict] = []

        for i, item in enumerate(raw_items):
            # Persist storyboard grid image
            img_bytes: bytes | None = item.get("image")
            if img_bytes:
                (sess_dir / f"storyboard_{i}.png").write_bytes(img_bytes)

            # Persist individual frame images
            frames: list[bytes] = item.get("frames") or []
            for j, frame in enumerate(frames):
                if frame:
                    (sess_dir / f"frame_{i}_{j}.png").write_bytes(frame)

            items_out.append(
                {
                    "index": i,
                    "scenes": item.get("scenes") or [],
                    "prompt": item.get("prompt") or "",
                    # List of frame indices — JSON-serializable proxy for frame count
                    "frames": list(range(len(frames))),
                    "has_image": img_bytes is not None,
                    "has_video": False,
                    "error": item.get("error"),
                }
            )

            _JOBS[job_id]["progress"] = 0.1 + 0.85 * (i + 1) / n

        _JOBS[job_id]["status"] = "done"
        _JOBS[job_id]["progress"] = 1.0
        _JOBS[job_id]["message"] = f"Storyboard complete — {len(items_out)} clip(s)"
        _JOBS[job_id]["result"] = {
            "session_id": session_id,
            "product": product,
            "items": items_out,
        }

    except Exception as exc:
        log.exception("_bg_storyboard failed for job %s", job_id)
        _JOBS[job_id]["status"] = "error"
        _JOBS[job_id]["error"] = str(exc)
        _JOBS[job_id]["message"] = f"Failed: {exc}"


def _bg_clip(
    job_id: str,
    session_id: str,
    clip_index: int,
    client,
) -> None:
    from podcast_studio.affiliate import generate_clip_from_storyboard

    _JOBS[job_id]["status"] = "running"
    _JOBS[job_id]["message"] = f"Rendering clip {clip_index}..."

    try:
        sess_dir = _session_dir(session_id)

        sb_result = _find_session_result(session_id)
        if sb_result is None:
            raise RuntimeError(
                f"Storyboard result not found for session {session_id!r}. "
                "Run /storyboard first and wait for it to complete."
            )

        items = sb_result.get("items") or []
        if clip_index >= len(items):
            raise RuntimeError(
                f"clip_index {clip_index} out of range "
                f"(storyboard has {len(items)} item(s))"
            )

        item = items[clip_index]
        product: str = sb_result["product"]
        scenes: list[str] = item.get("scenes") or []

        product_images = _load_product_images(session_id)
        frames = _load_frames(session_id, clip_index)

        storyboard_path = sess_dir / f"storyboard_{clip_index}.png"
        storyboard_image: bytes | None = (
            storyboard_path.read_bytes() if storyboard_path.exists() else None
        )

        _JOBS[job_id]["progress"] = 0.1
        _JOBS[job_id]["message"] = (
            f"Generating clip {clip_index} ({len(scenes)} scene(s))..."
        )

        video_bytes = generate_clip_from_storyboard(
            client,
            product_images=product_images,
            scene_images=[],
            product=product,
            scenes=scenes,
            frames=frames or None,
            storyboard_image=storyboard_image,
        )

        clip_path = sess_dir / f"clip_{clip_index}.mp4"
        clip_path.write_bytes(video_bytes)

        # Mark clip as rendered in the shared storyboard result
        item["has_video"] = True

        _JOBS[job_id]["status"] = "done"
        _JOBS[job_id]["progress"] = 1.0
        _JOBS[job_id]["message"] = f"Clip {clip_index} rendered"
        _JOBS[job_id]["result"] = {"session_id": session_id, "clip_index": clip_index}

    except Exception as exc:
        log.exception("_bg_clip failed for job %s clip %d", job_id, clip_index)
        _JOBS[job_id]["status"] = "error"
        _JOBS[job_id]["error"] = str(exc)
        _JOBS[job_id]["message"] = f"Failed: {exc}"


def _bg_stitch(
    job_id: str,
    session_id: str,
    client,
) -> None:
    from podcast_studio.affiliate import _stitch_videos, generate_clip_from_storyboard

    _JOBS[job_id]["status"] = "running"
    _JOBS[job_id]["message"] = "Preparing clips..."

    try:
        sess_dir = _session_dir(session_id)

        sb_result = _find_session_result(session_id)
        if sb_result is None:
            raise RuntimeError(
                f"Storyboard result not found for session {session_id!r}. "
                "Run /storyboard first and wait for it to complete."
            )

        items = sb_result.get("items") or []
        if not items:
            raise RuntimeError("No storyboard items found — run /storyboard first.")

        product: str = sb_result["product"]
        product_images = _load_product_images(session_id)
        all_clips: list[bytes] = []
        n = max(len(items), 1)

        for i, item in enumerate(items):
            clip_path = sess_dir / f"clip_{i}.mp4"

            if clip_path.exists():
                log.info("Stitch: loaded existing clip %d from disk", i)
                all_clips.append(clip_path.read_bytes())
            else:
                log.info("Stitch: clip %d missing — rendering now", i)
                _JOBS[job_id]["message"] = f"Rendering missing clip {i + 1}/{len(items)}..."

                frames = _load_frames(session_id, i)
                storyboard_path = sess_dir / f"storyboard_{i}.png"
                storyboard_image: bytes | None = (
                    storyboard_path.read_bytes() if storyboard_path.exists() else None
                )
                scenes: list[str] = item.get("scenes") or []

                video_bytes = generate_clip_from_storyboard(
                    client,
                    product_images=product_images,
                    scene_images=[],
                    product=product,
                    scenes=scenes,
                    frames=frames or None,
                    storyboard_image=storyboard_image,
                )
                clip_path.write_bytes(video_bytes)
                item["has_video"] = True
                all_clips.append(video_bytes)

            _JOBS[job_id]["progress"] = 0.1 + 0.75 * (i + 1) / n

        _JOBS[job_id]["message"] = "Stitching clips into final video..."
        _JOBS[job_id]["progress"] = 0.88

        final_bytes = _stitch_videos(all_clips)
        (sess_dir / "final.mp4").write_bytes(final_bytes)

        _JOBS[job_id]["status"] = "done"
        _JOBS[job_id]["progress"] = 1.0
        _JOBS[job_id]["message"] = "Final video ready"
        _JOBS[job_id]["result"] = {"session_id": session_id}

    except Exception as exc:
        log.exception("_bg_stitch failed for job %s", job_id)
        _JOBS[job_id]["status"] = "error"
        _JOBS[job_id]["error"] = str(exc)
        _JOBS[job_id]["message"] = f"Failed: {exc}"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/storyboard")
async def start_storyboard(
    request: Request,
    current_user: Annotated[str, Depends(get_current_user)],
    images: list[UploadFile] = File(...),
    idea: str = Form(...),
    clips: int = Form(default=3),
    beats_per_clip: int = Form(default=2),
    directions: str = Form(default=""),
) -> dict:
    """Upload product images and kick off storyboard generation."""
    # Storyboard chỉ gọi text + sinh ảnh → dùng global endpoint (quota rộng hơn
    # hẳn 1 region, đỡ 429 RESOURCE_EXHAUSTED). Veo ở /clip vẫn dùng client region.
    client = (
        getattr(request.app.state, "genai_client_global", None)
        or request.app.state.genai_client
    )

    if not images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one product image is required.",
        )

    product_images: list[tuple[bytes, str]] = []
    for f in images:
        data = await f.read()
        mime = f.content_type or "image/png"
        product_images.append((data, mime))

    session_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())

    _JOBS[job_id] = {
        "type": "storyboard",
        "status": "pending",
        "progress": 0.0,
        "message": "Queued",
        "result": None,
        "error": None,
    }

    asyncio.get_event_loop().run_in_executor(
        _executor,
        _bg_storyboard,
        job_id,
        session_id,
        product_images,
        idea,
        directions,
        clips,
        beats_per_clip,
        client,
    )

    log.info(
        "Storyboard job %s queued — user=%r session=%s clips=%d beats=%d",
        job_id,
        current_user,
        session_id,
        clips,
        beats_per_clip,
    )
    return {"job_id": job_id, "session_id": session_id}


@router.post("/clip")
async def start_clip(
    body: ClipRequest,
    request: Request,
    current_user: Annotated[str, Depends(get_current_user)],
) -> dict:
    """Render a single clip for the given session and clip index."""
    client = request.app.state.genai_client

    sb_result = _find_session_result(body.session_id)
    if sb_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Storyboard for session {body.session_id!r} not found. "
                "Run /storyboard first and wait for it to complete."
            ),
        )

    items = sb_result.get("items") or []
    if body.clip_index >= len(items):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"clip_index {body.clip_index} out of range "
                f"(storyboard has {len(items)} item(s))"
            ),
        )

    job_id = str(uuid.uuid4())
    _JOBS[job_id] = {
        "type": "clip",
        "status": "pending",
        "progress": 0.0,
        "message": "Queued",
        "result": None,
        "error": None,
    }

    asyncio.get_event_loop().run_in_executor(
        _executor,
        _bg_clip,
        job_id,
        body.session_id,
        body.clip_index,
        client,
    )

    log.info(
        "Clip job %s queued — user=%r session=%s clip_index=%d",
        job_id,
        current_user,
        body.session_id,
        body.clip_index,
    )
    return {"job_id": job_id}


@router.post("/stitch")
async def start_stitch(
    body: StitchRequest,
    request: Request,
    current_user: Annotated[str, Depends(get_current_user)],
) -> dict:
    """Stitch all clips for a session into a final video (renders missing clips first)."""
    client = request.app.state.genai_client

    sb_result = _find_session_result(body.session_id)
    if sb_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Storyboard for session {body.session_id!r} not found. "
                "Run /storyboard first and wait for it to complete."
            ),
        )

    job_id = str(uuid.uuid4())
    _JOBS[job_id] = {
        "type": "stitch",
        "status": "pending",
        "progress": 0.0,
        "message": "Queued",
        "result": None,
        "error": None,
    }

    asyncio.get_event_loop().run_in_executor(
        _executor,
        _bg_stitch,
        job_id,
        body.session_id,
        client,
    )

    log.info(
        "Stitch job %s queued — user=%r session=%s",
        job_id,
        current_user,
        body.session_id,
    )
    return {"job_id": job_id}


@router.get("/job/{job_id}")
def get_job(
    job_id: str,
    current_user: Annotated[str, Depends(get_current_user)],
) -> dict:
    """Poll job status and retrieve the result when done."""
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id!r} not found.",
        )
    return job


# ---------------------------------------------------------------------------
# File download endpoints
# ---------------------------------------------------------------------------


@router.get("/file/{session_id}/storyboard/{index}")
def get_storyboard_image(
    session_id: str,
    index: int,
    current_user: Annotated[str, Depends(get_current_user)],
) -> FileResponse:
    """Download the storyboard grid image for a clip."""
    path = _SESSION_BASE / session_id / f"storyboard_{index}.png"
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Storyboard image {index} not found for session {session_id!r}. "
                "The storyboard job may not have completed yet."
            ),
        )
    return FileResponse(
        path=str(path),
        media_type="image/png",
        filename=f"storyboard_{index}.png",
    )


@router.get("/file/{session_id}/clip/{index}")
def get_clip(
    session_id: str,
    index: int,
    current_user: Annotated[str, Depends(get_current_user)],
) -> FileResponse:
    """Download a rendered clip video."""
    path = _SESSION_BASE / session_id / f"clip_{index}.mp4"
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Clip {index} not found for session {session_id!r}. "
                "Run /clip to render it first."
            ),
        )
    return FileResponse(
        path=str(path),
        media_type="video/mp4",
        filename=f"clip_{index}.mp4",
    )


@router.get("/file/{session_id}/final")
def get_final(
    session_id: str,
    current_user: Annotated[str, Depends(get_current_user)],
) -> FileResponse:
    """Download the final stitched video."""
    path = _SESSION_BASE / session_id / "final.mp4"
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Final video not found for session {session_id!r}. "
                "Run /stitch first and wait for it to complete."
            ),
        )
    return FileResponse(
        path=str(path),
        media_type="video/mp4",
        filename="final.mp4",
    )


@router.get("/file/{session_id}/prompts")
def get_prompts(
    session_id: str,
    current_user: Annotated[str, Depends(get_current_user)],
) -> PlainTextResponse:
    """Download all clip prompts as a plain-text attachment."""
    sb_result = _find_session_result(session_id)
    if sb_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Storyboard for session {session_id!r} not found. "
                "Run /storyboard first and wait for it to complete."
            ),
        )

    items = sb_result.get("items") or []
    lines: list[str] = [
        f"Product: {sb_result.get('product', '')}",
        f"Session: {session_id}",
        "",
    ]

    for item in items:
        clip_num = item["index"] + 1
        lines.append(f"{'=' * 40}")
        lines.append(f"Clip {clip_num}")
        lines.append(f"{'=' * 40}")
        scenes: list[str] = item.get("scenes") or []
        for j, scene in enumerate(scenes, 1):
            lines.append(f"  Scene {j}: {scene}")
        lines.append("")
        lines.append(item.get("prompt") or "")
        lines.append("")

    return PlainTextResponse(
        content="\n".join(lines),
        headers={
            "Content-Disposition": 'attachment; filename="prompts.txt"',
        },
    )

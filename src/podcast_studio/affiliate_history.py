"""Log lịch sử query của Affiliate Gen Video (UGC).

Chỉ lưu thông tin TEXT quan trọng (idea, directions, cấu hình, tên sản phẩm,
scenes, prompt EN, model/engine). KHÔNG lưu bytes ảnh/video cho đỡ nặng —
chỉ ghi lại kích thước (bytes) của video render được.

Định dạng JSONL (mỗi dòng 1 event), giống usage_logger.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_LOG_PATH = Path(os.getenv("AFFILIATE_LOG_PATH", "history/affiliate_log.jsonl"))
_LOG_LOCK = threading.Lock()


def log_path() -> Path:
    return _DEFAULT_LOG_PATH


def _write(entry: dict, path: Path | None = None) -> None:
    entry["ts"] = datetime.now(timezone.utc).isoformat()
    p = path or _DEFAULT_LOG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_LOCK:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_storyboard(
    *,
    idea: str = "",
    directions: str = "",
    clips: int = 0,
    beats_per_clip: int = 0,
    product: str = "",
    engine: str = "",
    image_model: str = "",
    items: list[dict] | None = None,
    user: str = "",
    path: Path | None = None,
) -> None:
    """Ghi lại 1 lần sinh storyboard-set. Bỏ qua bytes ảnh (image/frames),
    chỉ giữ scenes + prompt EN của từng clip."""
    clips_detail = []
    for i, it in enumerate(items or [], start=1):
        clips_detail.append({
            "index": i,
            "scenes": it.get("scenes") or [],
            "prompt": it.get("prompt") or "",
            "frames": len(it.get("frames") or []),  # số frame, không lưu bytes
        })
    _write({
        "event": "storyboard",
        "user": user or "anonymous",
        "engine": engine,
        "image_model": image_model,
        "idea": idea,
        "directions": directions,
        "clips": int(clips),
        "beats_per_clip": int(beats_per_clip),
        "product": product,
        "clips_detail": clips_detail,
    }, path=path)


def log_video(
    *,
    product: str = "",
    engine: str = "",
    clip_index: int | None = None,
    scenes: list[str] | None = None,
    prompt: str = "",
    video_bytes: int = 0,
    final: bool = False,
    user: str = "",
    path: Path | None = None,
) -> None:
    """Ghi lại 1 lần render clip/video Veo. KHÔNG lưu mp4, chỉ lưu kích thước."""
    scenes = scenes or []
    _write({
        "event": "video_final" if final else "video_clip",
        "user": user or "anonymous",
        "engine": engine,
        "product": product,
        "clip_index": clip_index,
        "scenes": scenes,
        "prompt": prompt,
        "duration_s": len(scenes) * 4 if scenes else None,
        "video_bytes": int(video_bytes),
    }, path=path)


def read_history(path: Path | None = None) -> list[dict]:
    p = path or _DEFAULT_LOG_PATH
    if not p.exists():
        return []
    out: list[dict] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out

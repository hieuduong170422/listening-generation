from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _require_ffmpeg() -> None:
    if not ffmpeg_available():
        raise RuntimeError(
            "Chưa cài ffmpeg. Mở terminal chạy:  brew install ffmpeg"
        )


def build_part_video(
    image_path: Path,
    audio_path: Path,
    out_path: Path,
    width: int = 1920,
    height: int = 1080,
) -> Path:
    """Ghép 1 ảnh tĩnh + 1 file audio thành MP4 (ảnh hiện suốt thời lượng audio)."""
    _require_ffmpeg()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
    )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
        "-vf", vf, "-r", "25",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg lỗi khi tạo video:\n{result.stderr[-600:]}")
    return out_path


def concat_videos(video_paths: list[Path], out_path: Path) -> Path:
    """Nối nhiều MP4 thành 1. Re-encode để đảm bảo khớp codec."""
    _require_ffmpeg()
    if not video_paths:
        raise ValueError("Không có video nào để ghép.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = out_path.parent / f"{out_path.stem}_concat.txt"
    list_file.write_text(
        "\n".join(f"file '{Path(v).resolve()}'" for v in video_paths),
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    list_file.unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg lỗi khi ghép video:\n{result.stderr[-600:]}")
    return out_path

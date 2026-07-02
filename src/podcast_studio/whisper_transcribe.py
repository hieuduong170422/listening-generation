"""Local speech-to-text bằng faster-whisper — sinh phụ đề không cần script.

Khác với ``subtitle_gen.generate_srt`` (guided ASR, BẮT BUỘC có sẵn kịch bản
``Speaker1:``/``Speaker2:`` để align), module này làm *blind* ASR: nghe audio
rồi tự nhận diện lời nói. Nhờ vậy nó chạy được cho MỌI video/audio — kể cả
video tải về, video quay tay, hay file không có script.

Ưu điểm:
- Chạy 100% local trên máy (CPU), miễn phí, không giới hạn, không cần API key.
- Trả về timestamp theo từng câu VÀ theo từng từ (word-level) → dùng làm hiệu
  ứng highlight từng từ kiểu CapCut/TikTok.

Output (mặc định lưu cùng thư mục input):
- ``<tên>.srt``        → import thẳng vào CapCut / burn-in bằng ffmpeg.
- ``<tên>.json``       → transcript theo câu (segment) + metadata.
- ``<tên>.words.json`` → timestamp từng từ để làm hiệu ứng highlight.

CLI:
    python -m podcast_studio.whisper_transcribe input.mp4
    python -m podcast_studio.whisper_transcribe input.mp4 --language vi --model medium
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# faster-whisper là CTranslate2 nên trên Mac chỉ chạy CPU (int8 = nhanh + nhẹ RAM).
# Cho phép override qua env để tùy máy (vd máy khỏe dùng "large-v3").
_DEFAULT_MODEL = os.getenv("WHISPER_MODEL", "medium").strip() or "medium"
_DEFAULT_DEVICE = os.getenv("WHISPER_DEVICE", "cpu").strip() or "cpu"
_DEFAULT_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"

# Cân bằng tốc độ/độ chính xác. Với tiếng Việt "medium" là điểm ngọt.
MODEL_OPTIONS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]

# Cache model theo (name, device, compute_type) để lần gen thứ 2 không phải nạp
# lại (nạp model medium mất vài giây + vài trăm MB).
_MODEL_CACHE: dict[tuple[str, str, str], object] = {}


@dataclass
class Word:
    word: str
    start: float
    end: float
    probability: float = 0.0

    def to_dict(self) -> dict:
        return {
            "word": self.word,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "probability": round(self.probability, 4),
        }


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "text": self.text,
            "words": [w.to_dict() for w in self.words],
        }


@dataclass
class Transcript:
    language: str
    duration: float
    segments: list[Segment]

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments).strip()

    @property
    def words(self) -> list[Word]:
        out: list[Word] = []
        for s in self.segments:
            out.extend(s.words)
        return out

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "duration": round(self.duration, 3),
            "text": self.text,
            "segments": [s.to_dict() for s in self.segments],
        }


def _get_model(model_size: str, device: str, compute_type: str):
    """Nạp (hoặc lấy từ cache) một ``WhisperModel``."""
    key = (model_size, device, compute_type)
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:  # pragma: no cover - phụ thuộc môi trường
        raise RuntimeError(
            "Chưa cài faster-whisper. Chạy:  pip install faster-whisper"
        ) from e
    log.info(
        "whisper | nạp model=%s device=%s compute=%s (lần đầu tải model có thể mất vài phút)",
        model_size, device, compute_type,
    )
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    _MODEL_CACHE[key] = model
    return model


def _seconds_to_srt_time(t: float) -> str:
    """`12.345` → `00:00:12,345` (định dạng thời gian SRT)."""
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms >= 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcript_to_srt(transcript: Transcript) -> str:
    """Render transcript thành nội dung file .srt (theo từng câu)."""
    blocks = []
    for i, seg in enumerate(transcript.segments, start=1):
        text = seg.text.strip()
        if not text:
            continue
        blocks.append(
            f"{i}\n"
            f"{_seconds_to_srt_time(seg.start)} --> {_seconds_to_srt_time(seg.end)}\n"
            f"{text}\n"
        )
    return "\n".join(blocks)


def transcribe(
    media_path: Path | str,
    language: str | None = "vi",
    model_size: str = _DEFAULT_MODEL,
    device: str = _DEFAULT_DEVICE,
    compute_type: str = _DEFAULT_COMPUTE_TYPE,
    word_timestamps: bool = True,
    vad_filter: bool = True,
    beam_size: int = 5,
) -> Transcript:
    """Nhận diện lời nói trong 1 file audio/video bằng faster-whisper.

    faster-whisper tự decode audio từ file (kể cả .mp4, .mov, .mkv) nên KHÔNG
    cần tách audio trước bằng ffmpeg.

    Args:
        media_path: đường dẫn file audio hoặc video.
        language: mã ngôn ngữ (``"vi"``, ``"en"``…). ``None`` = tự nhận diện.
        model_size: tiny/base/small/medium/large-v3/large-v3-turbo.
        device: "cpu" (mặc định, hợp với Mac) hoặc "cuda".
        compute_type: "int8" (nhẹ, nhanh) / "int8_float16" / "float16".
        word_timestamps: xuất timestamp từng từ (cho hiệu ứng highlight).
        vad_filter: lọc khoảng lặng (bỏ đoạn không có tiếng nói) → nhanh + gọn.
        beam_size: beam search; cao hơn = chính xác hơn, chậm hơn.

    Returns:
        ``Transcript`` gồm segments (câu) và words (từ) đã có timestamp.
    """
    media_path = Path(media_path)
    if not media_path.exists():
        raise FileNotFoundError(f"File không tồn tại: {media_path}")

    model = _get_model(model_size, device, compute_type)

    log.info(
        "whisper | transcribe %s (lang=%s model=%s)",
        media_path.name, language or "auto", model_size,
    )
    seg_iter, info = model.transcribe(
        str(media_path),
        language=language,
        word_timestamps=word_timestamps,
        vad_filter=vad_filter,
        beam_size=beam_size,
    )

    segments: list[Segment] = []
    # seg_iter là generator — việc lặp mới thực sự chạy nhận diện.
    for seg in seg_iter:
        words: list[Word] = []
        for w in (seg.words or []):
            words.append(Word(
                word=w.word,
                start=float(w.start),
                end=float(w.end),
                probability=float(getattr(w, "probability", 0.0) or 0.0),
            ))
        segments.append(Segment(
            start=float(seg.start),
            end=float(seg.end),
            text=seg.text.strip(),
            words=words,
        ))

    return Transcript(
        language=getattr(info, "language", language or "unknown"),
        duration=float(getattr(info, "duration", 0.0) or 0.0),
        segments=segments,
    )


def generate_srt(
    media_path: Path | str,
    output_path: Path | str | None = None,
    language: str | None = "vi",
    model_size: str = _DEFAULT_MODEL,
    also_write_json: bool = False,
    **kwargs,
) -> Path:
    """Convenience: transcribe rồi ghi thẳng ra file .srt.

    Trả về đường dẫn file .srt. Nếu ``also_write_json=True`` thì ghi thêm
    ``.json`` (câu) và ``.words.json`` (từng từ) cùng thư mục.
    """
    media_path = Path(media_path)
    if output_path is None:
        output_path = media_path.with_suffix(".srt")
    output_path = Path(output_path)

    transcript = transcribe(
        media_path, language=language, model_size=model_size, **kwargs
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(transcript_to_srt(transcript), encoding="utf-8")

    if also_write_json:
        write_json_outputs(transcript, output_path.with_suffix(""))

    return output_path


def write_json_outputs(transcript: Transcript, base_path: Path | str) -> dict[str, Path]:
    """Ghi ``<base>.json`` (segments) và ``<base>.words.json`` (word-level).

    ``base_path`` là đường dẫn KHÔNG có đuôi, vd ``.../history/foo_part1``.
    Trả về dict {"json": ..., "words": ...}.
    """
    base_path = Path(base_path)
    base_path.parent.mkdir(parents=True, exist_ok=True)

    json_path = base_path.with_suffix(".json")
    words_path = base_path.with_name(base_path.name + ".words.json")

    json_path.write_text(
        json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    words_path.write_text(
        json.dumps(
            [w.to_dict() for w in transcript.words],
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return {"json": json_path, "words": words_path}


def _cli(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m podcast_studio.whisper_transcribe",
        description="Sinh phụ đề (.srt/.json/.words.json) từ video/audio bằng faster-whisper (local).",
    )
    parser.add_argument("input", help="File audio hoặc video (.mp4, .mp3, .wav…)")
    parser.add_argument("--language", "-l", default="vi", help="Mã ngôn ngữ, vd vi/en. 'auto' = tự nhận diện.")
    parser.add_argument("--model", "-m", default=_DEFAULT_MODEL, choices=MODEL_OPTIONS)
    parser.add_argument("--device", default=_DEFAULT_DEVICE, help="cpu | cuda")
    parser.add_argument("--compute-type", default=_DEFAULT_COMPUTE_TYPE)
    parser.add_argument("--no-words", action="store_true", help="Bỏ qua word-level timestamps.")
    parser.add_argument("--srt-only", action="store_true", help="Chỉ xuất .srt, không xuất .json/.words.json.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    src = Path(args.input)
    language = None if args.language.lower() == "auto" else args.language

    transcript = transcribe(
        src,
        language=language,
        model_size=args.model,
        device=args.device,
        compute_type=args.compute_type,
        word_timestamps=not args.no_words,
    )

    srt_path = src.with_suffix(".srt")
    srt_path.write_text(transcript_to_srt(transcript), encoding="utf-8")
    print(f"✓ {srt_path}")

    if not args.srt_only:
        outs = write_json_outputs(transcript, src.with_suffix(""))
        print(f"✓ {outs['json']}")
        print(f"✓ {outs['words']}")

    print(
        f"Done — lang={transcript.language} "
        f"duration={transcript.duration:.1f}s segments={len(transcript.segments)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

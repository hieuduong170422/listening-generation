import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from podcast_studio.config import AVAILABLE_VOICES, DEFAULT_SPEAKER_1, DEFAULT_SPEAKER_2, STYLES
from podcast_studio.multi_part import load_outline, run_multi_part
from podcast_studio.script_generator import generate_script
from podcast_studio.tts_renderer import render_script
from podcast_studio.unified_podcast_generator import run_unified_podcast

ROOT = Path(__file__).resolve().parent
HISTORY_DIR = ROOT / "history"


def _slug(text: str, max_len: int = 40) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


def _validate_voice(name: str) -> str:
    if name not in AVAILABLE_VOICES:
        raise SystemExit(
            f"Voice không hợp lệ: {name}\nDanh sách hợp lệ:\n  " + ", ".join(AVAILABLE_VOICES)
        )
    return name


def _prompt_choice(label: str, options: list[str], default_index: int = 0) -> str:
    print(f"\n{label}")
    for i, opt in enumerate(options, 1):
        marker = " (mặc định)" if i - 1 == default_index else ""
        print(f"  [{i}] {opt}{marker}")
    raw = input("Chọn số (Enter dùng mặc định): ").strip()
    if not raw:
        return options[default_index]
    try:
        idx = int(raw) - 1
        return options[idx]
    except (ValueError, IndexError):
        print("Không hợp lệ — dùng mặc định.")
        return options[default_index]


def _interactive_inputs() -> dict:
    topic = input("\nNhập CHỦ ĐỀ: ").strip()
    if not topic:
        raise SystemExit("Chủ đề không được để trống.")

    style_keys = list(STYLES.keys())
    style_labels = [f"{k} — {STYLES[k].label}" for k in style_keys]
    style_choice = _prompt_choice("Chọn kiểu kịch bản:", style_labels, 0)
    style = style_keys[style_labels.index(style_choice)]

    return {"topic": topic, "style": style, "speaker1": DEFAULT_SPEAKER_1, "speaker2": DEFAULT_SPEAKER_2}


def main() -> None:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description="Sinh kịch bản đối thoại + render TTS bằng Gemini.")
    parser.add_argument("--topic", help="Chủ đề kịch bản (nếu không truyền sẽ hỏi tương tác).")
    parser.add_argument("--style", choices=list(STYLES.keys()), help="Kiểu kịch bản.")
    parser.add_argument("--speaker1", default=DEFAULT_SPEAKER_1, help=f"Voice cho Speaker1 (mặc định {DEFAULT_SPEAKER_1}).")
    parser.add_argument("--speaker2", default=DEFAULT_SPEAKER_2, help=f"Voice cho Speaker2 (mặc định {DEFAULT_SPEAKER_2}).")
    parser.add_argument("--out", help="Đường dẫn file WAV output (mặc định: history/<slug>_<timestamp>.wav).")
    parser.add_argument("--multi", action="store_true", help="Chạy chế độ nhiều part (long-form podcast).")
    parser.add_argument("--unified", action="store_true", help="Chạy unified pipeline (Gemini script + ElevenLabs audio + Whisper subs).")
    parser.add_argument("--parts", type=int, default=10, help="Số part khi --multi hoặc --unified (mặc định 10).")
    parser.add_argument("--minutes-per-part", type=int, default=4, help="Phút mỗi part khi --multi (mặc định 4).")
    parser.add_argument("--generate-subs", action="store_true", help="Tạo phụ đề Whisper (chỉ dùng khi --unified).")
    parser.add_argument("--only", help="Chỉ chạy 1 số part, vd: --only 2,4 (cần --reuse-outline).")
    parser.add_argument("--reuse-outline", help="Đường dẫn outline.json đã có để regen part mà không gen lại outline.")
    args = parser.parse_args()

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("Thiếu GEMINI_API_KEY. Tạo file .env (xem .env.example).")

    if args.topic and args.style:
        params = {"topic": args.topic, "style": args.style, "speaker1": args.speaker1, "speaker2": args.speaker2}
    else:
        params = _interactive_inputs()
        params["speaker1"] = args.speaker1
        params["speaker2"] = args.speaker2

    _validate_voice(params["speaker1"])
    _validate_voice(params["speaker2"])

    client = genai.Client(api_key=api_key)

    if args.unified:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_slug = f"{_slug(params['topic'])}_{timestamp}"
        only_parts: tuple[int, ...] = ()
        if args.only:
            only_parts = tuple(int(x.strip()) for x in args.only.split(",") if x.strip())

        existing_outline = None
        if args.reuse_outline:
            outline_path = Path(args.reuse_outline)
            existing_outline = load_outline(outline_path)
            base_slug = outline_path.stem.replace("_outline", "")
            print(f"→ Reusing outline: {outline_path}")

        result = run_unified_podcast(
            client=client,
            topic=params["topic"],
            style_key=params["style"],
            speaker1=params["speaker1"],
            speaker2=params["speaker2"],
            num_parts=args.parts,
            minutes_per_part=args.minutes_per_part,
            output_dir=HISTORY_DIR,
            base_slug=base_slug,
            generate_subtitles=args.generate_subs,
            only_parts=only_parts,
            existing_outline=existing_outline,
        )
        print(f"\n✓ Done. Generated {len(result.parts)} part(s). Outline: {result.outline_path}")
        if result.has_subtitles:
            print(f"✓ Subtitles generated (.srt, .json, .words.json)")
        return

    if args.multi:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_slug = f"{_slug(params['topic'])}_{timestamp}"
        only_parts: tuple[int, ...] = ()
        if args.only:
            only_parts = tuple(int(x.strip()) for x in args.only.split(",") if x.strip())

        existing_outline = None
        if args.reuse_outline:
            outline_path = Path(args.reuse_outline)
            existing_outline = load_outline(outline_path)
            base_slug = outline_path.stem.replace("_outline", "")
            print(f"→ Reusing outline: {outline_path}")

        result = run_multi_part(
            client=client,
            topic=params["topic"],
            style_key=params["style"],
            speaker1=params["speaker1"],
            speaker2=params["speaker2"],
            num_parts=args.parts,
            minutes_per_part=args.minutes_per_part,
            output_dir=HISTORY_DIR,
            base_slug=base_slug,
            only_parts=only_parts,
            existing_outline=existing_outline,
        )
        print(f"\n✓ Done. Generated {len(result.parts)} part(s). Outline: {result.outline_path}")
        return

    print(f"\n→ Đang sinh kịch bản về: {params['topic']!r} (style={params['style']})")
    script = generate_script(client, params["topic"], params["style"])
    print(f"✓ Sinh được {len(script.lines)} lượt thoại.")
    print("\n--- KỊCH BẢN ---")
    print(script.to_readable())
    print("--- HẾT ---\n")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{_slug(params['topic'])}_{timestamp}"
    out_path = Path(args.out) if args.out else HISTORY_DIR / f"{base}.wav"
    transcript_path = out_path.with_suffix(".txt")

    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(
        f"Topic: {params['topic']}\nStyle: {params['style']}\n"
        f"Speaker1 ({params['speaker1']}) / Speaker2 ({params['speaker2']})\n\n"
        + script.to_readable(),
        encoding="utf-8",
    )
    print(f"✓ Đã lưu transcript: {transcript_path}")

    print(f"→ Đang render audio (Speaker1={params['speaker1']}, Speaker2={params['speaker2']})...")
    render_script(client, script, out_path, params["speaker1"], params["speaker2"])
    print(f"✓ Đã lưu audio: {out_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nHủy bởi người dùng.")
        sys.exit(130)

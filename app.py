import json
import os
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from google import genai

from config import (
    AUDIENCE_LEVELS,
    AVAILABLE_VOICES,
    DEFAULT_AUDIENCE,
    DEFAULT_CHANNEL_NAME,
    DEFAULT_HOST_NAMES,
    DEFAULT_NUM_SPEAKERS,
    DEFAULT_PACE,
    DEFAULT_SHOW_NAME,
    DEFAULT_TONE,
    DEFAULT_TOTAL_MINUTES,
    DEFAULT_VOICES_BY_INDEX,
    DURATION_PRESETS,
    MAX_NUM_SPEAKERS,
    SPEECH_PACES,
    STYLES,
    TEXT_MODEL_OPTIONS,
    TONES,
)
from outline_generator import Outline, PartBrief, generate_outline
from script_generator import extract_tail_lines, generate_part_script, parse_script_text
from srt_generator import write_full_srt
from tts_renderer import render_script_with_voices

ROOT = Path(__file__).resolve().parent
HISTORY_DIR = ROOT / "history"
load_dotenv(ROOT / ".env")


def _slug(text: str, max_len: int = 40) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


def _get_client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        st.error("Thiếu GEMINI_API_KEY trong .env")
        st.stop()
    return genai.Client(api_key=api_key)


def _init_state() -> None:
    defaults = {
        "outline": None,
        "outline_dict": None,
        "scripts": {},
        "audio_paths": {},
        "base_slug": None,
        "cancel": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _outline_from_dict(d: dict, fallback_topic: str, fallback_minutes: int) -> Outline:
    parts = tuple(
        PartBrief(
            index=i + 1,
            title=str(p["title"]),
            summary=str(p["summary"]),
            key_points=tuple(str(k) for k in p.get("key_points", [])),
        )
        for i, p in enumerate(d["parts"])
    )
    return Outline(
        topic=d.get("topic", fallback_topic),
        total_minutes=d.get("total_minutes", fallback_minutes),
        parts=parts,
    )


def _outline_to_dict(outline: Outline) -> dict:
    return {
        "topic": outline.topic,
        "total_minutes": outline.total_minutes,
        "parts": [
            {"title": p.title, "summary": p.summary, "key_points": list(p.key_points)}
            for p in outline.parts
        ],
    }


def _previous_tail_for(outline: Outline, part_index: int, n: int = 6) -> tuple[str, ...]:
    if part_index <= 1:
        return ()
    prev_idx = part_index - 1
    prev_text = st.session_state["scripts"].get(prev_idx)
    if not prev_text:
        return ()
    return extract_tail_lines(prev_text, n=n)


def _gen_part(
    client: genai.Client,
    outline: Outline,
    part: PartBrief,
    cfg: dict,
) -> str:
    prev_titles = tuple(p.title for p in outline.parts[: part.index - 1])
    prev_tail = _previous_tail_for(outline, part.index)
    script = generate_part_script(
        client=client,
        topic=outline.topic,
        style_key=cfg["style"],
        part_index=part.index,
        total_parts=len(outline.parts),
        target_minutes=cfg["minutes_per_part"],
        part_title=part.title,
        part_summary=part.summary,
        key_points=part.key_points,
        previous_part_titles=prev_titles,
        previous_tail_lines=prev_tail,
        text_model=cfg["text_model"],
        audience_level=cfg["audience_level"],
        tone=cfg["tone"],
        continuous=cfg["continuous"],
        show_name=cfg["show_name"],
        channel_name=cfg["channel_name"],
        num_speakers=cfg["num_speakers"],
        host_names=tuple(cfg["host_names"]),
    )
    return script.to_readable()


def _render_part(
    client: genai.Client,
    outline: Outline,
    part_index: int,
    style: str,
    base_slug: str,
    voices: list[str],
    pace: str,
    progress_callback=None,
) -> str:
    text = st.session_state["scripts"][part_index]
    script = parse_script_text(outline.topic, style, text)
    wav_path = HISTORY_DIR / f"{base_slug}_part{part_index}.wav"
    txt_path = HISTORY_DIR / f"{base_slug}_part{part_index}.txt"
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    txt_path.write_text(text, encoding="utf-8")
    render_script_with_voices(
        client, script, wav_path, voices, pace=pace, progress_callback=progress_callback
    )
    return str(wav_path)


def _suggest_num_parts(total_minutes: int) -> int:
    target_per_part = 4
    return max(1, round(total_minutes / target_per_part))


def _sidebar() -> dict:
    with st.sidebar:
        st.header("⚙️ Cấu hình")

        st.subheader("📺 Show & Chủ đề")
        channel_name = st.text_input("Tên kênh YouTube", value=DEFAULT_CHANNEL_NAME)
        show_name = st.text_input("Tên show / podcast", value=DEFAULT_SHOW_NAME)
        topic = st.text_area(
            "Chủ đề tập này",
            value="How to communicate effectively in English",
            height=80,
        )

        st.subheader("⏱️ Thời lượng")
        preset_options = [str(m) for m in DURATION_PRESETS] + ["Custom"]
        default_idx = (
            DURATION_PRESETS.index(DEFAULT_TOTAL_MINUTES)
            if DEFAULT_TOTAL_MINUTES in DURATION_PRESETS else 0
        )
        chosen = st.selectbox("Tổng video (phút)", preset_options, index=default_idx)
        if chosen == "Custom":
            total_minutes = int(
                st.number_input("Custom — tổng phút", min_value=1, max_value=180, value=20)
            )
        else:
            total_minutes = int(chosen)

        suggested = _suggest_num_parts(total_minutes)
        num_parts = int(
            st.number_input(
                "Số part (chia file)",
                min_value=1,
                max_value=min(20, total_minutes),
                value=suggested,
                help="Phút mỗi part tự derive từ tổng phút ÷ số part.",
            )
        )
        minutes_per_part = max(1, round(total_minutes / num_parts))
        st.caption(
            f"→ **{num_parts} file × ~{minutes_per_part} phút** "
            f"(tổng ~{num_parts * minutes_per_part} phút)"
        )

        st.subheader("✍️ Nội dung")
        style_keys = list(STYLES.keys())
        default_style_idx = (
            style_keys.index("english_learning") if "english_learning" in style_keys else 0
        )
        style = st.selectbox("Style kịch bản", style_keys, index=default_style_idx)
        audience_keys = list(AUDIENCE_LEVELS.keys())
        audience_level = st.selectbox(
            "Trình độ người nghe",
            audience_keys,
            index=audience_keys.index(DEFAULT_AUDIENCE),
        )
        tone_keys = list(TONES.keys())
        tone = st.selectbox(
            "Giọng điệu (tone)",
            tone_keys,
            index=tone_keys.index(DEFAULT_TONE),
        )
        continuous = st.toggle(
            "🔗 Hội thoại liên tục giữa các part",
            value=True,
            help=(
                "BẬT: cả series là 1 hội thoại dài, chỉ part 1 chào, chỉ part cuối kết.\n"
                "TẮT: mỗi part là episode độc lập."
            ),
        )

        st.subheader("🎙️ Giọng đọc")
        num_speakers = st.selectbox(
            "Số người dẫn",
            list(range(1, MAX_NUM_SPEAKERS + 1)),
            index=DEFAULT_NUM_SPEAKERS - 1,
            format_func=lambda n: f"{n} người" + (" (monologue)" if n == 1 else ""),
            help="1-2 người: render 1 lần / part. 3+ người: render từng line riêng rồi nối — chậm hơn, tốn API hơn.",
        )
        if num_speakers >= 3:
            st.warning(
                f"⚠️ {num_speakers} người: Gemini chỉ native support 2 voice/lần. "
                "Mỗi line sẽ render riêng rồi nối WAV — chậm và tốn nhiều API call hơn."
            )
        host_names: list[str] = []
        host_voices: list[str] = []
        for i in range(num_speakers):
            c1, c2 = st.columns(2)
            with c1:
                name = st.text_input(
                    f"Tên nhân vật {i + 1}",
                    value=DEFAULT_HOST_NAMES[i] if i < len(DEFAULT_HOST_NAMES) else f"Host{i + 1}",
                    key=f"host_name_{i}",
                )
                host_names.append(name)
            with c2:
                default_voice = (
                    DEFAULT_VOICES_BY_INDEX[i]
                    if i < len(DEFAULT_VOICES_BY_INDEX)
                    else AVAILABLE_VOICES[i % len(AVAILABLE_VOICES)]
                )
                voice = st.selectbox(
                    f"Voice {i + 1}",
                    AVAILABLE_VOICES,
                    index=AVAILABLE_VOICES.index(default_voice) if default_voice in AVAILABLE_VOICES else 0,
                    key=f"host_voice_{i}",
                )
                host_voices.append(voice)
        pace_keys = list(SPEECH_PACES.keys())
        pace = st.selectbox(
            "Tốc độ đọc",
            pace_keys,
            index=pace_keys.index(DEFAULT_PACE),
        )

        st.subheader("🤖 Model")
        text_model = st.selectbox("Text model", TEXT_MODEL_OPTIONS, index=0)

        st.divider()
        if st.button("🔄 Reset session", use_container_width=True):
            for k in ("outline", "outline_dict", "base_slug"):
                st.session_state[k] = None
            st.session_state["scripts"] = {}
            st.session_state["audio_paths"] = {}
            st.session_state["cancel"] = False
            for k in list(st.session_state.keys()):
                if k.startswith("script_text_"):
                    del st.session_state[k]
            st.rerun()

    return {
        "topic": topic,
        "style": style,
        "text_model": text_model,
        "num_speakers": int(num_speakers),
        "host_names": [n.strip() for n in host_names],
        "host_voices": list(host_voices),
        "pace": pace,
        "audience_level": audience_level,
        "tone": tone,
        "continuous": continuous,
        "show_name": show_name.strip(),
        "channel_name": channel_name.strip(),
        "num_parts": int(num_parts),
        "minutes_per_part": int(minutes_per_part),
    }


def _step_outline(client: genai.Client, cfg: dict) -> None:
    st.header("Step 1 — Outline")
    if st.button("📝 Generate outline", type="primary", disabled=not cfg["topic"].strip()):
        with st.spinner("Đang sinh outline..."):
            try:
                outline = generate_outline(
                    client,
                    cfg["topic"],
                    cfg["num_parts"],
                    cfg["minutes_per_part"],
                    text_model=cfg["text_model"],
                    audience_level=cfg["audience_level"],
                    tone=cfg["tone"],
                    continuous=cfg["continuous"],
                    show_name=cfg["show_name"],
                    channel_name=cfg["channel_name"],
                )
                st.session_state["outline"] = outline
                st.session_state["outline_dict"] = _outline_to_dict(outline)
                st.session_state["base_slug"] = (
                    f"{_slug(cfg['topic'])}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                st.session_state["scripts"] = {}
                st.session_state["audio_paths"] = {}
                for k in list(st.session_state.keys()):
                    if k.startswith("script_text_"):
                        del st.session_state[k]
                st.success(f"✓ Outline {len(outline.parts)} part đã sinh.")
            except Exception as e:
                st.error(f"Lỗi: {e}")

    if st.session_state["outline_dict"]:
        outline_text = st.text_area(
            "Outline JSON (sửa tay nếu muốn rồi bấm Apply)",
            value=json.dumps(st.session_state["outline_dict"], indent=2, ensure_ascii=False),
            height=280,
            key="outline_text_area",
        )
        if st.button("💾 Apply outline đã sửa"):
            try:
                d = json.loads(outline_text)
                fallback_min = cfg["num_parts"] * cfg["minutes_per_part"]
                st.session_state["outline"] = _outline_from_dict(d, cfg["topic"], fallback_min)
                st.session_state["outline_dict"] = d
                st.success("✓ Đã cập nhật outline.")
                st.rerun()
            except Exception as e:
                st.error(f"JSON lỗi: {e}")


def _step_parts(client: genai.Client, cfg: dict) -> None:
    outline: Outline = st.session_state["outline"]
    if outline is None:
        st.info("👆 Sinh outline ở Step 1 để bắt đầu.")
        return

    st.header("Step 2 — Scripts & Audio per Part")
    base_slug = st.session_state["base_slug"]
    total = len(outline.parts)
    n_scripts = len(st.session_state["scripts"])
    n_audios = len(st.session_state["audio_paths"])
    missing_audio_with_script = sum(
        1 for p in outline.parts
        if p.index in st.session_state["scripts"] and p.index not in st.session_state["audio_paths"]
    )
    st.caption(
        f"📊 Trạng thái: **{n_scripts}/{total}** scripts, **{n_audios}/{total}** audio "
        f"({missing_audio_with_script} part có script chưa render audio)"
    )

    cols = st.columns([1.4, 1.4, 1.4, 1, 2])
    run_all_clicked = cols[0].button("▶ Run All Remaining", type="primary")
    render_missing_clicked = cols[1].button(
        "🔊 Render audio thiếu", disabled=missing_audio_with_script == 0
    )
    export_srt_clicked = cols[2].button(
        "📥 Export subtitle (.srt)", disabled=n_audios == 0,
        help="Tạo 1 file SRT gộp toàn bộ part đã render, timestamps khớp với audio thực tế.",
    )
    if cols[3].button("■ Cancel"):
        st.session_state["cancel"] = True

    if export_srt_clicked:
        try:
            ordered_parts: list[tuple] = []
            for part in outline.parts:
                if part.index in st.session_state["audio_paths"]:
                    text = st.session_state["scripts"][part.index]
                    script = parse_script_text(outline.topic, cfg["style"], text)
                    wav_path = Path(st.session_state["audio_paths"][part.index])
                    ordered_parts.append((script, wav_path))
            srt_path = HISTORY_DIR / f"{base_slug}_full.srt"
            write_full_srt(
                parts=ordered_parts,
                out_path=srt_path,
                host_names=cfg["host_names"],
                pace=cfg["pace"],
            )
            st.session_state["full_srt_path"] = str(srt_path)
            st.success(f"✓ Đã tạo: `{srt_path}`")
        except Exception as e:
            st.error(f"Lỗi export SRT: {e}")

    full_srt = st.session_state.get("full_srt_path")
    if full_srt and Path(full_srt).exists():
        with open(full_srt, "rb") as f:
            st.download_button(
                "⬇️ Download full.srt",
                data=f,
                file_name=Path(full_srt).name,
                mime="text/plain",
            )

    if run_all_clicked or render_missing_clicked:
        st.session_state["cancel"] = False
        gen_scripts_too = run_all_clicked
        progress = st.progress(0.0, text="Bắt đầu...")
        total_steps = total * 2
        done = 0
        ok_count = 0
        for part in outline.parts:
            if st.session_state["cancel"]:
                st.warning("Đã hủy.")
                break
            if gen_scripts_too and part.index not in st.session_state["scripts"]:
                progress.progress(done / total_steps, text=f"Part {part.index}: gen script...")
                try:
                    st.session_state["scripts"][part.index] = _gen_part(
                        client, outline, part, cfg
                    )
                except Exception as e:
                    st.error(f"Part {part.index} script error: {e}")
                    break
            done += 1
            if st.session_state["cancel"]:
                break
            has_script_now = part.index in st.session_state["scripts"]
            need_audio = has_script_now and part.index not in st.session_state["audio_paths"]
            if need_audio:
                progress.progress(done / total_steps, text=f"Part {part.index}: render audio...")
                try:
                    st.session_state["audio_paths"][part.index] = _render_part(
                        client, outline, part.index, cfg["style"], base_slug,
                        cfg["host_voices"], cfg["pace"],
                    )
                    ok_count += 1
                except Exception as e:
                    st.error(f"Part {part.index} render error: {e}")
                    break
            done += 1
        progress.progress(1.0, text="Hoàn tất.")
        st.success(f"✓ Đã render thêm {ok_count} audio. Cuộn xuống xem player.")

    for part in outline.parts:
        has_script = part.index in st.session_state["scripts"]
        has_audio = part.index in st.session_state["audio_paths"]
        status = "🎵" if has_audio else ("📝" if has_script else "⬜")
        with st.expander(
            f"{status} Part {part.index}: {part.title}", expanded=not has_audio
        ):
            st.caption(part.summary)
            if part.key_points:
                st.markdown("\n".join(f"- {kp}" for kp in part.key_points))

            cols = st.columns([1, 1, 1, 3])
            gen_clicked = cols[0].button("Gen script", key=f"gen_{part.index}")
            regen_clicked = cols[1].button(
                "Regen script", key=f"regen_{part.index}", disabled=not has_script
            )
            render_clicked = cols[2].button(
                "Render audio", key=f"render_{part.index}", disabled=not has_script
            )

            if gen_clicked or regen_clicked:
                with st.spinner(f"Gen script Part {part.index}..."):
                    try:
                        text = _gen_part(client, outline, part, cfg)
                        st.session_state["scripts"][part.index] = text
                        st.session_state["audio_paths"].pop(part.index, None)
                        st.session_state.pop(f"script_text_{part.index}", None)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Lỗi: {e}")

            if has_script:
                widget_key = f"script_text_{part.index}"
                if widget_key not in st.session_state:
                    st.session_state[widget_key] = st.session_state["scripts"][part.index]
                edited = st.text_area(
                    f"Script (sửa tay được)",
                    height=380,
                    key=widget_key,
                )
                st.session_state["scripts"][part.index] = edited
                word_count = len(edited.split())
                est_minutes = word_count / 175
                target_words_est = cfg["minutes_per_part"] * 180
                color = "🟢" if word_count >= cfg["minutes_per_part"] * 160 else "🔴"
                st.caption(
                    f"{color} **{word_count} từ** ≈ ~{est_minutes:.1f} phút audio "
                    f"(target ~{target_words_est} từ)"
                )
                if has_audio and edited.strip() != "":
                    st.caption("⚠️ Đã sửa script? Bấm 'Render audio' lại để cập nhật WAV.")

            if render_clicked:
                with st.spinner(f"Render audio Part {part.index}..."):
                    try:
                        st.session_state["audio_paths"][part.index] = _render_part(
                            client, outline, part.index, cfg["style"], base_slug,
                            cfg["host_voices"], cfg["pace"],
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Lỗi render: {e}")

            if has_audio:
                wav_path = st.session_state["audio_paths"][part.index]
                st.audio(wav_path)
                st.caption(f"📁 `{wav_path}`")


def main() -> None:
    st.set_page_config(page_title="TTS Script Gen", layout="wide")
    _init_state()
    st.title("🎙️ TTS Script Gen — Long-form Podcast Builder")
    cfg = _sidebar()
    client = _get_client()
    _step_outline(client, cfg)
    st.divider()
    _step_parts(client, cfg)


if __name__ == "__main__":
    main()

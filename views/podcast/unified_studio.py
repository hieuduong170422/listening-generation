"""Unified Podcast Studio — Single UI cho toàn bộ luồng.

Script → Audio (ElevenLabs) → Subtitles (Whisper, tuỳ chọn)
"""
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
from google import genai

from paths import HISTORY_DIR, ROOT
from podcast_studio.auth import is_admin
from podcast_studio.config import (
    AUDIENCE_LEVELS,
    DEFAULT_AUDIENCE,
    DEFAULT_CHANNEL_NAME,
    DEFAULT_LANGUAGE,
    DEFAULT_NUM_SPEAKERS,
    DEFAULT_SHOW_NAME,
    DEFAULT_TONE,
    DURATION_PRESETS,
    LANGUAGES,
    MAX_NUM_SPEAKERS,
    STYLES,
    TONES,
)
from podcast_studio.elevenlabs_tts import (
    ElevenLabsError,
    list_voices as _el_list_voices,
)
from podcast_studio.tts_settings import ELEVEN_MODELS, load_settings as _el_load_settings
from podcast_studio.topic_suggester import suggest_topics
from podcast_studio.unified_podcast_generator import run_unified_podcast


def _slug(text: str, max_len: int = 40) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


def _init_state() -> None:
    defaults = {
        "topic_text": "How to communicate effectively in English",
        "base_slug": None,
        "topic_suggestions": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _get_client():
    import os

    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        st.error(
            "Chưa có `GEMINI_API_KEY` trong `.env`. "
            "Lấy key tại https://aistudio.google.com/apikey rồi restart app."
        )
        st.stop()
    return genai.Client(api_key=key, vertexai=False)


@st.cache_data(ttl=300, show_spinner="Đang tải voice list ElevenLabs…")
def _el_fetch_voices_cached():
    return _el_list_voices()


def _sidebar() -> dict:
    st.sidebar.header("⚙️ Cấu hình Podcast")

    with st.sidebar.expander("📺 Chủ đề & Show", expanded=True):
        language_keys = list(LANGUAGES.keys())
        language = st.selectbox(
            "🌐 Ngôn ngữ kịch bản",
            language_keys,
            index=language_keys.index(DEFAULT_LANGUAGE),
            format_func=lambda k: f"{LANGUAGES[k]['label']} ({LANGUAGES[k]['native']})",
        )

        sc1, sc2 = st.columns(2)
        with sc1:
            channel_name = st.text_input("Tên kênh", value=DEFAULT_CHANNEL_NAME)
        with sc2:
            show_name = st.text_input("Tên show", value=DEFAULT_SHOW_NAME)

        topic = st.text_area(
            "Chủ đề podcast",
            height=80,
            key="topic_text",
            help="Chủ đề chính cho toàn bộ series podcast",
        )

        suggest_count = st.slider("Số gợi ý", min_value=1, max_value=5, value=3)

        suggest_col1, suggest_col2 = st.columns(2)
        with suggest_col1:
            if st.button("💡 Gợi ý chủ đề", use_container_width=True):
                client = _get_client()
                with st.spinner("Đang nghĩ chủ đề..."):
                    try:
                        suggestions = suggest_topics(
                            client,
                            audience_level=st.session_state.get(
                                "_audience_for_suggest", "intermediate"
                            ),
                            count=int(suggest_count),
                            language=language,
                        )
                        st.session_state["topic_suggestions"] = suggestions
                    except Exception as e:
                        st.error(f"Lỗi: {e}")

        suggestions = st.session_state.get("topic_suggestions") or []
        if suggestions:
            picked = st.selectbox(
                "📋 Chọn từ gợi ý", ["— chọn —"] + suggestions, index=0
            )
            if picked != "— chọn —":
                st.session_state["topic_text"] = picked
                st.rerun()

    with st.sidebar.expander("⏱️ Cấu hình series", expanded=True):
        col1, col2 = st.columns(2)
        with col1:
            preset_options = [str(m) for m in DURATION_PRESETS] + ["Custom"]
            chosen = st.selectbox("Tổng thời lượng", preset_options, index=2)
            if chosen == "Custom":
                total_minutes = int(
                    st.number_input(
                        "Custom — phút",
                        min_value=1,
                        max_value=180,
                        value=40,
                    )
                )
            else:
                total_minutes = int(chosen)

        with col2:
            max_parts = min(20, total_minutes)
            default_parts = min(10, max_parts)  # Ensure default respects max
            num_parts = int(
                st.number_input(
                    "Số part",
                    min_value=1,
                    max_value=max_parts,
                    value=default_parts,
                    help="Chia nhỏ = ít lỗi TTS",
                )
            )

        minutes_per_part = max(1, round(total_minutes / num_parts))
        st.caption(
            f"→ **{num_parts} file × ~{minutes_per_part} phút** "
            f"(tổng ~{num_parts * minutes_per_part} phút)"
        )

    with st.sidebar.expander("✍️ Nội dung & Giọng", expanded=True):
        cc1, cc2 = st.columns(2)
        with cc1:
            style_keys = list(STYLES.keys())
            style = st.selectbox("Kiểu kịch bản", style_keys, index=0)
            audience_keys = list(AUDIENCE_LEVELS.keys())
            audience_level = st.selectbox(
                "Trình độ người nghe",
                audience_keys,
                index=audience_keys.index(DEFAULT_AUDIENCE),
            )
        with cc2:
            tone_keys = list(TONES.keys())
            tone = st.selectbox("Giọng điệu", tone_keys, index=0)
            continuous = st.toggle(
                "🔗 Hội thoại liên tục", value=True,
                help="Bật: series là 1 cuộc thoại dài. Tắt: mỗi part độc lập."
            )

        st.session_state["_audience_for_suggest"] = audience_level

    with st.sidebar.expander("🎙️ ElevenLabs Voices", expanded=True):
        try:
            all_voices = _el_fetch_voices_cached()
        except ElevenLabsError as e:
            st.error(f"Lỗi load voice: {e}")
            st.stop()

        settings = _el_load_settings()
        el_config = settings.get("elevenlabs", {})

        model_id = st.selectbox(
            "Model TTS",
            ELEVEN_MODELS,
            index=ELEVEN_MODELS.index(el_config.get("model_id", "eleven_flash_v2_5")),
        )

        num_speakers = st.selectbox(
            "Số người dẫn",
            list(range(1, MAX_NUM_SPEAKERS + 1)),
            index=DEFAULT_NUM_SPEAKERS - 1,
            format_func=lambda n: f"{n} người" + (" (monologue)" if n == 1 else ""),
        )

        voice_ids = []
        for i in range(num_speakers):
            voice_names = [f"{v.get('name', '')} (id: {v.get('voice_id', '')})" for v in all_voices]
            voice_names.insert(0, "— Không chọn —")
            chosen_idx = st.selectbox(
                f"Voice Speaker {i + 1}",
                range(len(voice_names)),
                format_func=lambda idx: voice_names[idx],
            )
            if chosen_idx > 0:
                voice_ids.append(all_voices[chosen_idx - 1]["voice_id"])
            else:
                voice_ids.append("")

    with st.sidebar.expander("🎬 Tùy chọn", expanded=False):
        generate_subs = st.checkbox("Tạo phụ đề Whisper", value=False,
                                    help="Thêm .srt, .json, .words.json")

    return {
        "topic": topic,
        "style": style,
        "channel_name": channel_name,
        "show_name": show_name,
        "language": language,
        "num_parts": num_parts,
        "minutes_per_part": minutes_per_part,
        "audience_level": audience_level,
        "tone": tone,
        "continuous": continuous,
        "num_speakers": num_speakers,
        "voice_ids": voice_ids,
        "model_id": model_id,
        "generate_subs": generate_subs,
    }


def main():
    st.set_page_config(page_title="Unified Podcast Studio", layout="wide")
    st.title("🎧 Unified Podcast Studio")
    st.markdown(
        "**Single pipeline:** Script (Gemini) → Audio (ElevenLabs) → Subtitles (Whisper)"
    )

    _init_state()

    cfg = _sidebar()

    if not cfg["topic"]:
        st.info("👈 Nhập chủ đề podcast ở sidebar để bắt đầu.")
        return

    client = _get_client()

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🚀 Tạo Podcast", use_container_width=True, type="primary"):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_slug = f"{_slug(cfg['topic'])}_{timestamp}"
            st.session_state["base_slug"] = base_slug

            # Filter out empty voice_ids; use defaults if not fully specified
            voice_ids = [v for v in cfg["voice_ids"] if v]
            if not voice_ids:
                # Use default empty list (will use ElevenLabs defaults)
                voice_ids = cfg["voice_ids"]

            try:
                # Create container for progress
                progress_container = st.container()

                with progress_container:
                    with st.status("🎙️ Đang tạo podcast...", expanded=True) as status:
                        st.write("📍 Bước 1/3: Generating outline...")

                        result = run_unified_podcast(
                            client=client,
                            topic=cfg["topic"],
                            style_key=cfg["style"],
                            speaker1="Speaker1",
                            speaker2="Speaker2",
                            num_parts=cfg["num_parts"],
                            minutes_per_part=cfg["minutes_per_part"],
                            output_dir=HISTORY_DIR,
                            base_slug=base_slug,
                            generate_subtitles=cfg["generate_subs"],
                            audience_level=cfg["audience_level"],
                            tone=cfg["tone"],
                            continuous=cfg["continuous"],
                            show_name=cfg["show_name"],
                            channel_name=cfg["channel_name"],
                            num_speakers=cfg["num_speakers"],
                            voice_ids=voice_ids if voice_ids else None,
                            progress_callback=lambda stage, msg: st.write(f"📍 {stage}: {msg}") if msg else None,
                        )

                        status.update(label="✅ Hoàn thành!", state="complete")

                st.success(f"✅ Tạo thành công! {len(result.parts)} part(s)")
                if result.has_subtitles:
                    st.info("📝 Phụ đề đã tạo (.srt, .json, .words.json)")

                with st.expander("📁 File outputs", expanded=True):
                    st.markdown("**Outline:**")
                    st.code(str(result.outline_path))

                    for part in result.parts:
                        st.markdown(f"**Part {part.index}: {part.title}**")
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.caption(f"📄 {part.txt_path.name}")
                        with col_b:
                            st.caption(f"🎵 {part.wav_path.name}")

            except ElevenLabsError as e:
                st.error(f"❌ ElevenLabs error: {e}")
            except Exception as e:
                st.error(f"❌ Error: {e}")
                import traceback
                st.error(traceback.format_exc())

    with col2:
        if st.button("📋 View History", use_container_width=True):
            if HISTORY_DIR.exists():
                files = sorted(HISTORY_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
                st.write(f"📁 {len(files)} files in history")
                for f in files[:20]:
                    st.write(f"  • {f.name}")
            else:
                st.info("No history yet")

    with col3:
        if is_admin():
            if st.button("🔄 Clear History", use_container_width=True):
                import shutil
                if HISTORY_DIR.exists():
                    shutil.rmtree(HISTORY_DIR)
                st.success("Cleared!")
                st.rerun()

    st.divider()
    st.markdown("### ℹ️ Luồng hoạt động")
    st.markdown(
        """
1. **Script Generation** — Gemini tạo kịch bản đối thoại theo từng part
2. **Audio Rendering** — ElevenLabs tạo audio từ kịch bản
3. **Subtitle Gen** — Whisper (local) tạo phụ đề từ audio (tuỳ chọn)

**Output:**
- `.wav` — audio files (1 per part)
- `.txt` — transcript (1 per part)
- `.srt`, `.json`, `.words.json` — subtitles (nếu bật)
- `_outline.json` — metadata structure
"""
    )


if __name__ == "__main__":
    main()

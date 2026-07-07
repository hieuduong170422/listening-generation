"""Unified Podcast Studio — Manual step-by-step workflow.

1. Generate Outline
2. For each part: Generate Script → Render Audio
3. (Optional) Generate Subtitles
"""
import re
from datetime import datetime
from pathlib import Path

import streamlit as st
from google import genai

from paths import HISTORY_DIR
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
    render_multi_speaker,
    render_single_voice,
)
from podcast_studio.genai_client import get_client
from podcast_studio.multi_part import load_outline
from podcast_studio.outline_generator import generate_outline as _generate_outline
from podcast_studio.script_generator import generate_part_script, parse_script_text
from podcast_studio.tts_settings import ELEVEN_MODELS, load_settings as _el_load_settings
from podcast_studio.topic_suggester import suggest_topics
from podcast_studio.whisper_transcribe import (
    transcribe,
    transcript_to_srt,
    write_json_outputs,
)


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
        "outline": None,
        "scripts": {},
        "audio_paths": {},
        "subtitle_paths": {},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


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
                client = get_client()
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
            # Default to 45 minutes (index 8) = ~10 parts × 4 min each
            default_preset_idx = 8 if len(DURATION_PRESETS) > 8 else len(DURATION_PRESETS) - 1
            chosen = st.selectbox("Tổng thời lượng", preset_options, index=default_preset_idx)
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
            default_parts = min(10, max_parts)
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
                "🔗 Hội thoại liên tục",
                value=True,
                help="Bật: series là 1 cuộc thoại dài. Tắt: mỗi part độc lập.",
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
            voice_names = [
                f"{v.get('name', '')} (id: {v.get('voice_id', '')})" for v in all_voices
            ]
            voice_names.insert(0, "— Default —")
            chosen_idx = st.selectbox(
                f"Voice Speaker {i + 1}",
                range(len(voice_names)),
                format_func=lambda idx: voice_names[idx],
            )
            if chosen_idx > 0:
                voice_ids.append(all_voices[chosen_idx - 1]["voice_id"])
            else:
                voice_ids.append("")

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
    }


def main():
    st.set_page_config(page_title="Unified Podcast Studio", layout="wide")
    st.title("🎧 Unified Podcast Studio")
    st.markdown(
        "**Manual workflow:** Outline → Script (per part) → Audio (per part) → Subtitles (optional)"
    )

    _init_state()
    cfg = _sidebar()

    if not cfg["topic"]:
        st.info("👈 Nhập chủ đề podcast ở sidebar để bắt đầu.")
        return

    client = get_client()
    el_config = _el_load_settings().get("elevenlabs", {})

    # ── Step 1: Generate Outline ────────────────────────────────────────
    st.header("1️⃣ Outline")

    outline_col1, outline_col2 = st.columns([3, 1])
    with outline_col1:
        if st.session_state["outline"]:
            st.success(f"✅ Outline created: {cfg['num_parts']} parts")
            with st.expander("📋 View Outline", expanded=False):
                for part in st.session_state["outline"].parts:
                    st.markdown(
                        f"**Part {part.index}: {part.title}**\n\n"
                        f"{part.summary}\n\n"
                        f"Key points: {', '.join(part.key_points)}"
                    )
        else:
            st.info("Chưa generate outline. Bấm nút bên phải.")

    with outline_col2:
        if st.button("Generate Outline", key="btn_outline", use_container_width=True):
            with st.spinner("⏳ Generating outline..."):
                try:
                    outline = _generate_outline(
                        client,
                        cfg["topic"],
                        cfg["num_parts"],
                        cfg["minutes_per_part"],
                        audience_level=cfg["audience_level"],
                        tone=cfg["tone"],
                        continuous=cfg["continuous"],
                        show_name=cfg["show_name"],
                        channel_name=cfg["channel_name"],
                    )
                    st.session_state["outline"] = outline
                    st.success("✅ Outline generated!")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error: {e}")

    if not st.session_state["outline"]:
        st.stop()

    # ── Step 2: Generate Scripts & Audio (per part) ──────────────────────
    st.divider()
    st.header("2️⃣ Scripts & Audio")

    outline = st.session_state["outline"]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if not st.session_state["base_slug"]:
        st.session_state["base_slug"] = f"{_slug(cfg['topic'])}_{timestamp}"

    base_slug = st.session_state["base_slug"]

    # Bulk script generation button
    col_gen_all, col_progress = st.columns([1, 3])
    with col_gen_all:
        if st.button("🚀 Generate All Scripts", use_container_width=True):
            progress_bar = st.progress(0)
            progress_text = st.empty()

            for idx, part in enumerate(outline.parts):
                progress_text.text(f"Generating Part {part.index}...")

                try:
                    prev_titles = tuple(p.title for p in outline.parts[: part.index - 1])
                    prev_tail = ()
                    if part.index > 1:
                        prev_text = st.session_state["scripts"].get(part.index - 1)
                        if prev_text:
                            lines = prev_text.strip().split("\n")
                            prev_tail = tuple(l for l in lines[-6:] if l.strip())

                    script = generate_part_script(
                        client=client,
                        topic=cfg["topic"],
                        style_key=cfg["style"],
                        part_index=part.index,
                        total_parts=cfg["num_parts"],
                        target_minutes=cfg["minutes_per_part"],
                        part_title=part.title,
                        part_summary=part.summary,
                        key_points=part.key_points,
                        previous_part_titles=prev_titles,
                        previous_tail_lines=prev_tail,
                        audience_level=cfg["audience_level"],
                        tone=cfg["tone"],
                        continuous=cfg["continuous"],
                        show_name=cfg["show_name"],
                        channel_name=cfg["channel_name"],
                    )
                    st.session_state["scripts"][part.index] = script.to_readable()

                    # Save transcript
                    txt_path = HISTORY_DIR / f"{base_slug}_part{part.index}.txt"
                    txt_path.parent.mkdir(parents=True, exist_ok=True)
                    txt_path.write_text(
                        f"Topic: {cfg['topic']}\n"
                        f"Part: {part.index}/{cfg['num_parts']} — {part.title}\n"
                        f"Summary: {part.summary}\n\n"
                        + script.to_readable(),
                        encoding="utf-8",
                    )
                except Exception as e:
                    st.error(f"Error Part {part.index}: {e}")
                    break

                progress_bar.progress((idx + 1) / len(outline.parts))

            st.success(f"✅ Generated {len(st.session_state['scripts'])} scripts!")
            st.rerun()

    with col_progress:
        scripts_done = len(st.session_state["scripts"])
        st.metric("Scripts Ready", f"{scripts_done}/{cfg['num_parts']}")

    # Bulk action buttons (appear after scripts are generated)
    if scripts_done > 0:
        st.divider()
        col_bulk1, col_bulk2, col_bulk3 = st.columns(3)

        with col_bulk1:
            if st.button("🎙️ Render All Audio", use_container_width=True):
                progress_bar = st.progress(0)
                progress_text = st.empty()

                for idx, part in enumerate(outline.parts):
                    if part.index not in st.session_state["scripts"]:
                        continue  # Skip parts without scripts

                    progress_text.text(f"Rendering audio Part {part.index}...")

                    try:
                        script_text = st.session_state["scripts"][part.index]
                        script = parse_script_text(cfg["topic"], cfg["style"], script_text)
                        wav_path = HISTORY_DIR / f"{base_slug}_part{part.index}.wav"

                        el_config_copy = dict(el_config)
                        el_config_copy["output_format"] = "pcm_24000"

                        voice_ids = cfg["voice_ids"]
                        cleaned_voices = [v for v in voice_ids if v]

                        if not cleaned_voices:
                            default_voices = el_config_copy.get("voices", [""])[:cfg["num_speakers"]]
                            cleaned_voices = [v for v in default_voices if v]

                        if not cleaned_voices:
                            try:
                                available_voices = _el_fetch_voices_cached()
                                if available_voices:
                                    first_voice = available_voices[0]["voice_id"]
                                    cleaned_voices = [first_voice] * cfg["num_speakers"]
                            except Exception:
                                pass

                        if not cleaned_voices:
                            st.error("❌ Không tìm được voice")
                            break

                        if len(cleaned_voices) == 1:
                            render_single_voice(script, wav_path, cleaned_voices[0], el_config_copy)
                        else:
                            render_multi_speaker(script, wav_path, cleaned_voices, el_config_copy)

                        st.session_state["audio_paths"][part.index] = str(wav_path)
                    except Exception as e:
                        st.error(f"Error Part {part.index}: {e}")
                        break

                    progress_bar.progress((idx + 1) / len(outline.parts))

                st.success(f"✅ Rendered {len(st.session_state['audio_paths'])} audio files!")
                st.rerun()

        with col_bulk2:
            audio_done = len(st.session_state["audio_paths"])
            if audio_done > 0:
                if st.button("📝 Generate All Subtitles", use_container_width=True):
                    progress_bar = st.progress(0)
                    progress_text = st.empty()

                    for idx, part in enumerate(outline.parts):
                        if part.index not in st.session_state["audio_paths"]:
                            continue  # Skip parts without audio

                        progress_text.text(f"Generating subtitles Part {part.index}...")

                        try:
                            wav_path = st.session_state["audio_paths"][part.index]
                            srt_path = Path(wav_path).with_suffix(".srt")
                            base_path = Path(wav_path).with_suffix("")

                            transcript = transcribe(wav_path, language="vi", model_size="medium")
                            srt_path.write_text(transcript_to_srt(transcript), encoding="utf-8")
                            write_json_outputs(transcript, base_path)

                            st.session_state["subtitle_paths"][part.index] = str(srt_path)
                        except Exception as e:
                            st.error(f"Error Part {part.index}: {e}")
                            break

                        progress_bar.progress((idx + 1) / len(outline.parts))

                    st.success(f"✅ Generated {len(st.session_state['subtitle_paths'])} subtitle files!")
                    st.rerun()

        with col_bulk3:
            st.metric(
                "Status",
                f"{len(st.session_state['audio_paths'])}/{len(st.session_state['scripts'])} audio",
            )

    st.divider()

    for part in outline.parts:
        with st.expander(
            f"Part {part.index}: {part.title}",
            expanded=True,
        ):
            # Clean 3-column layout: Script | Audio | Subtitle
            col_script, col_audio, col_subtitle = st.columns(3, gap="medium")

            # ─────── SCRIPT COLUMN ───────────────────────────────────────
            with col_script:
                st.subheader("📝 Script")

                if part.index in st.session_state["scripts"]:
                    st.success("✅ Generated", icon="✓")
                    script_text = st.session_state["scripts"][part.index]

                    # Show script text
                    st.text_area(
                        "content",
                        value=script_text,
                        height=200,
                        disabled=True,
                        key=f"view_script_{part.index}",
                        label_visibility="collapsed",
                    )

                    # Download button
                    st.download_button(
                        "📥 Download Script",
                        data=script_text,
                        file_name=f"{base_slug}_part{part.index}.txt",
                        mime="text/plain",
                        use_container_width=True,
                    )
                else:
                    st.info("⏳ Not generated", icon="ℹ️")
                    if st.button(f"Generate", key=f"btn_script_{part.index}", use_container_width=True, type="primary"):
                        with st.spinner(f"⏳ Generating script for Part {part.index}..."):
                            try:
                                prev_titles = tuple(
                                    p.title for p in outline.parts[: part.index - 1]
                                )
                                prev_tail = ()
                                if part.index > 1:
                                    prev_text = st.session_state["scripts"].get(part.index - 1)
                                    if prev_text:
                                        lines = prev_text.strip().split("\n")
                                        prev_tail = tuple(
                                            l for l in lines[-6:] if l.strip()
                                        )

                                script = generate_part_script(
                                    client=client,
                                    topic=cfg["topic"],
                                    style_key=cfg["style"],
                                    part_index=part.index,
                                    total_parts=cfg["num_parts"],
                                    target_minutes=cfg["minutes_per_part"],
                                    part_title=part.title,
                                    part_summary=part.summary,
                                    key_points=part.key_points,
                                    previous_part_titles=prev_titles,
                                    previous_tail_lines=prev_tail,
                                    audience_level=cfg["audience_level"],
                                    tone=cfg["tone"],
                                    continuous=cfg["continuous"],
                                    show_name=cfg["show_name"],
                                    channel_name=cfg["channel_name"],
                                )
                                st.session_state["scripts"][part.index] = script.to_readable()

                                # Save transcript
                                txt_path = HISTORY_DIR / f"{base_slug}_part{part.index}.txt"
                                txt_path.parent.mkdir(parents=True, exist_ok=True)
                                txt_path.write_text(
                                    f"Topic: {cfg['topic']}\n"
                                    f"Part: {part.index}/{cfg['num_parts']} — {part.title}\n"
                                    f"Summary: {part.summary}\n\n"
                                    + script.to_readable(),
                                    encoding="utf-8",
                                )

                                st.success(f"✅ Script saved!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Error: {e}")

            # ─────── AUDIO COLUMN ────────────────────────────────────────
            with col_audio:
                st.subheader("🎵 Audio")

                if part.index in st.session_state["audio_paths"]:
                    st.success("✅ Generated", icon="✓")
                    wav_path = st.session_state["audio_paths"][part.index]
                    st.caption(f"📁 {Path(wav_path).name}")

                    # Audio player
                    try:
                        with open(wav_path, "rb") as audio_file:
                            st.audio(audio_file, format="audio/wav")

                        # Download button
                        with open(wav_path, "rb") as audio_file:
                            st.download_button(
                                "📥 Download Audio",
                                data=audio_file.read(),
                                file_name=Path(wav_path).name,
                                mime="audio/wav",
                                use_container_width=True,
                            )
                    except Exception as e:
                        st.warning(f"Error: {e}")
                else:
                    st.info("⏳ Not generated", icon="ℹ️")

                audio_disabled = part.index not in st.session_state["scripts"]
                if st.button(
                    "Render Audio",
                    key=f"btn_audio_{part.index}",
                    disabled=audio_disabled,
                    use_container_width=True,
                    type="primary" if not audio_disabled else "secondary",
                ):
                    with st.spinner(f"⏳ Rendering audio for Part {part.index}..."):
                        try:
                            script_text = st.session_state["scripts"][part.index]
                            script = parse_script_text(cfg["topic"], cfg["style"], script_text)
                            wav_path = HISTORY_DIR / f"{base_slug}_part{part.index}.wav"

                            el_config_copy = dict(el_config)
                            el_config_copy["output_format"] = "pcm_24000"

                            # Get voices: use selected ones, fallback to config defaults, then API defaults
                            voice_ids = cfg["voice_ids"]
                            cleaned_voices = [v for v in voice_ids if v]

                            if not cleaned_voices:
                                # Fallback 1: use config defaults (tts_settings.json)
                                default_voices = el_config_copy.get("voices", [""])[
                                    :cfg["num_speakers"]
                                ]
                                cleaned_voices = [v for v in default_voices if v]

                            if not cleaned_voices:
                                # Fallback 2: fetch first available voice from ElevenLabs API
                                try:
                                    available_voices = _el_fetch_voices_cached()
                                    if available_voices:
                                        first_voice = available_voices[0]["voice_id"]
                                        cleaned_voices = [first_voice] * cfg["num_speakers"]
                                except Exception:
                                    pass

                            if not cleaned_voices:
                                st.error(
                                    "❌ Không tìm được voice. Check ELEVENLABS_API_KEY trong .env"
                                )
                                return

                            if len(cleaned_voices) == 1:
                                render_single_voice(script, wav_path, cleaned_voices[0], el_config_copy)
                            else:
                                render_multi_speaker(script, wav_path, cleaned_voices, el_config_copy)

                            st.session_state["audio_paths"][part.index] = str(wav_path)
                            st.success(f"✅ Audio rendered!")
                            st.rerun()
                        except ElevenLabsError as e:
                            st.error(f"❌ ElevenLabs error: {e}")
                        except Exception as e:
                            st.error(f"❌ Error: {e}")

            # ─────── SUBTITLE COLUMN ────────────────────────────────────
            with col_subtitle:
                st.subheader("📄 Subtitles")

                if part.index in st.session_state["subtitle_paths"]:
                    st.success("✅ Generated", icon="✓")
                    srt_path = st.session_state["subtitle_paths"][part.index]
                    st.caption(f"📁 {Path(srt_path).name}")

                    # Download SRT button
                    try:
                        with open(srt_path, "r", encoding="utf-8") as srt_file:
                            st.download_button(
                                "📥 Download SRT",
                                data=srt_file.read(),
                                file_name=Path(srt_path).name,
                                mime="text/plain",
                                use_container_width=True,
                            )
                    except Exception as e:
                        st.warning(f"Error: {e}")

                    # Also show JSON download
                    json_path = Path(srt_path).with_suffix(".json")
                    if json_path.exists():
                        try:
                            with open(json_path, "r", encoding="utf-8") as json_file:
                                st.download_button(
                                    "⏱️ Download JSON (timing)",
                                    data=json_file.read(),
                                    file_name=json_path.name,
                                    mime="application/json",
                                    use_container_width=True,
                                )
                        except Exception as e:
                            st.warning(f"Error: {e}")
                else:
                    st.info("⏳ Not generated", icon="ℹ️")

                sub_disabled = part.index not in st.session_state["audio_paths"]
                if st.button(
                    "Generate Subtitles",
                    key=f"btn_sub_{part.index}",
                    disabled=sub_disabled,
                    use_container_width=True,
                    type="primary" if not sub_disabled else "secondary",
                ):
                    with st.spinner(f"⏳ Generating subtitles for Part {part.index}..."):
                        try:
                            wav_path = st.session_state["audio_paths"][part.index]
                            srt_path = Path(wav_path).with_suffix(".srt")
                            base_path = Path(wav_path).with_suffix("")

                            transcript = transcribe(wav_path, language="vi", model_size="medium")
                            srt_path.write_text(
                                transcript_to_srt(transcript), encoding="utf-8"
                            )
                            write_json_outputs(transcript, base_path)

                            st.session_state["subtitle_paths"][part.index] = str(srt_path)
                            st.success(f"✅ Subtitles generated!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error: {e}")

    # ── Step 3: Summary ─────────────────────────────────────────────────
    st.divider()
    st.header("3️⃣ Summary")

    total_scripts = len(st.session_state["scripts"])
    total_audio = len(st.session_state["audio_paths"])
    total_subs = len(st.session_state["subtitle_paths"])

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Scripts", total_scripts, f"/ {cfg['num_parts']}")
    with col2:
        st.metric("Audio", total_audio, f"/ {cfg['num_parts']}")
    with col3:
        st.metric("Subtitles", total_subs, f"/ {cfg['num_parts']}")

    if total_audio > 0:
        st.success(
            f"✅ Generated {total_audio} audio file(s) in {HISTORY_DIR}"
        )

    # Download all subtitles as ZIP (if available)
    if total_subs > 0:
        st.divider()
        st.subheader("📥 Download Subtitles")

        # Show individual subtitle download links
        with st.expander(f"📝 {total_subs} Subtitle files", expanded=False):
            for part_idx, srt_path in st.session_state["subtitle_paths"].items():
                col_name, col_dl = st.columns([2, 1])
                with col_name:
                    st.caption(f"Part {part_idx}: {Path(srt_path).name}")
                with col_dl:
                    try:
                        with open(srt_path, "r", encoding="utf-8") as srt_file:
                            st.download_button(
                                "📥",
                                data=srt_file.read(),
                                file_name=Path(srt_path).name,
                                mime="text/plain",
                                key=f"summary_dl_srt_{part_idx}",
                                use_container_width=True,
                            )
                    except Exception as e:
                        st.warning(f"Error: {e}")

        # Also show JSON files (word-level timing)
        json_count = sum(1 for p in st.session_state["subtitle_paths"].values()
                        if Path(p).with_suffix(".json").exists())
        if json_count > 0:
            with st.expander(f"⏱️ {json_count} Word-level timing (.json)", expanded=False):
                for part_idx, srt_path in st.session_state["subtitle_paths"].items():
                    json_path = Path(srt_path).with_suffix(".json")
                    if json_path.exists():
                        col_name, col_dl = st.columns([2, 1])
                        with col_name:
                            st.caption(f"Part {part_idx}: {json_path.name}")
                        with col_dl:
                            try:
                                with open(json_path, "r", encoding="utf-8") as json_file:
                                    st.download_button(
                                        "📥",
                                        data=json_file.read(),
                                        file_name=json_path.name,
                                        mime="application/json",
                                        key=f"summary_dl_json_{part_idx}",
                                        use_container_width=True,
                                    )
                            except Exception as e:
                                st.warning(f"Error: {e}")

    if is_admin():
        st.divider()
        if st.button("🗑️ Clear all outputs", use_container_width=True):
            st.session_state["scripts"].clear()
            st.session_state["audio_paths"].clear()
            st.session_state["subtitle_paths"].clear()
            st.rerun()


if __name__ == "__main__":
    main()

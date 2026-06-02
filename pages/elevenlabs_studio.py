"""Dedicated ElevenLabs podcast generator — parallel to the Gemini TTS Studio."""
from __future__ import annotations

import os
import re

import streamlit as st
import streamlit.components.v1 as components
from google import genai

from config import STYLES, TEXT_MODEL
from elevenlabs_tts import (
    ElevenLabsError,
    list_voices,
    render_multi_speaker,
    render_single_voice,
)
from paths import HISTORY_DIR
from script_generator import generate_script, parse_script_text
from tts_settings import (
    ELEVEN_MODELS,
    ELEVEN_OUTPUT_FORMATS,
    get_elevenlabs_api_key,
    load_settings,
)

st.title("🎧 Tạo Podcast — ElevenLabs")
st.caption("Tool TTS song song với Tạo Podcast (Gemini). Dùng giọng ElevenLabs, không cần cài đặt provider.")

if not get_elevenlabs_api_key():
    st.error("Chưa có `ELEVENLABS_API_KEY` trong `.env`. Thêm key rồi restart app.")
    st.stop()

defaults = load_settings().get("elevenlabs", {})


# ── Cấu hình podcast ────────────────────────────────────────────────────────
st.subheader("1. Cấu hình")
c1, c2 = st.columns(2)
with c1:
    topic = st.text_input(
        "Chủ đề podcast",
        placeholder="VD: cách tự học tiếng Anh hiệu quả khi đi làm",
        key="els_topic",
    )
    style_key = st.selectbox(
        "Phong cách kịch bản",
        options=list(STYLES.keys()),
        format_func=lambda k: STYLES[k].label,
        key="els_style",
    )
with c2:
    num_speakers = st.radio(
        "Số speaker",
        options=[1, 2],
        format_func=lambda n: "1 người (narration)" if n == 1 else "2 người (đối thoại)",
        index=max(0, min(1, int(defaults.get("num_speakers", 2)) - 1)),
        horizontal=True,
        key="els_num_speakers",
    )


# ── Voice picker ────────────────────────────────────────────────────────────
st.divider()
st.subheader("2. Chọn voice")


@st.cache_data(ttl=300, show_spinner="Đang tải voice list…")
def _fetch_voices():
    return list_voices()


try:
    voices = _fetch_voices()
except Exception as e:
    st.error(f"Lỗi load voice: {e}")
    if st.button("🔄 Thử lại", key="els_retry_voices"):
        _fetch_voices.clear()
        st.rerun()
    st.stop()

_TIER_BY_USECASE = {
    "informative_educational": 3,
    "narrative_story": 3,
    "conversational": 2,
    "entertainment_tv": 2,
    "social_media": 1,
    "advertisement": 0,
    "characters_animation": 0,
}
_STARS = {3: "⭐⭐⭐", 2: "⭐⭐", 1: "⭐", 0: "  "}
_GENDER_ICON = {"male": "👨", "female": "👩", "neutral": "🧑"}


def _tier(v: dict) -> int:
    return _TIER_BY_USECASE.get((v.get("labels") or {}).get("use_case", ""), 1)


def _gender(v: dict) -> str:
    return (v.get("labels") or {}).get("gender", "").lower()


def _fmt_voice(v: dict) -> str:
    labels = v.get("labels") or {}
    name = v.get("name", "").split(" - ")[0].strip()
    bits = [b for b in (labels.get("accent", "").capitalize(), labels.get("descriptive", "")) if b]
    suffix = f" — {' · '.join(bits)}" if bits else ""
    return f"{_STARS[_tier(v)]} {_GENDER_ICON.get(_gender(v), '🎙️')} {name}{suffix}"


fc1, fc2 = st.columns(2)
with fc1:
    gender_filter = st.radio(
        "Giới tính",
        options=["all", "female", "male", "neutral"],
        format_func=lambda g: {"all": "Tất cả", "female": "👩 Nữ", "male": "👨 Nam", "neutral": "🧑 Trung tính"}[g],
        horizontal=True,
        key="els_gender_filter",
    )
with fc2:
    tier_filter = st.radio(
        "Tier",
        options=["listening", "podcast", "all"],
        format_func=lambda t: {
            "listening": "⭐⭐⭐ Listening (educational/narrative)",
            "podcast": "⭐⭐+ Listening + Podcast",
            "all": "Tất cả",
        }[t],
        key="els_tier_filter",
    )


def _passes(v: dict) -> bool:
    if gender_filter != "all" and _gender(v) != gender_filter:
        return False
    t = _tier(v)
    if t == 0:
        return False
    if tier_filter == "listening" and t < 3:
        return False
    if tier_filter == "podcast" and t < 2:
        return False
    return True


filtered = [v for v in voices if _passes(v)]
filtered_ids = [v["voice_id"] for v in filtered]
voice_label_map = {v["voice_id"]: _fmt_voice(v) for v in filtered}
voice_preview_map = {v["voice_id"]: v.get("preview_url", "") for v in voices}

if not filtered_ids:
    st.warning("Không có voice nào khớp filter. Thử nới filter.")
    st.stop()

st.caption(f"📊 Hiện {len(filtered_ids)}/{len(voices)} voice phù hợp filter")

current_voices = list(defaults.get("voices", ["", "", "", ""]))
while len(current_voices) < 4:
    current_voices.append("")


def _mark_changed(speaker_idx: int):
    st.session_state[f"_els_changed_{speaker_idx}"] = True


cols = st.columns(num_speakers) if num_speakers > 1 else [st.container()]
selected_voices: list[str] = []
for i in range(num_speakers):
    target = cols[i] if num_speakers > 1 else cols[0]
    with target:
        cur = current_voices[i] if current_voices[i] in filtered_ids else filtered_ids[0]
        chosen = st.selectbox(
            f"Speaker {i + 1}",
            options=filtered_ids,
            format_func=lambda vid: voice_label_map.get(vid, vid),
            index=filtered_ids.index(cur) if cur in filtered_ids else 0,
            key=f"els_voice_{i}",
            on_change=_mark_changed,
            args=(i,),
        )
        selected_voices.append(chosen)
        preview_url = voice_preview_map.get(chosen, "")
        if preview_url:
            jc = st.session_state.pop(f"_els_changed_{i}", False)
            autoplay = "autoplay" if jc else ""
            components.html(
                f"""
                <audio id="els_aud_{i}" controls {autoplay} style="width:100%">
                    <source src="{preview_url}" type="audio/mpeg">
                </audio>
                <script>
                    const a = document.getElementById('els_aud_{i}');
                    if (a && {str(jc).lower()}) {{ a.volume = 0.9; a.play().catch(() => {{}}); }}
                </script>
                """,
                height=60,
            )


# ── Voice tuning ────────────────────────────────────────────────────────────
with st.expander("⚙️ Voice tuning (model, sliders, output format)", expanded=False):
    mc1, mc2 = st.columns(2)
    with mc1:
        model_id = st.selectbox(
            "Model",
            options=ELEVEN_MODELS,
            index=ELEVEN_MODELS.index(defaults.get("model_id", "eleven_flash_v2_5"))
            if defaults.get("model_id") in ELEVEN_MODELS else 0,
            key="els_model",
        )
    with mc2:
        output_format = st.selectbox(
            "Output format",
            options=ELEVEN_OUTPUT_FORMATS,
            index=ELEVEN_OUTPUT_FORMATS.index(defaults.get("output_format", "mp3_44100_128"))
            if defaults.get("output_format") in ELEVEN_OUTPUT_FORMATS else 4,
            key="els_format",
        )
    sc1, sc2 = st.columns(2)
    with sc1:
        stability = st.slider("Stability", 0.0, 1.0, float(defaults.get("stability", 0.5)), 0.01, key="els_stab")
        similarity = st.slider("Similarity", 0.0, 1.0, float(defaults.get("similarity_boost", 0.75)), 0.01, key="els_sim")
    with sc2:
        style_val = st.slider("Style", 0.0, 1.0, float(defaults.get("style", 0.0)), 0.01, key="els_style_slider")
        speed = st.slider("Speed", 0.7, 1.2, float(defaults.get("speed", 1.0)), 0.05, key="els_speed")
    speaker_boost = st.toggle("Speaker boost", value=bool(defaults.get("use_speaker_boost", True)), key="els_boost")

current_config = {
    "model_id": model_id,
    "stability": stability,
    "similarity_boost": similarity,
    "style": style_val,
    "speed": speed,
    "use_speaker_boost": speaker_boost,
    "output_format": output_format,
}


# ── Script ──────────────────────────────────────────────────────────────────
st.divider()
st.subheader("3. Script")


def _slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w\s-]", "", text.lower()).strip()
    s = re.sub(r"[-\s]+", "_", s)
    return s[:max_len] or "podcast"


def _get_gemini_client():
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    try:
        return genai.Client(api_key=key)
    except Exception:
        return None


if "els_script_text" not in st.session_state:
    st.session_state["els_script_text"] = ""

bc1, bc2 = st.columns([1, 2])
with bc1:
    gen_disabled = not topic.strip()
    if st.button("🤖 Gen script (Gemini)", disabled=gen_disabled, use_container_width=True):
        client = _get_gemini_client()
        if client is None:
            st.error("Cần `GEMINI_API_KEY` trong `.env` để gen script bằng Gemini.")
        else:
            with st.spinner("Đang gen script…"):
                try:
                    sc = generate_script(client, topic, style_key, TEXT_MODEL)
                    st.session_state["els_script_text"] = sc.to_readable()
                    st.rerun()
                except Exception as e:
                    st.error(f"Lỗi gen script: {e}")
with bc2:
    st.caption(
        "Hoặc tự viết script — mỗi dòng theo format `Speaker1: ...` / `Speaker2: ...`. "
        "Nếu chọn 1 speaker, chỉ dùng `Speaker1:`."
    )

script_text = st.text_area(
    "Script (chỉnh sửa thoải mái)",
    value=st.session_state.get("els_script_text", ""),
    height=280,
    key="els_script_textarea",
    placeholder="Speaker1: Xin chào, hôm nay chúng ta sẽ nói về…\nSpeaker2: Tuyệt, tôi rất hứng thú về chủ đề này.",
)
st.session_state["els_script_text"] = script_text


# ── Render ──────────────────────────────────────────────────────────────────
st.divider()
st.subheader("4. Render audio")

render_disabled = not script_text.strip() or any(not v for v in selected_voices)
if st.button(
    "🎧 Render podcast với ElevenLabs",
    type="primary",
    disabled=render_disabled,
    use_container_width=True,
):
    slug = _slug(topic) if topic.strip() else "podcast"
    base_path = HISTORY_DIR / f"{slug}_elevenlabs"

    try:
        script = parse_script_text(topic or "Podcast", style_key, script_text)
    except Exception as e:
        st.error(f"Script parse failed: {e}")
        st.stop()

    if not script.lines:
        st.error("Script trống — kiểm tra lại format `Speaker1: ...`.")
        st.stop()

    progress = st.progress(0.0, "Đang render…")

    def _cb(idx: int, total: int, speaker: str):
        progress.progress(min(1.0, (idx + 1) / max(total, 1)), f"Render {idx + 1}/{total} ({speaker})")

    try:
        with st.spinner("Đang gọi ElevenLabs API…"):
            if num_speakers == 1:
                output_path = render_single_voice(script, base_path, selected_voices[0], current_config)
            else:
                output_path = render_multi_speaker(
                    script, base_path, selected_voices, current_config, progress_callback=_cb,
                )
        progress.empty()
        st.success(f"✅ Hoàn thành. File: `{output_path}`")
        audio_bytes = output_path.read_bytes()
        mime = "audio/mp3" if output_format.startswith("mp3") else "audio/wav"
        st.audio(audio_bytes, format=mime)
        st.download_button(
            "⬇️ Download",
            data=audio_bytes,
            file_name=output_path.name,
            mime=mime,
            use_container_width=True,
        )
    except ElevenLabsError as e:
        progress.empty()
        st.error(f"Lỗi ElevenLabs: {e}")
    except Exception as e:
        progress.empty()
        st.error(f"Lỗi không xác định: {e}")

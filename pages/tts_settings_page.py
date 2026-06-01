"""TTS Settings page — pick provider (Gemini / ElevenLabs) and tune ElevenLabs voices."""
import streamlit as st

from tts_settings import (
    ELEVEN_MODELS,
    ELEVEN_OUTPUT_FORMATS,
    PROVIDER_ELEVENLABS,
    PROVIDER_GEMINI,
    get_elevenlabs_api_key,
    load_settings,
    save_settings,
)

st.title("⚙️ Cài đặt TTS")

settings = load_settings()

st.subheader("1. Chọn nhà cung cấp TTS")
provider = st.radio(
    "Provider",
    options=[PROVIDER_GEMINI, PROVIDER_ELEVENLABS],
    format_func=lambda p: "🟢 Google Gemini (mặc định)" if p == PROVIDER_GEMINI else "🔵 ElevenLabs",
    index=0 if settings["tts_provider"] == PROVIDER_GEMINI else 1,
    horizontal=True,
)
settings["tts_provider"] = provider

st.divider()

if provider == PROVIDER_GEMINI:
    st.info(
        "Đang dùng **Google Gemini TTS** (`gemini-2.5-flash-preview-tts`). "
        "Voice + pace chọn trong tab **Tạo Podcast** ở sidebar bên trái. "
        "Cần `GEMINI_API_KEY` trong `.env`."
    )
    if st.button("💾 Lưu", type="primary"):
        save_settings(settings)
        st.success("Đã lưu — đang dùng Gemini.")
    st.stop()

# ───── ElevenLabs section ─────
api_key = get_elevenlabs_api_key()
if not api_key:
    st.error(
        "Chưa có `ELEVENLABS_API_KEY` trong `.env`. "
        "Thêm dòng `ELEVENLABS_API_KEY=sk_...` rồi restart app."
    )
    st.stop()

st.subheader("2. Voice cho từng Speaker")
st.caption(
    "Voice ở đây sẽ override voice picker trong tab Tạo Podcast. "
    "Speaker 1 = host A, Speaker 2 = host B (nếu podcast 1 giọng, chỉ Speaker 1 được dùng)."
)

@st.cache_data(ttl=300, show_spinner="Đang tải voice list từ ElevenLabs…")
def _fetch_voices():
    from elevenlabs_tts import list_voices
    return list_voices()

try:
    voices = _fetch_voices()
except Exception as e:
    st.error(f"Lỗi load voice list: {e}")
    if st.button("🔄 Thử lại"):
        _fetch_voices.clear()
        st.rerun()
    st.stop()

if not voices:
    st.warning("Tài khoản chưa có voice nào — hãy clone hoặc thêm voice trên web ElevenLabs.")
    st.stop()

voice_ids = [v["voice_id"] for v in voices]
voice_labels = {v["voice_id"]: f"{v['name']} ({v.get('category', '?')})" for v in voices}

current_voices = settings["elevenlabs"]["voices"]
while len(current_voices) < 4:
    current_voices.append("")

cols = st.columns(2)
selected_voices = []
for i in range(4):
    with cols[i % 2]:
        current = current_voices[i] if current_voices[i] in voice_ids else voice_ids[0]
        chosen = st.selectbox(
            f"Speaker {i + 1}",
            options=voice_ids,
            format_func=lambda vid: voice_labels.get(vid, vid),
            index=voice_ids.index(current) if current in voice_ids else 0,
            key=f"el_voice_{i}",
        )
        selected_voices.append(chosen)
settings["elevenlabs"]["voices"] = selected_voices

st.divider()
st.subheader("3. Model & Voice Settings")

el = settings["elevenlabs"]

mc1, mc2 = st.columns(2)
with mc1:
    el["model_id"] = st.selectbox(
        "Model",
        options=ELEVEN_MODELS,
        index=ELEVEN_MODELS.index(el["model_id"]) if el["model_id"] in ELEVEN_MODELS else 0,
        help="Flash v2.5 là model rẻ + nhanh nhất, phù hợp test.",
    )
with mc2:
    el["output_format"] = st.selectbox(
        "Output format",
        options=ELEVEN_OUTPUT_FORMATS,
        index=ELEVEN_OUTPUT_FORMATS.index(el["output_format"]) if el["output_format"] in ELEVEN_OUTPUT_FORMATS else 4,
        help="`mp3_44100_192` chỉ có ở gói Creator+. PCM/WAV sẽ tự wrap thành file .wav.",
    )

sc1, sc2 = st.columns(2)
with sc1:
    el["stability"] = st.slider(
        "Stability", 0.0, 1.0, float(el["stability"]), 0.01,
        help="Càng cao → giọng càng đều, ít cảm xúc. Thấp → biểu cảm hơn nhưng dễ vỡ.",
    )
    el["similarity_boost"] = st.slider(
        "Similarity", 0.0, 1.0, float(el["similarity_boost"]), 0.01,
        help="Mức độ bám sát voice gốc.",
    )
with sc2:
    el["style"] = st.slider(
        "Style", 0.0, 1.0, float(el["style"]), 0.01,
        help="Cường độ kiểu nói. v3 hỗ trợ tốt hơn. Để 0 nếu không chắc.",
    )
    el["speed"] = st.slider(
        "Speed", 0.7, 1.2, float(el["speed"]), 0.05,
        help="Flash v2.5 hỗ trợ 0.7–1.2. Ngoài range có thể bị clip.",
    )

el["use_speaker_boost"] = st.toggle(
    "Speaker boost",
    value=bool(el["use_speaker_boost"]),
    help="Tăng độ giống voice gốc, đánh đổi latency.",
)

st.divider()
if st.button("💾 Lưu cài đặt", type="primary", use_container_width=True):
    save_settings(settings)
    st.success("✅ Đã lưu. Tab Tạo Podcast sẽ dùng cài đặt này khi render.")

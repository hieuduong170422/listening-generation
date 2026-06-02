"""TTS Settings page — pick provider (Gemini / ElevenLabs) and tune ElevenLabs voices."""
import streamlit as st
import streamlit.components.v1 as components

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

# Tier mapping dựa trên use_case của ElevenLabs
_TIER_BY_USECASE = {
    "informative_educational": 3,  # ⭐⭐⭐ best for listening
    "narrative_story":         3,
    "conversational":          2,  # ⭐⭐ podcast tự nhiên
    "entertainment_tv":        2,
    "social_media":            1,  # ⭐ ổn nhưng hơi sôi nổi
    "advertisement":           0,  # không hợp listening
    "characters_animation":    0,
}
_TIER_STARS = {3: "⭐⭐⭐", 2: "⭐⭐", 1: "⭐", 0: "  "}
_GENDER_ICON = {"male": "👨", "female": "👩", "neutral": "🧑"}


def _voice_tier(voice: dict) -> int:
    uc = (voice.get("labels") or {}).get("use_case", "")
    return _TIER_BY_USECASE.get(uc, 1)


def _voice_gender(voice: dict) -> str:
    return (voice.get("labels") or {}).get("gender", "").lower()


def _format_voice(voice: dict) -> str:
    labels = voice.get("labels") or {}
    tier = _voice_tier(voice)
    gender = _voice_gender(voice)
    accent = labels.get("accent", "").capitalize()
    descriptive = labels.get("descriptive", "")
    name = voice.get("name", "").split(" - ")[0].strip()
    bits = [b for b in (accent, descriptive) if b]
    suffix = f" — {' · '.join(bits)}" if bits else ""
    return f"{_TIER_STARS[tier]} {_GENDER_ICON.get(gender, '🎙️')} {name}{suffix}"

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

all_voice_ids = [v["voice_id"] for v in voices]
voice_by_id = {v["voice_id"]: v for v in voices}
voice_labels = {v["voice_id"]: _format_voice(v) for v in voices}
voice_previews = {v["voice_id"]: v.get("preview_url", "") for v in voices}

# Filters
fc1, fc2 = st.columns(2)
with fc1:
    gender_filter = st.radio(
        "Giới tính",
        options=["all", "female", "male", "neutral"],
        format_func=lambda g: {"all": "Tất cả", "female": "👩 Nữ", "male": "👨 Nam", "neutral": "🧑 Trung tính"}[g],
        horizontal=True,
        key="el_gender_filter",
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
        horizontal=False,
        key="el_tier_filter",
    )

def _passes_filters(v: dict) -> bool:
    if gender_filter != "all" and _voice_gender(v) != gender_filter:
        return False
    tier = _voice_tier(v)
    if tier_filter == "listening" and tier < 3:
        return False
    if tier_filter == "podcast" and tier < 2:
        return False
    if tier_filter == "all" and tier == 0:
        # Vẫn ẩn nhóm character/ads ở "Tất cả" vì hoàn toàn không hợp listening
        return False
    return True

filtered_voices = [v for v in voices if _passes_filters(v)]
filtered_ids = [v["voice_id"] for v in filtered_voices]

if not filtered_ids:
    st.warning("Không có voice nào khớp filter. Thử nới filter.")
    st.stop()

st.caption(f"📊 Hiện {len(filtered_ids)}/{len(voices)} voice phù hợp filter")

# Số speaker (1-4)
num_speakers = st.radio(
    "Số speaker",
    options=[1, 2, 3, 4],
    format_func=lambda n: f"{n} speaker" if n == 1 else f"{n} speakers",
    horizontal=True,
    index=max(0, min(3, int(settings["elevenlabs"].get("num_speakers", 2)) - 1)),
    key="el_num_speakers",
)
settings["elevenlabs"]["num_speakers"] = num_speakers

current_voices = settings["elevenlabs"]["voices"]
while len(current_voices) < 4:
    current_voices.append("")

cols = st.columns(2) if num_speakers > 1 else [st.container()]
selected_voices = list(current_voices)  # keep all 4 slots for persistence

def _mark_voice_changed(speaker_idx: int):
    st.session_state[f"_el_just_changed_{speaker_idx}"] = True

for i in range(num_speakers):
    target = cols[i % len(cols)] if num_speakers > 1 else cols[0]
    with target:
        current = current_voices[i]
        if current not in filtered_ids:
            current = filtered_ids[0]
        chosen = st.selectbox(
            f"Speaker {i + 1}",
            options=filtered_ids,
            format_func=lambda vid: voice_labels.get(vid, vid),
            index=filtered_ids.index(current) if current in filtered_ids else 0,
            key=f"el_voice_{i}",
            on_change=_mark_voice_changed,
            args=(i,),
        )
        selected_voices[i] = chosen
        preview_url = voice_previews.get(chosen, "")
        if preview_url:
            just_changed = st.session_state.pop(f"_el_just_changed_{i}", False)
            autoplay_attr = "autoplay" if just_changed else ""
            components.html(
                f"""
                <audio id="aud_{i}" controls {autoplay_attr} style="width:100%">
                    <source src="{preview_url}" type="audio/mpeg">
                </audio>
                <script>
                    const a = document.getElementById('aud_{i}');
                    if (a && {str(just_changed).lower()}) {{
                        a.volume = 0.9;
                        a.play().catch(() => {{}});
                    }}
                </script>
                """,
                height=60,
            )
            st.caption("🔊 Phát khi đổi voice — sample gốc, chưa áp slider")
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
st.subheader("4. Test thử voice với cài đặt hiện tại")
st.caption("Gen câu mẫu với đúng slider + model + output format đang cài. Tốn ~1-2 credit.")

tc1, tc2 = st.columns([3, 1])
with tc1:
    test_text = st.text_input(
        "Câu mẫu",
        value="Xin chào, đây là bài test giọng đọc tiếng Việt — một, hai, ba.",
        key="el_test_text",
    )
with tc2:
    test_speaker = st.selectbox(
        "Voice của Speaker",
        options=list(range(1, num_speakers + 1)),
        format_func=lambda i: f"Speaker {i}",
        key="el_test_speaker",
    )

if st.button("🎧 Gen thử", use_container_width=True):
    target_voice = selected_voices[test_speaker - 1]
    if not target_voice:
        st.error(f"Speaker {test_speaker} chưa chọn voice.")
    elif not test_text.strip():
        st.error("Nhập câu mẫu trước.")
    else:
        from elevenlabs_tts import synthesize_preview, ElevenLabsError, _bytes_to_segment
        import io as _io
        try:
            with st.spinner("Đang gen…"):
                audio_bytes = synthesize_preview(test_text, target_voice, el)
            fmt = el["output_format"]
            if fmt.startswith("mp3"):
                playable_bytes = audio_bytes
                mime = "audio/mp3"
            else:
                segment = _bytes_to_segment(audio_bytes, fmt)
                buf = _io.BytesIO()
                segment.export(buf, format="wav")
                playable_bytes = buf.getvalue()
                mime = "audio/wav"
            st.audio(playable_bytes, format=mime)
            st.caption(f"✅ Voice: {voice_labels.get(target_voice, target_voice)} · Format: `{fmt}`")
        except ElevenLabsError as e:
            st.error(f"Lỗi: {e}")
        except Exception as e:
            st.error(f"Lỗi không xác định: {e}")

st.divider()
if st.button("💾 Lưu cài đặt", type="primary", use_container_width=True):
    save_settings(settings)
    st.success("✅ Đã lưu. Tab Tạo Podcast sẽ dùng cài đặt này khi render.")

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from google import genai

from paths import HISTORY_DIR
from podcast_studio.auth import is_admin as _is_admin
from podcast_studio.genai_client import (
    get_client as _get_text_client,
    get_api_key_client as _get_media_client,
    vertex_enabled as _vertex_enabled,
)
from podcast_studio.image_generator import generate_part_image
from podcast_studio.video_builder import build_part_video, concat_videos, ffmpeg_available
from podcast_studio.config import (
    AUDIENCE_LEVELS,
    DEFAULT_AUDIENCE,
    DEFAULT_CHANNEL_NAME,
    DEFAULT_HOST_NAMES,
    DEFAULT_LANGUAGE,
    DEFAULT_NUM_SPEAKERS,
    DEFAULT_PACE,
    DEFAULT_SHOW_NAME,
    DEFAULT_TONE,
    DEFAULT_TOTAL_MINUTES,
    DURATION_PRESETS,
    LANGUAGES,
    MAX_NUM_SPEAKERS,
    SPEECH_PACES,
    STYLES,
    TEXT_MODEL_OPTIONS,
    TONES,
)
from podcast_studio.api_utils import DEFAULT_USD_TO_VND, summarize_usage
from podcast_studio.outline_generator import Outline, PartBrief, generate_outline
from podcast_studio.script_generator import extract_tail_lines, generate_part_script, parse_script_text
from podcast_studio.topic_suggester import suggest_topics
from podcast_studio.elevenlabs_tts import (
    ElevenLabsError,
    list_voices as _el_list_voices,
    render_multi_speaker as _el_render_multi,
    render_single_voice as _el_render_single,
    voice_supports_model as _el_voice_supports_model,
)
from podcast_studio.tts_settings import (
    ELEVEN_MODELS,
    get_elevenlabs_api_key,
    load_settings as _el_load_settings,
)
from podcast_studio.usage_logger import (
    aggregate_by_period,
    aggregate_by_user,
    clear_log,
    events_to_csv,
    filter_by_date,
    log_event,
    log_path,
    read_log,
)

def _slug(text: str, max_len: int = 40) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


# ── ElevenLabs voice picker helpers ─────────────────────────────────────────
_EL_TIER_BY_USECASE = {
    "informative_educational": 3,
    "narrative_story": 3,
    "conversational": 2,
    "entertainment_tv": 2,
    "social_media": 1,
    "advertisement": 0,
    "characters_animation": 0,
}
_EL_STARS = {3: "⭐⭐⭐", 2: "⭐⭐", 1: "⭐", 0: "  "}
_EL_GENDER_ICON = {"male": "👨", "female": "👩", "neutral": "🧑"}


@st.cache_data(ttl=300, show_spinner="Đang tải voice list ElevenLabs…")
def _el_fetch_voices_cached() -> list[dict]:
    return _el_list_voices()


def _el_tier(v: dict) -> int:
    return _EL_TIER_BY_USECASE.get((v.get("labels") or {}).get("use_case", ""), 1)


def _el_gender(v: dict) -> str:
    return (v.get("labels") or {}).get("gender", "").lower()


def _el_fmt_voice(v: dict) -> str:
    labels = v.get("labels") or {}
    name = v.get("name", "").split(" - ")[0].strip()
    bits = [b for b in (labels.get("accent", "").capitalize(), labels.get("descriptive", "")) if b]
    suffix = f" — {' · '.join(bits)}" if bits else ""
    return f"{_EL_STARS[_el_tier(v)]} {_EL_GENDER_ICON.get(_el_gender(v), '🎙️')} {name}{suffix}"


def _el_passes(v: dict, gender_filter: str, tier_filter: str) -> bool:
    if gender_filter != "all" and _el_gender(v) != gender_filter:
        return False
    tier = _el_tier(v)
    if tier == 0:
        return False
    if tier_filter == "listening" and tier < 3:
        return False
    if tier_filter == "podcast" and tier < 2:
        return False
    return True


def _el_mark_voice_changed(speaker_idx: int) -> None:
    st.session_state[f"_el_voice_changed_{speaker_idx}"] = True


# Text (outline/script/topic) chạy qua Vertex AI khi bật GOOGLE_GENAI_USE_VERTEXAI →
# _get_text_client(). Sinh ảnh vẫn dùng GEMINI_API_KEY → _get_media_client().
# (TTS ở studio này đi qua ElevenLabs, không dùng genai client.)


def _persist_usage(action: str, topic: str, before_len: int) -> None:
    log = st.session_state.get("usage_log") or []
    user = st.session_state.get("username", "anonymous")
    for entry in log[before_len:]:
        try:
            log_event(
                kind=entry["kind"],
                action=action,
                prompt_tokens=entry["prompt_tokens"],
                output_tokens=entry["output_tokens"],
                cost_usd=entry["cost_usd"],
                user=user,
                topic=topic,
            )
        except Exception:
            pass


def _init_state() -> None:
    defaults = {
        "outline": None,
        "outline_dict": None,
        "scripts": {},
        "audio_paths": {},
        "image_paths": {},
        "video_paths": {},
        "subtitle_paths": {},
        "full_video_path": None,
        "base_slug": None,
        "cancel": False,
        "usage_log": [],
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
    before = len(st.session_state.get("usage_log") or [])
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
        language=cfg["language"],
        usage_store=st.session_state.get("usage_log"),
    )
    _persist_usage(f"script_part{part.index}", outline.topic, before)
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

    el_cfg = dict(st.session_state.get("_el_render_config") or {})
    el_cfg["output_format"] = "pcm_24000"

    cleaned_voices = [v for v in voices if v]
    if not cleaned_voices:
        raise ValueError("Chưa chọn voice cho speaker — kiểm tra sidebar.")

    if len(cleaned_voices) == 1:
        _el_render_single(script, wav_path, cleaned_voices[0], el_cfg)
    else:
        _el_render_multi(
            script, wav_path, cleaned_voices, el_cfg,
            progress_callback=progress_callback,
        )
    return str(wav_path)


def _suggest_num_parts(total_minutes: int) -> int:
    target_per_part = 2
    return max(1, round(total_minutes / target_per_part))


_SIDEBAR_CSS = """
<style>
section[data-testid="stSidebar"] { width: 520px !important; min-width: 520px !important; }
section[data-testid="stSidebar"] > div { width: 520px !important; }
</style>
"""


def _sidebar(client: genai.Client) -> dict:
    st.markdown(_SIDEBAR_CSS, unsafe_allow_html=True)
    with st.sidebar:
        st.header("⚙️ Cấu hình")

        with st.expander("📺 Show & Chủ đề", expanded=True):
            language_keys = list(LANGUAGES.keys())
            language = st.selectbox(
                "🌐 Ngôn ngữ kịch bản",
                language_keys,
                index=language_keys.index(DEFAULT_LANGUAGE),
                format_func=lambda k: f"{LANGUAGES[k]['label']} ({LANGUAGES[k]['native']})",
                help="Ngôn ngữ AI sẽ viết toàn bộ kịch bản. Đổi sang Chinese, Japanese, etc. tuỳ ý.",
            )
            st.session_state["_language_for_suggest"] = language

            bc1, bc2 = st.columns(2)
            with bc1:
                channel_name = st.text_input("Tên kênh YouTube", value=DEFAULT_CHANNEL_NAME)
            with bc2:
                show_name = st.text_input("Tên show / podcast", value=DEFAULT_SHOW_NAME)

            if "topic_text" not in st.session_state:
                st.session_state["topic_text"] = "How to communicate effectively in English"

            topic = st.text_area(
                "Chủ đề tập này",
                height=80,
                key="topic_text",
            )

            suggest_count = st.slider(
                "Số chủ đề gợi ý",
                min_value=1,
                max_value=5,
                value=3,
                help="Số lượng chủ đề AI sẽ gợi ý khi bấm 💡.",
            )

            sc1, sc2 = st.columns([1, 1])
            with sc1:
                suggest_clicked = st.button(
                    "💡 Gợi ý chủ đề", use_container_width=True,
                    help="AI gen N chủ đề gợi ý — chọn 1 để fill vào ô Chủ đề.",
                )
            with sc2:
                if st.button("🔁 Gen lại gợi ý", use_container_width=True,
                             disabled=not st.session_state.get("topic_suggestions")):
                    suggest_clicked = True

            if suggest_clicked:
                with st.spinner("Đang nghĩ chủ đề..."):
                    try:
                        before = len(st.session_state.get("usage_log") or [])
                        suggestions = suggest_topics(
                            client,
                            audience_level=st.session_state.get("_audience_for_suggest", "intermediate"),
                            count=int(suggest_count),
                            text_model=st.session_state.get("_model_for_suggest", "gemini-2.5-flash"),
                            seed_hint=topic if topic and topic != "How to communicate effectively in English" else "",
                            tone=st.session_state.get("_tone_for_suggest", ""),
                            language=language,
                            usage_store=st.session_state.get("usage_log"),
                        )
                        _persist_usage("suggest_topics", topic or "", before)
                        st.session_state["topic_suggestions"] = suggestions
                    except Exception as e:
                        st.error(f"Lỗi gen gợi ý: {e}")

            suggestions = st.session_state.get("topic_suggestions") or []
            if suggestions:
                picked = st.selectbox(
                    "📋 Gợi ý (chọn 1 để dùng)",
                    ["— chọn —"] + suggestions,
                    index=0,
                    key="topic_suggest_pick",
                )

                def _apply_picked_topic():
                    p = st.session_state.get("topic_suggest_pick")
                    if p and p != "— chọn —":
                        st.session_state["topic_text"] = p
                        st.session_state["topic_suggest_pick"] = "— chọn —"

                if picked != "— chọn —":
                    st.button(
                        "✅ Dùng chủ đề này",
                        use_container_width=True,
                        on_click=_apply_picked_topic,
                    )

        with st.expander("⏱️ Thời lượng", expanded=True):
            dc1, dc2 = st.columns(2)
            with dc1:
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
            with dc2:
                suggested = _suggest_num_parts(total_minutes)
                num_parts = int(
                    st.number_input(
                        "Số part (chia file)",
                        min_value=1,
                        max_value=min(20, total_minutes),
                        value=suggested,
                        help="Khuyến nghị ~2 phút/part. Part càng ngắn càng ít lỗi TTS rẹt/vang.",
                    )
                )
            minutes_per_part = max(1, round(total_minutes / num_parts))
            quality_hint = ""
            if minutes_per_part > 4:
                quality_hint = " ⚠️ part dài >4 phút dễ bị lỗi TTS, nên chia nhỏ hơn"
            elif minutes_per_part <= 2:
                quality_hint = " ✅ part ngắn ổn định"
            st.caption(
                f"→ **{num_parts} file × ~{minutes_per_part} phút** "
                f"(tổng ~{num_parts * minutes_per_part} phút){quality_hint}"
            )

        with st.expander("✍️ Nội dung", expanded=False):
            cc1, cc2 = st.columns(2)
            with cc1:
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
            with cc2:
                tone_keys = list(TONES.keys())
                tone = st.selectbox(
                    "Giọng điệu (tone)",
                    tone_keys,
                    index=tone_keys.index(DEFAULT_TONE),
                )
                continuous = st.toggle(
                    "🔗 Hội thoại liên tục",
                    value=True,
                    help=(
                        "BẬT: cả series là 1 hội thoại dài, chỉ part 1 chào, chỉ part cuối kết.\n"
                        "TẮT: mỗi part là episode độc lập."
                    ),
                )
            st.session_state["_audience_for_suggest"] = audience_level
            st.session_state["_tone_for_suggest"] = TONES.get(tone, "")

        with st.expander("🎙️ Giọng đọc (ElevenLabs)", expanded=False):
            _el_all_voices: list[dict] = []
            if not get_elevenlabs_api_key():
                st.info(
                    "ℹ️ Chưa có `ELEVENLABS_API_KEY` — phần chọn giọng tạm ẩn. "
                    "Vẫn gen script/outline bình thường; thêm key khi cần **Render audio**."
                )
            else:
                try:
                    _el_all_voices = _el_fetch_voices_cached()
                except Exception as _e:
                    st.error(f"Không load được voice list ElevenLabs: {_e}")

            _el_defaults_for_model = _el_load_settings().get("elevenlabs", {})
            _el_model = st.selectbox(
                "Model",
                ELEVEN_MODELS,
                index=ELEVEN_MODELS.index(_el_defaults_for_model.get("model_id", "eleven_flash_v2_5"))
                if _el_defaults_for_model.get("model_id") in ELEVEN_MODELS else 0,
                key="_el_model_sidebar",
                help=(
                    "Engine TTS của ElevenLabs. **Voice list bên dưới sẽ filter theo model này.**\n\n"
                    "• **eleven_flash_v2_5** — Rẻ + nhanh nhất, hỗ trợ Speed slider. Khuyên dùng.\n\n"
                    "• **eleven_turbo_v2_5** — Nhanh + chất lượng cao hơn Flash. Tốn credit gấp đôi.\n\n"
                    "• **eleven_multilingual_v2** — Chất lượng cao nhất, hợp đa ngôn ngữ. Voice ít hơn.\n\n"
                    "• **eleven_v3** — Mới nhất, hỗ trợ tags `[laugh]`, `[whispers]`. Voice ít nhất."
                ),
            )

            vc1, vc2 = st.columns(2)
            with vc1:
                num_speakers = st.selectbox(
                    "Số người dẫn",
                    list(range(1, MAX_NUM_SPEAKERS + 1)),
                    index=DEFAULT_NUM_SPEAKERS - 1,
                    format_func=lambda n: f"{n} người" + (" (monologue)" if n == 1 else ""),
                    help="2+ người: ElevenLabs render từng dòng riêng rồi ghép — tốn nhiều credit hơn.",
                )
            with vc2:
                pace_keys = list(SPEECH_PACES.keys())
                pace = st.selectbox(
                    "Tốc độ đọc (chỉ ảnh hưởng prompt)",
                    pace_keys,
                    index=pace_keys.index(DEFAULT_PACE),
                    help="ElevenLabs điều chỉnh tốc độ qua slider 'Speed' bên dưới, không qua prompt.",
                )

            fc1, fc2 = st.columns(2)
            with fc1:
                _gender_filter = st.radio(
                    "Giới tính",
                    options=["all", "female", "male", "neutral"],
                    format_func=lambda g: {"all": "Tất cả", "female": "👩 Nữ", "male": "👨 Nam", "neutral": "🧑 TT"}[g],
                    horizontal=True,
                    key="_el_gender_filter",
                )
            with fc2:
                _tier_filter = st.radio(
                    "Tier",
                    options=["listening", "podcast", "all"],
                    format_func=lambda t: {
                        "listening": "⭐⭐⭐ Listening",
                        "podcast": "⭐⭐+ Podcast",
                        "all": "Tất cả",
                    }[t],
                    horizontal=True,
                    key="_el_tier_filter",
                )

            _compat_count = sum(
                1 for v in _el_all_voices if _el_voice_supports_model(v, _el_model)
            )
            _model_compat_unknown = _compat_count == 0
            if _model_compat_unknown:
                st.info(
                    f"ℹ️ Model **{_el_model}** mới — ElevenLabs chưa cập nhật compat info, "
                    "tạm hiện tất cả voice. Render thực tế có thể fail với 1 số voice cũ."
                )
            _filtered = [
                v for v in _el_all_voices
                if _el_passes(v, _gender_filter, _tier_filter)
                and (_model_compat_unknown or _el_voice_supports_model(v, _el_model))
            ]
            if not _filtered and _el_all_voices:
                st.warning(
                    f"Không có voice nào khớp filter + model **{_el_model}**. "
                    "Thử đổi model hoặc nới filter giới tính/tier."
                )

            _filtered_ids = [v["voice_id"] for v in _filtered]
            _voice_label_map = {v["voice_id"]: _el_fmt_voice(v) for v in _filtered}
            _voice_preview_map = {v["voice_id"]: v.get("preview_url", "") for v in _el_all_voices}
            if _model_compat_unknown:
                st.caption(f"📊 Hiện **{len(_filtered_ids)}** voice (model compat info chưa có)")
            else:
                st.caption(
                    f"📊 Hiện **{len(_filtered_ids)}** voice "
                    f"(model `{_el_model}` hỗ trợ {_compat_count}/{len(_el_all_voices)})"
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
                    if _filtered_ids:
                        voice = st.selectbox(
                            f"Voice {i + 1}",
                            _filtered_ids,
                            format_func=lambda vid: _voice_label_map.get(vid, vid),
                            index=0,
                            key=f"host_voice_{i}",
                            on_change=_el_mark_voice_changed,
                            args=(i,),
                        )
                    else:
                        voice = ""
                        st.caption("— (cần `ELEVENLABS_API_KEY` để chọn giọng)")
                    host_voices.append(voice)
                _preview_url = _voice_preview_map.get(voice, "") if voice else ""
                if _preview_url:
                    _jc = st.session_state.pop(f"_el_voice_changed_{i}", False)
                    _autoplay = "autoplay" if _jc else ""
                    components.html(
                        f"""
                        <audio id="el_studio_aud_{i}" controls {_autoplay} style="width:100%">
                            <source src="{_preview_url}" type="audio/mpeg">
                        </audio>
                        <script>
                            const a = document.getElementById('el_studio_aud_{i}');
                            if (a && {str(_jc).lower()}) {{ a.volume = 0.9; a.play().catch(() => {{}}); }}
                        </script>
                        """,
                        height=60,
                    )

        with st.expander("🎚️ ElevenLabs voice tuning", expanded=False):
            st.markdown(
                "📘 **Hướng dẫn nhanh** — bấm icon ❔ cạnh từng slider để xem chi tiết. "
                "Nếu chưa quen, để mặc định và chỉnh dần."
            )
            st.caption(f"🤖 Model đang dùng: **`{_el_model}`** (đổi ở expander Giọng đọc bên trên)")
            _el_defaults = _el_load_settings().get("elevenlabs", {})
            tc1, tc2 = st.columns(2)
            with tc1:
                _el_stability = st.slider(
                    "Stability", 0.0, 1.0, float(_el_defaults.get("stability", 0.5)), 0.01,
                    key="_el_stab_sidebar",
                    help=(
                        "**Độ ổn định / nhất quán giữa các câu.**\n\n"
                        "• **Thấp (0.0–0.3)**: Giọng biểu cảm, có cảm xúc thay đổi mạnh — "
                        "nhưng dễ bị 'vỡ' (đột nhiên đổi tone, phát âm sai, thì thầm lạ).\n\n"
                        "• **Trung (0.4–0.6)**: Cân bằng — tự nhiên + đủ ổn định. **Khuyên dùng.**\n\n"
                        "• **Cao (0.7–1.0)**: Giọng đều, ổn định, ít cảm xúc — hợp đọc tin tức, "
                        "narration dài. Nhưng nghe khá đơn điệu, không truyền cảm.\n\n"
                        "👉 Podcast learning thường để **0.5** là vừa."
                    ),
                )
                _el_similarity = st.slider(
                    "Similarity", 0.0, 1.0, float(_el_defaults.get("similarity_boost", 0.75)), 0.01,
                    key="_el_sim_sidebar",
                    help=(
                        "**Độ giống voice gốc.**\n\n"
                        "Quyết định model bám sát đặc trưng (timbre, accent, phong cách) của voice mẫu tới mức nào.\n\n"
                        "• **Thấp (<0.5)**: Giọng có thể khác xa voice mẫu — bị 'pha trộn' với giọng generic.\n\n"
                        "• **Cao (>0.75)**: Bám sát voice gốc — nhưng nếu sample gốc có **noise** "
                        "(tiếng vang, gió, breath), noise đó cũng được khuếch đại theo.\n\n"
                        "👉 Voice từ thư viện ElevenLabs (premade) có sample sạch → để **0.75–0.85** an toàn."
                    ),
                )
            with tc2:
                _el_style = st.slider(
                    "Style", 0.0, 1.0, float(_el_defaults.get("style", 0.0)), 0.01,
                    key="_el_style_sidebar",
                    help=(
                        "**Mức độ phóng đại 'style' / ngữ điệu của voice gốc.**\n\n"
                        "• **0.0**: Không phóng đại — model dùng ngữ điệu trung tính. "
                        "**An toàn nhất, khuyên dùng nếu chưa rõ.**\n\n"
                        "• **0.3–0.5**: Hơi đậm style hơn — hợp voice có character rõ "
                        "(VD: storyteller, dramatic).\n\n"
                        "• **>0.5**: Phóng đại mạnh — dễ over-acting, nghe giả, "
                        "tăng latency render. Hiếm khi dùng cho podcast.\n\n"
                        "⚠️ Set >0 có thể giảm độ stability — bù bằng tăng Stability lên 0.5+."
                    ),
                )
                _el_speed = st.slider(
                    "Speed", 0.7, 1.2, float(_el_defaults.get("speed", 1.0)), 0.05,
                    key="_el_speed_sidebar",
                    help=(
                        "**Tốc độ đọc.**\n\n"
                        "• **0.7–0.9**: Chậm — hợp listening practice trình độ A2–B1, "
                        "người mới học, narration ASMR.\n\n"
                        "• **1.0**: Tốc độ tự nhiên (mặc định).\n\n"
                        "• **1.1–1.2**: Nhanh — hợp podcast năng động, target audience C1+.\n\n"
                        "⚠️ Chỉ Flash v2.5 / Turbo v2.5 hỗ trợ slider Speed. "
                        "Các model khác bỏ qua thông số này."
                    ),
                )
                _el_boost = st.toggle(
                    "Speaker boost",
                    value=bool(_el_defaults.get("use_speaker_boost", True)),
                    key="_el_boost_sidebar",
                    help=(
                        "**Tăng cường độ giống voice gốc.**\n\n"
                        "Bật → model 'cố gắng' hơn để khớp timbre/style của sample gốc, "
                        "đặc biệt hữu ích cho **cloned voice** (voice m tự upload).\n\n"
                        "• **Cost**: Tăng latency render ~10–20%.\n\n"
                        "• **Khi nào BẬT**: Đang dùng voice clone tự upload, hoặc voice từ "
                        "Voice Library mà m muốn khớp tối đa.\n\n"
                        "• **Khi nào TẮT**: Test nhanh, hoặc thấy giọng nghe đã đủ giống — "
                        "tắt để render nhanh hơn."
                    ),
                )

            st.session_state["_el_render_config"] = {
                "model_id": _el_model,
                "stability": _el_stability,
                "similarity_boost": _el_similarity,
                "style": _el_style,
                "speed": _el_speed,
                "use_speaker_boost": _el_boost,
                "output_format": "pcm_24000",
            }
            st.caption("⚙️ Audio output ép `pcm_24000` (.wav) để tương thích video assembly.")

        with st.expander("🤖 Model", expanded=False):
            text_model = st.selectbox("Text model", TEXT_MODEL_OPTIONS, index=0)
            st.session_state["_model_for_suggest"] = text_model

        with st.expander("💰 Token & Chi phí (session)", expanded=False):
            summary = summarize_usage(st.session_state.get("usage_log") or [])
            if summary["calls"] == 0:
                st.caption("Chưa có gen nào trong session này.")
            else:
                st.metric("Tổng chi phí session", f"${summary['total_cost_usd']:.4f}",
                          f"{summary['total_cost_vnd']:,}đ")
                st.caption(
                    f"Tổng {summary['calls']} calls · "
                    f"in {summary['total_prompt']:,} / out {summary['total_output']:,} tokens"
                )

                st.divider()
                text_info = summary["by_kind"].get("text", {"prompt": 0, "output": 0, "cost_usd": 0.0, "calls": 0})
                tts_info = summary["by_kind"].get("tts", {"prompt": 0, "output": 0, "cost_usd": 0.0, "calls": 0})
                total_cost = max(summary["total_cost_usd"], 1e-9)
                text_pct = text_info["cost_usd"] / total_cost * 100
                tts_pct = tts_info["cost_usd"] / total_cost * 100

                st.markdown(f"**📝 Script gen (text)** — {text_pct:.1f}% tổng")
                sg1, sg2 = st.columns(2)
                sg1.metric("Calls", text_info["calls"])
                sg2.metric(
                    "Cost",
                    f"${text_info['cost_usd']:.4f}",
                    f"{int(text_info['cost_usd'] * DEFAULT_USD_TO_VND):,}đ",
                )
                st.caption(
                    f"Input: {text_info['prompt']:,} tokens · Output: {text_info['output']:,} tokens"
                )

                st.markdown(f"**🔊 Audio gen (TTS)** — {tts_pct:.1f}% tổng")
                ag1, ag2 = st.columns(2)
                ag1.metric("Calls", tts_info["calls"])
                ag2.metric(
                    "Cost",
                    f"${tts_info['cost_usd']:.4f}",
                    f"{int(tts_info['cost_usd'] * DEFAULT_USD_TO_VND):,}đ",
                )
                st.caption(
                    f"Input: {tts_info['prompt']:,} tokens · Output (audio): {tts_info['output']:,} tokens"
                )
            if st.button("🗑️ Reset usage log", use_container_width=True):
                st.session_state["usage_log"] = []
                st.rerun()

        st.divider()
        if st.button("🔄 Reset session", use_container_width=True):
            for k in ("outline", "outline_dict", "base_slug", "full_video_path"):
                st.session_state[k] = None
            st.session_state["scripts"] = {}
            st.session_state["audio_paths"] = {}
            st.session_state["image_paths"] = {}
            st.session_state["video_paths"] = {}
            st.session_state["subtitle_paths"] = {}
            st.session_state["cancel"] = False
            st.session_state["usage_log"] = []
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
        "language": language,
    }


def _step_outline(client: genai.Client, cfg: dict) -> None:
    st.header("Step 1 — Outline")
    if st.button("📝 Generate outline", type="primary", disabled=not cfg["topic"].strip()):
        with st.spinner("Đang sinh outline..."):
            try:
                before = len(st.session_state.get("usage_log") or [])
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
                    language=cfg["language"],
                    usage_store=st.session_state.get("usage_log"),
                )
                _persist_usage("outline", cfg["topic"], before)
                st.session_state["outline"] = outline
                st.session_state["outline_dict"] = _outline_to_dict(outline)
                st.session_state["base_slug"] = (
                    f"{_slug(cfg['topic'])}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )
                st.session_state["scripts"] = {}
                st.session_state["audio_paths"] = {}
                st.session_state["image_paths"] = {}
                st.session_state["video_paths"] = {}
                st.session_state["full_video_path"] = None
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

    cols = st.columns([1.4, 1.4, 1, 3])
    run_all_clicked = cols[0].button("▶ Run All Remaining", type="primary")
    render_missing_clicked = cols[1].button(
        "🔊 Render audio thiếu", disabled=missing_audio_with_script == 0
    )
    if cols[2].button("■ Cancel"):
        st.session_state["cancel"] = True

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

    _render_full_video_bar(outline, base_slug)

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
                _render_part_video(part, base_slug)


def _render_full_video_bar(outline: Outline, base_slug: str) -> None:
    """Thanh ghép tất cả part-video thành 1 video full."""
    total = len(outline.parts)
    n_videos = len(st.session_state["video_paths"])
    if not ffmpeg_available():
        st.warning("⚠️ Chưa cài **ffmpeg** — chạy `brew install ffmpeg` để dùng tính năng video.")
        return
    if n_videos == 0:
        return

    st.caption(f"🎬 Video: **{n_videos}/{total}** part đã có MP4")
    can_concat = n_videos == total and total > 0
    if st.button(
        "🎬 Ghép video full", type="primary", disabled=not can_concat,
        help="Cần tất cả part đều đã tạo video MP4.",
    ):
        with st.spinner("Đang ghép video full..."):
            try:
                ordered = [
                    Path(st.session_state["video_paths"][p.index])
                    for p in outline.parts
                    if p.index in st.session_state["video_paths"]
                ]
                full_path = HISTORY_DIR / f"{base_slug}_full.mp4"
                concat_videos(ordered, full_path)
                st.session_state["full_video_path"] = str(full_path)
                st.success(f"✓ Video full: `{full_path}`")
            except Exception as e:
                st.error(f"Lỗi ghép video: {e}")

    full = st.session_state.get("full_video_path")
    if full and Path(full).exists():
        st.video(full)
        with open(full, "rb") as f:
            st.download_button(
                "⬇️ Download video full (.mp4)", data=f,
                file_name=Path(full).name, mime="video/mp4",
            )
    st.divider()


def _render_part_video(part: PartBrief, base_slug: str) -> None:
    """Khối gen sub + gen ảnh + tạo video MP4 cho 1 part."""
    idx = part.index
    has_image = idx in st.session_state["image_paths"]
    has_video = idx in st.session_state["video_paths"]
    has_audio = idx in st.session_state["audio_paths"]
    has_sub = idx in st.session_state["subtitle_paths"]

    # ── Subtitle section ──────────────────────────────────────────────
    st.markdown("**📝 Subtitle (.srt)**")
    sc1, sc2 = st.columns(2)
    gen_sub = sc1.button(
        "✨ Gen subtitle" if not has_sub else "🔁 Gen lại subtitle",
        key=f"gensub_{idx}", use_container_width=True, disabled=not has_audio,
    )
    if has_sub:
        srt_path = Path(st.session_state["subtitle_paths"][idx])
        if srt_path.exists():
            sc2.download_button(
                "⬇️ Tải SRT",
                data=srt_path.read_bytes(),
                file_name=srt_path.name,
                mime="text/plain",
                key=f"dlsub_{idx}",
                use_container_width=True,
            )

    if gen_sub:
        with st.spinner(f"Đang align subtitle cho Part {idx} (Gemini Audio)…"):
            try:
                from podcast_studio.subtitle_gen import generate_srt
                srt_out = HISTORY_DIR / f"{base_slug}_part{idx}.srt"
                generate_srt(
                    audio_path=Path(st.session_state["audio_paths"][idx]),
                    script_text=st.session_state["scripts"][idx],
                    output_path=srt_out,
                )
                st.session_state["subtitle_paths"][idx] = str(srt_out)
                st.session_state["video_paths"].pop(idx, None)
                st.rerun()
            except Exception as e:
                st.error(f"Lỗi gen subtitle: {e}")

    # ── Video section ─────────────────────────────────────────────────
    st.markdown("**🎬 Video**")
    vc1, vc2 = st.columns(2)
    gen_img = vc1.button(
        "🎨 Gen ảnh" if not has_image else "🔁 Gen lại ảnh",
        key=f"genimg_{idx}", use_container_width=True,
    )
    burn_sub = vc2.toggle(
        "Burn sub vào video",
        value=has_sub,
        disabled=not has_sub,
        key=f"burnsub_{idx}",
        help="Bật → sub hard-coded vào video (TikTok/Reels). Tắt → video không sub, dùng SRT riêng.",
    )
    build_vid = st.button(
        "🎬 Tạo video" + (" (có sub)" if burn_sub else ""),
        key=f"buildvid_{idx}",
        disabled=not has_image, use_container_width=True,
        type="primary",
    )

    if gen_img:
        with st.spinner(f"Đang vẽ ảnh Part {idx}..."):
            try:
                client = _get_media_client()  # sinh ảnh giữ trên GEMINI_API_KEY
                img_path = HISTORY_DIR / f"{base_slug}_part{idx}.png"
                before = len(st.session_state.get("usage_log") or [])
                generate_part_image(
                    client,
                    topic=st.session_state["outline"].topic,
                    part_title=part.title,
                    part_summary=part.summary,
                    out_path=img_path,
                    usage_store=st.session_state.get("usage_log"),
                )
                _persist_usage(f"image_part{idx}", st.session_state["outline"].topic, before)
                st.session_state["image_paths"][idx] = str(img_path)
                st.session_state["video_paths"].pop(idx, None)
                st.rerun()
            except Exception as e:
                st.error(f"Lỗi gen ảnh: {e}")

    if has_image:
        st.image(st.session_state["image_paths"][idx], use_container_width=True)

    if build_vid:
        with st.spinner(f"Đang ghép video Part {idx}..."):
            try:
                video_path = HISTORY_DIR / f"{base_slug}_part{idx}.mp4"
                build_part_video(
                    image_path=Path(st.session_state["image_paths"][idx]),
                    audio_path=Path(st.session_state["audio_paths"][idx]),
                    out_path=video_path,
                    subtitle_path=Path(st.session_state["subtitle_paths"][idx])
                    if burn_sub and has_sub else None,
                )
                st.session_state["video_paths"][idx] = str(video_path)
                st.session_state["full_video_path"] = None
                st.rerun()
            except Exception as e:
                st.error(f"Lỗi tạo video: {e}")

    if has_video:
        st.video(st.session_state["video_paths"][idx])
        st.caption(f"🎬 `{st.session_state['video_paths'][idx]}`")


def _render_stats() -> None:
    st.header("📊 Lịch sử & Thống kê")
    st.caption(
        f"Log file: `{log_path()}` — lưu mỗi request gen (text + TTS) + login events."
    )

    events = read_log()
    if not events:
        st.info("Chưa có log nào. Hãy gen 1 cái gì đó rồi quay lại tab này.")
        return

    st.subheader("👥 Tất cả users (lifetime — không bị filter)")
    lifetime_users = aggregate_by_user(events)
    now_utc = datetime.now(timezone.utc)
    today_local = (now_utc + timedelta(hours=7)).date()
    week_start_local = today_local - timedelta(days=today_local.weekday())
    month_start_local = today_local.replace(day=1)

    active_today = set()
    active_week = set()
    active_month = set()
    for e in events:
        try:
            ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
        except Exception:
            continue
        local_date = (ts + timedelta(hours=7)).date()
        u = e.get("user", "") or "anonymous"
        if local_date == today_local:
            active_today.add(u)
        if local_date >= week_start_local:
            active_week.add(u)
        if local_date >= month_start_local:
            active_month.add(u)

    um1, um2, um3, um4 = st.columns(4)
    um1.metric("Tổng users", len(lifetime_users))
    um2.metric("Active hôm nay", len(active_today))
    um3.metric("Active tuần này", len(active_week))
    um4.metric("Active tháng này", len(active_month))

    lifetime_rows = []
    for u, b in sorted(lifetime_users.items(), key=lambda kv: -kv[1]["cost_usd"]):
        lifetime_rows.append({
            "User": u,
            "Calls": b["calls"],
            "Tokens (in/out)": f"{b['prompt']:,} / {b['output']:,}",
            "Cost (USD)": round(b["cost_usd"], 4),
            "Cost (VND)": int(b["cost_usd"] * DEFAULT_USD_TO_VND),
            "First seen": b["first_ts"].strftime("%Y-%m-%d %H:%M") if b["first_ts"] else "—",
            "Last seen": b["last_ts"].strftime("%Y-%m-%d %H:%M") if b["last_ts"] else "—",
        })
    st.dataframe(lifetime_rows, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("🔍 Filter chi tiết theo period / user / date")

    all_users = sorted({e.get("user", "anonymous") for e in events})
    fc1, fc2, fc3 = st.columns([1, 1, 2])
    with fc1:
        period = st.selectbox("Gộp theo", ["day", "week", "month"], index=0,
                              format_func=lambda p: {"day": "Ngày", "week": "Tuần", "month": "Tháng"}[p])
    with fc2:
        user_filter = st.selectbox("User", ["(tất cả)"] + all_users)
    with fc3:
        dc1, dc2 = st.columns(2)
        with dc1:
            from_date = st.date_input("Từ", value=None, key="stat_from")
        with dc2:
            to_date = st.date_input("Đến", value=None, key="stat_to")

    start = None
    end = None
    if from_date:
        start = datetime(from_date.year, from_date.month, from_date.day,
                         tzinfo=timezone.utc) - timedelta(hours=7)
    if to_date:
        end = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59,
                       tzinfo=timezone.utc) - timedelta(hours=7)
    user_arg = "" if user_filter == "(tất cả)" else user_filter

    filtered = filter_by_date(events, start=start, end=end, user=user_arg)
    if not filtered:
        st.warning("Không có log nào khớp bộ lọc.")
        return

    total_cost_usd = sum(e.get("cost_usd", 0.0) for e in filtered)
    total_cost_vnd = int(total_cost_usd * DEFAULT_USD_TO_VND)
    total_prompt = sum(e.get("prompt_tokens", 0) for e in filtered)
    total_output = sum(e.get("output_tokens", 0) for e in filtered)
    unique_users = len({e.get("user", "") for e in filtered if e.get("user")})

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tổng calls", len(filtered))
    m2.metric("Chi phí (USD)", f"${total_cost_usd:.4f}")
    m3.metric("Chi phí (VND)", f"{total_cost_vnd:,}đ")
    m4.metric("Số user", unique_users)

    st.caption(f"Tokens — input: {total_prompt:,} · output: {total_output:,}")

    text_events = [e for e in filtered if e.get("kind") == "text"]
    tts_events = [e for e in filtered if e.get("kind") == "tts"]

    bc1, bc2 = st.columns(2)
    with bc1:
        text_cost = sum(e.get("cost_usd", 0.0) for e in text_events)
        text_prompt = sum(e.get("prompt_tokens", 0) for e in text_events)
        text_output = sum(e.get("output_tokens", 0) for e in text_events)
        pct = (text_cost / total_cost_usd * 100) if total_cost_usd > 0 else 0
        st.markdown(f"### 📝 Script gen (text) — {pct:.1f}% tổng")
        sc1, sc2 = st.columns(2)
        sc1.metric("Calls", len(text_events))
        sc2.metric(
            "Cost",
            f"${text_cost:.4f}",
            f"{int(text_cost * DEFAULT_USD_TO_VND):,}đ",
        )
        st.caption(f"Input: {text_prompt:,} · Output: {text_output:,} tokens")

    with bc2:
        tts_cost = sum(e.get("cost_usd", 0.0) for e in tts_events)
        tts_prompt = sum(e.get("prompt_tokens", 0) for e in tts_events)
        tts_output = sum(e.get("output_tokens", 0) for e in tts_events)
        pct = (tts_cost / total_cost_usd * 100) if total_cost_usd > 0 else 0
        st.markdown(f"### 🔊 Audio gen (TTS) — {pct:.1f}% tổng")
        ac1, ac2 = st.columns(2)
        ac1.metric("Calls", len(tts_events))
        ac2.metric(
            "Cost",
            f"${tts_cost:.4f}",
            f"{int(tts_cost * DEFAULT_USD_TO_VND):,}đ",
        )
        st.caption(f"Input: {tts_prompt:,} · Output (audio): {tts_output:,} tokens")

    st.subheader(f"Theo {('ngày' if period == 'day' else 'tuần' if period == 'week' else 'tháng')}")
    buckets = aggregate_by_period(filtered, period=period)
    if buckets:
        rows = []
        for key in sorted(buckets.keys()):
            b = buckets[key]
            rows.append({
                "Period": key,
                "Calls": b["calls"],
                "Users": len(b["users"]),
                "Input tokens": b["prompt"],
                "Output tokens": b["output"],
                "Cost (USD)": round(b["cost_usd"], 4),
                "Cost (VND)": int(b["cost_usd"] * DEFAULT_USD_TO_VND),
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)
        chart_data = {row["Period"]: row["Cost (USD)"] for row in rows}
        st.bar_chart(chart_data, height=200)

    st.subheader("Theo user")
    user_agg = aggregate_by_user(filtered)
    if user_agg:
        user_rows = []
        for u, b in sorted(user_agg.items(), key=lambda kv: -kv[1]["cost_usd"]):
            user_rows.append({
                "User": u,
                "Calls": b["calls"],
                "Tokens (in/out)": f"{b['prompt']:,} / {b['output']:,}",
                "Cost (USD)": round(b["cost_usd"], 4),
                "Cost (VND)": int(b["cost_usd"] * DEFAULT_USD_TO_VND),
                "Last activity": b["last_ts"].strftime("%Y-%m-%d %H:%M") if b["last_ts"] else "—",
            })
        st.dataframe(user_rows, use_container_width=True, hide_index=True)

    st.subheader("Recent activity (50 dòng cuối)")
    recent = list(reversed(filtered[-50:]))
    recent_rows = []
    for e in recent:
        ts = e.get("ts", "")
        try:
            local = datetime.fromisoformat(ts.replace("Z", "+00:00")) + timedelta(hours=7)
            ts_display = local.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            ts_display = ts
        recent_rows.append({
            "Time": ts_display,
            "User": e.get("user", ""),
            "Action": e.get("action", ""),
            "Kind": e.get("kind", ""),
            "Topic": (e.get("topic", "") or "")[:60],
            "In tokens": e.get("prompt_tokens", 0),
            "Out tokens": e.get("output_tokens", 0),
            "Cost (USD)": round(e.get("cost_usd", 0.0), 5),
        })
    st.dataframe(recent_rows, use_container_width=True, hide_index=True)

    ac1, ac2 = st.columns([1, 1])
    with ac1:
        csv_bytes = events_to_csv(filtered).encode("utf-8")
        st.download_button(
            "⬇️ Download CSV (filtered)",
            data=csv_bytes,
            file_name="usage_log.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with ac2:
        if st.button("🗑️ Xóa toàn bộ log", use_container_width=True, type="secondary"):
            clear_log()
            st.success("Đã xóa log.")
            st.rerun()


def render() -> None:
    _init_state()
    st.title("🎧 ElevenLabs Podcast Builder — Long-form")
    text_engine = "Vertex AI" if _vertex_enabled() else "Gemini"
    st.caption(f"**Text gen** dùng {text_engine} · **Audio TTS** dùng ElevenLabs.")

    # Không chặn cả trang: gen script (text) chỉ cần Vertex/Gemini, chưa cần ElevenLabs.
    # Key ElevenLabs chỉ cần khi bấm "Render audio" — lúc đó _render_part sẽ báo lỗi rõ ràng.
    if not get_elevenlabs_api_key():
        st.warning(
            "⚠️ Chưa có `ELEVENLABS_API_KEY` — vẫn gen được **script/outline**, "
            "nhưng bước **Render audio** sẽ cần key. Thêm key vào `.env` rồi restart app khi cần đọc giọng."
        )

    user_badge = st.session_state.get("username", "")
    if user_badge:
        admin_badge = " · 🛡️ admin" if _is_admin() else ""
        st.caption(f"👤 Logged in as: **{user_badge}**{admin_badge}")
    client = _get_text_client()  # outline/script/topic → Vertex khi bật
    cfg = _sidebar(client)

    if _is_admin():
        tab_gen, tab_stats = st.tabs(["🎙️ Generate", "📊 Stats & Lịch sử"])
        with tab_gen:
            _step_outline(client, cfg)
            st.divider()
            _step_parts(client, cfg)
        with tab_stats:
            _render_stats()
    else:
        _step_outline(client, cfg)
        st.divider()
        _step_parts(client, cfg)


render()

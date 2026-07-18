"""Podcast Studio — ElevenLabs unified (Studio · History · Analytics)."""
from __future__ import annotations

import json
import os
import re
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from google import genai

from paths import HISTORY_DIR
from podcast_studio.auth import is_admin as _is_admin
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

_EL_BASE = "https://api.elevenlabs.io/v1"

# ── Custom CSS ─────────────────────────────────────────────────────────────
_CSS = """<style>
.main .block-container { padding-top: 1.2rem; }

/* Tab bar */
.stTabs [data-baseweb="tab-list"] {
    gap: 2px;
    background: rgba(22,24,35,0.7);
    padding: 4px;
    border-radius: 10px;
    border: 1px solid rgba(255,255,255,0.06);
    margin-bottom: 8px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 7px;
    padding: 7px 20px;
    color: #8892b0;
    font-weight: 500;
    font-size: 0.88rem;
    transition: all .15s;
}
.stTabs [aria-selected="true"] {
    background: rgba(108,92,231,0.22) !important;
    color: #ccd6f6 !important;
}

/* Metric boxes */
div[data-testid="metric-container"] {
    background: rgba(22,24,35,0.8);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 8px;
    padding: 10px 14px;
}

/* Primary button */
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg,#6c5ce7,#a29bfe);
    border: none;
    border-radius: 7px;
    font-weight: 600;
    letter-spacing: .02em;
}

/* Expander headers */
details > summary { font-weight: 600; }

/* Part status pills (rendered via st.markdown unsafe_allow_html) */
.ps-row { display:flex; gap:6px; flex-wrap:wrap; margin:8px 0 14px; }
.ps-pill {
    display:inline-flex; align-items:center; gap:5px;
    padding:3px 11px; border-radius:20px; font-size:.78rem; font-weight:500;
    border:1px solid rgba(255,255,255,.09); background:rgba(22,24,35,.7);
    color:#8892b0; white-space:nowrap;
}
.ps-pill.audio  { border-color:#00b894; color:#00b894; background:rgba(0,184,148,.1); }
.ps-pill.script { border-color:#636e72; color:#b2bec3; background:rgba(99,110,114,.12); }

/* Quota card */
.quota-card {
    background:rgba(22,24,35,.8);
    border:1px solid rgba(255,255,255,.07);
    border-radius:10px;
    padding:14px 18px;
    margin-bottom:1rem;
}

/* History item */
.hist-item {
    background:rgba(22,24,35,.6);
    border:1px solid rgba(255,255,255,.06);
    border-radius:8px;
    padding:10px 14px;
    margin-bottom:8px;
}
</style>"""

# ── ElevenLabs voice picker helpers ────────────────────────────────────────
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


@st.cache_data(ttl=300, show_spinner="Đang tải voice list…")
def _el_fetch_voices_cached() -> list[dict]:
    return _el_list_voices()


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_subscription() -> dict:
    key = get_elevenlabs_api_key()
    resp = requests.get(f"{_EL_BASE}/user/subscription", headers={"xi-api-key": key}, timeout=10)
    return resp.json() if resp.status_code == 200 else {}


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_history(page_size: int = 100, voice_id: str = "") -> list[dict]:
    key = get_elevenlabs_api_key()
    params: dict = {"page_size": page_size, "sort_direction": "desc"}
    if voice_id:
        params["voice_id"] = voice_id
    resp = requests.get(f"{_EL_BASE}/history", headers={"xi-api-key": key}, params=params, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs history lỗi {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("history", [])


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


# ── Gemini client ───────────────────────────────────────────────────────────
def _get_client() -> genai.Client:
    key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not key:
        st.error("Chưa có `GEMINI_API_KEY` trong `.env`. Thêm key rồi restart app.")
        st.stop()
    try:
        return genai.Client(api_key=key, vertexai=False)
    except Exception as e:
        st.error(f"Khởi tạo Gemini client thất bại: {e}")
        st.stop()


# ── Usage logging ───────────────────────────────────────────────────────────
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


# ── Session state ───────────────────────────────────────────────────────────
def _init_state() -> None:
    defaults = {
        "outline": None,
        "outline_dict": None,
        "scripts": {},
        "audio_paths": {},
        "subtitle_paths": {},
        "words_paths": {},
        "base_slug": None,
        "cancel": False,
        "usage_log": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ── Outline serialization ───────────────────────────────────────────────────
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
    prev_text = st.session_state["scripts"].get(part_index - 1)
    if not prev_text:
        return ()
    return extract_tail_lines(prev_text, n=n)


def _suggest_num_parts(total_minutes: int) -> int:
    return max(1, round(total_minutes / 2))


# ── Script generation ────────────────────────────────────────────────────────
def _gen_part(client: genai.Client, outline: Outline, part: PartBrief, cfg: dict) -> str:
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


# ── Audio render ─────────────────────────────────────────────────────────────
def _render_audio(
    outline: Outline,
    part_index: int,
    style: str,
    base_slug: str,
    voices: list[str],
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

    cleaned = [v for v in voices if v]
    if not cleaned:
        raise ValueError("Chưa chọn voice — kiểm tra Voice Settings.")
    if len(cleaned) == 1:
        _el_render_single(script, wav_path, cleaned[0], el_cfg)
    else:
        _el_render_multi(script, wav_path, cleaned, el_cfg, progress_callback=progress_callback)
    return str(wav_path)


# ── Slug helper ──────────────────────────────────────────────────────────────
def _slug(text: str, max_len: int = 40) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


def _whisper_lang(lang_code: str | None) -> str | None:
    if not lang_code:
        return None
    return {"zh_tw": "zh"}.get(lang_code, lang_code)


# ── Config panel (inline — replaces sidebar) ─────────────────────────────────
def _config_panel(client: genai.Client) -> dict:
    """Render config panels inline above the workflow steps. Returns cfg dict."""

    # ── Show & Chủ đề ────────────────────────────────────────────────────────
    with st.expander("📺 Show & Chủ đề", expanded=True):
        language_keys = list(LANGUAGES.keys())
        c1, c2, c3 = st.columns([2, 2, 2])
        with c1:
            language = st.selectbox(
                "🌐 Ngôn ngữ",
                language_keys,
                index=language_keys.index(DEFAULT_LANGUAGE),
                format_func=lambda k: f"{LANGUAGES[k]['label']} ({LANGUAGES[k]['native']})",
            )
            st.session_state["_language_for_suggest"] = language
        with c2:
            channel_name = st.text_input("Tên kênh", value=DEFAULT_CHANNEL_NAME)
        with c3:
            show_name = st.text_input("Tên show", value=DEFAULT_SHOW_NAME)

        if "topic_text" not in st.session_state:
            st.session_state["topic_text"] = "How to communicate effectively in English"
        topic = st.text_area("Chủ đề tập này", height=70, key="topic_text")

        sc1, sc2, sc3 = st.columns([1, 1, 2])
        suggest_count = sc3.slider("Số gợi ý", 1, 5, 3)
        suggest_clicked = sc1.button("💡 Gợi ý chủ đề", use_container_width=True)
        if sc2.button("🔁 Gen lại", use_container_width=True,
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
            picked = st.selectbox("📋 Gợi ý (chọn 1)", ["— chọn —"] + suggestions, key="topic_suggest_pick")
            if picked != "— chọn —":
                def _apply():
                    p = st.session_state.get("topic_suggest_pick")
                    if p and p != "— chọn —":
                        st.session_state["topic_text"] = p
                        st.session_state["topic_suggest_pick"] = "— chọn —"
                st.button("✅ Dùng chủ đề này", on_click=_apply, use_container_width=False)

    # ── Thời lượng & Nội dung ────────────────────────────────────────────────
    with st.expander("⏱️ Thời lượng & Nội dung", expanded=False):
        r1c1, r1c2, r1c3, r1c4 = st.columns(4)
        with r1c1:
            preset_opts = [str(m) for m in DURATION_PRESETS] + ["Custom"]
            default_idx = DURATION_PRESETS.index(DEFAULT_TOTAL_MINUTES) if DEFAULT_TOTAL_MINUTES in DURATION_PRESETS else 0
            chosen = st.selectbox("Tổng (phút)", preset_opts, index=default_idx)
            total_minutes = int(st.number_input("Custom phút", 1, 180, 20)) if chosen == "Custom" else int(chosen)
        with r1c2:
            num_parts = int(st.number_input(
                "Số part",
                min_value=1, max_value=min(20, total_minutes),
                value=_suggest_num_parts(total_minutes),
            ))
        with r1c3:
            style_keys = list(STYLES.keys())
            default_style = style_keys.index("english_learning") if "english_learning" in style_keys else 0
            style = st.selectbox("Style", style_keys, index=default_style)
        with r1c4:
            audience_keys = list(AUDIENCE_LEVELS.keys())
            audience_level = st.selectbox("Trình độ", audience_keys, index=audience_keys.index(DEFAULT_AUDIENCE))
            st.session_state["_audience_for_suggest"] = audience_level

        r2c1, r2c2, r2c3 = st.columns(3)
        with r2c1:
            tone_keys = list(TONES.keys())
            tone = st.selectbox("Tone", tone_keys, index=tone_keys.index(DEFAULT_TONE))
            st.session_state["_tone_for_suggest"] = TONES.get(tone, "")
        with r2c2:
            pace_keys = list(SPEECH_PACES.keys())
            pace = st.selectbox("Tốc độ", pace_keys, index=pace_keys.index(DEFAULT_PACE))
        with r2c3:
            continuous = st.toggle("🔗 Hội thoại liên tục", value=True,
                                   help="BẬT: toàn series 1 hội thoại. TẮT: mỗi part độc lập.")

        minutes_per_part = max(1, round(total_minutes / num_parts))
        hint = " ✅ ổn định" if minutes_per_part <= 2 else (" ⚠️ dễ lỗi TTS" if minutes_per_part > 4 else "")
        st.caption(f"→ **{num_parts} file × ~{minutes_per_part} phút** (tổng ~{num_parts * minutes_per_part} phút){hint}")

    # ── Voice picker (ElevenLabs) ────────────────────────────────────────────
    with st.expander("🎙️ Voices & Model", expanded=False):
        try:
            all_voices = _el_fetch_voices_cached()
        except Exception as _e:
            st.error(f"Không load được voice list: {_e}")
            st.stop()

        _el_defaults = _el_load_settings().get("elevenlabs", {})
        vc1, vc2, vc3, vc4 = st.columns(4)
        with vc1:
            el_model = st.selectbox(
                "Model ElevenLabs",
                ELEVEN_MODELS,
                index=ELEVEN_MODELS.index(_el_defaults.get("model_id", "eleven_flash_v2_5"))
                if _el_defaults.get("model_id") in ELEVEN_MODELS else 0,
                key="_el_model",
            )
        with vc2:
            num_speakers = st.selectbox(
                "Số người dẫn",
                list(range(1, MAX_NUM_SPEAKERS + 1)),
                index=DEFAULT_NUM_SPEAKERS - 1,
                format_func=lambda n: f"{n} người" + (" (mono)" if n == 1 else ""),
                key="_num_speakers",
            )
        with vc3:
            gender_filter = st.radio(
                "Giới tính", ["all", "female", "male"],
                format_func=lambda g: {"all": "Tất cả", "female": "👩 Nữ", "male": "👨 Nam"}[g],
                horizontal=True, key="_el_gender_filter",
            )
        with vc4:
            tier_filter = st.radio(
                "Tier", ["listening", "podcast", "all"],
                format_func=lambda t: {"listening": "⭐⭐⭐", "podcast": "⭐⭐+", "all": "Tất cả"}[t],
                horizontal=True, key="_el_tier_filter",
            )

        compat_count = sum(1 for v in all_voices if _el_voice_supports_model(v, el_model))
        compat_unknown = compat_count == 0
        if compat_unknown:
            st.info(f"ℹ️ Model **{el_model}** mới — hiện tất cả voice, một số có thể fail.")

        filtered = [
            v for v in all_voices
            if _el_passes(v, gender_filter, tier_filter)
            and (compat_unknown or _el_voice_supports_model(v, el_model))
        ]
        if not filtered:
            st.warning(f"Không có voice nào khớp filter + model **{el_model}**.")
            st.stop()

        filtered_ids = [v["voice_id"] for v in filtered]
        label_map = {v["voice_id"]: _el_fmt_voice(v) for v in filtered}
        preview_map = {v["voice_id"]: v.get("preview_url", "") for v in all_voices}
        st.caption(f"📊 **{len(filtered_ids)}** voice phù hợp")

        host_names: list[str] = []
        host_voices: list[str] = []
        for i in range(int(num_speakers)):
            sp1, sp2 = st.columns(2)
            with sp1:
                name = st.text_input(
                    f"Tên nhân vật {i + 1}",
                    value=DEFAULT_HOST_NAMES[i] if i < len(DEFAULT_HOST_NAMES) else f"Host{i + 1}",
                    key=f"host_name_{i}",
                )
                host_names.append(name)
            with sp2:
                voice = st.selectbox(
                    f"Voice {i + 1}",
                    filtered_ids,
                    format_func=lambda vid: label_map.get(vid, vid),
                    key=f"host_voice_{i}",
                    on_change=_el_mark_voice_changed,
                    args=(i,),
                )
                host_voices.append(voice)
            if preview_map.get(voice):
                changed = st.session_state.pop(f"_el_voice_changed_{i}", False)
                components.html(
                    f"""<audio id="aud_{i}" controls {"autoplay" if changed else ""} style="width:100%;margin:0">
                        <source src="{preview_map[voice]}" type="audio/mpeg">
                    </audio>""",
                    height=55,
                )

    # ── Voice tuning ─────────────────────────────────────────────────────────
    with st.expander("🎚️ Voice Tuning", expanded=False):
        _d = _el_load_settings().get("elevenlabs", {})
        tc1, tc2 = st.columns(2)
        with tc1:
            el_stability = st.slider("Stability", 0.0, 1.0, float(_d.get("stability", 0.5)), 0.01,
                                     key="_el_stab",
                                     help="Thấp=biểu cảm hơn, Cao=ổn định hơn. Podcast: 0.5.")
            el_similarity = st.slider("Similarity", 0.0, 1.0, float(_d.get("similarity_boost", 0.75)), 0.01,
                                      key="_el_sim",
                                      help="Độ giống voice gốc. Thư viện EL: 0.75–0.85 an toàn.")
        with tc2:
            el_style = st.slider("Style", 0.0, 1.0, float(_d.get("style", 0.0)), 0.01,
                                 key="_el_style",
                                 help="Phóng đại style voice. 0.0=trung tính, khuyên dùng cho podcast.")
            el_speed = st.slider("Speed", 0.7, 1.2, float(_d.get("speed", 1.0)), 0.05,
                                 key="_el_speed",
                                 help="Tốc độ đọc. 1.0=tự nhiên. Chỉ Flash/Turbo v2.5 hỗ trợ.")
        el_boost = st.toggle("Speaker boost", value=bool(_d.get("use_speaker_boost", True)),
                             key="_el_boost",
                             help="Tăng độ giống voice gốc. Hữu ích với voice clone tự upload.")

        st.session_state["_el_render_config"] = {
            "model_id": el_model,
            "stability": el_stability,
            "similarity_boost": el_similarity,
            "style": el_style,
            "speed": el_speed,
            "use_speaker_boost": el_boost,
            "output_format": "pcm_24000",
        }

    # ── Text model + Cost ─────────────────────────────────────────────────────
    with st.expander("🤖 Text Model & Chi phí session", expanded=False):
        mc1, mc2 = st.columns([2, 3])
        with mc1:
            text_model = st.selectbox("Text model (Gemini)", TEXT_MODEL_OPTIONS, index=0, key="_text_model")
            st.session_state["_model_for_suggest"] = text_model
        with mc2:
            summary = summarize_usage(st.session_state.get("usage_log") or [])
            if summary["calls"] == 0:
                st.caption("Chưa có gen nào trong session này.")
            else:
                st.metric("Session cost", f"${summary['total_cost_usd']:.4f}",
                          f"{summary['total_cost_vnd']:,}đ")
                st.caption(f"{summary['calls']} calls · {summary['total_prompt']:,} in / {summary['total_output']:,} out tokens")
            if st.button("🗑️ Reset usage", use_container_width=True):
                st.session_state["usage_log"] = []
                st.rerun()

    # Reset session
    if st.button("🔄 Reset toàn bộ session", use_container_width=False, type="secondary"):
        for k in ("outline", "outline_dict", "base_slug"):
            st.session_state[k] = None
        st.session_state.update({"scripts": {}, "audio_paths": {}, "subtitle_paths": {}, "words_paths": {}, "cancel": False, "usage_log": []})
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
        "el_model": el_model,
    }


# ── Step 1: Outline ──────────────────────────────────────────────────────────
def _step_outline(client: genai.Client, cfg: dict) -> None:
    st.markdown("### Step 1 — Outline")
    if st.button("📝 Generate Outline", type="primary", disabled=not cfg["topic"].strip()):
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
                st.session_state.update({"scripts": {}, "audio_paths": {}, "subtitle_paths": {}, "words_paths": {}})
                for k in list(st.session_state.keys()):
                    if k.startswith("script_text_"):
                        del st.session_state[k]
                st.success(f"✓ Outline {len(outline.parts)} parts đã sinh.")
            except Exception as e:
                st.error(f"Lỗi: {e}")

    if st.session_state["outline_dict"]:
        outline_text = st.text_area(
            "Outline JSON (sửa tay rồi Apply)",
            value=json.dumps(st.session_state["outline_dict"], indent=2, ensure_ascii=False),
            height=260,
            key="outline_text_area",
        )
        if st.button("💾 Apply outline đã sửa"):
            try:
                d = json.loads(outline_text)
                st.session_state["outline"] = _outline_from_dict(d, cfg["topic"], cfg["num_parts"] * cfg["minutes_per_part"])
                st.session_state["outline_dict"] = d
                st.success("✓ Đã cập nhật outline.")
                st.rerun()
            except Exception as e:
                st.error(f"JSON lỗi: {e}")


# ── Step 2: Scripts & Audio ──────────────────────────────────────────────────
def _step_parts(client: genai.Client, cfg: dict) -> None:
    outline: Outline = st.session_state["outline"]
    if outline is None:
        st.info("👆 Sinh outline ở Step 1 để bắt đầu.")
        return

    st.markdown("### Step 2 — Scripts & Audio")
    base_slug = st.session_state["base_slug"]
    st.session_state["_podcast_language"] = cfg.get("language", DEFAULT_LANGUAGE)

    total = len(outline.parts)
    n_scripts = len(st.session_state["scripts"])
    n_audios = len(st.session_state["audio_paths"])
    missing_audio = sum(
        1 for p in outline.parts
        if p.index in st.session_state["scripts"] and p.index not in st.session_state["audio_paths"]
    )

    # Status pills
    pills_html = '<div class="ps-row">'
    for p in outline.parts:
        has_a = p.index in st.session_state["audio_paths"]
        has_s = p.index in st.session_state["scripts"]
        css = "audio" if has_a else ("script" if has_s else "")
        icon = "🎵" if has_a else ("📝" if has_s else "⬜")
        pills_html += f'<span class="ps-pill {css}">{icon} Part {p.index}</span>'
    pills_html += "</div>"
    st.markdown(pills_html, unsafe_allow_html=True)
    st.caption(f"**{n_scripts}/{total}** scripts · **{n_audios}/{total}** audio")

    rc1, rc2, rc3 = st.columns([1.4, 1.4, 1])
    run_all = rc1.button("▶ Run All Remaining", type="primary")
    render_missing = rc2.button("🔊 Render audio thiếu", disabled=missing_audio == 0)
    if rc3.button("■ Cancel"):
        st.session_state["cancel"] = True

    if run_all or render_missing:
        st.session_state["cancel"] = False
        progress = st.progress(0.0, text="Bắt đầu...")
        total_steps = total * 2
        done = 0
        ok_count = 0
        for part in outline.parts:
            if st.session_state["cancel"]:
                st.warning("Đã hủy.")
                break
            if run_all and part.index not in st.session_state["scripts"]:
                progress.progress(done / total_steps, text=f"Part {part.index}: gen script...")
                try:
                    st.session_state["scripts"][part.index] = _gen_part(client, outline, part, cfg)
                except Exception as e:
                    st.error(f"Part {part.index} script lỗi: {e}")
                    break
            done += 1
            if st.session_state["cancel"]:
                break
            need_audio = (
                part.index in st.session_state["scripts"]
                and part.index not in st.session_state["audio_paths"]
            )
            if need_audio:
                progress.progress(done / total_steps, text=f"Part {part.index}: render audio...")
                try:
                    st.session_state["audio_paths"][part.index] = _render_audio(
                        outline, part.index, cfg["style"], base_slug, cfg["host_voices"],
                    )
                    ok_count += 1
                except Exception as e:
                    st.error(f"Part {part.index} render lỗi: {e}")
                    break
            done += 1
        progress.progress(1.0, text="Hoàn tất.")
        st.success(f"✓ Đã render thêm {ok_count} audio.")

    for part in outline.parts:
        has_script = part.index in st.session_state["scripts"]
        has_audio = part.index in st.session_state["audio_paths"]
        has_sub = part.index in st.session_state["subtitle_paths"]
        icon = "🎵" if has_audio else ("📝" if has_script else "⬜")
        with st.expander(f"{icon} Part {part.index}: {part.title}", expanded=not has_audio):
            st.caption(part.summary)
            if part.key_points:
                st.markdown("\n".join(f"- {kp}" for kp in part.key_points))

            pc1, pc2, pc3 = st.columns([1, 1, 1])
            gen_clicked = pc1.button("Gen script", key=f"gen_{part.index}")
            regen_clicked = pc2.button("Regen", key=f"regen_{part.index}", disabled=not has_script)
            render_clicked = pc3.button("Render audio", key=f"render_{part.index}", disabled=not has_script)

            if gen_clicked or regen_clicked:
                with st.spinner(f"Gen script Part {part.index}..."):
                    try:
                        st.session_state["scripts"][part.index] = _gen_part(client, outline, part, cfg)
                        st.session_state["audio_paths"].pop(part.index, None)
                        st.session_state.pop(f"script_text_{part.index}", None)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Lỗi: {e}")

            if has_script:
                wk = f"script_text_{part.index}"
                if wk not in st.session_state:
                    st.session_state[wk] = st.session_state["scripts"][part.index]
                edited = st.text_area("Script (sửa tay được)", height=360, key=wk)
                st.session_state["scripts"][part.index] = edited
                wc = len(edited.split())
                em = wc / 175
                target = cfg["minutes_per_part"] * 180
                clr = "🟢" if wc >= cfg["minutes_per_part"] * 160 else "🔴"
                st.caption(f"{clr} **{wc} từ** ≈ ~{em:.1f} phút (target ~{target} từ)")

            if render_clicked:
                with st.spinner(f"Render audio Part {part.index}..."):
                    try:
                        st.session_state["audio_paths"][part.index] = _render_audio(
                            outline, part.index, cfg["style"], base_slug, cfg["host_voices"],
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Lỗi render: {e}")

            if has_audio:
                st.audio(st.session_state["audio_paths"][part.index])
                st.caption(f"📁 `{st.session_state['audio_paths'][part.index]}`")

                # ── Subtitle (optional, no video) ────────────────────────────
                st.markdown("**📝 Subtitle (.srt)**")
                sub_method = st.radio(
                    "Cách gen sub",
                    ["gemini", "whisper"],
                    format_func=lambda m: "Gemini (align script)" if m == "gemini" else "Whisper (local free)",
                    key=f"submethod_{part.index}",
                    horizontal=True,
                    label_visibility="collapsed",
                )
                sb1, sb2 = st.columns(2)
                gen_sub = sb1.button(
                    "✨ Gen subtitle" if not has_sub else "🔁 Gen lại sub",
                    key=f"gensub_{part.index}", use_container_width=True,
                )
                if has_sub:
                    srt_path = Path(st.session_state["subtitle_paths"][part.index])
                    if srt_path.exists():
                        sb2.download_button(
                            "⬇️ Tải SRT", data=srt_path.read_bytes(),
                            file_name=srt_path.name, mime="text/plain",
                            key=f"dlsub_{part.index}", use_container_width=True,
                        )
                wp = st.session_state["words_paths"].get(part.index)
                if wp and Path(wp).exists():
                    st.download_button(
                        "⬇️ Tải word-level (.words.json)", data=Path(wp).read_bytes(),
                        file_name=Path(wp).name, mime="application/json",
                        key=f"dlwords_{part.index}",
                    )

                if gen_sub:
                    srt_out = HISTORY_DIR / f"{base_slug}_part{part.index}.srt"
                    if sub_method == "whisper":
                        with st.spinner(f"Whisper Part {part.index}…"):
                            try:
                                from podcast_studio.whisper_transcribe import (
                                    transcribe, transcript_to_srt, write_json_outputs,
                                )
                                lang = _whisper_lang(st.session_state.get("_podcast_language"))
                                t = transcribe(Path(st.session_state["audio_paths"][part.index]), language=lang)
                                srt_out.write_text(transcript_to_srt(t), encoding="utf-8")
                                outs = write_json_outputs(t, srt_out.with_suffix(""))
                                st.session_state["subtitle_paths"][part.index] = str(srt_out)
                                st.session_state["words_paths"][part.index] = str(outs["words"])
                                st.rerun()
                            except Exception as e:
                                st.error(f"Lỗi Whisper: {e}")
                    else:
                        with st.spinner(f"Gemini subtitle Part {part.index}…"):
                            try:
                                from podcast_studio.subtitle_gen import generate_srt
                                generate_srt(
                                    audio_path=Path(st.session_state["audio_paths"][part.index]),
                                    script_text=st.session_state["scripts"][part.index],
                                    output_path=srt_out,
                                )
                                st.session_state["subtitle_paths"][part.index] = str(srt_out)
                                st.session_state["words_paths"].pop(part.index, None)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Lỗi gen subtitle: {e}")


# ── History tab ──────────────────────────────────────────────────────────────
def _fmt_date(unix_ts: int) -> str:
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%d/%m/%Y %H:%M")


def _chars_used(item: dict) -> int:
    return (item.get("character_count_change_to") or 0) - (item.get("character_count_change_from") or 0)


def _render_history() -> None:
    try:
        get_elevenlabs_api_key()
    except Exception as e:
        st.error(str(e))
        return

    with st.spinner("Đang tải..."):
        try:
            sub = _fetch_subscription()
            voices_raw = _el_fetch_voices_cached()
        except Exception as e:
            st.error(f"Lỗi kết nối ElevenLabs: {e}")
            return

    # Quota card
    if sub:
        used = sub.get("character_count", 0)
        limit = sub.get("character_limit", 1)
        tier = sub.get("tier", "—")
        pct = min(used / limit, 1.0) if limit else 0
        q1, q2, q3 = st.columns(3)
        q1.metric("Gói", tier.capitalize())
        q2.metric("Đã dùng", f"{used:,} ký tự")
        q3.metric("Còn lại", f"{max(0, limit - used):,}")
        st.progress(pct, text=f"{pct:.1%} quota đã dùng")
        st.divider()

    # Filters
    f1, f2, f3 = st.columns([3, 1, 1])
    voice_opts = {"": "Tất cả giọng"} | {v["voice_id"]: v["name"] for v in voices_raw}
    selected_voice = f1.selectbox("Lọc theo giọng", list(voice_opts.keys()), format_func=lambda k: voice_opts[k])
    limit_n = f2.selectbox("Số item", [50, 100, 200], index=1)
    if f3.button("🔄 Làm mới"):
        st.cache_data.clear()

    try:
        with st.spinner("Đang tải history..."):
            items = _fetch_history(page_size=limit_n, voice_id=selected_voice)
    except Exception as e:
        st.error(str(e))
        return

    if not items:
        st.info("Chưa có lịch sử generation nào.")
        return

    total_chars = sum(_chars_used(i) for i in items)
    st.caption(f"**{len(items)}** item · Tổng **{total_chars:,}** ký tự")

    for item in items:
        item_id = item.get("history_item_id", "")
        voice = item.get("voice_name") or "—"
        text = (item.get("text") or "").strip()
        chars = _chars_used(item)
        date_str = _fmt_date(item["date_unix"]) if item.get("date_unix") else "—"
        model = (item.get("model_id") or "—").replace("eleven_", "")
        preview = text[:120] + ("…" if len(text) > 120 else "")

        with st.expander(f"🎙️ {voice} · {date_str} · {chars:,} ký tự", expanded=False):
            ia, ib = st.columns([3, 1])
            with ia:
                st.caption(f"**Model:** {model} · **ID:** `{item_id}`")
                if preview:
                    st.markdown(f"> {preview}")
            with ib:
                if st.button("⬇️ Tải audio", key=f"dl_{item_id}"):
                    key = get_elevenlabs_api_key()
                    resp = requests.get(f"{_EL_BASE}/history/{item_id}/audio",
                                        headers={"xi-api-key": key}, timeout=30)
                    if resp.status_code == 200:
                        st.audio(resp.content, format="audio/mpeg")
                        st.download_button(
                            "💾 Lưu MP3", data=resp.content,
                            file_name=f"el_{item_id[:8]}.mp3", mime="audio/mpeg",
                            key=f"save_{item_id}",
                        )
                    else:
                        st.error("Không tải được audio.")


# ── Analytics tab (admin) ─────────────────────────────────────────────────────
def _render_stats() -> None:
    st.caption(f"Log: `{log_path()}`")
    events = read_log()
    if not events:
        st.info("Chưa có log nào.")
        return

    st.subheader("👥 Tất cả users (lifetime)")
    lifetime_users = aggregate_by_user(events)
    now_utc = datetime.now(timezone.utc)
    today_local = (now_utc + timedelta(hours=7)).date()
    week_start = today_local - timedelta(days=today_local.weekday())
    month_start = today_local.replace(day=1)
    active_today, active_week, active_month = set(), set(), set()
    for e in events:
        try:
            ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
        except Exception:
            continue
        local_date = (ts + timedelta(hours=7)).date()
        u = e.get("user", "") or "anonymous"
        if local_date == today_local:
            active_today.add(u)
        if local_date >= week_start:
            active_week.add(u)
        if local_date >= month_start:
            active_month.add(u)

    um1, um2, um3, um4 = st.columns(4)
    um1.metric("Tổng users", len(lifetime_users))
    um2.metric("Hôm nay", len(active_today))
    um3.metric("Tuần này", len(active_week))
    um4.metric("Tháng này", len(active_month))

    rows = []
    for u, b in sorted(lifetime_users.items(), key=lambda kv: -kv[1]["cost_usd"]):
        rows.append({
            "User": u,
            "Calls": b["calls"],
            "Tokens (in/out)": f"{b['prompt']:,} / {b['output']:,}",
            "Cost USD": round(b["cost_usd"], 4),
            "Cost VND": int(b["cost_usd"] * DEFAULT_USD_TO_VND),
            "Last seen": b["last_ts"].strftime("%Y-%m-%d %H:%M") if b["last_ts"] else "—",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("🔍 Filter chi tiết")
    all_users = sorted({e.get("user", "anonymous") for e in events})
    fc1, fc2, fc3 = st.columns([1, 1, 2])
    with fc1:
        period = st.selectbox("Gộp theo", ["day", "week", "month"],
                              format_func=lambda p: {"day": "Ngày", "week": "Tuần", "month": "Tháng"}[p])
    with fc2:
        user_filter = st.selectbox("User", ["(tất cả)"] + all_users)
    with fc3:
        dc1, dc2 = st.columns(2)
        from_date = dc1.date_input("Từ", value=None, key="stat_from")
        to_date = dc2.date_input("Đến", value=None, key="stat_to")

    start = datetime(from_date.year, from_date.month, from_date.day, tzinfo=timezone.utc) - timedelta(hours=7) if from_date else None
    end = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59, tzinfo=timezone.utc) - timedelta(hours=7) if to_date else None
    user_arg = "" if user_filter == "(tất cả)" else user_filter
    filtered = filter_by_date(events, start=start, end=end, user=user_arg)

    if not filtered:
        st.warning("Không có log nào khớp bộ lọc.")
        return

    total_cost = sum(e.get("cost_usd", 0.0) for e in filtered)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Calls", len(filtered))
    m2.metric("Cost (USD)", f"${total_cost:.4f}")
    m3.metric("Cost (VND)", f"{int(total_cost * DEFAULT_USD_TO_VND):,}đ")
    m4.metric("Users", len({e.get("user", "") for e in filtered if e.get("user")}))

    text_events = [e for e in filtered if e.get("kind") == "text"]
    tts_events = [e for e in filtered if e.get("kind") == "tts"]
    bc1, bc2 = st.columns(2)
    for col, evts, label in [(bc1, text_events, "📝 Script gen"), (bc2, tts_events, "🔊 TTS")]:
        with col:
            c = sum(e.get("cost_usd", 0.0) for e in evts)
            pct = c / total_cost * 100 if total_cost else 0
            st.markdown(f"**{label}** — {pct:.1f}%")
            st.metric("Calls", len(evts))
            st.metric("Cost", f"${c:.4f}", f"{int(c * DEFAULT_USD_TO_VND):,}đ")

    buckets = aggregate_by_period(filtered, period=period)
    if buckets:
        period_label = {"day": "ngày", "week": "tuần", "month": "tháng"}[period]
        st.subheader(f"Theo {period_label}")
        p_rows = []
        for key in sorted(buckets.keys()):
            b = buckets[key]
            p_rows.append({"Period": key, "Calls": b["calls"], "Users": len(b["users"]),
                           "Cost USD": round(b["cost_usd"], 4), "Cost VND": int(b["cost_usd"] * DEFAULT_USD_TO_VND)})
        st.dataframe(p_rows, use_container_width=True, hide_index=True)
        st.bar_chart({r["Period"]: r["Cost USD"] for r in p_rows}, height=180)

    st.subheader("50 hoạt động gần nhất")
    recent_rows = []
    for e in reversed(filtered[-50:]):
        ts = e.get("ts", "")
        try:
            local = datetime.fromisoformat(ts.replace("Z", "+00:00")) + timedelta(hours=7)
            ts_d = local.strftime("%Y-%m-%d %H:%M")
        except Exception:
            ts_d = ts
        recent_rows.append({
            "Time": ts_d, "User": e.get("user", ""), "Action": e.get("action", ""),
            "Kind": e.get("kind", ""), "Topic": (e.get("topic", "") or "")[:50],
            "Cost USD": round(e.get("cost_usd", 0.0), 5),
        })
    st.dataframe(recent_rows, use_container_width=True, hide_index=True)

    ac1, ac2 = st.columns(2)
    with ac1:
        st.download_button("⬇️ CSV (filtered)", data=events_to_csv(filtered).encode(),
                           file_name="usage_log.csv", mime="text/csv", use_container_width=True)
    with ac2:
        if st.button("🗑️ Xóa toàn bộ log", use_container_width=True, type="secondary"):
            clear_log()
            st.success("Đã xóa log.")
            st.rerun()


# ── Entry point ───────────────────────────────────────────────────────────────
def render() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    _init_state()

    if not get_elevenlabs_api_key():
        st.error("Chưa có `ELEVENLABS_API_KEY` trong `.env`. Thêm key rồi restart app.")
        st.stop()

    user_badge = st.session_state.get("username", "")
    badge_parts = [f"👤 **{user_badge}**"] if user_badge else []
    if _is_admin():
        badge_parts.append("🛡️ admin")
    st.title("🎧 Podcast Studio")
    if badge_parts:
        st.caption(" · ".join(badge_parts))

    tabs = ["🎙️ Studio", "📜 History"]
    if _is_admin():
        tabs.append("📊 Analytics")

    tab_objs = st.tabs(tabs)

    with tab_objs[0]:
        client = _get_client()
        cfg = _config_panel(client)
        st.divider()
        _step_outline(client, cfg)
        st.divider()
        _step_parts(client, cfg)

    with tab_objs[1]:
        _render_history()

    if _is_admin() and len(tab_objs) > 2:
        with tab_objs[2]:
            _render_stats()


render()

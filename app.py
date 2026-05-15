import json
import os
import re
from datetime import datetime, timedelta, timezone
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
    DEFAULT_LANGUAGE,
    DEFAULT_NUM_SPEAKERS,
    DEFAULT_PACE,
    DEFAULT_SHOW_NAME,
    DEFAULT_TONE,
    DEFAULT_TOTAL_MINUTES,
    DEFAULT_VOICES_BY_INDEX,
    DURATION_PRESETS,
    LANGUAGES,
    MAX_NUM_SPEAKERS,
    SPEECH_PACES,
    STYLES,
    TEXT_MODEL_OPTIONS,
    TONES,
)
from api_utils import DEFAULT_USD_TO_VND, summarize_usage
from outline_generator import Outline, PartBrief, generate_outline
from script_generator import extract_tail_lines, generate_part_script, parse_script_text
from topic_suggester import suggest_topics
from tts_renderer import render_script_with_voices
from usage_logger import (
    aggregate_by_period,
    aggregate_by_user,
    clear_log,
    events_to_csv,
    filter_by_date,
    log_event,
    log_path,
    read_log,
)

ROOT = Path(__file__).resolve().parent
HISTORY_DIR = ROOT / "history"
load_dotenv(ROOT / ".env")


def _slug(text: str, max_len: int = 40) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:max_len].strip("-") or "untitled"


def _read_secret(key: str) -> str:
    try:
        value = st.secrets.get(key)
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(key, "")


def _get_client() -> genai.Client:
    api_key = _read_secret("GEMINI_API_KEY")
    if not api_key:
        st.error("Thiếu GEMINI_API_KEY (kiểm tra .env hoặc Streamlit secrets).")
        st.stop()
    return genai.Client(api_key=api_key)


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


def _check_auth() -> bool:
    expected = _read_secret("APP_PASSWORD")
    if not expected:
        if not st.session_state.get("username"):
            st.session_state["username"] = "anonymous"
        return True
    if st.session_state.get("_authed"):
        return True

    st.title("🔐 TTS Script Gen — Audivy")
    st.caption("Nhập tên + password để truy cập.")
    username = st.text_input("Tên (để track usage)", key="_login_user", value="")
    pwd = st.text_input("Password", type="password", key="_login_pwd")
    if st.button("Đăng nhập", type="primary"):
        if pwd == expected:
            clean = (username or "").strip() or "anonymous"
            st.session_state["_authed"] = True
            st.session_state["username"] = clean
            try:
                log_event(
                    kind="auth", action="login",
                    prompt_tokens=0, output_tokens=0, cost_usd=0.0,
                    user=clean, topic="",
                )
            except Exception:
                pass
            st.rerun()
        else:
            st.error("Sai password.")
    return False


def _init_state() -> None:
    defaults = {
        "outline": None,
        "outline_dict": None,
        "scripts": {},
        "audio_paths": {},
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
    before = len(st.session_state.get("usage_log") or [])
    render_script_with_voices(
        client, script, wav_path, voices, pace=pace,
        progress_callback=progress_callback,
        usage_store=st.session_state.get("usage_log"),
    )
    _persist_usage(f"tts_part{part_index}", outline.topic, before)
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

        with st.expander("🎙️ Giọng đọc", expanded=False):
            vc1, vc2 = st.columns(2)
            with vc1:
                num_speakers = st.selectbox(
                    "Số người dẫn",
                    list(range(1, MAX_NUM_SPEAKERS + 1)),
                    index=DEFAULT_NUM_SPEAKERS - 1,
                    format_func=lambda n: f"{n} người" + (" (monologue)" if n == 1 else ""),
                    help="1-2 người: render 1 lần / part. 3+ người: chậm hơn, tốn API hơn.",
                )
            with vc2:
                pace_keys = list(SPEECH_PACES.keys())
                pace = st.selectbox(
                    "Tốc độ đọc",
                    pace_keys,
                    index=pace_keys.index(DEFAULT_PACE),
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
            for k in ("outline", "outline_dict", "base_slug"):
                st.session_state[k] = None
            st.session_state["scripts"] = {}
            st.session_state["audio_paths"] = {}
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


def _is_admin() -> bool:
    admin_secret = _read_secret("ADMIN_USERS")
    admins = {
        u.strip().lower()
        for u in (admin_secret or "admin").split(",")
        if u.strip()
    }
    return (st.session_state.get("username", "") or "").lower() in admins


def main() -> None:
    st.set_page_config(page_title="TTS Script Gen", layout="wide")
    _init_state()
    if not _check_auth():
        return
    st.title("🎙️ TTS Script Gen — Long-form Podcast Builder")
    user_badge = st.session_state.get("username", "")
    if user_badge:
        admin_badge = " · 🛡️ admin" if _is_admin() else ""
        st.caption(f"👤 Logged in as: **{user_badge}**{admin_badge}")
    client = _get_client()
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


if __name__ == "__main__":
    main()

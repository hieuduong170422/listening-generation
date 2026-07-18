"""ElevenLabs History — xem lịch sử gen audio, usage quota, re-download."""
from __future__ import annotations

from datetime import datetime, timezone

import requests
import streamlit as st

from podcast_studio.tts_settings import get_elevenlabs_api_key

_BASE = "https://api.elevenlabs.io/v1"
_PAGE_SIZE = 100


def _headers() -> dict:
    return {"xi-api-key": get_elevenlabs_api_key()}


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_history(page_size: int = _PAGE_SIZE, voice_id: str = "") -> list[dict]:
    params: dict = {"page_size": page_size, "sort_direction": "desc"}
    if voice_id:
        params["voice_id"] = voice_id
    resp = requests.get(f"{_BASE}/history", headers=_headers(), params=params, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"ElevenLabs history API lỗi {resp.status_code}: {resp.text[:200]}")
    return resp.json().get("history", [])


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_voices() -> list[dict]:
    resp = requests.get(f"{_BASE}/voices", headers=_headers(), timeout=10)
    if resp.status_code != 200:
        return []
    return resp.json().get("voices", [])


@st.cache_data(ttl=300, show_spinner=False)
def _fetch_subscription() -> dict:
    resp = requests.get(f"{_BASE}/user/subscription", headers=_headers(), timeout=10)
    if resp.status_code != 200:
        return {}
    return resp.json()


def _download_audio(item_id: str) -> bytes | None:
    resp = requests.get(f"{_BASE}/history/{item_id}/audio", headers=_headers(), timeout=30)
    if resp.status_code == 200:
        return resp.content
    return None


def _fmt_date(unix_ts: int) -> str:
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).strftime("%d/%m/%Y %H:%M")


def _chars_used(item: dict) -> int:
    return (item.get("character_count_change_to") or 0) - (item.get("character_count_change_from") or 0)


# ── Page ──────────────────────────────────────────────────────────────────────

st.title("📜 ElevenLabs History")

try:
    api_key = get_elevenlabs_api_key()
except Exception as e:
    st.error(str(e))
    st.stop()

# ── Subscription stats ────────────────────────────────────────────────────────
with st.spinner("Đang tải..."):
    try:
        sub = _fetch_subscription()
        voices = _fetch_voices()
    except Exception as e:
        st.error(f"Lỗi kết nối ElevenLabs: {e}")
        st.stop()

if sub:
    used = sub.get("character_count", 0)
    limit = sub.get("character_limit", 0)
    tier = sub.get("tier", "—")
    pct = used / limit if limit else 0

    col1, col2, col3 = st.columns(3)
    col1.metric("Gói", tier.capitalize())
    col2.metric("Đã dùng", f"{used:,} ký tự")
    col3.metric("Còn lại", f"{max(0, limit - used):,} / {limit:,}")
    st.progress(min(pct, 1.0), text=f"{pct:.1%} quota đã dùng")

st.divider()

# ── Filters ───────────────────────────────────────────────────────────────────
col_f1, col_f2 = st.columns([3, 1])
with col_f1:
    voice_options = {"": "Tất cả giọng"} | {v["voice_id"]: v["name"] for v in voices}
    selected_voice = st.selectbox(
        "Lọc theo giọng",
        options=list(voice_options.keys()),
        format_func=lambda k: voice_options[k],
    )
with col_f2:
    limit_n = st.selectbox("Số item", [50, 100, 200, 500], index=1)

if st.button("🔄 Làm mới", use_container_width=False):
    st.cache_data.clear()

# ── Fetch & display ───────────────────────────────────────────────────────────
try:
    with st.spinner("Đang tải history..."):
        items = _fetch_history(page_size=limit_n, voice_id=selected_voice)
except Exception as e:
    st.error(str(e))
    st.stop()

if not items:
    st.info("Chưa có lịch sử generation nào.")
    st.stop()

# Aggregate stats
total_chars = sum(_chars_used(i) for i in items)
total_items = len(items)
st.caption(f"Hiển thị **{total_items}** item · Tổng **{total_chars:,}** ký tự trong batch này")

# ── List ──────────────────────────────────────────────────────────────────────
for item in items:
    item_id = item.get("history_item_id", "")
    voice = item.get("voice_name") or "—"
    text = (item.get("text") or "").strip()
    chars = _chars_used(item)
    date_str = _fmt_date(item["date_unix"]) if item.get("date_unix") else "—"
    model = (item.get("model_id") or "—").replace("eleven_", "")
    source = item.get("source") or "TTS"

    preview = text[:120] + ("…" if len(text) > 120 else "")

    with st.expander(f"🎙️ {voice} · {date_str} · {chars:,} ký tự", expanded=False):
        col_a, col_b = st.columns([3, 1])
        with col_a:
            st.caption(f"**Model:** {model} · **Source:** {source} · **ID:** `{item_id}`")
            if preview:
                st.markdown(f"> {preview}")
            else:
                st.caption("_(không có text)_")
        with col_b:
            if st.button("⬇️ Tải audio", key=f"dl_{item_id}"):
                audio_bytes = _download_audio(item_id)
                if audio_bytes:
                    st.audio(audio_bytes, format="audio/mpeg")
                    st.download_button(
                        "💾 Lưu MP3",
                        data=audio_bytes,
                        file_name=f"elevenlabs_{item_id[:8]}.mp3",
                        mime="audio/mpeg",
                        key=f"save_{item_id}",
                    )
                else:
                    st.error("Không tải được audio.")

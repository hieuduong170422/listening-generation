"""Admin Dashboard — tổng hợp toàn bộ hoạt động của tất cả tài khoản."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from podcast_studio.auth import is_admin
from podcast_studio import affiliate_history
from podcast_studio.usage_logger import read_log as read_usage_log

_VND = 25_000

if not is_admin():
    st.error("⛔ Trang này chỉ dành cho admin.")
    st.stop()

st.title("🛡️ Admin Dashboard")
st.caption("Tổng hợp toàn bộ hoạt động của tất cả tài khoản.")


# ── helpers ─────────────────────────────────────────────────────────────────

def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _fmt_ts(ts: str) -> str:
    dt = _parse_ts(ts)
    if not dt:
        return ts
    return (dt + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")


# ── load & normalize logs ────────────────────────────────────────────────────

usage_events = read_usage_log()
affiliate_events = affiliate_history.read_history()

_AFFILIATE_LABEL = {
    "storyboard": "Gen storyboard",
    "video_clip": "Render clip",
    "video_final": "Render video (final)",
}
_KIND_LABEL = {
    "text": "Script gen",
    "tts": "TTS render",
    "auth": "Đăng nhập",
}

unified: list[dict] = []

for e in usage_events:
    kind = e.get("kind", "")
    unified.append({
        "ts": e.get("ts", ""),
        "user": e.get("user", "anonymous") or "anonymous",
        "module": "Podcast",
        "kind": kind,
        "action": _KIND_LABEL.get(kind, kind),
        "detail": (e.get("topic", "") or "")[:80],
        "cost_usd": float(e.get("cost_usd", 0.0)),
        "prompt_tokens": int(e.get("prompt_tokens", 0)),
        "output_tokens": int(e.get("output_tokens", 0)),
    })

for e in affiliate_events:
    evt = e.get("event", "")
    detail = (e.get("product", "") or e.get("idea", "") or "")[:80]
    engine = e.get("engine", "")
    label = _AFFILIATE_LABEL.get(evt, evt)
    if engine:
        label = f"{label} ({engine})"
    unified.append({
        "ts": e.get("ts", ""),
        "user": e.get("user", "anonymous") or "anonymous",
        "module": "Affiliate",
        "kind": evt,
        "action": label,
        "detail": detail,
        "cost_usd": 0.0,
        "prompt_tokens": 0,
        "output_tokens": 0,
    })

unified.sort(key=lambda x: x.get("ts", ""), reverse=True)
all_users = sorted({e["user"] for e in unified if e["user"]})

if not unified:
    st.info("Chưa có hoạt động nào được ghi log. Thử gen 1 podcast hoặc affiliate rồi quay lại.")
    st.stop()

# ── user overview ────────────────────────────────────────────────────────────

st.subheader("👥 Tổng quan users")

now_utc = datetime.now(timezone.utc)
today_local = (now_utc + timedelta(hours=7)).date()
week_start = today_local - timedelta(days=today_local.weekday())
month_start = today_local.replace(day=1)

active_today: set[str] = set()
active_week: set[str] = set()
active_month: set[str] = set()

for e in unified:
    dt = _parse_ts(e["ts"])
    if not dt:
        continue
    ld = (dt + timedelta(hours=7)).date()
    u = e["user"]
    if ld == today_local:
        active_today.add(u)
    if ld >= week_start:
        active_week.add(u)
    if ld >= month_start:
        active_month.add(u)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Tổng users", len(all_users))
c2.metric("Active hôm nay", len(active_today))
c3.metric("Active tuần này", len(active_week))
c4.metric("Active tháng này", len(active_month))

# Per-user summary table
user_stats: dict[str, dict] = {}
for e in unified:
    u = e["user"]
    b = user_stats.setdefault(u, {
        "calls": 0, "cost_usd": 0.0,
        "podcast": 0, "affiliate": 0,
        "first_ts": None, "last_ts": None,
    })
    b["calls"] += 1
    b["cost_usd"] += e["cost_usd"]
    b["podcast"] += 1 if e["module"] == "Podcast" else 0
    b["affiliate"] += 1 if e["module"] == "Affiliate" else 0
    dt = _parse_ts(e["ts"])
    if dt:
        if b["first_ts"] is None or dt < b["first_ts"]:
            b["first_ts"] = dt
        if b["last_ts"] is None or dt > b["last_ts"]:
            b["last_ts"] = dt

user_rows = []
for u, b in sorted(user_stats.items(), key=lambda kv: (kv[1]["last_ts"] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True):
    user_rows.append({
        "User": u,
        "Tổng actions": b["calls"],
        "Podcast": b["podcast"],
        "Affiliate": b["affiliate"],
        "Chi phí (USD)": f"${b['cost_usd']:.4f}",
        "Chi phí (VND)": f"{int(b['cost_usd'] * _VND):,}đ",
        "Lần đầu": b["first_ts"].strftime("%Y-%m-%d %H:%M") if b["first_ts"] else "—",
        "Gần nhất": b["last_ts"].strftime("%Y-%m-%d %H:%M") if b["last_ts"] else "—",
    })

st.dataframe(user_rows, use_container_width=True, hide_index=True)

st.divider()

# ── activity feed ────────────────────────────────────────────────────────────

st.subheader("📋 Activity feed")

fc1, fc2, fc3, fc4 = st.columns([1, 1, 1, 1])
with fc1:
    user_filter = st.selectbox("User", ["(tất cả)"] + all_users, key="adm_user")
with fc2:
    module_filter = st.selectbox("Module", ["(tất cả)", "Podcast", "Affiliate"], key="adm_module")
with fc3:
    from_date = st.date_input("Từ ngày", value=None, key="adm_from")
with fc4:
    to_date = st.date_input("Đến ngày", value=None, key="adm_to")

filtered = unified
if user_filter != "(tất cả)":
    filtered = [e for e in filtered if e["user"] == user_filter]
if module_filter != "(tất cả)":
    filtered = [e for e in filtered if e["module"] == module_filter]
if from_date:
    from_dt = datetime(from_date.year, from_date.month, from_date.day, tzinfo=timezone.utc) - timedelta(hours=7)
    filtered = [e for e in filtered if (_parse_ts(e["ts"]) or datetime.min.replace(tzinfo=timezone.utc)) >= from_dt]
if to_date:
    to_dt = datetime(to_date.year, to_date.month, to_date.day, 23, 59, 59, tzinfo=timezone.utc) - timedelta(hours=7)
    filtered = [e for e in filtered if (_parse_ts(e["ts"]) or datetime.min.replace(tzinfo=timezone.utc)) <= to_dt]

if not filtered:
    st.warning("Không có hoạt động nào khớp bộ lọc.")
else:
    total_cost = sum(e["cost_usd"] for e in filtered)
    sc1, sc2, sc3 = st.columns(3)
    sc1.metric("Số events", len(filtered))
    sc2.metric("Chi phí (USD)", f"${total_cost:.4f}")
    sc3.metric("Chi phí (VND)", f"{int(total_cost * _VND):,}đ")

    rows = []
    for e in filtered[:300]:
        rows.append({
            "Thời gian": _fmt_ts(e["ts"]),
            "User": e["user"],
            "Module": e["module"],
            "Action": e["action"],
            "Chi tiết": e["detail"],
            "Cost (USD)": f"${e['cost_usd']:.5f}" if e["cost_usd"] > 0 else "—",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(f"Hiển thị tối đa 300 events gần nhất. Tổng: {len(filtered)} events.")

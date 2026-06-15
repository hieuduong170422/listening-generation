"""Trang chủ — workspace landing + bảng trending TikTok Shop products."""
from __future__ import annotations

import streamlit as st

from kalodata.store import (
    get_latest_snapshot_id,
    get_snapshot,
    get_snapshot_rows,
    tiktok_url,
)

# ── Custom CSS ─────────────────────────────────────────────────────────────
_CSS = """
<style>
  /* Hero header */
  .hero-title { font-size: 2rem; font-weight: 700; margin: 0 0 .25rem 0; }
  .hero-sub   { color: #888; font-size: .95rem; margin: 0 0 1.5rem 0; }

  /* Tool chips row */
  .tool-row { display: flex; gap: .75rem; flex-wrap: wrap; margin-bottom: 2rem; }
  .tool-chip {
    flex: 1; min-width: 240px;
    background: rgba(255,255,255,.03);
    border: 1px solid rgba(255,255,255,.08);
    border-radius: 10px; padding: 1rem 1.25rem;
    transition: all .15s ease;
  }
  .tool-chip:hover {
    background: rgba(255,255,255,.06);
    border-color: rgba(255,255,255,.15);
    transform: translateY(-1px);
  }
  .tool-chip-title { font-weight: 600; font-size: 1rem; margin: 0 0 .25rem 0; }
  .tool-chip-desc  { color: #999; font-size: .82rem; margin: 0; }

  /* Section header */
  .section-header {
    display: flex; align-items: center; justify-content: space-between;
    margin: 1rem 0 1rem 0;
  }
  .section-title { font-size: 1.4rem; font-weight: 600; margin: 0; }
  .section-meta  { color: #888; font-size: .82rem; }

  /* Product card — fixed total height so 4 cards in a row line up */
  .product-card {
    border: 1px solid rgba(255,255,255,.08);
    border-radius: 12px;
    overflow: hidden;
    background: rgba(255,255,255,.02);
    transition: all .15s ease;
    display: flex; flex-direction: column;
    height: 540px;          /* fixed; tweak if you add more rows */
    margin-bottom: .5rem;
  }
  .product-card:hover {
    border-color: rgba(255,255,255,.18);
    transform: translateY(-2px);
  }

  /* Image area with rank badge */
  .product-img-wrap {
    position: relative;
    aspect-ratio: 1;
    background: #1a1a1a;
    overflow: hidden;
  }
  .product-img-wrap img {
    width: 100%; height: 100%;
    object-fit: cover;
  }
  .rank-badge {
    position: absolute; top: 8px; left: 8px;
    background: rgba(0,0,0,.7);
    color: #fff;
    padding: 3px 9px;
    border-radius: 6px;
    font-size: .8rem;
    font-weight: 600;
    backdrop-filter: blur(8px);
  }
  .img-count-badge {
    position: absolute; bottom: 8px; right: 8px;
    background: rgba(0,0,0,.7);
    color: #fff;
    padding: 3px 8px;
    border-radius: 6px;
    font-size: .72rem;
    backdrop-filter: blur(8px);
  }

  /* Card body */
  .product-body {
    padding: .75rem .85rem;
    display: flex; flex-direction: column;
    gap: .35rem; flex: 1;
  }
  .product-name {
    font-size: .9rem; font-weight: 500; line-height: 1.3;
    color: #eee;
    display: -webkit-box; -webkit-line-clamp: 2;
    -webkit-box-orient: vertical; overflow: hidden;
    height: 2.4em;
  }
  .price-block {
    background: rgba(255,255,255,.04);
    border-radius: 8px;
    padding: .5rem .7rem;
    margin-top: .2rem;
  }
  .price-label {
    font-size: .68rem; color: #999; text-transform: uppercase;
    letter-spacing: .05em; margin-bottom: .15rem;
  }
  .product-price {
    font-size: 1.25rem; font-weight: 700;
    color: #ff4d4f; line-height: 1.1;
  }
  .product-stats {
    display: flex; flex-direction: column;
    gap: .3rem;
    padding-top: .55rem;
    border-top: 1px solid rgba(255,255,255,.06);
    margin-top: auto;     /* push stats to bottom of card body */
  }
  .stat-row {
    display: flex; justify-content: space-between; align-items: center;
    font-size: .78rem;
    height: 1.1rem;       /* fixed row height so all cards align */
  }
  .stat-label { color: #888; }
  .stat-value { color: #ddd; font-weight: 500; }
  .stat-value-muted { color: #555; font-weight: 400; }
</style>
"""

st.markdown(_CSS, unsafe_allow_html=True)


# ── Hero ───────────────────────────────────────────────────────────────────
st.markdown(
    '<div class="hero-title">Audivy Workspace</div>'
    '<p class="hero-sub">Podcast · Prompt Templates · Affiliate · Kalodata Trends</p>',
    unsafe_allow_html=True,
)


# ── Tools row ──────────────────────────────────────────────────────────────
tool_cols = st.columns(3, gap="small")
_TOOLS = [
    ("🎧", "Podcast Studio", "Kịch bản + TTS Gemini/ElevenLabs", "views/podcast/tts_studio.py"),
    ("🧩", "Prompt Templates", "Template biến `{{...}}` + flow", "views/prompt_template/home.py"),
    ("🎬", "Video Affiliate", "Storyboard + prompt VEO/Omni", "views/affiliate/generate.py"),
]
for col, (icon, title, desc, page) in zip(tool_cols, _TOOLS):
    with col:
        st.markdown(
            f'<div class="tool-chip">'
            f'<div class="tool-chip-title">{icon} {title}</div>'
            f'<div class="tool-chip-desc">{desc}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
        if st.button("Mở →", key=f"go_{title}", use_container_width=True):
            st.switch_page(page)


# ── Trending section ───────────────────────────────────────────────────────
st.markdown('<div style="height: .5rem"></div>', unsafe_allow_html=True)

hc1, hc2 = st.columns([3, 1])
with hc1:
    st.markdown(
        '<div class="section-title">🔥 Trending TikTok Shop</div>',
        unsafe_allow_html=True,
    )
with hc2:
    country = st.selectbox(
        "Country",
        options=["VN", "US", "GB", "ID", "TH", "MY", "PH", "SG", "BR"],
        index=0,
        key="home_country",
        label_visibility="collapsed",
    )

snap_id = get_latest_snapshot_id(country=country)
if not snap_id:
    st.info(
        f"Chưa có snapshot cho **{country}**. "
        "Vào tab **📊 Kalodata → Daily Auto-Fetch → ▶️ Run Now**."
    )
    st.stop()

snap = get_snapshot(snap_id)
rows = get_snapshot_rows(snap_id)

st.markdown(
    f'<div class="section-meta">'
    f'Snapshot #{snap_id} · {len(rows)} sản phẩm · '
    f'{snap["start_date"]} → {snap["end_date"]} · '
    f'cập nhật {snap["fetched_at"][:16]}'
    f"</div>",
    unsafe_allow_html=True,
)
st.markdown('<div style="height: 1rem"></div>', unsafe_allow_html=True)


def _fmt_money(v) -> str:
    if v is None or v == 0:
        return "—"
    v = float(v)
    if v >= 1e9:
        return f"₫{v / 1e9:.2f}B"
    if v >= 1e6:
        return f"₫{v / 1e6:.1f}M"
    if v >= 1e3:
        return f"₫{v / 1e3:.0f}K"
    return f"₫{v:.0f}"


def _fmt_count(v) -> str:
    if v is None or v == 0:
        return "0"
    v = float(v)
    if v >= 1e6:
        return f"{v / 1e6:.1f}M"
    if v >= 1e3:
        return f"{v / 1e3:.1f}K"
    return f"{int(v):,}"


def _kalodata_url(pid: str) -> str:
    return (
        f"https://www.kalodata.com/product/detail?id={pid}"
        f"&language=en-US&currency=VND&region={country}"
    )


@st.dialog("Ảnh sản phẩm", width="large")
def _show_images_dialog(name: str, images: list[str], pid: str | None) -> None:
    st.markdown(f"#### {name}")
    if pid:
        st.caption(f"ID: `{pid}`  ·  {len(images)} ảnh")
    st.divider()
    for url in images:
        st.markdown(
            f'<img src="{url}" referrerpolicy="no-referrer" '
            'style="width:100%;border-radius:8px;margin-bottom:12px"/>',
            unsafe_allow_html=True,
        )


PER_ROW = 4
for chunk_start in range(0, len(rows), PER_ROW):
    cols = st.columns(PER_ROW, gap="medium")
    for col, row in zip(cols, rows[chunk_start : chunk_start + PER_ROW]):
        with col:
            images = row.get("image_urls") or []
            name = (row.get("product_name") or "Không tên").strip()
            pid = row.get("product_id")
            rank = row.get("rank", 0)
            revenue = row.get("revenue") or 0
            sales = row.get("sales") or 0
            price = row.get("price") or 0
            rating = row.get("rating")
            creators = row.get("creator_num") or 0
            commission = row.get("commission_pct") or 0

            img_html = (
                f'<img src="{images[0]}" referrerpolicy="no-referrer"/>'
                if images
                else '<div style="display:flex;align-items:center;justify-content:center;'
                     'height:100%;color:#555;font-size:2rem">📦</div>'
            )
            img_count_html = (
                f'<div class="img-count-badge">+{len(images) - 1}</div>'
                if len(images) > 1
                else ""
            )
            def _stat_row(label: str, value: object) -> str:
                cls = "stat-value" if value not in (None, 0, "", "—") else "stat-value-muted"
                v = value if value not in (None, 0, "") else "—"
                return (
                    f'<div class="stat-row">'
                    f'<span class="stat-label">{label}</span>'
                    f'<span class="{cls}">{v}</span>'
                    f"</div>"
                )

            st.markdown(
                f'<div class="product-card">'
                f'  <div class="product-img-wrap">'
                f'    {img_html}'
                f'    <div class="rank-badge">#{rank}</div>'
                f'    {img_count_html}'
                f"  </div>"
                f'  <div class="product-body">'
                f'    <div class="product-name">{name}</div>'
                f'    <div class="price-block">'
                f'      <div class="price-label">Giá bán</div>'
                f'      <div class="product-price">{_fmt_money(price)}</div>'
                f"    </div>"
                f'    <div class="product-stats">'
                f"      {_stat_row('💰 Doanh thu', _fmt_money(revenue))}"
                f"      {_stat_row('📦 Đã bán', _fmt_count(sales))}"
                f"      {_stat_row('🎥 Creators', _fmt_count(creators) if creators else None)}"
                f"      {_stat_row('💸 Hoa hồng', f'{commission:.0f}%' if commission else None)}"
                f"      {_stat_row('⭐ Đánh giá', f'{rating:.1f}' if rating else None)}"
                f"    </div>"
                f"  </div>"
                f"</div>",
                unsafe_allow_html=True,
            )

            # Action buttons (Streamlit-native, dưới card)
            bc1, bc2, bc3 = st.columns(3)
            with bc1:
                if images and st.button(
                    "🔍 Ảnh",
                    key=f"zoom_{snap_id}_{pid or rank}",
                    use_container_width=True,
                ):
                    _show_images_dialog(name, images, pid)
            with bc2:
                if pid:
                    st.link_button(
                        "🎵 TikTok",
                        tiktok_url(pid),
                        use_container_width=True,
                    )
            with bc3:
                if pid:
                    st.link_button(
                        "📊 Kalo",
                        _kalodata_url(pid),
                        use_container_width=True,
                    )
            st.markdown('<div style="height: 1rem"></div>', unsafe_allow_html=True)

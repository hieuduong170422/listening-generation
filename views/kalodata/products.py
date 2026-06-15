"""Kalodata Product Explorer — fetch + persist snapshots + detect trending."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from kalodata.client import (
    KalodataAPIError,
    KalodataAuthError,
    SORT_FIELDS,
    SORT_TYPES,
    fetch_all_products,
)
from kalodata.store import (
    compute_trending,
    delete_snapshot,
    get_snapshot,
    get_snapshot_rows,
    list_snapshots,
    product_url,
    save_snapshot,
)


def _decorate_rows(rows: list[dict], country: str) -> pd.DataFrame:
    """Add product_url column + drop heavy fields; reorder for display.

    Note: kalocdn chặn hotlink theo Referer, st.column_config.ImageColumn
    sẽ load 403 → bỏ cột thumbnail ở DataFrame. Xem ảnh ở trang Home.
    """
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["product_url"] = df["product_id"].apply(
        lambda pid: product_url(str(pid), country) if pid else None
    )
    cols = [
        c for c in (
            "rank", "product_name", "product_url",
            "revenue", "sales", "price", "rating", "category", "product_id",
        ) if c in df.columns
    ]
    return df[cols]


_DF_COLUMN_CONFIG = {
    "product_url": st.column_config.LinkColumn(
        "Link", display_text="🔗 kalodata", width="small",
    ),
    "rank": st.column_config.NumberColumn("#", width="small"),
    "revenue": st.column_config.NumberColumn("Revenue (₫)", format="₫%.0f"),
    "sales": st.column_config.NumberColumn("Sales", format="%.0f"),
    "price": st.column_config.NumberColumn("Giá (₫)", format="₫%.0f"),
    "rating": st.column_config.NumberColumn("⭐", format="%.1f"),
    "product_name": st.column_config.TextColumn("Sản phẩm", width="large"),
}

st.title("📊 Kalodata — TikTok Shop Product Tracker")
st.caption(
    "Fetch product list từ kalodata.com, lưu DB local, "
    "so sánh snapshot để phát hiện trending."
)

with st.expander("🔧 Diagnostic (kiểm tra cookie / kết nối)", expanded=False):
    import os as _os
    cookie = (_os.getenv("KALODATA_COOKIE") or "").strip()
    dc1, dc2, dc3 = st.columns(3)
    dc1.metric("Cookie length", len(cookie))
    dc2.metric("Has cf_clearance", "✓" if "cf_clearance=" in cookie else "✗")
    dc3.metric("Has SESSION", "✓" if "SESSION=" in cookie else "✗")
    if cookie:
        st.caption(f"Đầu: `{cookie[:60]}...`")
        st.caption(f"Cuối: `...{cookie[-60:]}`")
    if st.button("🧪 Test fetch (1 request, không lưu)"):
        with st.spinner("Đang gọi…"):
            try:
                from kalodata.client import query_products
                resp = query_products(
                    start_date="2026-06-08", end_date="2026-06-14",
                    page_no=1, page_size=10,
                )
                from kalodata.client import extract_rows
                rows = extract_rows(resp)
                st.success(f"✅ OK — fetched {len(rows)} rows. Cookie + IP đều OK.")
            except Exception as e:
                err_str = str(e)
                if "403" in err_str or "Just a moment" in err_str or "cf_clearance" in err_str:
                    st.error(
                        "❌ **Cloudflare chặn (403)**\n\n"
                        "Nguyên nhân khả năng cao:\n"
                        "1. **IP mismatch** — `cf_clearance` được Cloudflare cấp gắn với "
                        "IP của browser m. Server Streamlit Cloud có IP khác → Cloudflare "
                        "phát hiện mismatch → reject.\n"
                        "2. Cookie expired (sau 30-60 phút).\n\n"
                        f"Raw: {err_str[:300]}"
                    )
                else:
                    st.error(f"❌ {type(e).__name__}: {err_str[:500]}")
st.warning(
    "⚠️ **Gói kalodata hiện tại của bạn chỉ cho xem 10 rows/query** (pageSize=10, pageNo=1). "
    "Fetch nhiều hơn = server trả 'Upgrade to view more data'. "
    "Mẹo: fetch snapshot nhiều lần với filter khác nhau (sort field / category / date range) "
    "để có data đa dạng hơn. Hoặc upgrade plan."
)

tab_fetch, tab_browse, tab_trend, tab_daily = st.tabs(
    ["🔄 Fetch & Save", "📚 Browse Snapshots", "🔥 Trending", "🕒 Daily Auto-Fetch"]
)


# ── Tab 1: Fetch & Save ─────────────────────────────────────────────────────
with tab_fetch:
    st.subheader("Fetch toàn bộ product list rồi lưu thành snapshot")

    c1, c2 = st.columns(2)
    with c1:
        today = date.today()
        default_end = today - timedelta(days=1)
        default_start = default_end - timedelta(days=29)
        dr = st.date_input(
            "Khoảng thời gian",
            value=(default_start, default_end),
            max_value=today,
            key="fetch_dr",
        )
        if isinstance(dr, tuple) and len(dr) == 2:
            start_d, end_d = dr
        else:
            start_d, end_d = default_start, default_end

        country = st.selectbox(
            "Country",
            options=["VN", "US", "GB", "ID", "TH", "MY", "PH", "SG", "BR"],
            index=0,
            key="fetch_country",
        )
        notes = st.text_input(
            "Notes (optional)",
            placeholder="VD: snapshot tháng 6, beauty category…",
        )
    with c2:
        sort_field = st.selectbox("Sort by", options=SORT_FIELDS, index=0, key="fetch_sort")
        sort_type = st.radio("Order", options=SORT_TYPES, horizontal=True, key="fetch_order")
        page_size = st.selectbox(
            "Page size", options=[10, 20, 50, 100], index=0,
            help="Free plan giới hạn = 10. Lớn hơn sẽ bị 'Upgrade to view more data'.",
        )
        max_pages = st.number_input(
            "Max pages (safety cap)", min_value=1, max_value=500, value=1,
            help="Free plan chỉ truy cập được page 1. Đặt =1 để tránh lỗi.",
        )
        cate_raw = st.text_input(
            "Category IDs (comma, optional)",
            value="",
            help="Để trống = tất cả.",
        )
        try:
            cate_ids = [int(x.strip()) for x in cate_raw.split(",") if x.strip()]
        except ValueError:
            st.error("Category IDs phải là số nguyên cách nhau dấu phẩy.")
            cate_ids = []

    if st.button("🚀 Fetch & Save Snapshot", type="primary", use_container_width=True):
        progress = st.progress(0.0, "Đang fetch trang 1…")

        def _cb(page: int, total_pages: int | None, rows_so_far: int):
            if total_pages:
                progress.progress(
                    min(1.0, page / total_pages),
                    f"Trang {page}/{total_pages} · {rows_so_far} rows",
                )
            else:
                progress.progress(
                    min(0.9, page / max_pages),
                    f"Trang {page} · {rows_so_far} rows (tổng chưa rõ)",
                )

        try:
            rows, total = fetch_all_products(
                start_date=str(start_d),
                end_date=str(end_d),
                sort_field=sort_field,
                sort_type=sort_type,
                category_ids=cate_ids,
                country=country,
                page_size=int(page_size),
                max_pages=int(max_pages),
                progress_callback=_cb,
            )
            progress.progress(1.0, f"Done — {len(rows)} rows")
        except KalodataAuthError as e:
            progress.empty()
            st.error(f"🔒 Auth failed: {e}")
            st.stop()
        except KalodataAPIError as e:
            progress.empty()
            st.error(f"❌ API: {e}")
            st.stop()
        except Exception as e:
            progress.empty()
            st.error(f"❌ {type(e).__name__}: {e}")
            st.stop()

        if not rows:
            st.warning("Fetch xong nhưng không có row nào.")
            st.stop()

        snapshot_id = save_snapshot(
            country=country,
            start_date=str(start_d),
            end_date=str(end_d),
            sort_field=sort_field,
            sort_type=sort_type,
            rows=rows,
            notes=notes,
        )
        progress.empty()
        st.success(
            f"✅ Saved snapshot #{snapshot_id} — {len(rows)} products "
            f"(server total: {total if total is not None else '?'})"
        )
        st.info("Sang tab **Browse Snapshots** để xem chi tiết.")


# ── Tab 2: Browse Snapshots ─────────────────────────────────────────────────
with tab_browse:
    st.subheader("Snapshot đã lưu")
    snap_country = st.selectbox(
        "Filter theo country (optional)",
        options=["(tất cả)", "VN", "US", "GB", "ID", "TH", "MY", "PH", "SG", "BR"],
        key="browse_country",
    )
    snaps = list_snapshots(
        country=None if snap_country == "(tất cả)" else snap_country
    )
    if not snaps:
        st.info("Chưa có snapshot nào. Sang tab Fetch & Save để tạo.")
        st.stop()

    df_snaps = pd.DataFrame(snaps)[
        ["id", "country", "start_date", "end_date", "sort_field", "sort_type",
         "fetched_at", "total_products", "notes"]
    ]
    st.dataframe(df_snaps, use_container_width=True)

    pick = st.selectbox(
        "Xem chi tiết snapshot",
        options=[s["id"] for s in snaps],
        format_func=lambda i: (
            f"#{i} · {next(s for s in snaps if s['id']==i)['country']} · "
            f"{next(s for s in snaps if s['id']==i)['fetched_at'][:16]} · "
            f"{next(s for s in snaps if s['id']==i)['total_products']} rows"
        ),
        key="browse_pick",
    )

    bc1, bc2 = st.columns([3, 1])
    with bc2:
        if st.button("🗑️ Xóa snapshot này", type="secondary"):
            delete_snapshot(pick)
            st.rerun()

    snap_obj = get_snapshot(pick)
    rows = get_snapshot_rows(pick)
    df = _decorate_rows(rows, snap_obj["country"] if snap_obj else "VN")
    st.write(f"**{len(df)} products** trong snapshot #{pick}")
    st.dataframe(
        df, use_container_width=True, height=600,
        column_config=_DF_COLUMN_CONFIG,
        hide_index=True,
    )

    if not df.empty:
        st.download_button(
            "⬇️ Download CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name=f"kalodata_snapshot_{pick}.csv",
            mime="text/csv",
        )


# ── Tab 3: Trending ─────────────────────────────────────────────────────────
with tab_trend:
    st.subheader("So sánh 2 snapshot → tìm sản phẩm trending")
    all_snaps = list_snapshots()
    if len(all_snaps) < 2:
        st.info("Cần ít nhất 2 snapshot để so sánh. Fetch thêm snapshot ở tab Fetch & Save.")
        st.stop()

    snap_opts = {s["id"]: f"#{s['id']} · {s['country']} · {s['fetched_at'][:16]}" for s in all_snaps}
    tc1, tc2 = st.columns(2)
    with tc1:
        new_id = st.selectbox(
            "Snapshot MỚI (so với)",
            options=list(snap_opts.keys()),
            format_func=lambda i: snap_opts[i],
            key="trend_new",
        )
    with tc2:
        old_id = st.selectbox(
            "Snapshot CŨ",
            options=list(snap_opts.keys()),
            format_func=lambda i: snap_opts[i],
            index=1 if len(snap_opts) > 1 else 0,
            key="trend_old",
        )

    if new_id == old_id:
        st.warning("Chọn 2 snapshot khác nhau.")
        st.stop()

    new_snap = get_snapshot(new_id)
    old_snap = get_snapshot(old_id)
    if new_snap["country"] != old_snap["country"]:
        st.warning(
            f"⚠️ 2 snapshot khác country ({new_snap['country']} vs {old_snap['country']}) — "
            "kết quả không có ý nghĩa."
        )

    diff = compute_trending(new_id, old_id)

    top_n = st.slider("Hiện top N", 5, 100, 20)

    _country = new_snap["country"] if new_snap else "VN"
    st.markdown("### 🚀 Climbers (rank tăng mạnh nhất)")
    if diff["climbers"]:
        st.dataframe(
            _decorate_rows(diff["climbers"][:top_n], _country),
            use_container_width=True,
            column_config=_DF_COLUMN_CONFIG, hide_index=True,
        )
    else:
        st.caption("Không có product nào tăng rank.")

    st.markdown("### 📉 Fallers (rank giảm mạnh nhất)")
    if diff["fallers"]:
        st.dataframe(
            _decorate_rows(diff["fallers"][:top_n], _country),
            use_container_width=True,
            column_config=_DF_COLUMN_CONFIG, hide_index=True,
        )
    else:
        st.caption("Không có product nào giảm rank.")

    st.markdown(f"### ✨ New entries — {len(diff['new_entries'])} sản phẩm mới")
    if diff["new_entries"]:
        st.dataframe(
            _decorate_rows(diff["new_entries"][:top_n], _country),
            use_container_width=True,
            column_config=_DF_COLUMN_CONFIG, hide_index=True,
        )

    st.markdown(f"### 👻 Dropped — {len(diff['dropped'])} sản phẩm biến mất")
    if diff["dropped"]:
        st.dataframe(
            _decorate_rows(diff["dropped"][:top_n], _country),
            use_container_width=True,
            column_config=_DF_COLUMN_CONFIG, hide_index=True,
        )


# ── Tab 4: Daily Auto-Fetch ────────────────────────────────────────────────
with tab_daily:
    import subprocess
    from pathlib import Path as _Path

    st.subheader("Snapshot tự động mỗi ngày")
    st.markdown(
        "Script gộp **2 query** (sort `conversionRate` + sort `revenue`) → "
        "dedupe → snapshot ~20 sản phẩm nổi nhất / ngày."
    )

    # Lịch sử các snapshot daily
    daily_snaps = [
        s for s in list_snapshots(limit=30)
        if "daily auto-fetch" in (s.get("notes") or "")
    ]
    if daily_snaps:
        latest = daily_snaps[0]
        m1, m2, m3 = st.columns(3)
        m1.metric("Lần cuối", latest["fetched_at"][:16])
        m2.metric("Sản phẩm", latest["total_products"])
        m3.metric("Tổng snapshot daily", len(daily_snaps))
    else:
        st.info("Chưa có snapshot daily nào. Bấm **Run Now** để chạy lần đầu.")

    rc1, rc2 = st.columns([1, 3])
    with rc1:
        run_now = st.button("▶️ Run Now", type="primary", use_container_width=True)
    with rc2:
        st.caption(
            "Chạy script ngay — log hiện ở dưới. Snapshot vào tab Browse / Trending."
        )

    if run_now:
        script_path = _Path(__file__).resolve().parents[2] / "scripts" / "daily_kalodata_fetch.py"
        python_bin = _Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python"
        if not python_bin.exists():
            python_bin = "python3"
        with st.spinner("Đang chạy script daily fetch…"):
            try:
                result = subprocess.run(
                    [str(python_bin), str(script_path)],
                    cwd=str(script_path.parent.parent),
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                log = (result.stdout or "") + ("\n--- stderr ---\n" + result.stderr if result.stderr else "")
                if result.returncode == 0:
                    st.success("✅ Done. Reload page để xem snapshot mới.")
                else:
                    st.error(f"❌ Script exit code {result.returncode}")
                st.code(log, language="text")
            except subprocess.TimeoutExpired:
                st.error("⏱️ Script chạy quá 120s — có thể cookie hỏng hoặc Cloudflare block.")
            except Exception as e:
                st.error(f"❌ {type(e).__name__}: {e}")

    st.divider()
    st.subheader("📅 Setup cron để tự động chạy mỗi ngày")
    st.markdown(
        "Streamlit không tự chạy background job. Cần OS scheduler bên ngoài."
    )

    with st.expander("🍎 macOS — launchd (khuyên dùng)", expanded=False):
        plist_path = "~/Library/LaunchAgents/com.audivy.kalodata-daily.plist"
        script_abs = str(_Path(__file__).resolve().parents[2] / "scripts" / "daily_kalodata_fetch.py")
        python_abs = str(_Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python")
        st.markdown(
            f"1. Tạo file plist tại `{plist_path}`:\n\n"
            "```xml\n"
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n'
            "<dict>\n"
            "  <key>Label</key>      <string>com.audivy.kalodata-daily</string>\n"
            "  <key>ProgramArguments</key>\n"
            f"  <array><string>{python_abs}</string><string>{script_abs}</string></array>\n"
            "  <key>StartCalendarInterval</key>\n"
            "  <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>0</integer></dict>\n"
            "  <key>StandardOutPath</key> <string>/tmp/kalodata-daily.log</string>\n"
            "  <key>StandardErrorPath</key><string>/tmp/kalodata-daily.err</string>\n"
            "</dict>\n"
            "</plist>\n"
            "```\n\n"
            "2. Load job: `launchctl load ~/Library/LaunchAgents/com.audivy.kalodata-daily.plist`\n\n"
            "3. Test chạy ngay: `launchctl start com.audivy.kalodata-daily`\n\n"
            "4. Kiểm log: `tail -f /tmp/kalodata-daily.log`"
        )

    with st.expander("🐧 Linux / WSL — crontab", expanded=False):
        script_abs = str(_Path(__file__).resolve().parents[2] / "scripts" / "daily_kalodata_fetch.py")
        python_abs = str(_Path(__file__).resolve().parents[2] / ".venv" / "bin" / "python")
        st.code(
            f"# crontab -e\n"
            f"# Chạy mỗi ngày lúc 8 giờ sáng\n"
            f"0 8 * * * {python_abs} {script_abs} >> /tmp/kalodata-daily.log 2>&1\n",
            language="bash",
        )

    with st.expander("☁️ GitHub Actions (chạy trên cloud, không cần máy bật)", expanded=False):
        st.markdown(
            "Tạo `.github/workflows/kalodata-daily.yml`:\n\n"
            "```yaml\n"
            "name: Kalodata Daily Fetch\n"
            "on:\n"
            "  schedule:\n"
            "    - cron: '0 1 * * *'  # 08:00 VN (UTC+7)\n"
            "  workflow_dispatch:\n"
            "jobs:\n"
            "  fetch:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - uses: actions/setup-python@v5\n"
            "        with: { python-version: '3.12' }\n"
            "      - run: pip install -r requirements.txt\n"
            "      - run: python scripts/daily_kalodata_fetch.py\n"
            "        env:\n"
            "          KALODATA_COOKIE: ${{ secrets.KALODATA_COOKIE }}\n"
            "      - uses: stefanzweifel/git-auto-commit-action@v5\n"
            "        with: { commit_message: 'chore: daily kalodata snapshot' }\n"
            "```\n\n"
            "⚠️ Vẫn cần update cookie thủ công vào Secret khi expire."
        )


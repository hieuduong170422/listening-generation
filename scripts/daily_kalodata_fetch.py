#!/usr/bin/env python3
"""Daily kalodata snapshot job.

Fetches top-CVR products and saves a snapshot to the local SQLite DB.
Designed to be triggered by a cron/launchd schedule once per day.

Strategy — finds genuinely hot products for affiliate UGC creators:
    Window = LAST 7 DAYS (hot NOW, not "trending 30 days ago").
    Three queries × 10 rows each, dedupe by product_id → up to ~25 unique
    products that show up on the "hot" side of multiple signals:
      • revenue DESC      — proven demand, real money on table
      • sales DESC        — mass appeal, lots of buyers
      • creatorCnt DESC   — many TikTok creators making videos = HOT
    NOTE: we explicitly avoid ``conversionRate DESC`` — it surfaces tiny
    1-3-sale products that happen to have 100% CVR (noise, not trending).

Env vars (all optional, defaults shown):
    KALODATA_DAILY_COUNTRY   = VN
    KALODATA_DAILY_DAYS_BACK = 30      # date range = today - N days
    KALODATA_COOKIE          = (required)

Exit codes:
    0 = success
    1 = auth/cookie problem (re-paste cookie)
    2 = unexpected error
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

# Allow running standalone: ``python scripts/daily_kalodata_fetch.py``
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from kalodata.client import (
    KalodataAPIError,
    KalodataAuthError,
    fetch_all_products,
)
from kalodata.store import save_snapshot


def _date_range() -> tuple[str, str]:
    days_back = int(os.getenv("KALODATA_DAILY_DAYS_BACK", "7"))
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days_back - 1)
    return str(start), str(end)


def main() -> int:
    country = os.getenv("KALODATA_DAILY_COUNTRY", "VN")
    start_d, end_d = _date_range()
    print(f"[daily-fetch] country={country} range={start_d}..{end_d}", flush=True)

    merged_by_id: dict[str, dict] = {}
    queries = [
        ("revenue", "doanh thu cao nhất (proven demand)"),
        ("sales", "số đơn cao nhất (mass appeal)"),
        ("creatorCnt", "nhiều creator nhất (hot TikTok)"),
    ]

    for sort_field, label in queries:
        print(f"[daily-fetch] fetching sort={sort_field!r} ({label})…", flush=True)
        try:
            rows, _ = fetch_all_products(
                start_date=start_d,
                end_date=end_d,
                sort_field=sort_field,
                sort_type="DESC",
                country=country,
                page_size=10,
                max_pages=1,
            )
        except KalodataAuthError as e:
            print(f"[daily-fetch] AUTH ERROR ({sort_field}): {e}", file=sys.stderr)
            return 1
        except KalodataAPIError as e:
            print(f"[daily-fetch] API ERROR ({sort_field}): {e}", file=sys.stderr)
            return 2

        for row in rows:
            pid = row.get("id") or row.get("productId") or row.get("product_id")
            if pid is None:
                continue
            pid = str(pid)
            if pid not in merged_by_id:
                merged_by_id[pid] = row
        print(
            f"[daily-fetch]   → {len(rows)} rows fetched, "
            f"{len(merged_by_id)} unique so far",
            flush=True,
        )
        time.sleep(1)  # polite gap between queries

    if not merged_by_id:
        print("[daily-fetch] no rows fetched, nothing to save", file=sys.stderr)
        return 2

    merged_rows = list(merged_by_id.values())

    def _media_progress(i: int, total: int, name: str) -> None:
        print(f"[daily-fetch]   media {i}/{total}: {name[:60]}", flush=True)

    snapshot_id = save_snapshot(
        country=country,
        start_date=start_d,
        end_date=end_d,
        sort_field="revenue",
        sort_type="DESC",
        rows=merged_rows,
        notes=(
            "daily auto-fetch: merge revenue+sales+creatorCnt DESC, 7d window, "
            f"{len(merged_rows)} unique products"
        ),
        fetch_media=True,
        progress_callback=_media_progress,
    )
    print(
        f"[daily-fetch] ✅ saved snapshot #{snapshot_id} "
        f"with {len(merged_rows)} unique products (+ ảnh)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"[daily-fetch] UNEXPECTED: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)

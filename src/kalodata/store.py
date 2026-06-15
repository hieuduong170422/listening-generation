"""Persist kalodata snapshots + product rows + compute trending diff."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from kalodata.client import get_product_images
from kalodata.db import get_connection, init_db


KALODATA_PRODUCT_URL = (
    "https://www.kalodata.com/product/detail?id={pid}"
    "&language=en-US&currency=VND&region={country}"
)


def product_url(product_id: str, country: str = "VN") -> str:
    return KALODATA_PRODUCT_URL.format(pid=product_id, country=country)

# Field-name synonyms for the kalodata /product/queryList response. Each
# tuple lists candidate keys in priority order. Numeric fields use the raw
# numeric key first, falling back to the formatted-string key.
_FIELD_SYNONYMS = {
    "product_id":     ("id", "productId", "product_id", "productIdStr"),
    "product_name":   ("product_title", "productName", "name", "title"),
    "image_url":      ("image", "productImage", "imageUrl", "picUrl", "cover", "product_image"),
    "category":       ("categoryName", "cateName", "cate", "category"),
    "revenue":        ("revenue", "gmv_A"),
    "sales":          ("sale", "sales", "salesCount", "orderCount"),
    "views":          ("video_revenue", "views", "viewCount", "videoViews"),
    "price":          ("unit_price", "min_real_price", "price"),
    "rating":         ("product_rating", "rating", "score"),
    "creator_num":    ("creator_num", "creatorNum", "creatorCnt"),
    "commission_pct": ("commission_rate", "commissionRate"),
    "launch_date":    ("launch_date", "launchDate"),
}

# kalodata uses Vietnamese currency suffixes: b=billion, m=million, k=thousand.
_SUFFIX_MULT = {"b": 1_000_000_000, "m": 1_000_000, "k": 1_000}


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, "", []):
            return row[k]
    return None


def _coerce_num(v: Any) -> float | None:
    """Parse ints, floats, and kalodata format strings like '₫21.77b' / '15%'."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip().replace(",", "").replace("₫", "").replace("$", "").replace("%", "").strip()
    if not s:
        return None
    mult = 1.0
    if s and s[-1].lower() in _SUFFIX_MULT:
        mult = _SUFFIX_MULT[s[-1].lower()]
        s = s[:-1]
    try:
        return float(s) * mult
    except (ValueError, TypeError):
        return None


def _extract(row: dict[str, Any]) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    for col, syns in _FIELD_SYNONYMS.items():
        val = _first(row, syns)
        if col in ("revenue", "sales", "views", "price", "rating",
                   "creator_num", "commission_pct"):
            val = _coerce_num(val)
        extracted[col] = val
    return extracted


def save_snapshot(
    *,
    country: str,
    start_date: str,
    end_date: str,
    sort_field: str,
    sort_type: str,
    rows: list[dict[str, Any]],
    notes: str = "",
    fetch_media: bool = False,
    progress_callback=None,
) -> int:
    """Persist a complete fetched list as one snapshot.

    If ``fetch_media=True``, also calls :func:`get_product_images` /
    :func:`get_product_videos` for every product so the home page has media
    ready to render. Adds 1 extra request per product per media type.
    """
    init_db()
    fetched_at = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """INSERT INTO snapshots
               (country, start_date, end_date, sort_field, sort_type,
                fetched_at, total_products, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (country, start_date, end_date, sort_field, sort_type,
             fetched_at, len(rows), notes),
        )
        snapshot_id = cursor.lastrowid
        total = len(rows)
        for idx, row in enumerate(rows, start=1):
            ex = _extract(row)
            pid = str(ex["product_id"]) if ex["product_id"] is not None else None
            image_urls_json = None
            video_urls_json = None
            if fetch_media and pid:
                imgs = get_product_images(pid)
                if imgs:
                    image_urls_json = json.dumps(imgs, ensure_ascii=False)
            if progress_callback is not None:
                progress_callback(idx, total, ex.get("product_name") or "")
            conn.execute(
                """INSERT INTO products
                   (snapshot_id, rank, product_id, product_name, image_url,
                    image_urls, video_urls, category, revenue, sales, views,
                    price, rating, creator_num, commission_pct, launch_date,
                    raw_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    idx,
                    pid,
                    ex["product_name"],
                    ex["image_url"],
                    image_urls_json,
                    video_urls_json,
                    ex["category"],
                    ex["revenue"],
                    ex["sales"],
                    ex["views"],
                    ex["price"],
                    ex["rating"],
                    int(ex["creator_num"]) if ex["creator_num"] is not None else None,
                    ex["commission_pct"],
                    ex["launch_date"],
                    json.dumps(row, ensure_ascii=False),
                ),
            )
        conn.commit()
        return int(snapshot_id)
    finally:
        conn.close()


def enrich_snapshot_media(snapshot_id: int, progress_callback=None) -> int:
    """Backfill image URLs for products in an existing snapshot.

    Returns count of products that received images. Idempotent — products
    with image_urls already populated are skipped.
    """
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute(
            """SELECT id, product_id, image_urls FROM products
               WHERE snapshot_id = ? ORDER BY rank""",
            (snapshot_id,),
        ).fetchall()
        updated = 0
        total = len(rows)
        for i, r in enumerate(rows, start=1):
            pid = r["product_id"]
            if not pid or r["image_urls"]:
                if progress_callback is not None:
                    progress_callback(i, total, pid or "")
                continue
            imgs = get_product_images(pid)
            if imgs:
                conn.execute(
                    "UPDATE products SET image_urls = ? WHERE id = ?",
                    (json.dumps(imgs, ensure_ascii=False), r["id"]),
                )
                updated += 1
            if progress_callback is not None:
                progress_callback(i, total, pid or "")
        conn.commit()
        return updated
    finally:
        conn.close()


def list_snapshots(country: str | None = None, limit: int = 100) -> list[dict]:
    conn = get_connection()
    try:
        if country:
            cursor = conn.execute(
                """SELECT * FROM snapshots WHERE country = ?
                   ORDER BY fetched_at DESC LIMIT ?""",
                (country, limit),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM snapshots ORDER BY fetched_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_snapshot(snapshot_id: int) -> dict | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_snapshot_rows(snapshot_id: int) -> list[dict]:
    conn = get_connection()
    try:
        cursor = conn.execute(
            """SELECT rank, product_id, product_name, image_url, image_urls,
                      video_urls, category, revenue, sales, views, price, rating,
                      creator_num, commission_pct, launch_date
               FROM products WHERE snapshot_id = ? ORDER BY rank ASC""",
            (snapshot_id,),
        )
        out = []
        for r in cursor.fetchall():
            row = dict(r)
            row["image_urls"] = json.loads(row["image_urls"]) if row["image_urls"] else []
            row["video_urls"] = json.loads(row["video_urls"]) if row["video_urls"] else []
            out.append(row)
        return out
    finally:
        conn.close()


def get_latest_snapshot_id(country: str | None = None) -> int | None:
    conn = get_connection()
    try:
        if country:
            row = conn.execute(
                """SELECT id FROM snapshots WHERE country = ?
                   ORDER BY fetched_at DESC LIMIT 1""",
                (country,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM snapshots ORDER BY fetched_at DESC LIMIT 1"
            ).fetchone()
        return int(row["id"]) if row else None
    finally:
        conn.close()


def delete_snapshot(snapshot_id: int) -> None:
    conn = get_connection()
    try:
        # FK ON DELETE CASCADE handles products
        conn.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
        conn.commit()
    finally:
        conn.close()


def compute_trending(
    new_snapshot_id: int,
    old_snapshot_id: int,
) -> dict[str, list[dict]]:
    """Compare two snapshots → return climbers, fallers, new entries, dropped.

    Climbers/fallers: products present in both, sorted by rank delta.
    New entries: in new, not in old.
    Dropped: in old, not in new.
    """
    new_rows = {r["product_id"]: r for r in get_snapshot_rows(new_snapshot_id) if r["product_id"]}
    old_rows = {r["product_id"]: r for r in get_snapshot_rows(old_snapshot_id) if r["product_id"]}

    diffs: list[dict] = []
    for pid, new_row in new_rows.items():
        if pid not in old_rows:
            continue
        old_row = old_rows[pid]
        rank_delta = (old_row.get("rank") or 0) - (new_row.get("rank") or 0)
        revenue_delta = (new_row.get("revenue") or 0) - (old_row.get("revenue") or 0)
        diffs.append({
            **new_row,
            "old_rank": old_row.get("rank"),
            "rank_delta": rank_delta,
            "old_revenue": old_row.get("revenue"),
            "revenue_delta": revenue_delta,
        })

    climbers = sorted(diffs, key=lambda r: r["rank_delta"], reverse=True)
    fallers = sorted(diffs, key=lambda r: r["rank_delta"])
    new_entries = [
        new_rows[pid] for pid in new_rows if pid not in old_rows
    ]
    dropped = [
        old_rows[pid] for pid in old_rows if pid not in new_rows
    ]

    return {
        "climbers": climbers,
        "fallers": fallers,
        "new_entries": new_entries,
        "dropped": dropped,
    }

"""Kalodata.com internal API client.

Uses a Chrome-style POST to ``/product/queryList`` with the session cookie
copied from a logged-in browser. Cloudflare bot-protection cookies
(``cf_clearance``) expire after ~30-60 minutes; when they do, the request
returns 403 and the user must re-copy the cookie header from DevTools.

Env vars:
  KALODATA_COOKIE   — full Cookie header value copied from DevTools.
  KALODATA_COUNTRY  — defaults to "VN".
  KALODATA_CURRENCY — defaults to "VND".
  KALODATA_LANGUAGE — defaults to "en-US".
"""
from __future__ import annotations

import logging
import os
from typing import Any

# curl_cffi impersonates a real Chrome TLS handshake so Cloudflare doesn't
# flag the request as a bot. Falls back to plain requests if not installed.
try:
    from curl_cffi import requests as _http
    _IMPERSONATE = "chrome120"
except ImportError:  # pragma: no cover
    import requests as _http
    _IMPERSONATE = None

log = logging.getLogger(__name__)

BASE_URL = "https://www.kalodata.com"
DEFAULT_TIMEOUT = 30

SORT_FIELDS = (
    "revenue",
    "sales",
    "views",
    "videoViews",
    "liveViews",
    "creatorCnt",
    "conversionRate",          # tỉ lệ chuyển đổi (đã xác thực với API thật)
    "price",
    "rating",
)
SORT_TYPES = ("DESC", "ASC")


class KalodataAuthError(RuntimeError):
    pass


class KalodataAPIError(RuntimeError):
    pass


def _cookie() -> str:
    cookie = (os.getenv("KALODATA_COOKIE") or "").strip()
    if not cookie:
        raise KalodataAuthError(
            "KALODATA_COOKIE chưa set trong .env. "
            "Login kalodata.com → F12 → Network → tìm 1 request → "
            "copy header `cookie` nguyên cụm → paste vào .env."
        )
    return cookie


def _headers() -> dict[str, str]:
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "origin": BASE_URL,
        "referer": f"{BASE_URL}/product",
        "country": os.getenv("KALODATA_COUNTRY", "VN"),
        "currency": os.getenv("KALODATA_CURRENCY", "VND"),
        "language": os.getenv("KALODATA_LANGUAGE", "en-US"),
        "cookie": _cookie(),
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/149.0.0.0 Safari/537.36"
        ),
        "sec-ch-ua": '"Google Chrome";v="149", "Chromium";v="149", "Not)A;Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
    }


def query_products(
    start_date: str,
    end_date: str,
    page_no: int = 1,
    page_size: int = 10,
    sort_field: str = "revenue",
    sort_type: str = "DESC",
    category_ids: list[int] | None = None,
    show_category_ids: list[int] | None = None,
    country: str | None = None,
) -> dict[str, Any]:
    """Query the kalodata product list.

    Args:
        start_date: ISO date string ``YYYY-MM-DD``.
        end_date: ISO date string ``YYYY-MM-DD`` (inclusive).
        page_no: 1-based page index.
        page_size: rows per page (10 / 20 / 50).
        sort_field: one of :data:`SORT_FIELDS`.
        sort_type: ``DESC`` or ``ASC``.
        category_ids: numeric kalodata category ids — empty = all.
        show_category_ids: child category ids — empty = all.
        country: overrides ``KALODATA_COUNTRY`` env for one call.

    Returns:
        Parsed JSON response (kalodata returns ``{"code", "data", "msg"}``).

    Raises:
        KalodataAuthError: cookie missing or expired (401/403).
        KalodataAPIError: any other non-2xx response.
    """
    if sort_field not in SORT_FIELDS:
        raise ValueError(f"sort_field phải thuộc {SORT_FIELDS}, got {sort_field!r}")
    if sort_type not in SORT_TYPES:
        raise ValueError(f"sort_type phải thuộc {SORT_TYPES}, got {sort_type!r}")
    if page_no < 1:
        raise ValueError("page_no phải >= 1")

    payload = {
        "country": country or os.getenv("KALODATA_COUNTRY", "VN"),
        "startDate": start_date,
        "endDate": end_date,
        "cateIds": list(category_ids or []),
        "showCateIds": list(show_category_ids or []),
        "pageNo": page_no,
        "pageSize": page_size,
        "sort": [{"field": sort_field, "type": sort_type}],
    }

    log.info(
        "kalodata queryProducts | %s..%s page=%d/%d sort=%s/%s",
        start_date, end_date, page_no, page_size, sort_field, sort_type,
    )

    post_kwargs: dict[str, Any] = dict(
        headers=_headers(),
        json=payload,
        timeout=DEFAULT_TIMEOUT,
    )
    if _IMPERSONATE is not None:
        post_kwargs["impersonate"] = _IMPERSONATE
    resp = _http.post(f"{BASE_URL}/product/queryList", **post_kwargs)

    if resp.status_code in (401, 403):
        raise KalodataAuthError(
            f"{resp.status_code} — cookie session / cf_clearance hết hạn. "
            "Mở browser → DevTools → copy lại cookie mới vào .env. "
            f"Server msg: {resp.text[:200]}"
        )
    if resp.status_code != 200:
        raise KalodataAPIError(
            f"HTTP {resp.status_code}: {resp.text[:400]}"
        )

    try:
        data = resp.json()
    except ValueError as e:
        raise KalodataAPIError(f"Response không phải JSON: {resp.text[:200]}") from e

    # Kalodata responses use either {"success", "data", "message", "code"} or
    # legacy {"code", "data", "msg"}. Treat success=False as an API error.
    success = data.get("success")
    if success is False:
        msg = data.get("message")
        if isinstance(msg, dict):
            # Server packs paywall hints as a dict.
            paywall = msg.get("message") or msg.get("desc") or str(msg)
            if "Upgrade" in paywall or "limit" in paywall.lower():
                raise KalodataAPIError(
                    "Đạt giới hạn gói kalodata — server trả 'Upgrade to view more data'. "
                    "Free/basic plan chỉ cho xem tối đa 10 rows (pageSize=10, pageNo=1). "
                    "Muốn fetch nhiều hơn → upgrade plan."
                )
            raise KalodataAPIError(f"API: {paywall}")
        raise KalodataAPIError(f"API: {msg or data.get('code')}")
    code = data.get("code")
    if code not in (None, 0, "0"):
        raise KalodataAPIError(
            f"API code={code} msg={data.get('msg', data.get('message', '<no msg>'))}"
        )
    return data


def fetch_all_products(
    start_date: str,
    end_date: str,
    sort_field: str = "revenue",
    sort_type: str = "DESC",
    category_ids: list[int] | None = None,
    country: str | None = None,
    page_size: int = 50,
    max_pages: int = 200,
    progress_callback=None,
) -> tuple[list[dict[str, Any]], int | None]:
    """Auto-paginate through `/product/queryList` and collect every row.

    Args:
        start_date / end_date / sort_*: same as :func:`query_products`.
        page_size: rows per request — bigger = fewer requests but heavier.
        max_pages: safety cap; stops if exceeded even with more rows server-side.
        progress_callback: ``fn(page, total_pages_known_or_None, rows_so_far)``.

    Returns:
        (all_rows, total_server_count_or_None)

    Raises:
        KalodataAuthError on auth failure mid-pagination (partial rows discarded).
        KalodataAPIError on any other API error.
    """
    all_rows: list[dict[str, Any]] = []
    total: int | None = None
    page = 1
    while page <= max_pages:
        resp = query_products(
            start_date=start_date,
            end_date=end_date,
            page_no=page,
            page_size=page_size,
            sort_field=sort_field,
            sort_type=sort_type,
            category_ids=category_ids,
            country=country,
        )
        rows = extract_rows(resp)
        if total is None:
            total = extract_total(resp)
        all_rows.extend(rows)
        total_pages = (
            (total + page_size - 1) // page_size if total else None
        )
        if progress_callback is not None:
            progress_callback(page, total_pages, len(all_rows))
        if not rows:
            break
        if total is not None and len(all_rows) >= total:
            break
        if len(rows) < page_size:
            # Server returned fewer than asked → last page.
            break
        page += 1
    return all_rows, total


def get_product_images(product_id: str) -> list[str]:
    """GET /product/detail/getImages — returns list of CDN image URLs.

    Returns empty list on auth/API failure (caller decides whether to surface).
    """
    post_kwargs: dict[str, Any] = dict(
        headers=_headers(),
        timeout=DEFAULT_TIMEOUT,
    )
    if _IMPERSONATE is not None:
        post_kwargs["impersonate"] = _IMPERSONATE
    try:
        resp = _http.get(
            f"{BASE_URL}/product/detail/getImages",
            params={"productId": product_id},
            **post_kwargs,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("getImages network error pid=%s err=%s", product_id, e)
        return []
    if resp.status_code != 200:
        log.warning("getImages http %d pid=%s", resp.status_code, product_id)
        return []
    try:
        data = resp.json()
    except ValueError:
        return []
    if data.get("success") is False:
        return []
    rows = data.get("data") or []
    if isinstance(rows, list):
        return [str(u) for u in rows if isinstance(u, str)]
    return []


def extract_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull product rows out of a queryProducts response.

    Kalodata's response shape varies slightly; we look at the common
    locations and return whatever list we find first.
    """
    data = response.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "rows", "items", "records", "products"):
            rows = data.get(key)
            if isinstance(rows, list):
                return rows
    return []


def extract_total(response: dict[str, Any]) -> int | None:
    data = response.get("data") or {}
    if isinstance(data, dict):
        for key in ("total", "totalCount", "count"):
            val = data.get(key)
            if isinstance(val, int):
                return val
    return None

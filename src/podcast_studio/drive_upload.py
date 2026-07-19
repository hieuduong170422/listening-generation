"""Upload video affiliate lên Google Drive bằng service account.

Cách hoạt động:
- User share thư mục gốc (vd "affiliate") trên Drive cho email service account
  (quyền Editor) và đặt env AFFILIATE_DRIVE_FOLDER_ID=<id thư mục đó>.
- Mỗi sản phẩm 1 folder con (tên = "Mô tả sản phẩm" user nhập), tự tạo nếu chưa có.
- Upload là best-effort: lỗi chỉ log, KHÔNG làm fail job render video.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from pathlib import Path

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

log = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_API = "https://www.googleapis.com/drive/v3"
_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
_TIMEOUT = 120  # video vài chục MB — cho dư thời gian

_creds_lock = threading.Lock()
_creds: service_account.Credentials | None = None

# Cache (parent_id, tên folder) → folder_id — tránh 2 job song song tạo folder trùng
_folder_lock = threading.Lock()
_folder_cache: dict[tuple[str, str], str] = {}


def is_enabled() -> bool:
    return bool(os.getenv("AFFILIATE_DRIVE_FOLDER_ID", "").strip())


def _get_credentials() -> service_account.Credentials:
    global _creds
    with _creds_lock:
        if _creds is None:
            raw = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "").strip()
            if raw:
                info = json.loads(raw)
                _creds = service_account.Credentials.from_service_account_info(
                    info, scopes=_SCOPES
                )
            else:
                path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
                if not path:
                    raise RuntimeError(
                        "Thiếu GCP_SERVICE_ACCOUNT_JSON / GOOGLE_APPLICATION_CREDENTIALS"
                    )
                _creds = service_account.Credentials.from_service_account_file(
                    path, scopes=_SCOPES
                )
        if not _creds.valid:
            _creds.refresh(Request())
        return _creds


def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_credentials().token}"}


def sanitize_folder_name(name: str) -> str:
    """Tên folder Drive hợp lệ từ mô tả sản phẩm user nhập."""
    cleaned = re.sub(r'[\\/:*?"<>|]', " ", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:80] or "san-pham"


def _escape_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_or_create_folder(name: str, parent_id: str) -> str:
    """Tìm folder con theo tên trong parent; chưa có thì tạo. Trả folder id."""
    key = (parent_id, name)
    with _folder_lock:
        cached = _folder_cache.get(key)
    if cached:
        return cached

    with _folder_lock:
        # Double-check sau khi giữ lock để 2 thread không cùng tạo
        cached = _folder_cache.get(key)
        if cached:
            return cached

        query = (
            f"name = '{_escape_query(name)}' and '{_escape_query(parent_id)}' in parents "
            "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        resp = requests.get(
            f"{_API}/files",
            params={
                "q": query,
                "fields": "files(id, name)",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            },
            headers=_headers(),
            timeout=30,
        )
        resp.raise_for_status()
        found = resp.json().get("files", [])
        if found:
            folder_id = found[0]["id"]
        else:
            create = requests.post(
                f"{_API}/files",
                params={"supportsAllDrives": "true", "fields": "id"},
                headers={**_headers(), "Content-Type": "application/json"},
                json={
                    "name": name,
                    "mimeType": "application/vnd.google-apps.folder",
                    "parents": [parent_id],
                },
                timeout=30,
            )
            create.raise_for_status()
            folder_id = create.json()["id"]
            log.info("Drive: đã tạo folder %r (id=%s)", name, folder_id)

        _folder_cache[key] = folder_id
        return folder_id


def upload_file(path: Path, folder_id: str, filename: str | None = None) -> dict:
    """Upload multipart 1 file vào folder. Trả {'id', 'webViewLink'}."""
    data = path.read_bytes()
    name = filename or path.name
    mime = "video/mp4" if path.suffix.lower() == ".mp4" else "application/octet-stream"

    boundary = "drive-upload-boundary-7f3a"
    meta = json.dumps({"name": name, "parents": [folder_id]})
    body = (
        (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{meta}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime}\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--".encode()
    )
    resp = requests.post(
        f"{_UPLOAD_API}/files",
        params={
            "uploadType": "multipart",
            "supportsAllDrives": "true",
            "fields": "id, webViewLink",
        },
        headers={
            **_headers(),
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
        data=body,
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def upload_video_for_product(path: Path, product_name: str, filename: str | None = None) -> str | None:
    """Upload video vào affiliate/<sản phẩm>/ trên Drive. Trả webViewLink, lỗi → None.

    Best-effort: mọi exception đều nuốt + log — upload hỏng không được làm fail render.
    """
    root_id = os.getenv("AFFILIATE_DRIVE_FOLDER_ID", "").strip()
    if not root_id:
        return None
    try:
        folder_id = find_or_create_folder(sanitize_folder_name(product_name), root_id)
        result = upload_file(path, folder_id, filename)
        link = result.get("webViewLink")
        log.info("Drive: đã upload %s → folder %r (%s)", path.name, product_name, link)
        return link
    except Exception:
        log.exception("Drive upload thất bại cho %s (product=%r)", path, product_name)
        return None

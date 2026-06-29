"""Chọn google-genai client dùng chung cho toàn app.

- `get_client()`  → Vertex AI (dùng credit GCP) khi bật `GOOGLE_GENAI_USE_VERTEXAI`,
  nếu không thì dùng `GEMINI_API_KEY`. Dùng cho **sinh text** (outline/script/topic)
  và feature affiliate.
- `get_api_key_client()` → LUÔN dùng `GEMINI_API_KEY`. Dùng cho những thứ giữ trên
  key cũ: **TTS** (Gemini TTS) và **sinh ảnh** Nano Banana.

Tách riêng vì ở Việt Nam Gemini Developer API bắt prepay và credit free-trial $300 của
GCP chỉ dùng được qua Vertex AI — nên text (rẻ) chạy Vertex, còn TTS vẫn trên key cũ.
"""

from __future__ import annotations

import os

import streamlit as st
from google import genai

from podcast_studio.auth import get_api_key

_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def vertex_enabled() -> bool:
    return os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in ("1", "true", "yes")


def _vertex_credentials():
    """Service account cho Vertex (bắt buộc trên Streamlit Cloud — ở đó KHÔNG có ADC).

    Thứ tự ưu tiên:
      1. st.secrets["gcp_service_account"]  (dán nội dung JSON vào Streamlit secrets)
      2. env GCP_SERVICE_ACCOUNT_JSON       (chuỗi JSON inline)
      3. env GOOGLE_APPLICATION_CREDENTIALS (đường dẫn file JSON)
      4. None → google-genai tự dùng ADC (chỉ chạy được ở local có `gcloud auth ...`)
    """
    import json

    from google.oauth2 import service_account

    info = None
    try:
        if "gcp_service_account" in st.secrets:  # Streamlit Cloud
            info = dict(st.secrets["gcp_service_account"])
    except Exception:
        pass  # st.secrets có thể chưa cấu hình → bỏ qua
    if info is None:
        raw = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "").strip()
        if raw:
            info = json.loads(raw)
    if info is not None:
        return service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)

    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path and os.path.exists(path):
        return service_account.Credentials.from_service_account_file(path, scopes=_SCOPES)

    return None  # fallback ADC (local)


def get_vertex_client() -> genai.Client:
    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip() or "us-central1"
    if not project:
        st.error("Vertex AI: thiếu GOOGLE_CLOUD_PROJECT trong .env.")
        st.stop()
    try:
        creds = _vertex_credentials()
        return genai.Client(
            vertexai=True, project=project, location=location, credentials=creds
        )
    except Exception as e:
        st.error(
            f"Không tạo được Vertex client: {e}\n\n"
            "• Local: chạy `gcloud auth application-default login`.\n"
            "• Streamlit Cloud: dán service account JSON vào Settings → Secrets "
            "dưới khoá [gcp_service_account] (xem hướng dẫn)."
        )
        st.stop()


def get_api_key_client() -> genai.Client:
    """LUÔN dùng GEMINI_API_KEY (cho TTS + sinh ảnh)."""
    api_key = get_api_key()
    if not api_key:
        st.error("Chưa có API key. Nhập GEMINI_API_KEY trong .env hoặc ô 🔑 API Key ở sidebar.")
        st.stop()
    return genai.Client(api_key=api_key)


def get_client() -> genai.Client:
    """Vertex AI khi bật GOOGLE_GENAI_USE_VERTEXAI; nếu không thì key Gemini."""
    if vertex_enabled():
        return get_vertex_client()
    return get_api_key_client()

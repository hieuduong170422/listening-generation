import os
import sys

import streamlit as st
from dotenv import load_dotenv

from paths import ROOT

# Đưa thư mục src/ lên path để import 2 package: podcast_studio và prompt_template.
sys.path.insert(0, str(ROOT / "src"))

# Local dev: nạp biến từ .env. Trên Cloud không có file này nên call thành no-op.
load_dotenv(ROOT / ".env")

# Streamlit Cloud KHÔNG tự inject st.secrets vào os.environ. Bridge thủ công
# để mọi `os.getenv("KEY")` đang dùng khắp codebase đều thấy được giá trị —
# bất kể secret được set ở local .env hay Streamlit Cloud Secrets.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str) and _k not in os.environ:
            os.environ[_k] = _v
except Exception:  # pragma: no cover — secrets file missing on first boot
    pass

st.set_page_config(page_title="Audivy Workspace", layout="wide")

from podcast_studio.auth import apply_api_key_env, check_auth, is_admin, render_api_key_box
from prompt_template.database import init_db

# Đảm bảo bảng của Prompt Template Engine tồn tại (file SQLite tạo ở lần chạy đầu).
try:
    init_db()
except Exception as e:  # pragma: no cover - hiển thị trên UI
    st.warning(f"Không khởi tạo được DB prompt-template: {e}")

if not check_auth():
    st.stop()

# Đẩy key nhập runtime vào os.environ để mọi client thấy (dựa trên os.getenv).
apply_api_key_env()
# Chỉ admin mới thấy / sửa được API key. Người dùng thường vẫn dùng key
# admin đã nhập (key tồn tại process-wide qua os.environ).
if is_admin():
    render_api_key_box()

# ── Điều hướng nhóm: hiện rõ các công cụ trong workspace ────────────────────
pages = {
    "🏠 Bắt đầu": [
        st.Page("views/home.py", title="Trang chủ", icon="🏠", url_path="home", default=True),
    ],
    "🎧 Podcast Studio": [
        st.Page("views/podcast/unified_studio.py", title="Tạo Podcast (Unified)", icon="✨", url_path="podcast-unified"),
        st.Page("views/podcast/elevenlabs_studio.py", title="Podcast (ElevenLabs)", icon="🎧", url_path="podcast-elevenlabs"),
        st.Page("views/podcast/elevenlabs_history.py", title="ElevenLabs History", icon="📜", url_path="elevenlabs-history"),
        st.Page("views/podcast/tts_settings.py", title="Cài đặt TTS", icon="⚙️", url_path="tts-settings"),
    ],
    "🧩 Prompt Template Engine": [
        st.Page("views/prompt_template/home.py", title="Danh sách Template", icon="📋", url_path="templates"),
        st.Page("views/prompt_template/create.py", title="Tạo Template", icon="➕", url_path="template-create"),
        st.Page("views/prompt_template/run.py", title="Chạy Template", icon="🚀", url_path="template-run"),
        st.Page("views/prompt_template/history.py", title="Lịch sử", icon="📜", url_path="template-history"),
    ],
    "🎬 Video Affiliate": [
        st.Page("views/affiliate/generate.py", title="Tạo Video Affiliate", icon="🎬", url_path="affiliate"),
    ],
    "📊 Kalodata": [
        st.Page("views/kalodata/products.py", title="Product Explorer", icon="📊", url_path="kalodata-products"),
    ],
}

if is_admin():
    pages["🛡️ Admin"] = [
        st.Page("views/admin/dashboard.py", title="Admin Dashboard", icon="🛡️", url_path="admin"),
    ]

# expanded=True: luôn mở hết, không thu gọn nhóm / không "View X more".
pg = st.navigation(pages, expanded=True)
pg.run()

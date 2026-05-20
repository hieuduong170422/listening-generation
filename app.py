import streamlit as st
from dotenv import load_dotenv

from paths import ROOT

load_dotenv(ROOT / ".env")

st.set_page_config(page_title="Audivy Studio", layout="wide")

from auth import check_auth
from prompt_template.database import init_db

# Ensure prompt-template tables exist (SQLite file created on first run).
try:
    init_db()
except Exception as e:  # pragma: no cover - surfaced in UI
    st.warning(f"Không khởi tạo được DB prompt-template: {e}")

if not check_auth():
    st.stop()

_pages = [
    st.Page("pages/tts_studio.py", title="TTS Script Gen", icon="🎙️", default=True),
    st.Page("pages/pt_home.py", title="Prompt Templates", icon="📋"),
    st.Page("pages/pt_create.py", title="Create Template", icon="➕"),
    st.Page("pages/pt_run.py", title="Run Template", icon="🚀"),
    st.Page("pages/pt_history.py", title="Template History", icon="📜"),
]

st.navigation(_pages).run()

import os

import streamlit as st

from podcast_studio.usage_logger import log_event


def read_secret(key: str) -> str:
    try:
        value = st.secrets.get(key)
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(key, "")


def get_api_key() -> str:
    """Gemini API key — priority: session override > secrets/.env."""
    override = (st.session_state.get("_api_key_override") or "").strip()
    if override:
        return override
    return read_secret("GEMINI_API_KEY") or read_secret("API_KEY")


def apply_api_key_env() -> None:
    """Push the session-overridden key into os.environ so all clients see it."""
    override = (st.session_state.get("_api_key_override") or "").strip()
    if override:
        os.environ["GEMINI_API_KEY"] = override
        os.environ["API_KEY"] = override


def render_api_key_box() -> None:
    """Sidebar widget to enter / override the Gemini API key at runtime."""
    with st.sidebar:
        current = get_api_key()
        with st.expander("🔑 API Key", expanded=not current):
            if current:
                st.success(f"✅ Đang dùng key …{current[-4:]}")
            else:
                st.warning("⚠️ Chưa có API key. Nhập bên dưới để dùng app.")
            new_key = st.text_input(
                "Gemini API Key",
                type="password",
                value=st.session_state.get("_api_key_override", ""),
                key="_api_key_input",
                help="Lấy tại https://aistudio.google.com/apikey",
            )
            bc1, bc2 = st.columns(2)
            if bc1.button("💾 Lưu", key="_save_api_key", use_container_width=True):
                st.session_state["_api_key_override"] = (new_key or "").strip()
                apply_api_key_env()
                st.rerun()
            if bc2.button("🗑️ Xoá", key="_clear_api_key", use_container_width=True):
                st.session_state["_api_key_override"] = ""
                st.rerun()
            st.caption("Key lưu trong session trình duyệt, không ghi ra file.")


def is_admin() -> bool:
    admin_secret = read_secret("ADMIN_USERS")
    admins = {
        u.strip().lower()
        for u in (admin_secret or "admin").split(",")
        if u.strip()
    }
    return (st.session_state.get("username", "") or "").lower() in admins


def _allowed_users() -> set[str]:
    """Tập username được phép đăng nhập (lowercase). Đọc từ ALLOWED_USERS secret/env."""
    raw = read_secret("ALLOWED_USERS")
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


def check_auth() -> bool:
    expected = read_secret("APP_PASSWORD")
    if not expected:
        if not st.session_state.get("username"):
            st.session_state["username"] = "anonymous"
        return True
    if st.session_state.get("_authed"):
        return True

    st.title("🔐 Audivy Studio")
    st.caption("Nhập tên + password để truy cập.")
    username = st.text_input("Tên", key="_login_user", value="")
    pwd = st.text_input("Password", type="password", key="_login_pwd")
    if st.button("Đăng nhập", type="primary"):
        clean = (username or "").strip().lower()
        allowed = _allowed_users()
        if allowed and clean not in allowed:
            st.error("Tên tài khoản không hợp lệ.")
        elif pwd != expected:
            st.error("Sai password.")
        else:
            st.session_state["_authed"] = True
            st.session_state["username"] = clean
            try:
                log_event(
                    kind="auth", action="login",
                    prompt_tokens=0, output_tokens=0, cost_usd=0.0,
                    user=clean, topic="",
                )
            except Exception:
                pass
            st.rerun()
    return False

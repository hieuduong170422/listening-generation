import os

import streamlit as st

from usage_logger import log_event


def read_secret(key: str) -> str:
    try:
        value = st.secrets.get(key)
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(key, "")


def is_admin() -> bool:
    admin_secret = read_secret("ADMIN_USERS")
    admins = {
        u.strip().lower()
        for u in (admin_secret or "admin").split(",")
        if u.strip()
    }
    return (st.session_state.get("username", "") or "").lower() in admins


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
    username = st.text_input("Tên (để track usage)", key="_login_user", value="")
    pwd = st.text_input("Password", type="password", key="_login_pwd")
    if st.button("Đăng nhập", type="primary"):
        if pwd == expected:
            clean = (username or "").strip() or "anonymous"
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
        else:
            st.error("Sai password.")
    return False

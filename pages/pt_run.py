"""Run Template page — select a template, fill in fields, call Gemini, see results."""

import os
import re

import streamlit as st

from prompt_template.llm_client import generate
from prompt_template.history_store import save_execution
from prompt_template.template_store import get_template, list_templates

st.title("🚀 Chạy Prompt Template")

# ── Template Selector ──────────────────────────────────────────────────────

templates = list_templates()
if not templates:
    st.info("Chưa có template nào. Tạo template đầu tiên để bắt đầu.")
    if st.button("➕ Tạo template", type="primary"):
        st.switch_page("pages/pt_create.py")
    st.stop()

template_options = {t["name"]: t["id"] for t in templates}
_preselect = st.session_state.pop("_run_tid", None)
_names = list(template_options.keys())
_idx = 0
if _preselect is not None:
    for _i, _n in enumerate(_names):
        if template_options[_n] == _preselect:
            _idx = _i
            break

st.caption("**Bước 1** — Chọn template")
selected_name = st.selectbox("Template", options=_names, index=_idx, label_visibility="collapsed")

if not selected_name:
    st.stop()

template_id = template_options[selected_name]
template = get_template(template_id)

if not template:
    st.error("Không tìm thấy template.")
    st.stop()

system_prompt = template.get("system_prompt", "")
with st.expander("👁️ Xem system prompt của template này", expanded=False):
    st.code(system_prompt or "(trống)", language="text")
ic1, ic2 = st.columns(2)
ic1.caption(f"🤖 Model: `{template['model']}`")
ic2.caption(f"🌡️ Temperature: `{template['temperature']}`")

st.divider()

# ── Dynamic Form Rendering ─────────────────────────────────────────────────

st.caption("**Bước 2** — Điền thông tin")

inputs = template.get("inputs", [])
if not inputs:
    st.info("Template này không có input field nào — bấm Chạy luôn.")

user_values = {}
uploaded_files = []

for field in inputs:
    field_key = f"field_{field['id']}"
    label = field["label"] or field["key"]
    required = bool(field.get("required", 0))
    placeholder = field.get("placeholder", "")
    label_display = f"{label} {'*' if required else ''}".strip()

    if field["type"] == "TEXT":
        user_values[field["key"]] = st.text_input(
            label_display, key=field_key, placeholder=placeholder,
        )

    elif field["type"] == "TEXTAREA":
        user_values[field["key"]] = st.text_area(
            label_display, key=field_key, placeholder=placeholder,
        )

    elif field["type"] == "IMAGE":
        uploaded = st.file_uploader(
            label_display, key=field_key,
            type=["png", "jpg", "jpeg", "gif", "webp"],
        )
        if uploaded:
            file_path = os.path.join("uploads", uploaded.name)
            with open(file_path, "wb") as f:
                f.write(uploaded.getbuffer())
            uploaded_files.append(file_path)
            user_values[field["key"]] = f"[Image: {uploaded.name}]"
            pc1, pc2 = st.columns([1, 2])
            with pc1:
                st.image(uploaded, use_container_width=True)
            with pc2:
                size_kb = len(uploaded.getvalue()) / 1024
                st.caption(f"🖼️ **{uploaded.name}**")
                st.caption(f"Dung lượng: {size_kb:.0f} KB")
                st.caption("✅ Ảnh đã sẵn sàng để gửi.")

    elif field["type"] == "FILE":
        uploaded = st.file_uploader(label_display, key=field_key)
        if uploaded:
            file_path = os.path.join("uploads", uploaded.name)
            with open(file_path, "wb") as f:
                f.write(uploaded.getbuffer())
            uploaded_files.append(file_path)
            user_values[field["key"]] = f"[File: {uploaded.name}]"
            size_kb = len(uploaded.getvalue()) / 1024
            st.caption(f"📄 **{uploaded.name}** — {size_kb:.0f} KB ✅")

    elif field["type"] == "NUMBER":
        user_values[field["key"]] = str(
            st.number_input(label_display, key=field_key)
        )

    elif field["type"] == "BOOLEAN":
        user_values[field["key"]] = str(st.checkbox(label_display, key=field_key))

    elif field["type"] == "SELECT":
        options_raw = field.get("select_options", "")
        options = (
            [ln.strip() for ln in options_raw.split("\n") if ln.strip()]
            if options_raw else []
        )
        user_values[field["key"]] = st.selectbox(
            label_display, options or ["(no options)"], key=field_key,
        )

# ── Variable Replacement ────────────────────────────────────────────────────


def replace_variables(prompt: str, values: dict) -> str:
    """Replace ``{{key}}`` placeholders with corresponding values."""

    def replacer(match: re.Match) -> str:
        key = match.group(1).strip()
        return str(values.get(key, match.group(0)))

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replacer, prompt)


# ── Run Button ──────────────────────────────────────────────────────────────

st.divider()
st.caption("**Bước 3** — Chạy")

if st.button("🚀 Chạy template", type="primary", use_container_width=True):
    errors = []
    for field in inputs:
        if field.get("required") and not user_values.get(field["key"], "").strip():
            errors.append(f"'{field['label']}' là bắt buộc.")

    if errors:
        for err in errors:
            st.error(err)
    else:
        user_prompt = replace_variables(
            template.get("system_prompt", ""), user_values
        )

        with st.spinner("Đang gọi Gemini API..."):
            try:
                result = generate(
                    system_prompt=template.get("system_prompt", ""),
                    user_prompt=user_prompt,
                    model=template["model"],
                    temperature=template["temperature"],
                    files=uploaded_files if uploaded_files else None,
                )

                st.divider()
                st.subheader("✨ Kết quả")
                if result["type"] == "text":
                    st.markdown(result["text"])
                elif result["type"] == "image":
                    img_src = result.get("response_data") or result["text"]
                    st.image(img_src)
                elif result["type"] == "video":
                    st.video(result["text"])
                elif result["type"] == "audio":
                    st.audio(result["text"])
                else:
                    st.text(result["text"])

                st.caption(
                    f"Model: {template['model']} · Temperature: {template['temperature']}"
                )

                save_execution(
                    template_id=template_id,
                    template_name=template["name"],
                    inputs_dict=user_values,
                    response_text=result["text"],
                    response_type=result["type"],
                    response_data=result.get("response_data", ""),
                    model=template["model"],
                    temperature=template["temperature"],
                )
                st.success("✅ Đã lưu vào lịch sử.")

            except ValueError as e:
                st.error(str(e))
            except RuntimeError as e:
                st.error(f"Lỗi API: {e}")
            except Exception as e:
                st.error(f"Lỗi không xác định: {e}")

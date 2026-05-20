"""Run Template page — select a template, fill in fields, call Gemini, see results."""

import json
import os
import re

import streamlit as st

from prompt_template.llm_client import generate
from prompt_template.history_store import save_execution
from prompt_template.template_store import get_template, list_templates

st.title("▶️ Run Prompt Template")

# ── Template Selector ──────────────────────────────────────────────────────

templates = list_templates()
if not templates:
    st.info("No templates yet. Create a template first!")
    if st.button("+ Create Template"):
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
selected_name = st.selectbox("Select Template", options=_names, index=_idx)

if not selected_name:
    st.stop()

template_id = template_options[selected_name]
template = get_template(template_id)

if not template:
    st.error("Template not found.")
    st.stop()

system_prompt = template.get("system_prompt", "")
prompt_preview = system_prompt[:200]
if len(system_prompt) > 200:
    prompt_preview += "…"
st.markdown(f"**System Prompt:** `{prompt_preview}`")

# ── Dynamic Form Rendering ─────────────────────────────────────────────────

st.subheader("Input Values")

user_values = {}
uploaded_files = []

for field in template.get("inputs", []):
    field_key = f"field_{field['id']}"
    label = field["label"]
    required = bool(field.get("required", 0))
    placeholder = field.get("placeholder", "")

    if field["type"] == "TEXT":
        val = st.text_input(
            label,
            key=field_key,
            placeholder=placeholder,
            help="Required" if required else "",
        )
        user_values[field["key"]] = val

    elif field["type"] == "TEXTAREA":
        val = st.text_area(
            label,
            key=field_key,
            placeholder=placeholder,
            help="Required" if required else "",
        )
        user_values[field["key"]] = val

    elif field["type"] == "IMAGE":
        uploaded = st.file_uploader(
            label,
            key=field_key,
            type=["png", "jpg", "jpeg", "gif", "webp"],
            help="Required" if required else "",
        )
        if uploaded:
            file_path = os.path.join("uploads", uploaded.name)
            with open(file_path, "wb") as f:
                f.write(uploaded.getbuffer())
            uploaded_files.append(file_path)
            user_values[field["key"]] = f"[Image: {uploaded.name}]"

    elif field["type"] == "FILE":
        uploaded = st.file_uploader(
            label,
            key=field_key,
            help="Required" if required else "",
        )
        if uploaded:
            file_path = os.path.join("uploads", uploaded.name)
            with open(file_path, "wb") as f:
                f.write(uploaded.getbuffer())
            uploaded_files.append(file_path)
            user_values[field["key"]] = f"[File: {uploaded.name}]"

    elif field["type"] == "NUMBER":
        val = st.number_input(
            label,
            key=field_key,
            help="Required" if required else "",
        )
        user_values[field["key"]] = str(val)

    elif field["type"] == "BOOLEAN":
        val = st.checkbox(label, key=field_key)
        user_values[field["key"]] = str(val)

    elif field["type"] == "SELECT":
        options_raw = field.get("select_options", "")
        options = (
            [ln.strip() for ln in options_raw.split("\n") if ln.strip()]
            if options_raw
            else []
        )
        if options:
            val = st.selectbox(label, options, key=field_key)
        else:
            val = st.selectbox(label, ["(no options)"], key=field_key)
        user_values[field["key"]] = val

# ── Variable Replacement ────────────────────────────────────────────────────


def replace_variables(prompt: str, values: dict) -> str:
    """Replace ``{{key}}`` placeholders with corresponding values."""

    def replacer(match: re.Match) -> str:
        key = match.group(1).strip()
        return str(values.get(key, match.group(0)))

    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replacer, prompt)


# ── Run Button ──────────────────────────────────────────────────────────────

if st.button("🚀 Run", type="primary"):
    errors = []
    for field in template.get("inputs", []):
        if field.get("required") and not user_values.get(field["key"], "").strip():
            errors.append(f"'{field['label']}' is required.")

    if errors:
        for err in errors:
            st.error(err)
    else:
        user_prompt = replace_variables(
            template.get("system_prompt", ""), user_values
        )

        with st.spinner("Calling Gemini API..."):
            try:
                result = generate(
                    system_prompt=template.get("system_prompt", ""),
                    user_prompt=user_prompt,
                    model=template["model"],
                    temperature=template["temperature"],
                    files=uploaded_files if uploaded_files else None,
                )

                # ── Display Result ──
                st.subheader("Response")
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
                    f"Model: {template['model']} | "
                    f"Temperature: {template['temperature']}"
                )

                # ── Save to History ──
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
                st.success("Execution saved to history.")

            except ValueError as e:
                st.error(str(e))
            except RuntimeError as e:
                st.error(f"API Error: {e}")
            except Exception as e:
                st.error(f"Unexpected error: {e}")

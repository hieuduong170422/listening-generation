import streamlit as st
from prompt_template.template_store import create_template, get_template, update_template
from prompt_template.llm_client import AVAILABLE_MODELS

st.title("Create / Edit Template")

# Template ID is passed via session_state by the Edit button in app.py.
# Must read BEFORE the first rerun trigger so is_edit remains stable.
template_id = st.session_state.get("_edit_tid")
is_edit = template_id is not None

if "input_fields" not in st.session_state:
    st.session_state.input_fields = []

if is_edit and not st.session_state.get("_loaded", False):
    t = get_template(int(template_id))
    if t:
        st.session_state["_name"] = t["name"]
        st.session_state["_description"] = t.get("description", "")
        st.session_state["_system_prompt"] = t.get("system_prompt", "")
        st.session_state["_model"] = t["model"]
        st.session_state["_temperature"] = t["temperature"]
        st.session_state.input_fields = []
        for inp in t.get("inputs", []):
            st.session_state.input_fields.append({
                "key": inp["key"],
                "label": inp["label"],
                "type": inp["type"],
                "required": bool(inp.get("required", 0)),
                "placeholder": inp.get("placeholder", ""),
                "options": inp.get("select_options", ""),
            })
        st.session_state["_loaded"] = True
elif not is_edit:
    # On first visit, ensure clean state.  On reruns (e.g. after button click)
    # let Streamlit preserve widget values via the `key` parameter.
    if not st.session_state.get("_initialized", False):
        st.session_state._initialized = True
        for key in ["_name", "_description", "_system_prompt", "_model", "_temperature", "_loaded"]:
            st.session_state.pop(key, None)
        st.session_state.input_fields = []

# --- Template Metadata Form ---
name = st.text_input("Template Name *", key="_name")
description = st.text_area("Description", key="_description")
system_prompt = st.text_area(
    "System Prompt",
    height=200,
    help="Use {{variable_name}} for placeholders",
    key="_system_prompt",
)

saved_model_id = st.session_state.get("_model", "")
model_index = 0
if saved_model_id:
    for i, m in enumerate(AVAILABLE_MODELS):
        if m["id"] == saved_model_id:
            model_index = i
            break

model = st.selectbox(
    "Model",
    options=AVAILABLE_MODELS,
    format_func=lambda m: m["label"],
    index=model_index,
)

temperature = st.slider(
    "Temperature",
    0.0,
    2.0,
    0.7,
    0.05,
    key="_temperature",
)

# --- Dynamic Input Fields Builder ---
st.subheader("Input Fields")
st.caption("Define the variables users will fill in when running this template.")

for i, field in enumerate(st.session_state.input_fields):
    with st.container(border=True):
        st.write(f"**Field {i + 1}**")
        cols = st.columns([1, 1, 1, 0.5])
        with cols[0]:
            field["key"] = st.text_input(
                "Key (variable name)",
                value=field["key"],
                key=f"key_{i}",
            )
        with cols[1]:
            field["label"] = st.text_input(
                "Label",
                value=field["label"],
                key=f"label_{i}",
            )
        with cols[2]:
            FIELD_TYPES = ["TEXT", "TEXTAREA", "IMAGE", "FILE", "NUMBER", "BOOLEAN", "SELECT"]
            type_index = FIELD_TYPES.index(field["type"]) if field["type"] in FIELD_TYPES else 0
            field["type"] = st.selectbox(
                "Type",
                FIELD_TYPES,
                index=type_index,
                key=f"type_{i}",
            )
        with cols[3]:
            field["required"] = st.checkbox(
                "Required",
                value=field["required"],
                key=f"req_{i}",
            )

        if field["type"] in ("TEXT", "TEXTAREA"):
            field["placeholder"] = st.text_input(
                "Placeholder",
                value=field.get("placeholder", ""),
                key=f"ph_{i}",
            )

        if field["type"] == "SELECT":
            field["options"] = st.text_area(
                "Options (one per line)",
                value=field.get("options", ""),
                key=f"opt_{i}",
            )

        if st.button("Remove", key=f"remove_{i}"):
            st.session_state.input_fields.pop(i)
            st.rerun()

if st.button("+ Add Input Field"):
    st.session_state.input_fields.append(
        {"key": "", "label": "", "type": "TEXT", "required": False, "placeholder": "", "options": ""}
    )
    st.rerun()

# --- Save ---
if st.button("Save Template", type="primary"):
    errors = []

    if not name.strip():
        errors.append("Template name is required.")

    keys = [f["key"].strip() for f in st.session_state.input_fields if f["key"].strip()]
    if len(keys) != len(set(keys)):
        errors.append("Input field keys must be unique.")

    for f in st.session_state.input_fields:
        if not f["key"].strip():
            errors.append("All input fields must have a key.")
            break

    if errors:
        for err in errors:
            st.error(err)
    else:
        model_id = model["id"] if isinstance(model, dict) else model
        inputs = []
        for i, f in enumerate(st.session_state.input_fields):
            select_options = ""
            if f["type"] == "SELECT":
                select_options = "\n".join(
                    ln.strip()
                    for ln in f.get("options", "").strip().split("\n")
                    if ln.strip()
                )
            inputs.append({
                "key": f["key"].strip(),
                "label": f["label"].strip(),
                "type": f["type"],
                "required": 1 if f["required"] else 0,
                "placeholder": f.get("placeholder", ""),
                "select_options": select_options,
                "sort_order": i,
            })

        if is_edit:
            st.session_state.pop("_edit_tid", None)
            update_template(
                int(template_id),
                name.strip(),
                description.strip(),
                system_prompt.strip(),
                model_id,
                temperature,
                inputs,
            )
            st.success("Template updated!")
        else:
            create_template(
                name.strip(),
                description.strip(),
                system_prompt.strip(),
                model_id,
                temperature,
                inputs,
            )
            st.success("Template created!")

        # Clear all template editing state so it doesn't leak into future Create visits
        for k in ["_name", "_description", "_system_prompt", "_model", "_temperature", "_loaded"]:
            st.session_state.pop(k, None)
        st.session_state.input_fields = []
        st.switch_page("pages/pt_home.py")

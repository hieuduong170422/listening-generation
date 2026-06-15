import re
import streamlit as st
from prompt_template.template_store import create_template, get_template, update_template, set_flow_bindings, list_templates
from prompt_template.llm_client import (PROVIDER_FRIENDLY,
    get_output_type, filter_models_by_sdk_type, get_sdk_output_types,
    _get_provider)

st.title("➕ Tạo / Sửa Template")

# Template ID được truyền qua session_state bởi nút Sửa.
# Phải đọc TRƯỚC lần rerun đầu tiên để is_edit ổn định.
template_id = st.session_state.get("_edit_tid")
is_edit = template_id is not None

if "input_fields" not in st.session_state:
    st.session_state.input_fields = []
if "_flow_bindings" not in st.session_state:
    st.session_state._flow_bindings = []

if is_edit and st.session_state.get("_loaded_tid") != template_id:
    t = get_template(int(template_id))
    if t:
        st.session_state["_name"] = t["name"]
        st.session_state["_description"] = t.get("description", "")
        st.session_state["_system_prompt"] = t.get("system_prompt", "")
        st.session_state["_model"] = t["model"]
        # Suy ra SDK và output type cho cascade
        raw_provider = _get_provider(t["model"])
        if raw_provider:
            friendly_sdk = PROVIDER_FRIENDLY.get(raw_provider, "Unknown")
            st.session_state["_cascade_sdk"] = friendly_sdk
            output_type_derived = get_output_type(t["model"])
            st.session_state["_cascade_type"] = output_type_derived
            # Khởi tạo giá trị prev để logic reset cascade không kích hoạt ở lần render đầu
            st.session_state["_prev_cascade_sdk"] = friendly_sdk
            st.session_state["_prev_cascade_type"] = output_type_derived
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
        st.session_state["_is_flow"] = t.get("is_flow", 0)
        st.session_state["_flow_bindings"] = [
            {"sub_template_id": b["sub_template_id"], "output_key": b["output_key"]}
            for b in t.get("flow_bindings", [])
        ]
        st.session_state["_loaded_tid"] = template_id
elif not is_edit:
    # Lần đầu vào: đảm bảo state sạch. Khi rerun (vd sau click nút)
    # để Streamlit giữ giá trị widget qua tham số `key`.
    if not st.session_state.get("_initialized", False):
        st.session_state._initialized = True
        for key in ["_name", "_description", "_system_prompt", "_model", "_temperature", "_loaded_tid", "_cascade_sdk", "_cascade_type", "_cascade_model", "_prev_cascade_sdk", "_prev_cascade_type", "_is_flow", "_flow_bindings"]:
            st.session_state.pop(key, None)
        st.session_state["_is_flow"] = False
        st.session_state["_flow_bindings"] = []
        st.session_state.input_fields = []
        st.session_state["_temperature"] = 0.7

# Cảnh báo model không còn tồn tại khi đang sửa
if is_edit and st.session_state.get("_model", ""):
    saved_model_id = st.session_state["_model"]
    raw_provider = _get_provider(saved_model_id)
    if raw_provider is None:
        st.warning(f"Model '{saved_model_id}' không còn khả dụng. Hãy chọn model khác bên dưới.")
        st.text_input("Model hiện tại (chỉ đọc)", value=saved_model_id, disabled=True)

# --- Form thông tin template ---
name = st.text_input("Tên template *", key="_name")
description = st.text_area("Mô tả", key="_description")
system_prompt = st.text_area(
    "System Prompt",
    height=200,
    help="Dùng {{tên_biến}} cho chỗ điền động",
    key="_system_prompt",
)

_PROVIDER_EMOJI = {
    "google-genai": "🟢",
    "dashscope": "🔵",
    "openai": "🟣",
    "elevenlabs": "🔊",
}

# ── Bước 1: Chọn SDK ────────────────────────────────
SDK_OPTIONS = ["Google Gemini", "DashScope", "OpenAI", "ElevenLabs"]
sdk = st.selectbox("SDK", options=SDK_OPTIONS, key="_cascade_sdk")

# Cascade reset: đổi SDK → reset Output Type và Model
if sdk != st.session_state.get("_prev_cascade_sdk"):
    st.session_state.pop("_cascade_type", None)
    st.session_state.pop("_cascade_model", None)
    st.session_state["_prev_cascade_sdk"] = sdk
    st.rerun()

# ── Bước 2: Chọn Output Type ─────────────────────────
output_types = get_sdk_output_types(sdk)
output_type = st.selectbox("Loại output", options=output_types, key="_cascade_type")

# Cascade reset: đổi Output Type → reset Model
if output_type != st.session_state.get("_prev_cascade_type"):
    st.session_state.pop("_cascade_model", None)
    st.session_state["_prev_cascade_type"] = output_type
    st.rerun()

# ── Bước 3: Chọn Model ───────────────────────────────
models = filter_models_by_sdk_type(sdk, output_type)
saved_model_id = st.session_state.get("_model", "")
model_index = 0
if saved_model_id:
    for i, m in enumerate(models):
        if m["id"] == saved_model_id:
            model_index = i
            break
model = st.selectbox(
    "Model",
    options=models if models else ["Không có model"],
    format_func=lambda m: f"{_PROVIDER_EMOJI.get(m.get('provider', ''), '')} {m['label']}" if isinstance(m, dict) else m,
    index=model_index if models else 0,
    key="_cascade_model",
)
if not models:
    st.warning("Không có model nào khớp tổ hợp SDK và Loại output đã chọn.")

temperature = st.slider(
    "Temperature",
    min_value=0.0,
    max_value=2.0,
    step=0.05,
    key="_temperature",
)

# --- Cấu hình Flow Template ---
st.divider()
is_flow = st.checkbox(
    "Flow Template",
    key="_is_flow",
    help="Khi bật, các {{placeholder}} của template này có thể được điền bằng output của sub-template. "
         "Sub-template chạy trước, rồi output của chúng được nối vào template này.",
)

if st.session_state.get("_is_flow", False):
    st.subheader("Sub-Template")

    all_templates = list_templates()
    current_id = st.session_state.get("_edit_tid")

    for i, binding in enumerate(st.session_state._flow_bindings):
        with st.container(border=True):
            st.write(f"**Sub-Template {i + 1}**")
            cols = st.columns([2, 2, 0.5])
            with cols[0]:
                exclude_ids = set()
                if current_id:
                    exclude_ids.add(int(current_id))
                for j, other in enumerate(st.session_state._flow_bindings):
                    if j != i and other.get("sub_template_id"):
                        exclude_ids.add(int(other["sub_template_id"]))

                options = [t for t in all_templates if t["id"] not in exclude_ids]
                opt_map = {t["id"]: t["name"] for t in options}
                selected_id = binding.get("sub_template_id")

                selected = st.selectbox(
                    "Template",
                    options=list(opt_map.keys()),
                    format_func=lambda x: opt_map[x],
                    index=list(opt_map.keys()).index(selected_id) if selected_id in opt_map else 0,
                    key=f"flow_sub_{i}",
                )
                binding["sub_template_id"] = selected
            with cols[1]:
                binding["output_key"] = st.text_input(
                    "Biến output ({{key}})",
                    value=binding.get("output_key", ""),
                    key=f"flow_key_{i}",
                )
            with cols[2]:
                if st.button("✕", key=f"flow_rm_{i}"):
                    st.session_state._flow_bindings.pop(i)
                    st.rerun()

            if binding.get("sub_template_id"):
                sub = get_template(binding["sub_template_id"])
                if sub:
                    with st.expander(f"Input của '{sub['name']}'"):
                        if sub.get("inputs"):
                            for field in sub["inputs"]:
                                st.caption(
                                    f"**{field['key']}** ({field['type']}): "
                                    f"{field['label']}"
                                    + (" *bắt buộc" if field.get("required") else "")
                                )
                        else:
                            st.caption("Không có input field")

    if st.button("+ Thêm Sub-Template"):
        st.session_state._flow_bindings.append({"sub_template_id": None, "output_key": ""})
        st.rerun()

# --- Trình tạo Input Field động ---
st.subheader("Input Fields")
st.caption("Khai báo các biến mà người dùng sẽ điền khi chạy template.")

for i, field in enumerate(st.session_state.input_fields):
    with st.container(border=True):
        st.write(f"**Field {i + 1}**")
        cols = st.columns([1.5, 1.5, 1.5, 0.5])
        with cols[0]:
            field["key"] = st.text_input(
                "Key (tên biến)",
                value=field["key"],
                key=f"key_{i}",
            )
        with cols[1]:
            field["label"] = st.text_input(
                "Nhãn",
                value=field["label"],
                key=f"label_{i}",
            )
        with cols[2]:
            FIELD_TYPES = ["TEXT", "TEXTAREA", "IMAGE", "FILE", "NUMBER", "BOOLEAN", "SELECT"]
            type_index = FIELD_TYPES.index(field["type"]) if field["type"] in FIELD_TYPES else 0
            field["type"] = st.selectbox(
                "Kiểu",
                FIELD_TYPES,
                index=type_index,
                key=f"type_{i}",
            )
        with cols[3]:
            field["required"] = st.checkbox(
                "Bắt buộc",
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
                "Lựa chọn (mỗi dòng một mục)",
                value=field.get("options", ""),
                key=f"opt_{i}",
            )

        if st.button("Xoá field", key=f"remove_{i}"):
            st.session_state.input_fields.pop(i)
            st.rerun()

if st.button("+ Thêm Input Field"):
    st.session_state.input_fields.append(
        {"key": "", "label": "", "type": "TEXT", "required": False, "placeholder": "", "options": ""}
    )
    st.rerun()

# --- Lưu ---
if st.button("Lưu Template", type="primary"):
    errors = []

    if not name.strip():
        errors.append("Tên template là bắt buộc.")

    keys = [f["key"].strip() for f in st.session_state.input_fields if f["key"].strip()]
    if len(keys) != len(set(keys)):
        errors.append("Key của các input field phải là duy nhất.")

    for f in st.session_state.input_fields:
        if not f["key"].strip():
            errors.append("Mọi input field đều phải có key.")
            break

    is_flow_checked = st.session_state.get("_is_flow", False)
    if is_flow_checked:
        seen_keys = set()
        for b in st.session_state._flow_bindings:
            key = b.get("output_key", "").strip()
            if not key:
                errors.append("Mỗi sub-template phải có tên biến output.")
                break
            if not re.match(r"^\w+$", key):
                errors.append(f"Biến output '{key}' không hợp lệ. Chỉ dùng chữ, số, gạch dưới.")
                break
            if key in seen_keys:
                errors.append(f"Biến output '{key}' bị trùng. Mỗi key output phải là duy nhất.")
                break
            if not b.get("sub_template_id"):
                errors.append("Mỗi sub-template phải chọn một template.")
                break
            seen_keys.add(key)

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

        is_flow_val = 1 if st.session_state.get("_is_flow", False) else 0

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
                output_type=output_type,
                is_flow=is_flow_val,
            )
            tid = int(template_id)
        else:
            tid = create_template(
                name.strip(),
                description.strip(),
                system_prompt.strip(),
                model_id,
                temperature,
                inputs,
                output_type=output_type,
                is_flow=is_flow_val,
            )

        if is_flow_val:
            bindings = [
                {"sub_template_id": int(b["sub_template_id"]), "output_key": b["output_key"].strip()}
                for b in st.session_state._flow_bindings
                if b.get("sub_template_id") and b.get("output_key", "").strip()
            ]
            set_flow_bindings(tid, bindings)

        st.success("Đã cập nhật template!" if is_edit else "Đã tạo template!")

        # Xoá toàn bộ state đang sửa để không rò sang lần Tạo sau
        for k in ["_name", "_description", "_system_prompt", "_model", "_temperature", "_loaded_tid", "_cascade_sdk", "_cascade_type", "_cascade_model", "_prev_cascade_sdk", "_prev_cascade_type", "_is_flow", "_flow_bindings"]:
            st.session_state.pop(k, None)
        st.session_state.input_fields = []
        st.switch_page("views/prompt_template/home.py")

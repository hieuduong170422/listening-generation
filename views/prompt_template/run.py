"""Chạy Template — chọn template, điền field, gọi model, xem kết quả."""

import os

import streamlit as st

from prompt_template.llm_client import generate, get_output_type
from prompt_template.history_store import save_execution
from prompt_template.template_store import get_template, list_templates
from prompt_template.flow_engine import get_flow_input_groups, execute_flow, replace_variables
from prompt_template.elevenlabs_client import get_cached_voices, update_voice_cache, get_client as el_get_client

st.title("▶️ Chạy Prompt Template")

# ── Bộ chọn template ───────────────────────────────────────────────────────

templates = list_templates()
if not templates:
    st.info("Chưa có template nào. Hãy tạo template trước!")
    if st.button("+ Tạo template"):
        st.switch_page("views/prompt_template/create.py")
    st.stop()

template_options = {t["name"]: t["id"] for t in templates}

# Chọn sẵn template khi đến từ nút ▶️ ở trang Danh sách.
# Lưu index vào session state để giữ qua các lần rerun.
if "_run_tid" in st.session_state:
    run_tid = st.session_state.pop("_run_tid")
    for i, (name, tid) in enumerate(template_options.items()):
        if tid == run_tid:
            st.session_state._run_default_index = i
            break

default_index = st.session_state.get("_run_default_index", 0)

selected_name = st.selectbox(
    "Chọn template",
    options=list(template_options.keys()),
    index=default_index,
)

if not selected_name:
    st.stop()

template_id = template_options[selected_name]
template = get_template(template_id)

if not template:
    st.error("Không tìm thấy template.")
    st.stop()

is_flow = template.get("is_flow", 0)

system_prompt = template.get("system_prompt", "")
prompt_preview = system_prompt[:200]
if len(system_prompt) > 200:
    prompt_preview += "…"
st.markdown(f"**System Prompt:** `{prompt_preview}`")

# ── Hàm render field ───────────────────────────────────────────────────────


def _render_field(field, skey, group_values, group_files):
    label = field["label"]
    required = bool(field.get("required", 0))
    placeholder = field.get("placeholder", "")
    ftype = field["type"]

    if ftype == "TEXT":
        val = st.text_input(label, key=skey, placeholder=placeholder, help="Bắt buộc" if required else "")
        group_values[field["key"]] = val

    elif ftype == "TEXTAREA":
        val = st.text_area(label, key=skey, placeholder=placeholder, help="Bắt buộc" if required else "")
        group_values[field["key"]] = val

    elif ftype == "IMAGE":
        uploaded = st.file_uploader(label, key=skey, type=["png", "jpg", "jpeg", "gif", "webp"],
                                    help="Bắt buộc" if required else "")
        if uploaded:
            file_path = os.path.join("uploads", uploaded.name)
            with open(file_path, "wb") as f:
                f.write(uploaded.getbuffer())
            group_files.append(file_path)
            group_values[field["key"]] = f"[Image: {uploaded.name}]"

    elif ftype == "FILE":
        uploaded = st.file_uploader(label, key=skey, help="Bắt buộc" if required else "")
        if uploaded:
            file_path = os.path.join("uploads", uploaded.name)
            with open(file_path, "wb") as f:
                f.write(uploaded.getbuffer())
            group_files.append(file_path)
            group_values[field["key"]] = f"[File: {uploaded.name}]"

    elif ftype == "NUMBER":
        val = st.number_input(label, key=skey, help="Bắt buộc" if required else "")
        group_values[field["key"]] = str(val)

    elif ftype == "BOOLEAN":
        val = st.checkbox(label, key=skey)
        group_values[field["key"]] = str(val)

    elif ftype == "SELECT":
        options_raw = field.get("select_options", "")
        options = [ln.strip() for ln in options_raw.split("\n") if ln.strip()] if options_raw else []
        if options:
            val = st.selectbox(label, options, key=skey)
        else:
            val = st.selectbox(label, ["(không có lựa chọn)"], key=skey)
        group_values[field["key"]] = val

    return skey


# ── Render form động ───────────────────────────────────────────────────────

st.subheader("Giá trị đầu vào")

if is_flow:
    input_groups = get_flow_input_groups(template["id"])
    if not input_groups:
        st.info("Flow template này chưa có ràng buộc sub-template nào.")

    user_values_by_group = {}

    for group in input_groups:
        path_str = "__".join(group["path"])
        st.markdown(f"**{group['path_display']}** - *{group['template_name']}*")
        with st.container(border=True):
            group_values = {}
            group_files = []
            for field in group["inputs"]:
                skey = f"inp_{path_str}_{field['id']}"
                _render_field(field, skey, group_values, group_files)
            group_values["_files"] = group_files
            user_values_by_group[path_str] = group_values

    if template.get("inputs"):
        st.markdown("**Input của template chính**")
        with st.container(border=True):
            main_values = {}
            main_files = []
            for field in template["inputs"]:
                skey = f"inp_main_{field['id']}"
                _render_field(field, skey, main_values, main_files)
            main_values["_files"] = main_files
            user_values_by_group["_main"] = main_values

    st.session_state._flow_user_values = user_values_by_group

else:
    user_values = {}
    uploaded_files = []

    for field in template.get("inputs", []):
        skey = f"field_{field['id']}"
        _render_field(field, skey, user_values, uploaded_files)

    st.session_state._user_values = user_values
    st.session_state._uploaded_files = uploaded_files

# ── Cấu hình model Video ───────────────────────────────────────────────────
if template["model"].startswith(("veo", "wan")):
    st.subheader("🎬 Cấu hình Video")
    video_size = st.text_input(
        "Kích thước (rộng*cao)",
        value="1280*720",
        key="_video_size",
        help="Độ phân giải video. Chỉ dùng cho model DashScope/Wan.",
    )
    video_duration = st.number_input(
        "Thời lượng (giây)",
        min_value=1,
        max_value=60,
        value=5,
        key="_video_duration",
        help="Thời lượng video tính bằng giây.",
    )
else:
    video_size = "1280*720"
    video_duration = 5

# ── Cấu hình TTS ───────────────────────────────────────────────────────────
output_type = get_output_type(template["model"])
voice = "Puck"  # mặc định cho Gemini TTS
language = "Auto"
voice_id = None
if output_type == "audio" and not template["model"].startswith("eleven_"):
    st.subheader("🔊 Cấu hình TTS")
    if template["model"].startswith("qwen"):
        voice_options = ["Cherry", "Serena", "Ethan", "Stella", "Moon", "Kai"]
        default_voice = "Cherry"
    elif "tts" in template["model"]:
        voice_options = ["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse", "marin", "cedar"]
        default_voice = "alloy"
    else:
        voice_options = ["Puck", "Charon", "Kore", "Fenrir", "Aoede"]
        default_voice = "Puck"
    voice = st.selectbox(
        "Giọng",
        options=voice_options,
        index=voice_options.index(default_voice),
        key="_tts_voice",
    )
    language = st.selectbox(
        "Ngôn ngữ",
        options=["Auto", "vi-VN", "en-US", "zh-CN", "ja-JP", "ko-KR"],
        key="_tts_language",
    )


# ── Cấu hình ElevenLabs TTS ──────────────────────────────────────────
if template["model"].startswith("eleven_"):
    st.subheader("🔊 Cấu hình ElevenLabs TTS")

    if "_elevenlabs_voices_fetched" not in st.session_state:
        st.session_state._elevenlabs_voices_fetched = False
        st.session_state._elevenlabs_fetch_error = None

    if not st.session_state._elevenlabs_voices_fetched:
        voices = get_cached_voices()
        if not voices:
            with st.spinner("Đang tải danh sách giọng ElevenLabs..."):
                try:
                    client = el_get_client()
                    update_voice_cache(client)
                    st.session_state._elevenlabs_voices_fetched = True
                    st.rerun()
                except Exception as e:
                    st.session_state._elevenlabs_fetch_error = str(e)
                    st.session_state._elevenlabs_voices_fetched = True
        else:
            st.session_state._elevenlabs_voices_fetched = True

    if st.session_state.get("_elevenlabs_fetch_error"):
        st.warning(f"Không lấy được danh sách giọng: {st.session_state._elevenlabs_fetch_error}. Nhập Voice ID thủ công bên dưới.")

    voice_id = "JBFqnCBsd6RMkjVDRZzb"  # Rachel mặc định
    voices = get_cached_voices()
    if voices:
        voice_options = {v["name"]: v["voice_id"] for v in voices if v.get("voice_id")}
        if voice_options:
            default_voice_name = "Rachel" if "Rachel" in voice_options else list(voice_options.keys())[0]
            selected_voice_name = st.selectbox(
                "Giọng",
                options=list(voice_options.keys()),
                index=list(voice_options.keys()).index(default_voice_name),
                key="_eleven_voice_name",
            )
            voice_id = voice_options[selected_voice_name]
        else:
            voice_id = st.text_input("Voice ID", value="JBFqnCBsd6RMkjVDRZzb", key="_eleven_voice_id_manual",
                help="Nhập Voice ID của ElevenLabs. Bấm 'Cập nhật danh sách giọng' để tải.")
            st.warning("Danh sách giọng trống. Bấm 'Cập nhật danh sách giọng' để tải từ ElevenLabs.")
    else:
        voice_id = st.text_input("Voice ID", value="JBFqnCBsd6RMkjVDRZzb", key="_eleven_voice_id_empty",
            help="Nhập Voice ID của ElevenLabs. Bấm 'Cập nhật danh sách giọng' để tải.")

    if st.button("🔄 Cập nhật danh sách giọng", key="_eleven_update_voices"):
        with st.spinner("Đang cập nhật danh sách giọng..."):
            try:
                client = el_get_client()
                count = update_voice_cache(client)
                st.session_state._elevenlabs_voices_fetched = True
                st.session_state._elevenlabs_fetch_error = None
                st.rerun()
            except Exception as ex:
                st.error(f"Cập nhật danh sách giọng thất bại: {ex}")

    language_code = st.selectbox(
        "Ngôn ngữ (ISO 639-1)",
        options=["", "en", "vi", "es", "fr", "de", "it", "pt", "pl", "tr", "ja", "ko", "zh", "ar", "hi"],
        index=2,
        key="_eleven_language",
        help="Mã ngôn ngữ tuỳ chọn cho output TTS.",
    )

    col1, col2 = st.columns(2)
    with col1:
        stability = st.slider("Độ ổn định", 0.0, 1.0, 0.5, key="_eleven_stability",
            help="Thấp=nhiều cảm xúc, Cao=ổn định hơn")
        style = st.slider("Cường điệu phong cách", 0.0, 1.0, 0.0, key="_eleven_style",
            help="Khuếch đại phong cách giọng gốc. Giá trị cao tăng độ trễ.")
    with col2:
        similarity_boost = st.slider("Tăng độ giống", 0.0, 1.0, 0.75, key="_eleven_similarity",
            help="Mức bám sát giọng gốc")
        use_speaker_boost = st.checkbox("Speaker Boost", value=False, key="_eleven_speaker_boost",
            help="Tăng độ giống giọng gốc (độ trễ cao hơn một chút)")

    with st.expander("Cấu hình nâng cao"):
        speed = st.slider("Tốc độ", 0.5, 2.0, 1.0, key="_eleven_speed",
            help="Tốc độ nói. 1.0=bình thường")

# ── Nút chạy ────────────────────────────────────────────────────────────────

if st.button("🚀 Chạy", type="primary"):
    if is_flow:
        user_values_by_group = st.session_state.get("_flow_user_values", {})
        errors = []

        for group in input_groups:
            path_str = "__".join(group["path"])
            group_data = user_values_by_group.get(path_str, {})
            for field in group["inputs"]:
                if field.get("required") and not str(group_data.get(field["key"], "")).strip():
                    errors.append(f"'{field['label']}' ({group['path_display']}) là bắt buộc.")

        if template.get("inputs"):
            main_data = user_values_by_group.get("_main", {})
            for field in template["inputs"]:
                if field.get("required") and not str(main_data.get(field["key"], "")).strip():
                    errors.append(f"'{field['label']}' (template chính) là bắt buộc.")

        if errors:
            for err in errors:
                st.error(err)
        else:
            with st.spinner("Đang chạy flow..."):
                try:
                    result = execute_flow(template, user_values_by_group)

                    st.subheader("Kết quả")
                    if result["type"] == "text":
                        st.markdown(result["text"])
                    elif result["type"] == "image":
                        img_src = result.get("response_data") or result["text"]
                        st.image(img_src)
                    elif result["type"] == "video":
                        vid_src = result.get("response_data") or result["text"]
                        st.video(vid_src)
                    elif result["type"] == "audio":
                        aud_src = result.get("response_data") or result["text"]
                        st.audio(aud_src)
                        audio_path = result.get("response_data")
                        if audio_path and os.path.exists(audio_path):
                            with open(audio_path, "rb") as f:
                                st.download_button(
                                    label="Tải audio",
                                    data=f.read(),
                                    file_name=os.path.basename(audio_path),
                                    mime="audio/mpeg" if audio_path.endswith(".mp3") else "audio/wav",
                                )
                    else:
                        st.text(result["text"])

                    st.caption(
                        f"Model: {template['model']} | "
                        f"Temperature: {template['temperature']}"
                    )

                    save_execution(
                        template_id=template_id,
                        template_name=template["name"],
                        inputs_dict={
                            "flow_run": True,
                            "user_values_by_group": {
                                k: {kk: vv for kk, vv in v.items() if kk != "_files"}
                                for k, v in user_values_by_group.items()
                            },
                        },
                        response_text=result["text"],
                        response_type=result["type"],
                        response_data=result.get("response_data", ""),
                        model=template["model"],
                        temperature=template["temperature"],
                    )
                    st.success("Đã lưu vào lịch sử.")

                except ValueError as e:
                    st.error(str(e))
                except RuntimeError as e:
                    st.error(f"Lỗi API: {e}")
                except Exception as e:
                    st.error(f"Lỗi không xác định: {e}")

    else:
        errors = []
        for field in template.get("inputs", []):
            if field.get("required") and not st.session_state._user_values.get(field["key"], "").strip():
                errors.append(f"'{field['label']}' là bắt buộc.")

        if errors:
            for err in errors:
                st.error(err)
        else:
            user_prompt = replace_variables(
                template.get("system_prompt", ""), st.session_state._user_values
            )

            stability = st.session_state.get("_eleven_stability", 0.5)
            similarity_boost = st.session_state.get("_eleven_similarity", 0.75)
            style = st.session_state.get("_eleven_style", 0.0)
            use_speaker_boost = st.session_state.get("_eleven_speaker_boost", False)
            speed = st.session_state.get("_eleven_speed", 1.0)
            language_code = st.session_state.get("_eleven_language", "vi")

            with st.spinner("Đang gọi model..."):
                try:
                    result = generate(
                        system_prompt=template.get("system_prompt", ""),
                        user_prompt=user_prompt,
                        model=template["model"],
                        temperature=template["temperature"],
                        files=st.session_state._uploaded_files if st.session_state._uploaded_files else None,
                        size=video_size,
                        duration=video_duration,
                        voice_name=voice,
                        voice=voice,
                        language=language,
                        voice_id=voice_id if template["model"].startswith("eleven_") else None,
                        stability=stability if template["model"].startswith("eleven_") else None,
                        similarity_boost=similarity_boost if template["model"].startswith("eleven_") else None,
                        style=style if template["model"].startswith("eleven_") else None,
                        use_speaker_boost=use_speaker_boost if template["model"].startswith("eleven_") else None,
                        speed=speed if template["model"].startswith("eleven_") else None,
                        language_code=language_code if template["model"].startswith("eleven_") else None,
                    )

                    # ── Hiển thị kết quả ──
                    st.subheader("Kết quả")
                    if result["type"] == "text":
                        st.markdown(result["text"])
                    elif result["type"] == "image":
                        img_src = result.get("response_data") or result["text"]
                        st.image(img_src)
                    elif result["type"] == "video":
                        vid_src = result.get("response_data") or result["text"]
                        st.video(vid_src)
                    elif result["type"] == "audio":
                        aud_src = result.get("response_data") or result["text"]
                        st.audio(aud_src)
                        audio_path = result.get("response_data")
                        if audio_path and os.path.exists(audio_path):
                            with open(audio_path, "rb") as f:
                                audio_bytes = f.read()
                            st.download_button(
                                label="Tải audio",
                                data=audio_bytes,
                                file_name=os.path.basename(audio_path),
                                mime="audio/mpeg" if audio_path.endswith(".mp3") else "audio/wav",
                            )
                    else:
                        st.text(result["text"])

                    st.caption(
                        f"Model: {template['model']} | "
                        f"Temperature: {template['temperature']}"
                    )

                    # ── Lưu lịch sử ──
                    save_execution(
                        template_id=template_id,
                        template_name=template["name"],
                        inputs_dict=st.session_state._user_values,
                        response_text=result["text"],
                        response_type=result["type"],
                        response_data=result.get("response_data", ""),
                        model=template["model"],
                        temperature=template["temperature"],
                    )
                    st.success("Đã lưu vào lịch sử.")

                except ValueError as e:
                    st.error(str(e))
                except RuntimeError as e:
                    st.error(f"Lỗi API: {e}")
                except Exception as e:
                    st.error(f"Lỗi không xác định: {e}")

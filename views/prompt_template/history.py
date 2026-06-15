import os
import streamlit as st
import json
from prompt_template.history_store import list_history, get_history_entry, delete_history

st.title("📜 Lịch sử chạy")

entries = list_history()

if entries:
    col1, col2 = st.columns([6, 1])
    with col2:
        with st.popover("🗑️ Xoá tất cả"):
            st.warning("Xoá TOÀN BỘ lịch sử chạy? Không thể hoàn tác.")
            if st.button("Xác nhận xoá tất cả", type="primary"):
                for e in entries:
                    delete_history(e["id"])
                st.rerun()

if not entries:
    st.info("Chưa có lịch sử chạy. Chạy một template để thấy kết quả ở đây.")
    st.stop()

for entry in entries:
    with st.container(border=True):
        col1, col2, col3, col4 = st.columns([2.5, 1.5, 1, 0.5])

        with col1:
            st.write(f"**{entry['template_name']}**")
            st.caption(entry.get("created_at", ""))

        with col2:
            st.write(f"Model: {entry['model']}")
            st.write(f"Loại: {entry['response_type']}")

        with col3:
            try:
                inputs = json.loads(entry.get("inputs_json", "{}"))
                st.write(f"Input: {len(inputs)} trường")
            except (json.JSONDecodeError, TypeError):
                st.write("Input: -")

        with col4:
            with st.popover("🗑️", key=f"del_pop_{entry['id']}"):
                st.warning(f"Xoá mục của '{entry['template_name']}'?")
                if st.button("Xác nhận xoá", key=f"confirm_del_{entry['id']}"):
                    delete_history(entry["id"])
                    st.rerun()

        with st.expander("Xem chi tiết"):
            st.write("**Input:**")
            try:
                inputs = json.loads(entry.get("inputs_json", "{}"))
                st.json(inputs)
            except (json.JSONDecodeError, TypeError):
                st.write(entry.get("inputs_json", ""))

            st.write("**Kết quả:**")
            response_text = entry.get("response_text", "")
            response_type = entry.get("response_type", "text")
            response_data = entry.get("response_data", "")

            if response_type == "image":
                img_src = response_data or response_text
                st.image(img_src)
            elif response_type == "video":
                vid_src = response_data or response_text
                st.video(vid_src)
            elif response_type == "audio":
                aud_src = response_data or response_text
                st.audio(aud_src)
                if response_data and os.path.exists(response_data):
                    with open(response_data, "rb") as f:
                        audio_bytes = f.read()
                    st.download_button(
                        label="Tải audio",
                        data=audio_bytes,
                        file_name=os.path.basename(response_data),
                        mime="audio/wav",
                        key=f"download_audio_{entry['id']}",
                    )
            else:
                st.markdown(response_text if response_text else "*Không có nội dung*")

            st.write("**Metadata:**")
            st.json(
                {
                    "model": entry["model"],
                    "temperature": entry.get("temperature"),
                    "response_type": entry["response_type"],
                    "created_at": entry.get("created_at"),
                }
            )

"""Trang chủ — landing giới thiệu các công cụ trong workspace."""

import streamlit as st

st.title("🏠 Audivy Workspace")
st.markdown(
    "Workspace gồm **3 công cụ** độc lập. Chọn công cụ bên dưới hoặc dùng menu điều hướng bên trái."
)

st.write("")

col1, col2, col3 = st.columns(3, gap="large")

with col1:
    with st.container(border=True):
        st.subheader("🎧 Podcast Studio")
        st.markdown(
            "Sinh **kịch bản + audio/video** dạng podcast/luyện nghe.\n\n"
            "- Dàn ý & kịch bản hội thoại nhiều phần\n"
            "- Giọng đọc **Gemini TTS** hoặc **ElevenLabs**\n"
            "- Ghép ảnh minh hoạ + dựng video\n"
            "- Quản lý cài đặt TTS, giọng đọc"
        )
        if st.button("Mở Podcast Studio →", type="primary", use_container_width=True, key="_go_podcast"):
            st.switch_page("views/podcast/tts_studio.py")

with col2:
    with st.container(border=True):
        st.subheader("🧩 Prompt Template Engine")
        st.markdown(
            "Tạo & chạy **prompt template tái sử dụng** với biến `{{...}}` động.\n\n"
            "- SDK: Gemini / OpenAI / DashScope / ElevenLabs\n"
            "- Output: text, ảnh, video, audio\n"
            "- **Flow**: nối nhiều template với nhau\n"
            "- Lưu & xem lại lịch sử chạy"
        )
        if st.button("Mở Prompt Template Engine →", type="primary", use_container_width=True, key="_go_pt"):
            st.switch_page("views/prompt_template/home.py")

with col3:
    with st.container(border=True):
        st.subheader("🎬 Video Affiliate (UGC)")
        st.markdown(
            "Sinh **ảnh storyboard nhiều bước** (faceless) + **prompt** cho VEO/Omni.\n\n"
            "- Upload ảnh sản phẩm + ảnh scene tham khảo\n"
            "- Nhập N → ra N ảnh storyboard lưới các bước dùng SP\n"
            "- Mỗi ảnh kèm 1 prompt video UGC (EN) có cấu trúc\n"
            "- Tải ảnh + prompt để tạo clip review"
        )
        if st.button("Mở Video Affiliate →", type="primary", use_container_width=True, key="_go_affiliate"):
            st.switch_page("views/affiliate/generate.py")

st.divider()
st.caption("💡 Các công cụ dùng chung phiên đăng nhập và API key, nhưng dữ liệu (lịch sử, template) tách riêng.")

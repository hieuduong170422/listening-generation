"""Generate Video Affiliate (UGC) — ảnh sản phẩm + ảnh scene → N keyframe UGC + N prompt VEO/Omni."""

import streamlit as st
from google import genai

from podcast_studio.auth import get_api_key as _get_api_key
from podcast_studio.api_utils import is_hard_quota_error
from podcast_studio.affiliate import (
    TARGET_MODELS,
    DEFAULT_TARGET,
    DASHSCOPE_IMAGE_MODELS,
    DEFAULT_IMAGE_MODEL,
    generate_ugc_scene,
)


def _friendly_error(e: Exception) -> str:
    if is_hard_quota_error(e):
        return (
            "Hết quota Gemini cho model sinh ảnh. Key free tier **không sinh được ảnh** "
            "(hạn mức = 0). Hãy **bật billing** cho key tại https://aistudio.google.com/apikey "
            "(hoặc dùng key trả phí), rồi thử lại."
        )
    msg = str(e)
    return msg if len(msg) <= 300 else msg[:300] + "…"


def _get_client() -> genai.Client:
    api_key = _get_api_key()
    if not api_key:
        st.error("Chưa có API key. Nhập GEMINI_API_KEY trong .env hoặc ô 🔑 API Key ở sidebar.")
        st.stop()
    return genai.Client(api_key=api_key)


def _read_uploads(files) -> list[tuple[bytes, str]]:
    return [(f.getvalue(), f.type or "image/png") for f in (files or [])]


st.title("🎬 Generate Video Affiliate — UGC")
st.caption(
    "Upload **ảnh sản phẩm** + **ảnh scene** (screenshot TikTok) → sinh N **keyframe UGC không lộ mặt** "
    "kèm **prompt tiếng Anh** để bạn đưa vào VEO/Omni tạo video review."
)

# ── Bước 1: Ảnh đầu vào ────────────────────────────────────────────────────
st.subheader("1️⃣ Ảnh đầu vào")
c1, c2 = st.columns(2)
with c1:
    product_files = st.file_uploader(
        "Ảnh sản phẩm *",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="_ugc_product",
        help="Ảnh sản phẩm rõ nét, nhiều góc càng tốt.",
    )
    if product_files:
        st.image([f for f in product_files], width=90)
with c2:
    scene_files = st.file_uploader(
        "Ảnh scene tham khảo (screenshot TikTok)",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="_ugc_scenes",
        help="Tuỳ chọn — dùng làm gợi ý bối cảnh / bố cục / phong cách.",
    )
    if scene_files:
        st.image([f for f in scene_files], width=90)

from podcast_studio.affiliate import MAX_DASHSCOPE_IMAGES

_total_imgs = len(product_files or []) + len(scene_files or [])
st.caption(
    f"ℹ️ Model DashScope chỉ nhận tối đa **{MAX_DASHSCOPE_IMAGES} ảnh** tham chiếu/lần "
    "(ưu tiên ảnh sản phẩm trước, rồi tới ảnh scene)."
)
if _total_imgs > MAX_DASHSCOPE_IMAGES:
    st.warning(
        f"Bạn đã chọn {_total_imgs} ảnh — chỉ **{MAX_DASHSCOPE_IMAGES} ảnh đầu** được dùng. "
        "Bớt ảnh scene hoặc chỉ giữ ảnh sản phẩm quan trọng nhất để kết quả đúng ý hơn."
    )

# ── Bước 2: Cấu hình ───────────────────────────────────────────────────────
st.subheader("2️⃣ Cấu hình")
idea = st.text_area(
    "Mô tả sản phẩm / ý tưởng chiến dịch",
    key="_ugc_idea",
    height=80,
    placeholder="vd: serum dưỡng ẩm cho da khô, nhấn cảm giác thấm nhanh, hợp dân văn phòng...",
)
cc1, cc2, cc3 = st.columns(3)
with cc1:
    n = st.number_input("Số lượng output (N)", min_value=1, max_value=10, value=3, step=1, key="_ugc_n")
with cc2:
    image_model = st.selectbox(
        "Model sinh ảnh (DashScope)",
        options=list(DASHSCOPE_IMAGE_MODELS.keys()),
        index=list(DASHSCOPE_IMAGE_MODELS.keys()).index(DEFAULT_IMAGE_MODEL),
        format_func=lambda k: DASHSCOPE_IMAGE_MODELS[k],
        key="_ugc_image_model",
        help="Dùng key DASHSCOPE_API_KEY. Prompt video vẫn do Gemini sinh.",
    )
with cc3:
    target_model = st.selectbox(
        "Model video đích (để tối ưu prompt)",
        options=list(TARGET_MODELS.keys()),
        index=list(TARGET_MODELS.keys()).index(DEFAULT_TARGET),
        format_func=lambda k: TARGET_MODELS[k],
        key="_ugc_target",
    )

if st.button("🚀 Sinh keyframe + prompt", type="primary"):
    if not product_files:
        st.error("Cần ít nhất 1 ảnh sản phẩm.")
    else:
        product_images = _read_uploads(product_files)
        scene_images = _read_uploads(scene_files)
        client = _get_client()
        results = []
        total = int(n)
        progress = st.progress(0.0, text="Đang sinh...")
        for i in range(1, total + 1):
            progress.progress((i - 1) / total, text=f"Đang sinh scene {i}/{total}...")
            try:
                scene = generate_ugc_scene(
                    client,
                    product_images=product_images,
                    scene_images=scene_images,
                    idea=idea,
                    target_model=target_model,
                    scene_index=i,
                    total=total,
                    image_model=image_model,
                )
                results.append(scene)
            except Exception as e:
                results.append({"image": None, "prompt": None, "error": _friendly_error(e)})
                # Hết quota cứng → dừng luôn, không thử các scene còn lại cho đỡ tốn thời gian.
                if is_hard_quota_error(e):
                    progress.empty()
                    st.error(_friendly_error(e))
                    break
        progress.progress(1.0, text="Xong.")
        st.session_state["_ugc_results"] = results
        st.session_state["_ugc_target_done"] = target_model

# ── Bước 3: Kết quả ────────────────────────────────────────────────────────
results = st.session_state.get("_ugc_results")
if results:
    st.divider()
    st.subheader(f"3️⃣ Kết quả ({len(results)} scene)")
    st.caption(f"Prompt tối ưu cho: **{TARGET_MODELS.get(st.session_state.get('_ugc_target_done',''), '—')}**")

    for idx, scene in enumerate(results, start=1):
        with st.container(border=True):
            st.markdown(f"**Scene {idx}**")
            if scene.get("error"):
                st.error(f"Lỗi scene {idx}: {scene['error']}")
                continue
            icol, pcol = st.columns([1, 2])
            with icol:
                if scene.get("image"):
                    st.image(scene["image"], use_container_width=True)
                    st.download_button(
                        "⬇️ Tải ảnh",
                        data=scene["image"],
                        file_name=f"ugc_scene_{idx}.png",
                        mime="image/png",
                        key=f"_dl_img_{idx}",
                    )
            with pcol:
                st.markdown("**Prompt (EN):**")
                st.code(scene.get("prompt") or "", language="text")

    # Tải tất cả prompt
    all_prompts = "\n\n".join(
        f"# Scene {i}\n{s.get('prompt','')}" for i, s in enumerate(results, start=1) if s.get("prompt")
    )
    if all_prompts:
        st.download_button(
            "⬇️ Tải tất cả prompt (.txt)",
            data=all_prompts,
            file_name="ugc_prompts.txt",
            mime="text/plain",
            key="_dl_all_prompts",
        )
    st.info("Bước tiếp theo (ghép thành video) sẽ bổ sung sau.")

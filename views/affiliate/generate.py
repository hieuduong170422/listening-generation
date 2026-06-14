"""Generate Video Affiliate (UGC) — ảnh sản phẩm + scene → N ảnh storyboard nhiều bước + N prompt video."""

import streamlit as st
from google import genai

from podcast_studio.auth import get_api_key as _get_api_key
from podcast_studio.api_utils import is_hard_quota_error
from podcast_studio.affiliate import (
    TARGET_MODELS,
    DEFAULT_TARGET,
    DASHSCOPE_IMAGE_MODELS,
    DEFAULT_IMAGE_MODEL,
    MAX_DASHSCOPE_IMAGES,
    DEFAULT_PANELS,
    generate_ugc_storyboard,
    generate_video_veo,
)


def _friendly_error(e: Exception) -> str:
    if is_hard_quota_error(e):
        return (
            "Hết quota cho model AI. Nếu là Gemini: key free tier không sinh được ảnh — "
            "bật billing tại https://aistudio.google.com/apikey, hoặc dùng model ảnh DashScope."
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
    "Upload **ảnh sản phẩm** + **ảnh scene** tham khảo → sinh N **ảnh storyboard nhiều bước** "
    "(faceless, mỗi panel 1 bước dùng sản phẩm) kèm **prompt video tiếng Anh** để đưa vào VEO/Omni."
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
        "Ảnh scene tham khảo",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="_ugc_scenes",
        help="Tuỳ chọn — gợi ý bối cảnh / bố cục / phong cách.",
    )
    if scene_files:
        st.image([f for f in scene_files], width=90)

_total_imgs = len(product_files or []) + len(scene_files or [])
st.caption(
    f"ℹ️ Model DashScope chỉ nhận tối đa **{MAX_DASHSCOPE_IMAGES} ảnh** tham chiếu/lần "
    "(ưu tiên ảnh sản phẩm trước, rồi tới ảnh scene)."
)
if _total_imgs > MAX_DASHSCOPE_IMAGES:
    st.warning(
        f"Bạn đã chọn {_total_imgs} ảnh — chỉ **{MAX_DASHSCOPE_IMAGES} ảnh đầu** được dùng. "
        "Nên giữ 1-2 ảnh sản phẩm rõ nét để model bám đúng sản phẩm."
    )

# ── Bước 2: Cấu hình ───────────────────────────────────────────────────────
st.subheader("2️⃣ Cấu hình")
idea = st.text_area(
    "Mô tả sản phẩm / ý tưởng chiến dịch",
    key="_ugc_idea",
    height=80,
    placeholder="vd: thùng rác treo tủ bếp, nắp đậy kín, ruột tháo rời đổ rác tiện...",
)
cc1, cc2, cc3, cc4 = st.columns(4)
with cc1:
    n = st.number_input("Số ảnh output (N)", min_value=1, max_value=10, value=3, step=1, key="_ugc_n")
with cc2:
    panels = st.slider("Số bước/panel mỗi ảnh", min_value=4, max_value=8, value=DEFAULT_PANELS, key="_ugc_panels")
with cc3:
    image_model = st.selectbox(
        "Model sinh ảnh (DashScope)",
        options=list(DASHSCOPE_IMAGE_MODELS.keys()),
        index=list(DASHSCOPE_IMAGE_MODELS.keys()).index(DEFAULT_IMAGE_MODEL),
        format_func=lambda k: DASHSCOPE_IMAGE_MODELS[k],
        key="_ugc_image_model",
        help="Dùng key DASHSCOPE_API_KEY. Prompt video do Gemini sinh (đọc ảnh sản phẩm).",
    )
with cc4:
    target_model = st.selectbox(
        "Model video đích",
        options=list(TARGET_MODELS.keys()),
        index=list(TARGET_MODELS.keys()).index(DEFAULT_TARGET),
        format_func=lambda k: TARGET_MODELS[k],
        key="_ugc_target",
    )

if st.button("🚀 Sinh storyboard + prompt", type="primary"):
    if not product_files:
        st.error("Cần ít nhất 1 ảnh sản phẩm.")
    else:
        product_images = _read_uploads(product_files)
        scene_images = _read_uploads(scene_files)
        st.session_state["_ugc_product_imgs"] = product_images  # dùng lại cho bước tạo video
        client = _get_client()
        results = []
        total = int(n)
        progress = st.progress(0.0, text="Đang sinh...")
        for i in range(1, total + 1):
            progress.progress((i - 1) / total, text=f"Đang sinh ảnh {i}/{total}...")
            try:
                item = generate_ugc_storyboard(
                    client,
                    product_images=product_images,
                    scene_images=scene_images,
                    idea=idea,
                    target_model=target_model,
                    panels=int(panels),
                    variation_index=i,
                    total=total,
                    image_model=image_model,
                )
                results.append(item)
            except Exception as e:
                results.append({"image": None, "prompt": None, "error": _friendly_error(e)})
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
    st.subheader(f"3️⃣ Kết quả ({len(results)} ảnh)")
    st.caption(f"Prompt tối ưu cho: **{TARGET_MODELS.get(st.session_state.get('_ugc_target_done',''), '—')}**")

    for idx, item in enumerate(results, start=1):
        with st.container(border=True):
            st.markdown(f"**Storyboard {idx}**")
            if item.get("error"):
                st.error(f"Lỗi ảnh {idx}: {item['error']}")
                continue

            left, right = st.columns([1, 1.3])

            # ── Cột trái: ảnh storyboard + tạo/tải video ──
            with left:
                if item.get("image"):
                    st.image(item["image"], use_container_width=True)
                    st.download_button(
                        "⬇️ Tải ảnh",
                        data=item["image"],
                        file_name=f"ugc_storyboard_{idx}.png",
                        mime="image/png",
                        key=f"_dl_img_{idx}",
                        use_container_width=True,
                    )
                if item.get("video"):
                    st.video(item["video"])
                    st.download_button(
                        "⬇️ Tải video",
                        data=item["video"],
                        file_name=f"ugc_video_{idx}.mp4",
                        mime="video/mp4",
                        key=f"_dl_vid_{idx}",
                        use_container_width=True,
                    )
                elif st.button("🎬 Tạo video (Veo 3.1)", key=f"_mkvid_{idx}", use_container_width=True):
                    prod = st.session_state.get("_ugc_product_imgs", [])
                    client = _get_client()
                    with st.spinner("Veo 3.1 đang dựng video (có thể mất vài phút)..."):
                        try:
                            vid = generate_video_veo(
                                client,
                                prompt=item.get("prompt") or "",
                                product_images=prod,
                                storyboard_image=item.get("image"),
                            )
                            item["video"] = vid  # lưu vào kết quả (persist qua session_state)
                            st.rerun()
                        except Exception as e:
                            st.error(_friendly_error(e))

            # ── Cột phải: prompt ──
            with right:
                st.markdown("**Prompt video (EN):**")
                st.code(item.get("prompt") or "", language="text")

    all_prompts = "\n\n".join(
        f"# Storyboard {i}\n{x.get('prompt','')}" for i, x in enumerate(results, start=1) if x.get("prompt")
    )
    if all_prompts:
        st.download_button(
            "⬇️ Tải tất cả prompt (.txt)",
            data=all_prompts,
            file_name="ugc_prompts.txt",
            mime="text/plain",
            key="_dl_all_prompts",
        )
    st.caption(
        "🎬 Nút **Tạo video (Veo 3.1)** dùng ảnh sản phẩm (ASSET) + ảnh storyboard (STYLE) + prompt. "
        "Veo cần **key Gemini đã bật billing** và mất vài phút mỗi video."
    )

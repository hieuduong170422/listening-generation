"""Generate Video Affiliate (UGC) — ảnh sản phẩm + scene → N ảnh storyboard nhiều bước + N prompt video."""

import os

import streamlit as st
from google import genai

from podcast_studio.auth import get_api_key as _get_api_key
from podcast_studio.api_utils import is_hard_quota_error
from podcast_studio.affiliate import (
    TARGET_MODELS,
    DEFAULT_TARGET,
    DEFAULT_IMAGE_MODEL,
    MAX_REF_IMAGES,
    DEFAULT_PANELS,
    DEFAULT_VIDEO_CLIPS,
    MAX_VIDEO_CLIPS,
    generate_ugc_storyboard,
    generate_review_video,
    generate_video_veo,
)


def _friendly_error(e: Exception) -> str:
    if is_hard_quota_error(e):
        return (
            "Hết quota cho model AI. Nano Banana (sinh ảnh) cần GEMINI_API_KEY đã bật billing — "
            "bật tại https://aistudio.google.com/apikey."
        )
    msg = str(e)
    return msg if len(msg) <= 300 else msg[:300] + "…"


def _vertex_enabled() -> bool:
    return os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in ("1", "true", "yes")


def _get_client() -> genai.Client:
    """Vertex AI (dùng credit GCP) nếu bật GOOGLE_GENAI_USE_VERTEXAI; nếu không thì key Gemini."""
    if _vertex_enabled():
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip() or "us-central1"
        if not project:
            st.error("Vertex AI: thiếu GOOGLE_CLOUD_PROJECT trong .env.")
            st.stop()
        try:
            return genai.Client(vertexai=True, project=project, location=location)
        except Exception as e:
            st.error(
                f"Không tạo được Vertex client: {e}\n\n"
                "Chạy `gcloud auth application-default login` để xác thực."
            )
            st.stop()
    api_key = _get_api_key()
    if not api_key:
        st.error("Chưa có API key. Nhập GEMINI_API_KEY trong .env hoặc ô 🔑 API Key ở sidebar.")
        st.stop()
    return genai.Client(api_key=api_key)


def _normalize_image(data: bytes, mime: str) -> tuple[bytes, str]:
    """Chuẩn hoá ảnh input để AI đọc rõ: RGB, upscale ảnh quá nhỏ, cap ảnh quá lớn, lưu PNG lossless."""
    from io import BytesIO

    from PIL import Image

    try:
        im = Image.open(BytesIO(data)).convert("RGB")
        long_side = max(im.size)
        scale = None
        if long_side < 1280:        # ảnh nhỏ → phóng lên cho rõ chi tiết sản phẩm
            scale = 1280 / long_side
        elif long_side > 2048:      # ảnh quá lớn → thu về mức hợp lý (vẫn nét)
            scale = 2048 / long_side
        if scale:
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        out = BytesIO()
        im.save(out, "PNG")         # PNG = không nén mất chất lượng
        return out.getvalue(), "image/png"
    except Exception:
        return data, mime


def _read_uploads(files) -> list[tuple[bytes, str]]:
    return [_normalize_image(f.getvalue(), f.type or "image/png") for f in (files or [])]


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
        st.image([f for f in product_files], width=150)
        st.caption("✅ Ảnh gửi tới AI ở chất lượng gốc (đã chuẩn hoá, không thu nhỏ).")
with c2:
    scene_files = st.file_uploader(
        "Ảnh scene tham khảo",
        type=["png", "jpg", "jpeg", "webp"],
        accept_multiple_files=True,
        key="_ugc_scenes",
        help="Nên có! Ảnh CHỤP THỰC TẾ sản phẩm → dùng làm 'mỏ neo' độ chân thực: model bắt chước "
             "ánh sáng/chất liệu/cảm giác ảnh thật để output bớt giả.",
    )
    if scene_files:
        st.image([f for f in scene_files], width=150)

_total_imgs = len(product_files or []) + len(scene_files or [])
st.caption(
    f"ℹ️ **Nano Banana** dùng trực tiếp ảnh sản phẩm (giữ ĐÚNG sản phẩm) — tối đa "
    f"**{MAX_REF_IMAGES} ảnh**/lần (ưu tiên ảnh sản phẩm trước, rồi ảnh scene). "
    "Up 1-3 ảnh sản phẩm rõ nét, nhiều góc để model bám sát nhất."
)
if _total_imgs > MAX_REF_IMAGES:
    st.warning(
        f"Bạn đã chọn {_total_imgs} ảnh — chỉ **{MAX_REF_IMAGES} ảnh đầu** được dùng."
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
    image_model = DEFAULT_IMAGE_MODEL
    st.markdown("**Model sinh ảnh**")
    engine = "🟢 Vertex AI" if _vertex_enabled() else "Key Gemini"
    st.caption(f"Nano Banana\n({engine})")
with cc4:
    target_model = st.selectbox(
        "Model video đích",
        options=list(TARGET_MODELS.keys()),
        index=list(TARGET_MODELS.keys()).index(DEFAULT_TARGET),
        format_func=lambda k: TARGET_MODELS[k],
        key="_ugc_target",
    )

vc1, vc2 = st.columns([1.2, 1])
with vc1:
    video_mode = st.radio(
        "🎬 Chế độ tạo video",
        options=["multiscene", "storyboard"],
        format_func=lambda m: {
            "multiscene": "Nhiều cảnh — mỗi cảnh 1 góc, nối lại (NÊN DÙNG)",
            "storyboard": "1 clip từ ảnh storyboard + prompt (giống Gemini app)",
        }[m],
        key="_ugc_video_mode",
        help="• Nhiều cảnh: mỗi clip = 1 cảnh/góc quay riêng theo flow rồi nối → video NHIỀU GÓC, có chuyển "
             "cảnh (chọn số cảnh bên phải).\n• Storyboard: gửi cả ảnh lưới + prompt cho Veo (1 clip 8s, 1 góc) "
             "— giống thao tác tay trên gemini.google.com.",
    )
with vc2:
    video_clips = st.slider(
        "Số cảnh / góc quay (chế độ Nhiều cảnh)",
        min_value=1, max_value=MAX_VIDEO_CLIPS, value=DEFAULT_VIDEO_CLIPS, key="_ugc_clips",
        help=f"Mỗi cảnh = 1 góc quay riêng (~8s), nối lại → nhiều góc/chuyển cảnh. "
             f"Càng nhiều cảnh càng phong phú nhưng càng tốn credit & lâu (mỗi cảnh 1 lần gen Veo). "
             f"Vd 5 cảnh ≈ 40s.",
    )

if st.button("🚀 Sinh storyboard + prompt", type="primary"):
    if not product_files:
        st.error("Cần ít nhất 1 ảnh sản phẩm.")
    else:
        product_images = _read_uploads(product_files)
        scene_images = _read_uploads(scene_files)
        st.session_state["_ugc_product_imgs"] = product_images  # dùng lại cho bước tạo video
        st.session_state["_ugc_scene_imgs"] = scene_images       # ảnh scene = neo độ chân thực
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
                do_generate = False
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
                    if st.button(
                        "🔄 Tạo lại video", key=f"_regen_vid_{idx}", use_container_width=True,
                        help="Chưa ưng? Gen lại video mới (mỗi lần tốn credit).",
                    ):
                        do_generate = True
                elif st.button("🎬 Tạo video", key=f"_mkvid_{idx}", use_container_width=True):
                    do_generate = True

                if do_generate:
                    client = _get_client()
                    mode = st.session_state.get("_ugc_video_mode", "storyboard")
                    prod = st.session_state.get("_ugc_product_imgs", [])
                    try:
                        if mode == "storyboard":
                            # Y như Gemini app: gửi đúng ảnh storyboard đã sinh + prompt → 1 clip i2v.
                            with st.spinner("⏳ Veo đang dựng video (~2-4 PHÚT). ĐỪNG đóng/đổi tab — cứ chờ..."):
                                vid = generate_video_veo(
                                    client,
                                    prompt=item.get("prompt") or "",
                                    product_images=[],
                                    storyboard_image=item.get("image"),
                                )
                        else:
                            nclips = int(st.session_state.get("_ugc_clips", DEFAULT_VIDEO_CLIPS))
                            with st.spinner(f"⏳ Veo đang dựng {nclips} cảnh rồi nối (~3-5 PHÚT). ĐỪNG đóng/đổi tab — cứ chờ..."):
                                vid = generate_review_video(
                                    client,
                                    product_images=prod,
                                    scene_images=st.session_state.get("_ugc_scene_imgs", []),
                                    idea=st.session_state.get("_ugc_idea", "") or "",
                                    clips=nclips,
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
        "🎬 Nút **Tạo video review (nhiều cảnh)** sinh nhiều clip **Veo 3.1** (mỗi cảnh ~8s, giữ đúng "
        "sản phẩm qua ảnh sản phẩm) rồi **nối liên tục** bằng ffmpeg thành 1 video review dài. "
        "Số cảnh chỉnh ở Bước 2. Trừ credit GCP, mỗi cảnh mất vài phút."
    )

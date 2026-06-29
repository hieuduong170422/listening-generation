"""Generate Video Affiliate (UGC) — ảnh sản phẩm + scene → N ảnh storyboard nhiều bước + N prompt video."""

import streamlit as st

from podcast_studio.api_utils import is_hard_quota_error
from podcast_studio.genai_client import get_client as _get_client, vertex_enabled as _vertex_enabled
from podcast_studio import affiliate_history
from podcast_studio.affiliate import (
    DEFAULT_IMAGE_MODEL,
    MAX_REF_IMAGES,
    DEFAULT_VIDEO_CLIPS,
    MAX_VIDEO_CLIPS,
    DEFAULT_BEATS_PER_CLIP,
    MAX_BEATS_PER_CLIP,
    generate_storyboard_set,
    generate_clip_from_storyboard,
    _stitch_videos,
)


def _friendly_error(e: Exception) -> str:
    if is_hard_quota_error(e):
        return (
            "Hết quota cho model AI. Nano Banana (sinh ảnh) cần GEMINI_API_KEY đã bật billing — "
            "bật tại https://aistudio.google.com/apikey."
        )
    msg = str(e)
    return msg if len(msg) <= 300 else msg[:300] + "…"




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
    "Upload **ảnh sản phẩm** → sinh N **ảnh storyboard nhiều bước** "
    "(faceless, mỗi panel 1 bước dùng sản phẩm) kèm **prompt video tiếng Anh** để đưa vào VEO/Omni."
)

# ── Bước 1: Ảnh đầu vào ────────────────────────────────────────────────────
st.subheader("1️⃣ Ảnh sản phẩm")
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

scene_files = None  # đã bỏ ảnh scene tham khảo
_total_imgs = len(product_files or [])
st.caption(
    f"ℹ️ **Nano Banana** dùng trực tiếp ảnh sản phẩm (giữ ĐÚNG sản phẩm) — tối đa "
    f"**{MAX_REF_IMAGES} ảnh**/lần. Up 1-3 ảnh sản phẩm rõ nét, nhiều góc để model bám sát nhất."
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
directions = st.text_area(
    "🎯 Yêu cầu cụ thể về cảnh / góc quay (tuỳ chọn)",
    key="_ugc_directions",
    height=70,
    placeholder="vd: cảnh 1 quay top-down đổ nho vào bát; cảnh cuối push-in cận mặt cười của bát; "
                "thêm cảnh tay nhặt 1 quả nho lên ăn...",
    help="Để trống → dùng flow review mặc định. Nhập vào → các cảnh/góc quay này được ƯU TIÊN đưa vào "
         "ảnh storyboard + prompt + frame, phần còn lại lấp bằng flow mặc định.",
)
cc1, cc2, cc3 = st.columns([1, 1, 1.2])
with cc1:
    video_clips = st.slider(
        "Số clip (= số ảnh storyboard)",
        min_value=1, max_value=MAX_VIDEO_CLIPS, value=DEFAULT_VIDEO_CLIPS, key="_ugc_clips",
        help="Mỗi clip = 1 ảnh storyboard (gồm nhiều cảnh). Nối các clip thành video cuối. "
             "Clip dài = số cảnh × 4s.",
    )
with cc2:
    beats_per_clip = st.slider(
        "Số cảnh mỗi clip (mỗi cảnh 4s)",
        min_value=1, max_value=MAX_BEATS_PER_CLIP, value=DEFAULT_BEATS_PER_CLIP, key="_ugc_beats",
        help="Số cú cắt trong 1 clip. Mỗi cảnh = 1 sub-clip 4s có frame NEO đúng panel storyboard → "
             "MỌI cảnh giữ đúng sản phẩm (không để Veo tự bịa). Mỗi cảnh = 1 lần render Veo 4s, dùng "
             "trọn không cắt bỏ → không phí thừa. Càng nhiều cảnh càng nhiều cú cắt & càng tốn.",
    )
with cc3:
    st.markdown("**Engine**")
    engine = "🟢 Vertex AI" if _vertex_enabled() else "Key Gemini"
    st.caption(f"Ảnh: Nano Banana · Video: Veo 3.1\n({engine})")

_clips = int(st.session_state.get("_ugc_clips", DEFAULT_VIDEO_CLIPS))
_beats = int(st.session_state.get("_ugc_beats", DEFAULT_BEATS_PER_CLIP))
_total_scenes = _clips * _beats
st.caption(
    f"≈ **{_total_scenes * 4}s** video · **{_total_scenes} cảnh × 4s** ({_clips} clip × {_beats} cảnh) · "
    f"**{_total_scenes} lần render Veo × 4s = {_total_scenes * 4}s tính phí** (dùng TRỌN, không cắt bỏ → 0 phí thừa). "
    "Mỗi cảnh neo panel storyboard riêng → bám đúng sản phẩm."
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
        with st.spinner(f"⏳ Đang lên flow & sinh {_clips} storyboard ({_beats} cảnh/ảnh)..."):
            try:
                data = generate_storyboard_set(
                    client,
                    product_images=product_images,
                    scene_images=scene_images,
                    idea=idea,
                    clips=_clips,
                    beats_per_clip=_beats,
                    directions=directions,
                    image_model=DEFAULT_IMAGE_MODEL,
                )
                st.session_state["_ugc_product_name"] = data["product"]
                st.session_state["_ugc_results"] = data["items"]
                st.session_state.pop("_ugc_final_video", None)
                try:
                    affiliate_history.log_storyboard(
                        idea=idea,
                        directions=directions,
                        clips=_clips,
                        beats_per_clip=_beats,
                        product=data["product"],
                        engine="vertex" if _vertex_enabled() else "gemini",
                        image_model=DEFAULT_IMAGE_MODEL,
                        items=data["items"],
                    )
                except Exception:
                    pass  # log lỗi không được phá flow chính
            except Exception as e:
                st.error(_friendly_error(e))

def _make_clip(item: dict, clip_index: int | None = None) -> bytes:
    """Render 1 clip 8s cho 1 storyboard: Omni đọc ảnh + cảnh → Veo."""
    client = _get_client()
    video = generate_clip_from_storyboard(
        client,
        product_images=st.session_state.get("_ugc_product_imgs", []),
        scene_images=st.session_state.get("_ugc_scene_imgs", []),
        product=st.session_state.get("_ugc_product_name", "product"),
        scenes=item.get("scenes") or [],
        frames=item.get("frames") or [],
        storyboard_image=item.get("image"),
    )
    try:
        affiliate_history.log_video(
            product=st.session_state.get("_ugc_product_name", "product"),
            engine="vertex" if _vertex_enabled() else "gemini",
            clip_index=clip_index,
            scenes=item.get("scenes") or [],
            prompt=item.get("prompt") or "",
            video_bytes=len(video or b""),
        )
    except Exception:
        pass  # log lỗi không được phá flow chính
    return video


# ── Bước 3: Kết quả ────────────────────────────────────────────────────────
results = st.session_state.get("_ugc_results")
if results:
    st.divider()
    st.subheader(f"3️⃣ Kết quả — {len(results)} clip (mỗi storyboard = 1 clip 8s)")

    for idx, item in enumerate(results, start=1):
        with st.container(border=True):
            scenes = item.get("scenes") or []
            st.markdown(f"**Clip {idx}** · {len(scenes)} cảnh")
            if item.get("error"):
                st.error(f"Lỗi clip {idx}: {item['error']}")
                continue

            left, right = st.columns([1, 1.3])

            # ── Cột trái: ảnh storyboard + tạo/tải clip ──
            with left:
                if item.get("image"):
                    st.image(item["image"], use_container_width=True)
                    st.download_button(
                        "⬇️ Tải ảnh", data=item["image"],
                        file_name=f"ugc_storyboard_{idx}.png", mime="image/png",
                        key=f"_dl_img_{idx}", use_container_width=True,
                    )
                do_generate = False
                if item.get("video"):
                    st.video(item["video"])
                    st.download_button(
                        "⬇️ Tải clip", data=item["video"],
                        file_name=f"ugc_clip_{idx}.mp4", mime="video/mp4",
                        key=f"_dl_vid_{idx}", use_container_width=True,
                    )
                    if st.button(
                        "🔄 Tạo lại clip", key=f"_regen_vid_{idx}", use_container_width=True,
                        help="Chưa ưng? Gen lại clip này (mỗi lần tốn credit).",
                    ):
                        do_generate = True
                elif st.button("🎬 Tạo clip", key=f"_mkvid_{idx}", use_container_width=True):
                    do_generate = True

                if do_generate:
                    try:
                        with st.spinner("⏳ Veo đang dựng clip (~2-4 PHÚT). ĐỪNG đóng/đổi tab — cứ chờ..."):
                            item["video"] = _make_clip(item, clip_index=idx)
                        st.session_state.pop("_ugc_final_video", None)  # clip đổi → video nối cũ hết hiệu lực
                        st.rerun()
                    except Exception as e:
                        st.error(_friendly_error(e))

            # ── Cột phải: các cảnh + prompt ──
            with right:
                if scenes:
                    st.markdown("**Cảnh trong clip này:**")
                    st.markdown("\n".join(f"{i}. {s}" for i, s in enumerate(scenes, start=1)))
                st.markdown("**Prompt (EN):**")
                st.code(item.get("prompt") or "", language="text")

    # ── Nối tất cả clip thành 1 video ──
    st.divider()
    done = sum(1 for x in results if x.get("video"))
    st.markdown(f"**🎬 Video hoàn chỉnh** — {done}/{len(results)} clip đã render")
    if st.button(
        "🎬 Nối tất cả thành 1 video", type="primary", use_container_width=True,
        help="Render nốt các clip chưa tạo rồi nối tất cả bằng ffmpeg. Mỗi clip mất vài phút, trừ credit GCP.",
    ):
        try:
            vids = []
            prog = st.progress(0.0, text="Chuẩn bị...")
            for i, x in enumerate(results):
                if not x.get("video"):
                    prog.progress(i / len(results), text=f"⏳ Veo dựng clip {i + 1}/{len(results)}...")
                    x["video"] = _make_clip(x, clip_index=i + 1)
                vids.append(x["video"])
            prog.progress(0.99, text="Đang nối clip...")
            final_video = _stitch_videos(vids)
            st.session_state["_ugc_final_video"] = final_video
            try:
                affiliate_history.log_video(
                    product=st.session_state.get("_ugc_product_name", "product"),
                    engine="vertex" if _vertex_enabled() else "gemini",
                    scenes=[s for x in results for s in (x.get("scenes") or [])],
                    video_bytes=len(final_video or b""),
                    final=True,
                )
            except Exception:
                pass
            prog.empty()
            st.rerun()
        except Exception as e:
            st.error(_friendly_error(e))

    final = st.session_state.get("_ugc_final_video")
    if final:
        st.video(final)
        st.download_button(
            "⬇️ Tải video hoàn chỉnh", data=final,
            file_name="ugc_review.mp4", mime="video/mp4", key="_dl_final",
            use_container_width=True,
        )

    all_prompts = "\n\n".join(
        f"# Clip {i}\n{x.get('prompt','')}" for i, x in enumerate(results, start=1) if x.get("prompt")
    )
    if all_prompts:
        st.download_button(
            "⬇️ Tải tất cả prompt (.txt)", data=all_prompts,
            file_name="ugc_prompts.txt", mime="text/plain", key="_dl_all_prompts",
        )

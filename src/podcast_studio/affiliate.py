"""Video Affiliate (UGC) — sinh ẢNH STORYBOARD nhiều bước (faceless) + PROMPT video có cấu trúc.

Đầu vào: ảnh sản phẩm + ảnh scene tham khảo (screenshot TikTok). Mỗi output gồm:
  - 1 ảnh storyboard dạng lưới nhiều panel (mỗi panel = 1 bước dùng sản phẩm, không lộ mặt),
  - 1 prompt tiếng Anh theo template "UGC product video" để đưa vào VEO/Omni tạo clip.
Ảnh sinh bằng DashScope (qwen-image / wan-image); prompt sinh bằng Gemini (đọc ảnh sản phẩm).
"""

import base64
import os
from http import HTTPStatus

from google import genai
from google.genai import types

from podcast_studio.api_utils import call_with_retry, track_response

TEXT_MODEL = "gemini-2.5-flash"
VEO_MODEL = "veo-3.1-generate-preview"

# Model đích để tinh chỉnh prompt image-to-video.
TARGET_MODELS: dict[str, str] = {
    "veo": "Google VEO",
    "omni": "Omni (image-to-video)",
    "generic": "Chung (image-to-video)",
}
DEFAULT_TARGET = "veo"

# Model sinh ảnh DashScope ([text+ảnh→ảnh]) — dùng key DASHSCOPE_API_KEY.
DASHSCOPE_IMAGE_MODELS: dict[str, str] = {
    "qwen-image-2.0": "Qwen Image 2.0 (ghép + chỉnh sửa)",
    "qwen-image-2.0-pro": "Qwen Image 2.0 Pro (chất lượng cao)",
    "wan2.7-image-pro": "Wan 2.7 Image Pro (4K)",
}
DEFAULT_IMAGE_MODEL = "qwen-image-2.0"

# DashScope image-edit (I2I) chỉ nhận tối đa 3 ảnh tham chiếu.
MAX_DASHSCOPE_IMAGES = 3

DEFAULT_PANELS = 8

# Quy tắc faceless + chất lượng dùng chung cho cả ảnh lẫn prompt.
_FACELESS_CLEAN_RULES = (
    "- FACELESS: never show a human face; only hands/forearms interacting with the product, "
    "or the product by itself. No faces, no full bodies, no people in the background.\n"
    "- Photorealistic, bright, CLEAN lifestyle / e-commerce photography (NOT gritty, NOT low quality).\n"
    "- Soft natural lighting, tidy real-world setting, neutral/minimal palette.\n"
    "- The PRODUCT from the reference image(s) is the HERO and must look identical everywhere "
    "(same shape, color, material, proportions and details).\n"
    "- Keep the product identity and the overall setting CONSISTENT across the whole image.\n"
    "- ABSOLUTELY NO phone screen, NO app / TikTok / Reels interface, NO icons, NO buttons, "
    "NO search bar, NO text, NO captions, NO numbers, NO logo overlay, NO watermark.\n"
)


# ── Helpers: Gemini image parts & DashScope ────────────────────────────────

def _image_parts(images: list[tuple[bytes, str]]) -> list:
    """Chuyển list (bytes, mime) thành list types.Part (cho Gemini multimodal)."""
    return [
        types.Part.from_bytes(data=data, mime_type=mime or "image/png")
        for data, mime in images
    ]


def _configure_dashscope():
    """Cấu hình dashscope SDK từ env (DASHSCOPE_API_KEY, có fallback DASHCOPE_*)."""
    import dashscope

    api_key = os.getenv("DASHSCOPE_API_KEY") or os.getenv("DASHCOPE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Chưa có DASHSCOPE_API_KEY trong .env — cần để sinh ảnh bằng DashScope."
        )
    dashscope.api_key = api_key
    base_url = os.getenv("DASHSCOPE_BASE_URL") or os.getenv("DASHCOPE_BASE_URL")
    if base_url:
        dashscope.base_http_api_url = base_url.rstrip("/")
    return dashscope


def _data_uri(data: bytes, mime: str) -> str:
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime or 'image/png'};base64,{b64}"


def _extract_dashscope_image_url(response) -> str:
    """Lấy URL ảnh từ response MultiModalConversation (content = [{'image': url}])."""
    choices = response.output.choices
    if not choices:
        raise RuntimeError("DashScope không trả về kết quả nào.")
    content = choices[0].message.content
    if not isinstance(content, list):
        content = [content]
    for item in content:
        if isinstance(item, dict) and item.get("image"):
            return item["image"]
    raise RuntimeError("DashScope không trả về ảnh — thử lại hoặc đổi model/ảnh input.")


# ── Sinh ảnh STORYBOARD (lưới nhiều bước) bằng DashScope ────────────────────

def generate_storyboard_dashscope(
    *,
    product_images: list[tuple[bytes, str]],
    scene_images: list[tuple[bytes, str]],
    idea: str,
    panels: int = DEFAULT_PANELS,
    variation_index: int = 1,
    total: int = 1,
    model: str = DEFAULT_IMAGE_MODEL,
) -> bytes:
    """Sinh 1 ảnh storyboard dạng lưới (panels panel) bằng DashScope → bytes ảnh."""
    import requests
    from dashscope import MultiModalConversation

    _configure_dashscope()

    instruction = (
        f"Create ONE photorealistic STORYBOARD GRID image: a neat grid of {panels} equal panels "
        "(thin clean white gutters between panels) showing a faceless UGC product-demo sequence.\n"
        "Each panel = a DIFFERENT step of using the product, in logical order: "
        "product shown in place → open / activate it → main use → pour / fill / insert → "
        "wipe / clean → remove or replace a part → final tidy beauty shot.\n"
        + _FACELESS_CLEAN_RULES
        + "- EACH individual panel MUST be PORTRAIT orientation (vertical, clearly TALLER than wide, "
        "like a phone-photo crop) — NOT wide landscape strips.\n"
        "- Arrange the portrait panels in a GRID of 2 COLUMNS × several ROWS (e.g. 2×3 or 2×4), "
        "equal size, with thin white gutters. Do NOT stack wide panels in a single column.\n"
        "- The overall image is vertical/portrait.\n"
        "- Use the product reference image(s) for the EXACT product; use any scene screenshots "
        "ONLY for setting / composition / style inspiration.\n"
    )
    if idea.strip():
        instruction += f"- Product / context: {idea.strip()}\n"
    if total > 1:
        instruction += (
            f"- This is concept variation {variation_index} of {total}; vary the angles and steps "
            "so it differs from the other variations.\n"
        )

    ref_images = (list(product_images) + list(scene_images))[:MAX_DASHSCOPE_IMAGES]
    parts: list = [{"text": instruction}]
    for data, mime in ref_images:
        parts.append({"image": _data_uri(data, mime)})

    messages = [{"role": "user", "content": parts}]
    response = call_with_retry(
        MultiModalConversation.call, model=model, messages=messages
    )
    if response.status_code != HTTPStatus.OK:
        msg = getattr(response, "message", None) or getattr(response, "code", "Unknown error")
        raise RuntimeError(f"DashScope lỗi ({response.status_code}): {msg}")

    url = _extract_dashscope_image_url(response)
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return resp.content


# ── Sinh PROMPT video có cấu trúc bằng Gemini (đọc ảnh sản phẩm) ─────────────

def generate_sequence_prompt(
    client: genai.Client,
    *,
    product_images: list[tuple[bytes, str]],
    idea: str,
    target_model: str = DEFAULT_TARGET,
    variation_index: int = 1,
    total: int = 1,
    text_model: str = TEXT_MODEL,
) -> str:
    """Sinh 1 prompt video UGC (tiếng Anh) theo template cố định, mô tả đúng sản phẩm trong ảnh."""
    target_label = TARGET_MODELS.get(target_model, TARGET_MODELS[DEFAULT_TARGET])
    instruction = (
        f"You write UGC product-video prompts for {target_label}. Look at the product image(s) and "
        "write ONE prompt in ENGLISH using EXACTLY this structure and tone (keep the headings/lines):\n\n"
        "Create a realistic UGC-style product video featuring <one concise product description> "
        "(like in the reference image).\n\n"
        "Show the following actions in sequence:\n"
        "1. <step>\n"
        "2. <step>\n"
        "3. <step>\n"
        "(list 5-8 concrete steps that suit THIS product, faceless, hands only, logical order)\n\n"
        "Camera angles: slight top-down and front view, close-ups on hands interacting with the product, "
        "maintain consistent product proportions.\n"
        "Lighting: soft, natural <setting> lighting.\n"
        "Do not show faces, do not add text overlays, do not exaggerate movements.\n"
        "Keep the product form, size, and proportions true to the reference image.\n"
        "Style: realistic, natural, unobtrusive, instructional, no dramatization.\n"
        "Duration: short, 15-30 seconds, smooth transitions between actions.\n\n"
        "RULES: replace every <...> with content specific to the product seen in the image. "
        "All actions must be faceless (hands only) and realistic. "
        "Output ONLY the prompt text — no preamble, no markdown fences, no extra commentary.\n"
    )
    if idea.strip():
        instruction += f"Extra context: {idea.strip()}\n"
    if total > 1:
        instruction += (
            f"This is variation {variation_index} of {total}; vary the action order / camera angles "
            "so it is distinct from the other variations.\n"
        )

    contents: list = []
    if product_images:
        contents.append("PRODUCT IMAGE(S):")
        contents += _image_parts(product_images)
    contents.append(instruction)

    response = call_with_retry(
        client.models.generate_content, model=text_model, contents=contents
    )
    track_response(None, response, "text")
    return (response.text or "").strip()


# ── Sinh VIDEO bằng Veo 3.1 (ảnh sản phẩm + storyboard + prompt) ────────────

_VEO_POLL_TIMEOUT = 600  # giây
_VEO_POLL_INTERVAL = 10


def generate_video_veo(
    client: genai.Client,
    *,
    prompt: str,
    product_images: list[tuple[bytes, str]],
    storyboard_image: bytes | None = None,
    aspect_ratio: str = "9:16",
    model: str = VEO_MODEL,
) -> bytes:
    """Tạo video bằng Veo 3.1 từ prompt + ảnh sản phẩm (ASSET) + ảnh storyboard (STYLE).

    Trả về bytes video MP4. Veo cần key Gemini đã bật billing; quá trình mất vài phút.
    """
    import time

    neg = "human faces, on-screen text, captions, watermark, app interface"
    # Gemini API chỉ hỗ trợ reference type ASSET (STYLE là của Vertex) → chỉ dùng ảnh sản phẩm.
    first_img = product_images[0] if product_images else (
        (storyboard_image, "image/png") if storyboard_image else None
    )

    def _start_with_references():
        refs = [
            types.VideoGenerationReferenceImage(
                image=types.Image(image_bytes=data, mime_type=mime or "image/png"),
                reference_type=types.VideoGenerationReferenceType.ASSET,
            )
            for data, mime in product_images[:3]
        ]
        if not refs:
            raise ValueError("no-asset-refs")
        config = types.GenerateVideosConfig(
            aspect_ratio=aspect_ratio, number_of_videos=1,
            reference_images=refs, negative_prompt=neg,
        )
        return client.models.generate_videos(model=model, prompt=prompt, config=config)

    def _start_with_first_frame():
        config = types.GenerateVideosConfig(
            aspect_ratio=aspect_ratio, number_of_videos=1, negative_prompt=neg,
        )
        source_kwargs = {"prompt": prompt}
        if first_img:
            data, mime = first_img
            source_kwargs["image"] = types.Image(image_bytes=data, mime_type=mime or "image/png")
        source = types.GenerateVideosSource(**source_kwargs)
        return client.models.generate_videos(model=model, source=source, config=config)

    try:
        operation = _start_with_references()
    except Exception as e:
        # Reference images không được hỗ trợ → fallback first-frame image-to-video.
        if "reference" in str(e).lower() or "not supported" in str(e).lower() or "no-asset-refs" in str(e):
            operation = _start_with_first_frame()
        else:
            raise

    deadline = time.time() + _VEO_POLL_TIMEOUT
    while not operation.done and time.time() < deadline:
        time.sleep(_VEO_POLL_INTERVAL)
        operation = client.operations.get(operation)

    if not operation.done:
        raise RuntimeError(f"Veo quá thời gian chờ ({_VEO_POLL_TIMEOUT}s).")
    if operation.error:
        raise RuntimeError(f"Veo lỗi: {getattr(operation.error, 'message', None) or operation.error}")

    result = operation.result
    if not result.generated_videos:
        raise RuntimeError("Veo không trả về video nào.")

    video = result.generated_videos[0].video
    # Cố tải bytes inline; nếu chưa có thì download từ file API / URI.
    try:
        client.files.download(file=video)
    except Exception:
        pass
    data = getattr(video, "video_bytes", None)
    if data:
        return data

    uri = getattr(video, "uri", None)
    if uri:
        import os
        import requests
        key = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY") or ""
        sep = "&" if "?" in uri else "?"
        r = requests.get(f"{uri}{sep}key={key}" if key else uri, timeout=300)
        r.raise_for_status()
        return r.content

    raise RuntimeError("Veo trả về video nhưng không lấy được dữ liệu.")


# ── Sinh 1 output hoàn chỉnh: ảnh storyboard + prompt ───────────────────────

def generate_ugc_storyboard(
    client: genai.Client,
    *,
    product_images: list[tuple[bytes, str]],
    scene_images: list[tuple[bytes, str]],
    idea: str,
    target_model: str,
    panels: int = DEFAULT_PANELS,
    variation_index: int = 1,
    total: int = 1,
    image_model: str = DEFAULT_IMAGE_MODEL,
) -> dict:
    """Trả về {'image': bytes (storyboard lưới), 'prompt': str (template video UGC)}."""
    image_bytes = generate_storyboard_dashscope(
        product_images=product_images,
        scene_images=scene_images,
        idea=idea,
        panels=panels,
        variation_index=variation_index,
        total=total,
        model=image_model,
    )
    prompt = generate_sequence_prompt(
        client,
        product_images=product_images,
        idea=idea,
        target_model=target_model,
        variation_index=variation_index,
        total=total,
    )
    return {"image": image_bytes, "prompt": prompt}

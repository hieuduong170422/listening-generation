"""Video Affiliate (UGC) — sinh keyframe UGC không lộ mặt + prompt image-to-video.

Đầu vào: ảnh sản phẩm + ảnh scene tham khảo (screenshot TikTok). Đầu ra: N keyframe
(khung hình đầu, dọc 9:16, phong cách UGC, KHÔNG lộ mặt) kèm N prompt tiếng Anh để đưa
vào VEO/Omni... tạo clip review UGC.
"""

import base64
import os
from http import HTTPStatus

from google import genai
from google.genai import types

from podcast_studio.api_utils import call_with_retry, track_response
from podcast_studio.image_generator import IMAGE_MODEL, _extract_image_bytes

TEXT_MODEL = "gemini-2.5-flash"

# Model đích để tối ưu prompt image-to-video.
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

# Quy tắc UGC dùng chung cho cả ảnh lẫn prompt.
_UGC_RULES = (
    "STYLE & RULES:\n"
    "- Photorealistic, bright, CLEAN lifestyle / e-commerce UGC product photography "
    "(like a high-quality real-customer review), NOT gritty or low-quality.\n"
    "- Soft natural lighting, tidy modern real-world setting, neutral/minimal palette, "
    "pleasing shallow depth of field.\n"
    "- FACELESS: never show a human face. Only hands/forearms interacting with the product, "
    "or the product by itself. No faces, no full bodies, no people in the background.\n"
    "- The PRODUCT from the provided image(s) is the clear HERO and must look identical: "
    "same shape, color, material, proportions and details.\n"
    "- Keep the product identity and overall setting/style CONSISTENT across the whole series.\n"
    "- Output a SINGLE clean photo — NO collage, NO split frames, NO grid, NO before/after panels.\n"
    "- NO text, NO captions, NO logo overlay, NO watermark, NO UI elements.\n"
    "- Vertical 9:16 framing.\n"
)

# Mỗi scene = 1 "beat" hành động khác nhau để tạo flow demo sản phẩm (faceless).
SCENE_BEATS = (
    "Hero shot: the product shown clearly in its real-use environment, no hands.",
    "A hand opening / activating the product (lid, switch, drawer, cap...).",
    "A hand using the product's MAIN function in a realistic everyday moment.",
    "Tight close-up of a key feature, texture or detail of the product.",
    "The product seen from a different angle that highlights its design.",
    "A hand doing maintenance: cleaning, refilling, or swapping a part.",
    "The product in context next to related everyday items it is used with.",
    "Final clean beauty shot of the product, tidy and appealing.",
)


def _scene_beat(scene_index: int) -> str:
    return SCENE_BEATS[(scene_index - 1) % len(SCENE_BEATS)]


def _image_parts(images: list[tuple[bytes, str]]) -> list:
    """Chuyển list (bytes, mime) thành list types.Part để đưa vào contents."""
    return [
        types.Part.from_bytes(data=data, mime_type=mime or "image/png")
        for data, mime in images
    ]


def generate_ugc_keyframe(
    client: genai.Client,
    *,
    product_images: list[tuple[bytes, str]],
    scene_images: list[tuple[bytes, str]],
    idea: str,
    scene_index: int,
    total: int,
) -> bytes:
    """Sinh 1 keyframe UGC (bytes ảnh) cho scene thứ scene_index."""
    instruction = (
        "You are a UGC ad creative director. Generate ONE photorealistic keyframe image "
        "for a faceless UGC product-review video.\n"
        + _UGC_RULES
        + "- Use the product reference image(s) for the EXACT product; use any scene screenshots "
        "ONLY for setting / composition / style inspiration.\n"
        f"- SCENE FOCUS (shot {scene_index} of {total}): {_scene_beat(scene_index)}\n"
        "- Make this shot visually DISTINCT from the other shots in the series.\n"
    )
    if idea.strip():
        instruction += f"- Product / campaign idea: {idea.strip()}\n"

    contents: list = []
    if product_images:
        contents.append("PRODUCT IMAGE(S):")
        contents += _image_parts(product_images)
    if scene_images:
        contents.append("REFERENCE SCENE SCREENSHOTS (style/setting only):")
        contents += _image_parts(scene_images)
    contents.append(instruction)

    response = call_with_retry(
        client.models.generate_content,
        model=IMAGE_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
    )
    track_response(None, response, "image")
    return _extract_image_bytes(response)


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


def generate_ugc_keyframe_dashscope(
    *,
    product_images: list[tuple[bytes, str]],
    scene_images: list[tuple[bytes, str]],
    idea: str,
    scene_index: int,
    total: int,
    model: str = DEFAULT_IMAGE_MODEL,
) -> bytes:
    """Sinh 1 keyframe UGC bằng DashScope (qwen-image / wan-image) → trả về bytes ảnh."""
    import requests
    from dashscope import MultiModalConversation

    dashscope = _configure_dashscope()

    instruction = (
        "Generate ONE photorealistic vertical 9:16 keyframe for a faceless UGC product-review video.\n"
        + _UGC_RULES
        + "- Use the product reference image(s) for the EXACT product; use any scene screenshots "
        "ONLY for setting / composition / style inspiration.\n"
        f"- SCENE FOCUS (shot {scene_index} of {total}): {_scene_beat(scene_index)}\n"
        "- Make this shot visually DISTINCT from the other shots in the series.\n"
    )
    if idea.strip():
        instruction += f"- Product / campaign idea: {idea.strip()}\n"

    # Giới hạn tổng số ảnh tham chiếu ≤ MAX (ưu tiên ảnh sản phẩm).
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


def generate_video_prompt(
    client: genai.Client,
    *,
    idea: str,
    target_model: str,
    scene_index: int,
    total: int,
    text_model: str = TEXT_MODEL,
) -> str:
    """Sinh 1 prompt image-to-video (tiếng Anh) cho keyframe của scene scene_index."""
    target_label = TARGET_MODELS.get(target_model, TARGET_MODELS[DEFAULT_TARGET])
    prompt = (
        f"Write ONE image-to-video prompt in ENGLISH, optimized for {target_label}. "
        "It will animate a given keyframe into a 5-8 second faceless UGC product-review clip.\n"
        + _UGC_RULES
        + f"SCENE FOCUS (shot {scene_index} of {total}): {_scene_beat(scene_index)}\n"
        "The prompt MUST describe: camera movement, the hands' action on the product, product "
        "interaction, lighting, mood and pacing — in a single cohesive paragraph that matches the "
        "scene focus above.\n"
        "Keep it distinct from the other shots. Output ONLY the prompt text — no preamble, no "
        "markdown, no quotes, no numbering.\n"
    )
    if idea.strip():
        prompt += f"Product / campaign idea: {idea.strip()}\n"

    response = call_with_retry(
        client.models.generate_content, model=text_model, contents=prompt
    )
    track_response(None, response, "text")
    return (response.text or "").strip()


def generate_ugc_scene(
    client: genai.Client,
    *,
    product_images: list[tuple[bytes, str]],
    scene_images: list[tuple[bytes, str]],
    idea: str,
    target_model: str,
    scene_index: int,
    total: int,
    image_model: str = DEFAULT_IMAGE_MODEL,
) -> dict:
    """Sinh 1 scene hoàn chỉnh: keyframe ảnh (DashScope) + prompt image-to-video (Gemini text)."""
    image_bytes = generate_ugc_keyframe_dashscope(
        product_images=product_images,
        scene_images=scene_images,
        idea=idea,
        scene_index=scene_index,
        total=total,
        model=image_model,
    )
    prompt = generate_video_prompt(
        client,
        idea=idea,
        target_model=target_model,
        scene_index=scene_index,
        total=total,
    )
    return {"image": image_bytes, "prompt": prompt}

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

# Quy tắc UGC dùng chung cho cả ảnh lẫn prompt.
_UGC_RULES = (
    "STRICT UGC RULES:\n"
    "- FACELESS: never show a human face. Allowed: hands interacting with the product, "
    "over-the-shoulder, POV, product close-ups, partial body below the neck.\n"
    "- Authentic user-generated look: shot on a phone, natural/imperfect lighting, real "
    "everyday setting (home, desk, cafe, bathroom, outdoor), handheld feel.\n"
    "- NO on-screen text, NO captions, NO watermark, NO logo overlay.\n"
    "- Vertical 9:16 framing for TikTok/Reels.\n"
)


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
        "(the opening frame) for a faceless TikTok-style product-review video.\n"
        + _UGC_RULES
        + "- The PRODUCT shown in the provided product image(s) MUST be featured clearly and "
        "look identical (same shape, color, label).\n"
        "- Use the reference scene screenshots ONLY for setting / composition / style inspiration.\n"
        f"- This is scene {scene_index} of {total}; make the angle, action and setting "
        "visually DISTINCT from the other scenes.\n"
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
        "Generate ONE photorealistic vertical 9:16 keyframe (opening frame) for a faceless "
        "TikTok-style product-review video.\n"
        + _UGC_RULES
        + "- The PRODUCT in the provided product image(s) MUST be featured clearly and look "
        "identical (same shape, color, label).\n"
        "- Use the reference scene screenshots ONLY for setting / composition / style.\n"
        f"- Scene {scene_index} of {total}; make angle, action and setting DISTINCT from other scenes.\n"
    )
    if idea.strip():
        instruction += f"- Product / campaign idea: {idea.strip()}\n"

    parts: list = [{"text": instruction}]
    for data, mime in product_images:
        parts.append({"image": _data_uri(data, mime)})
    for data, mime in scene_images:
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
        "It will animate a given keyframe into a 5-8 second faceless UGC TikTok product-review clip.\n"
        + _UGC_RULES
        + "The prompt MUST describe: camera movement, the action (hands using/showing the product), "
        "product interaction, lighting, mood and pacing — in a single cohesive paragraph.\n"
        f"This is scene {scene_index} of {total}; keep it distinct from other scenes.\n"
        "Output ONLY the prompt text — no preamble, no markdown, no quotes, no numbering.\n"
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

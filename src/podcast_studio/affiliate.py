"""Video Affiliate (UGC) — sinh ẢNH STORYBOARD nhiều bước (faceless) + PROMPT video có cấu trúc.

Đầu vào: ảnh sản phẩm + ảnh scene tham khảo (screenshot TikTok). Mỗi output gồm:
  - 1 ảnh storyboard dạng lưới nhiều panel (mỗi panel = 1 bước dùng sản phẩm, không lộ mặt),
  - 1 prompt tiếng Anh theo template "UGC product video" để đưa vào VEO/Omni tạo clip.
Ảnh sinh bằng "Nano Banana" (gemini-2.5-flash-image); prompt sinh bằng Gemini — đều dùng GEMINI_API_KEY.
"""

import os

from google import genai
from google.genai import types

from podcast_studio.api_utils import call_with_retry, track_response

TEXT_MODEL = "gemini-2.5-flash"
VEO_MODEL = "veo-3.1-generate-preview"          # Gemini Developer API (key trả phí)
VEO_VERTEX_MODEL = "veo-3.1-generate-001"        # Vertex AI — Veo 3.1 (tên GA khác Developer API)

# Model đích để tinh chỉnh prompt image-to-video.
TARGET_MODELS: dict[str, str] = {
    "veo": "Google VEO",
    "omni": "Omni (image-to-video)",
    "generic": "Chung (image-to-video)",
}
DEFAULT_TARGET = "veo"

# Model sinh ảnh "Nano Banana" của Gemini ([text+ảnh→ảnh]) — dùng key GEMINI_API_KEY.
IMAGE_MODELS: dict[str, str] = {
    "gemini-2.5-flash-image": "Nano Banana (Gemini 2.5 Flash Image)",
}
DEFAULT_IMAGE_MODEL = "gemini-2.5-flash-image"

# Số ảnh sản phẩm tối đa người dùng upload (Imagen customization dùng tối đa MAX_SUBJECT_REFS).
MAX_REF_IMAGES = 10

# Khổ + độ phân giải ảnh storyboard (Nano Banana hỗ trợ qua ImageConfig).
STORYBOARD_ASPECT_RATIO = "9:16"
STORYBOARD_IMAGE_SIZE = "2K"

# Imagen 3 Customization (Vertex) — sinh từng cảnh THỰC giữ đúng sản phẩm rồi ghép lưới.
IMAGEN_EDIT_MODEL = "imagen-3.0-capability-001"
MAX_SUBJECT_REFS = 4        # giới hạn ảnh tham chiếu / subject của Imagen customization
PANEL_ASPECT_RATIO = "3:4"  # khổ mỗi panel trong lưới

DEFAULT_PANELS = 8

# Phong cách UGC review TikTok (faceless, clean/premium lifestyle như ảnh mẫu) — dùng chung ảnh + prompt.
_UGC_REVIEW_STYLE = (
    "Clean, bright, premium product-review look: photorealistic high-quality lifestyle / e-commerce "
    "photography, tidy real-world home setting (neat desk, table or shelf with simple tasteful decor), "
    "soft flattering natural daylight, neutral minimal palette, crisp and sharp — looks professional, "
    "NOT messy, NOT gritty, NOT low quality. FACELESS: show only clean hands/forearms holding or using "
    "the product, or the product by itself; never a human face or full body. "
    "The product is the clear HERO, well-lit and in focus. "
    "No on-screen text, no app / TikTok / Reels interface, no icons, no captions baked in, "
    "no logo overlay, no watermark."
)

# Quy tắc faceless + style dùng cho ảnh storyboard (Nano Banana fallback).
_FACELESS_CLEAN_RULES = (
    "- FACELESS: never show a human face; only hands/forearms interacting with the product, "
    "or the product by itself. No faces, no full bodies, no people in the background.\n"
    "- Authentic TikTok UGC phone-shot look: handheld smartphone vibe, real lived-in home setting, "
    "natural soft window light, genuine and casual (NOT a polished studio / stock ad).\n"
    "- Must look like a REAL PHOTOGRAPH of the actual product — match the realism of real product photos; "
    "NOT a 3D render, NOT CGI, NOT a glossy fake mockup.\n"
    "- The PRODUCT from the reference image(s) is the HERO and must look identical everywhere "
    "(same shape, color, material, proportions and details).\n"
    "- Keep the product identity CONSISTENT across the whole image.\n"
    "- ABSOLUTELY NO phone screen, NO app / TikTok / Reels interface, NO icons, NO buttons, "
    "NO search bar, NO text, NO captions, NO numbers, NO logo overlay, NO watermark.\n"
)

# Quy tắc physics/logic — chống ảnh vô lý (tay xuyên sản phẩm, méo, lơ lửng, gộp lung tung, gương soi người).
_PHYSICAL_LOGIC_RULES = (
    "- PHYSICALLY PLAUSIBLE & LOGICAL: every scene must make real-world sense, with correct scale and "
    "proportions between the hands, the product and the surroundings.\n"
    "- HANDS: natural human hands with EXACTLY five fingers each, correct anatomy and a natural grip; "
    "hands hold or touch the product CORRECTLY and NEVER pass through, clip into or merge with the product "
    "or any surface.\n"
    "- PRODUCT: render it as ONE single clean object that EXACTLY matches the reference; keep its exact "
    "real shape — NOT distorted, warped, melted, stretched, bent, duplicated or floating. DO NOT merge, "
    "fuse, jumble, pile or combine it with other objects; DO NOT stack or float extra items, tubes or cups "
    "onto/above it. It sits, mounts or is held in a gravity-correct, physically supported way.\n"
    "- COMPOSITION: keep it SIMPLE and uncluttered — focus on the product (and at most the hands). "
    "No busy backgrounds, no random extra objects crowding the product.\n"
    "- ABSOLUTELY NO people anywhere — including NO mirrors or reflective/shiny surfaces showing any person, "
    "NO human reflection, NO human silhouette, NO body in the background.\n"
    "- NO impossible arrangements, NO objects intersecting or overlapping unnaturally, NO extra or missing "
    "parts, NO nonsensical interactions.\n"
)


# ── Helpers: Gemini image parts & trích ảnh kết quả ─────────────────────────

def _image_parts(images: list[tuple[bytes, str]]) -> list:
    """Chuyển list (bytes, mime) thành list types.Part (cho Gemini multimodal)."""
    return [
        types.Part.from_bytes(data=data, mime_type=mime or "image/png")
        for data, mime in images
    ]


def _extract_genai_image(response) -> bytes:
    """Lấy bytes ảnh inline đầu tiên từ response generate_content của Gemini."""
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                return inline.data
    raise RuntimeError(
        "Nano Banana không trả về ảnh — thử lại, đổi ảnh input, hoặc kiểm tra billing GEMINI_API_KEY."
    )


# ── Sinh ảnh STORYBOARD (lưới nhiều bước) bằng Nano Banana (Gemini) ──────────

def generate_storyboard_banana(
    client: genai.Client,
    *,
    product_images: list[tuple[bytes, str]],
    scene_images: list[tuple[bytes, str]],
    idea: str,
    panels: int = DEFAULT_PANELS,
    variation_index: int = 1,
    total: int = 1,
    model: str = DEFAULT_IMAGE_MODEL,
) -> bytes:
    """Sinh 1 ảnh storyboard dạng lưới (panels panel) bằng Nano Banana → bytes ảnh."""
    instruction = (
        f"Create ONE photorealistic STORYBOARD GRID image: a neat grid of {panels} equal panels "
        "(thin clean white gutters between panels) — a faceless UGC product-REVIEW sequence for TikTok, "
        "from unboxing to using and experiencing the product.\n"
        "Each panel = ONE step, in this review order: "
        "1) hands opening the delivery box / unboxing, 2) taking the product out of the box / first look, "
        "3) close-up of the product's key detail, 4) setting it up (plug in / mount / place it), "
        "5) the product turned on and working, 6) hands using / interacting with it, "
        "7) the product in real use in the room, 8) final beauty shot in a styled home setting.\n"
        "CRITICAL — PRODUCT CONSISTENCY: every single panel must show the EXACT SAME product as the "
        "reference image — identical design, shape, size, color, digits/LED layout and every detail. "
        "DO NOT invent different product variants, DO NOT change the product between panels, "
        "DO NOT add any brand text or logo onto it.\n"
        + _FACELESS_CLEAN_RULES
        + _PHYSICAL_LOGIC_RULES
        + "- EACH individual panel MUST be PORTRAIT orientation (vertical, clearly TALLER than wide, "
        "like a phone-photo crop) — NOT wide landscape strips.\n"
        "- Arrange the portrait panels in a GRID of 2 COLUMNS × several ROWS (e.g. 2×3 or 2×4), "
        "equal size, with thin white gutters. Do NOT stack wide panels in a single column.\n"
        "- The overall image is vertical/portrait.\n"
        "- Use the PRODUCT reference image(s) for the EXACT product identity (shape, color, details).\n"
        "- Use the SCENE reference image(s) as the REALISM ANCHOR: they are REAL-LIFE photos of this "
        "product, so closely MATCH their authentic photographic look — same real lighting, textures, "
        "materials, depth of field, color grading, camera feel and natural imperfections. Every panel must "
        "look like a REAL PHOTO of the actual product (NOT a 3D render, NOT CGI, NOT a fake mockup).\n"
    )
    if idea.strip():
        instruction += f"- Product / context: {idea.strip()}\n"
    if total > 1:
        instruction += (
            f"- This is concept variation {variation_index} of {total}; vary the angles and steps "
            "so it differs from the other variations.\n"
        )

    ref_images = (list(product_images) + list(scene_images))[:MAX_REF_IMAGES]
    contents: list = []
    if ref_images:
        contents.append("REFERENCE IMAGE(S) — product first, then scene:")
        contents += _image_parts(ref_images)
    contents.append(instruction)

    response = call_with_retry(
        client.models.generate_content,
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=STORYBOARD_ASPECT_RATIO,
                image_size=STORYBOARD_IMAGE_SIZE,
            ),
        ),
    )
    track_response(None, response, "image")
    return _extract_genai_image(response)


def _scene_image_banana(
    client: genai.Client,
    *,
    product_images: list[tuple[bytes, str]],
    scene_images: list[tuple[bytes, str]] | None = None,
    subject_desc: str,
    scene: str,
    model: str = DEFAULT_IMAGE_MODEL,
) -> bytes:
    """1 frame góc quay đơn (9:16) giữ ĐÚNG sản phẩm — dùng làm first-frame cho Veo image-to-video."""
    scene_images = scene_images or []
    instruction = (
        f"Create ONE photorealistic vertical 9:16 photo for a TikTok product review. {scene}\n"
        f"Show the EXACT SAME product as the PRODUCT reference image — identical {subject_desc}: same design, "
        "shape, size, color, digits/LED layout and every detail. DO NOT invent a different product, "
        "DO NOT change it, DO NOT add any brand text or logo onto it.\n"
        "If SCENE reference image(s) are given, treat them as the REALISM ANCHOR (real-life photos of this "
        "product): match their authentic real-photo look — real lighting, textures, depth of field, camera "
        "feel. Make it look like a REAL PHOTO, NOT a 3D render or CGI.\n"
        + _PHYSICAL_LOGIC_RULES + _UGC_REVIEW_STYLE
    )
    contents: list = ["PRODUCT REFERENCE IMAGE(S):"]
    contents += _image_parts(product_images[:MAX_REF_IMAGES])
    if scene_images:
        contents.append("SCENE REFERENCE IMAGE(S) (real-life look to match):")
        contents += _image_parts(scene_images[:MAX_REF_IMAGES])
    contents.append(instruction)
    resp = call_with_retry(
        client.models.generate_content,
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=STORYBOARD_ASPECT_RATIO, image_size=STORYBOARD_IMAGE_SIZE,
            ),
        ),
    )
    track_response(None, resp, "image")
    return _extract_genai_image(resp)


# ── Sinh ảnh THỰC giữ đúng sản phẩm bằng Imagen Customization + ghép lưới ────

def _plan_steps(
    client: genai.Client,
    *,
    product_images: list[tuple[bytes, str]],
    idea: str,
    panels: int,
    variation_index: int = 1,
    total: int = 1,
    text_model: str = TEXT_MODEL,
) -> tuple[str, list[str]]:
    """Hỏi Gemini: tên sản phẩm ngắn + danh sách `panels` cảnh (mỗi cảnh 1 bước, faceless)."""
    import json
    import re

    instruction = (
        "Look at the product image(s). Return ONLY JSON (no markdown) of the form "
        '{"product": "<short 2-5 word product name>", "steps": ["<scene>", ...]}. '
        f"Give EXACTLY {panels} steps for a FACELESS TikTok UGC product-review video, in natural review "
        "order: attention-grabbing hero shot of the product in hand -> unboxing / first impression -> "
        "close-up of a key feature or detail -> hands demonstrating the main use -> showing it working / "
        "the result or benefit -> final satisfying shot in the real setting. "
        "Each step = a short visual description of ONE shot, faceless (hands/forearms only or product alone), "
        "clean premium lifestyle look in a tidy real home. Each scene <= 18 words, concrete. "
        "Keep each shot SIMPLE (one product, at most hands — no clutter). "
        "DO NOT place the scene in front of a mirror or any reflective surface (avoids showing people)."
    )
    if idea.strip():
        instruction += f" Product/context: {idea.strip()}."
    if total > 1:
        instruction += f" This is variation {variation_index} of {total}; vary angles/order."

    contents: list = []
    if product_images:
        contents.append("PRODUCT IMAGE(S):")
        contents += _image_parts(product_images)
    contents.append(instruction)
    resp = call_with_retry(client.models.generate_content, model=text_model, contents=contents)
    track_response(None, resp, "text")

    txt = (resp.text or "").strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(txt)
        product = str(data.get("product") or "").strip() or (idea[:40].strip() or "product")
        steps = [str(s).strip() for s in (data.get("steps") or []) if str(s).strip()]
    except Exception:
        product = idea[:40].strip() or "product"
        steps = []
    return product, steps[:panels]


def _imagen_scene(
    client: genai.Client,
    *,
    product_images: list[tuple[bytes, str]],
    subject_desc: str,
    scene: str,
    aspect_ratio: str = PANEL_ASPECT_RATIO,
) -> bytes:
    """1 ảnh lifestyle THỰC giữ đúng sản phẩm bằng Imagen customization (subject = product)."""
    refs = [
        types.SubjectReferenceImage(
            reference_id=1,
            reference_image=types.Image(image_bytes=data, mime_type=mime or "image/png"),
            config=types.SubjectReferenceConfig(
                subject_type="SUBJECT_TYPE_PRODUCT", subject_description=subject_desc,
            ),
        )
        for data, mime in product_images[:MAX_SUBJECT_REFS]
    ]
    if not refs:
        raise RuntimeError("Cần ít nhất 1 ảnh sản phẩm cho Imagen customization.")
    prompt = (
        f"Clean premium TikTok product-review photo, vertical. {scene} "
        f"Use ONLY the {subject_desc} [1] itself from the reference (the product object) — IGNORE the "
        "reference photo's original background, packaging and surroundings; recreate the product fresh in "
        "the new scene described above. "
        f"The {subject_desc} must look IDENTICAL to the reference product "
        "(same shape, color, material, proportions, details). " + _UGC_REVIEW_STYLE
    )
    r = call_with_retry(
        client.models.edit_image,
        model=IMAGEN_EDIT_MODEL,
        prompt=prompt,
        reference_images=refs,
        config=types.EditImageConfig(number_of_images=1, aspect_ratio=aspect_ratio),
    )
    img = r.generated_images[0].image if r.generated_images else None
    data = getattr(img, "image_bytes", None) if img else None
    if not data:
        raise RuntimeError("Imagen customization không trả về ảnh.")
    return data


def _isolate_product(
    client: genai.Client, image: tuple[bytes, str], model: str = DEFAULT_IMAGE_MODEL,
) -> tuple[bytes, str]:
    """Tách CHỈ sản phẩm khỏi ảnh gốc (Nano Banana) → ảnh sản phẩm sạch trên nền trơn.

    Nếu lỗi thì trả lại ảnh gốc (không chặn flow).
    """
    instruction = (
        "Extract ONLY the single main product object from this photo and place it centered, full and "
        "unobstructed, on a plain solid light-gray studio background. Remove the original background, any "
        "packaging, boxes, hands, props, people and text. Keep the product EXACTLY identical — same shape, "
        "color, material, proportions and details. Output a clean studio product cutout, sharp and well-lit."
    )
    try:
        resp = call_with_retry(
            client.models.generate_content,
            model=model,
            contents=_image_parts([image]) + [instruction],
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        return _extract_genai_image(resp), "image/png"
    except Exception:
        return image


def _compose_grid(images: list[bytes], cols: int = 2, gutter: int = 14) -> bytes:
    """Ghép nhiều ảnh panel thành 1 lưới portrait (cols cột), gutter trắng giữa các panel."""
    from io import BytesIO

    from PIL import Image

    ims = [Image.open(BytesIO(b)).convert("RGB") for b in images]
    w = min(i.width for i in ims)
    h = min(i.height for i in ims)
    ims = [i.resize((w, h)) for i in ims]
    rows = (len(ims) + cols - 1) // cols
    W = cols * w + (cols + 1) * gutter
    H = rows * h + (rows + 1) * gutter
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    for idx, im in enumerate(ims):
        r, c = divmod(idx, cols)
        canvas.paste(im, (gutter + c * (w + gutter), gutter + r * (h + gutter)))
    out = BytesIO()
    canvas.save(out, "PNG")
    return out.getvalue()


def generate_storyboard_imagen(
    client: genai.Client,
    *,
    product_images: list[tuple[bytes, str]],
    scene_images: list[tuple[bytes, str]],
    idea: str,
    panels: int = DEFAULT_PANELS,
    variation_index: int = 1,
    total: int = 1,
) -> bytes:
    """Sinh từng cảnh THỰC (Imagen, giữ sản phẩm) cho mỗi bước rồi ghép thành 1 ảnh lưới.

    Trước tiên TÁCH sản phẩm khỏi nền ảnh gốc để chỉ dùng đúng sản phẩm (không bê cả tấm ảnh).
    """
    from concurrent.futures import ThreadPoolExecutor

    product, steps = _plan_steps(
        client, product_images=product_images, idea=idea, panels=panels,
        variation_index=variation_index, total=total,
    )
    if not steps:
        steps = ["the product shown in a tidy real-world setting, faceless"] * panels

    # Tách sản phẩm khỏi nền (1 lần, dùng lại cho mọi panel) → Imagen bám đúng sản phẩm.
    refs = list(product_images[:MAX_SUBJECT_REFS])
    with ThreadPoolExecutor(max_workers=min(MAX_SUBJECT_REFS, len(refs))) as ex:
        clean_products = list(ex.map(lambda im: _isolate_product(client, im), refs))

    def _one(scene: str) -> bytes:
        return _imagen_scene(client, product_images=clean_products, subject_desc=product, scene=scene)

    with ThreadPoolExecutor(max_workers=min(4, len(steps))) as ex:
        panel_imgs = list(ex.map(_one, steps))
    return _compose_grid(panel_imgs, cols=2)


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
    """Sinh 1 prompt video review TikTok UGC (faceless, tiếng Anh), mô tả đúng sản phẩm trong ảnh."""
    target_label = TARGET_MODELS.get(target_model, TARGET_MODELS[DEFAULT_TARGET])
    instruction = (
        f"You write prompts for a FACELESS TikTok UGC product-REVIEW video for {target_label} "
        "(vertical 9:16). Look at the product image(s) and write ONE prompt in ENGLISH "
        "using EXACTLY this structure and tone (keep the headings/lines):\n\n"
        "Create a clean, premium vertical TikTok-style UGC review video of "
        "<one concise product description> (exactly like the reference image), in a tidy real home, "
        "faceless (hands only).\n\n"
        "Review flow:\n"
        "1. Hook: a close, attention-grabbing shot of the product in hand.\n"
        "2. <unboxing / first impression>\n"
        "3. <show a key feature or detail in close-up>\n"
        "4. <hands demonstrate the main use>\n"
        "5. <show it working / the result or benefit>\n"
        "6. <final satisfying shot in the real setting>\n"
        "(list 5-8 concrete steps suited to THIS product, faceless, hands only, natural review order)\n\n"
        "Camera: smooth, steady close-ups on hands and product, POV and slight top-down, vertical 9:16, "
        "keep product proportions consistent.\n"
        "Lighting: soft, bright, flattering natural daylight — clean and premium, NOT messy or gritty.\n"
        "Do not show faces, do not bake in on-screen text or captions, do not exaggerate movements.\n"
        "Keep the product form, size, and proportions IDENTICAL to the reference image.\n"
        "Style: clean, premium yet believable UGC review — high-quality lifestyle look, the product is the "
        "clear hero, well-lit and in focus.\n"
        "Duration: short, 15-30 seconds, smooth natural transitions.\n\n"
        "RULES: replace every <...> with content specific to the product seen in the image. "
        "All actions must be faceless (hands only) and authentic phone-shot. "
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

def _optimize_video_prompt(
    client: genai.Client,
    base_prompt: str,
    *,
    first_frame: bytes | None = None,
    text_model: str = TEXT_MODEL,
) -> str:
    """Cấu trúc lại prompt thành 'super prompt' Veo thích đọc (như Gemini app pre-process).

    Nhìn cả frame đầu (nếu có) để mô tả chuyển động từ ảnh đó. Lỗi thì trả prompt gốc.
    """
    instruction = (
        "You are a Veo 3.1 video-prompt engineer. Rewrite the request below into ONE optimized English "
        "prompt that Veo 3.1 reads best. Structure it clearly in this order: "
        "[Scene/setting] [Subject — keep the product IDENTICAL to the starting image] "
        "[ONE single action] [Camera movement] [Lighting] [Mood & style] [Motion & physics].\n"
        "CRITICAL for natural, non-glitchy motion:\n"
        "- Describe ONLY ONE simple, slow, smooth, continuous action (~8s). If the request lists several "
        "steps, PICK JUST ONE coherent action — do NOT cram multiple steps (cramming causes chaotic, "
        "unnatural motion).\n"
        "- Enforce REALISTIC PHYSICS: objects are solid with real weight; hands grip and touch the product "
        "naturally and NEVER pass through / clip into the product, surfaces or each other; no morphing, no "
        "warping, no melting; the product keeps its exact shape; calm, minimal, steady motion.\n"
        "Constraints: vertical 9:16; FACELESS (hands/forearms only, no human face); clean premium UGC "
        "review look; NO on-screen text, NO captions, NO logo, NO watermark. "
        "Output ONLY the final prompt text — no preamble, no markdown.\n\nREQUEST:\n" + base_prompt
    )
    contents: list = []
    if first_frame:
        contents.append("STARTING FRAME (the video begins from this exact image):")
        contents += _image_parts([(first_frame, "image/png")])
    contents.append(instruction)
    try:
        resp = call_with_retry(
            client.models.generate_content, model=text_model, contents=contents
        )
        track_response(None, resp, "text")
        return (resp.text or "").strip() or base_prompt
    except Exception:
        return base_prompt


_VEO_POLL_TIMEOUT = 600  # giây
_VEO_POLL_INTERVAL = 10
VEO_MAX_DURATION = 8        # Veo 3.1 tối đa 8s/clip → ghép nhiều clip để video dài hơn
VEO_RESOLUTION_DEFAULT = "1080p"  # chất lượng cao như Gemini app (override bằng env VEO_RESOLUTION)
DEFAULT_VIDEO_CLIPS = 3     # số clip mặc định; mỗi clip 1 cảnh/góc quay riêng (~8s)
MAX_VIDEO_CLIPS = 6         # tối đa 6 cảnh để video có nhiều góc/chuyển cảnh (mỗi cảnh tốn credit)


def generate_video_veo(
    client: genai.Client,
    *,
    prompt: str,
    product_images: list[tuple[bytes, str]],
    storyboard_image: bytes | None = None,
    aspect_ratio: str = "9:16",
    model: str | None = None,
    optimize_prompt: bool = True,
) -> bytes:
    """Tạo video bằng Veo từ prompt + ảnh sản phẩm (ASSET) + ảnh storyboard (STYLE).

    Trả về bytes video MP4. Veo cần billing; quá trình mất vài phút.
    Bắt chước Gemini app: tự cấu trúc lại prompt thành super-prompt + bật enhance_prompt + ép 9:16/1080p.
    """
    import time

    neg = (
        "human faces, people, human body, person in mirror, mirror reflection of a person, human reflection, "
        "on-screen text, captions, watermark, app interface, "
        "objects passing through each other, clipping through objects, intersecting geometry, "
        "morphing, melting, warping, distorted product, changing product shape, merged objects, "
        "jumbled objects, floating toothpaste tube, deformed hands, extra fingers, fused fingers, "
        "broken anatomy, chaotic motion, jittery fast movement, shaky, glitchy, unstable, floating objects, "
        "physically impossible motion, teleporting, duplicated product"
    )
    # Trên Vertex, Veo xuất MP4 ra GCS bucket → cần VEO_OUTPUT_GCS_URI=gs://<bucket>/<prefix>.
    is_vertex = bool(getattr(client, "vertexai", False))
    if model is None:
        model = os.getenv("VEO_MODEL") or (VEO_VERTEX_MODEL if is_vertex else VEO_MODEL)
    gcs_out = os.getenv("VEO_OUTPUT_GCS_URI", "").strip() if is_vertex else ""
    if is_vertex and not gcs_out:
        raise RuntimeError(
            "Vertex Veo cần biến VEO_OUTPUT_GCS_URI=gs://<bucket>/<prefix> trong .env "
            "(Veo ghi video ra GCS bucket)."
        )
    extra = {"output_gcs_uri": gcs_out} if gcs_out else {}
    if is_vertex:
        extra["duration_seconds"] = VEO_MAX_DURATION  # kéo dài hết cỡ mỗi clip (Veo 3.1 max 8s)
        extra["enhance_prompt"] = True                # bộ tự tinh chỉnh prompt của Veo (như Gemini app)
        res = os.getenv("VEO_RESOLUTION", VEO_RESOLUTION_DEFAULT).strip()
        if res:
            extra["resolution"] = res  # 1080p cho nét như Gemini app
    # Gemini API chỉ hỗ trợ reference type ASSET (STYLE là của Vertex) → chỉ dùng ảnh sản phẩm.
    first_img = product_images[0] if product_images else (
        (storyboard_image, "image/png") if storyboard_image else None
    )
    # Pre-process prompt thành "super prompt" (như Gemini app) — nhìn frame đầu để tả chuyển động.
    if optimize_prompt and is_vertex:
        prompt = _optimize_video_prompt(
            client, prompt, first_frame=(first_img[0] if first_img else None),
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
            reference_images=refs, negative_prompt=neg, **extra,
        )
        return client.models.generate_videos(model=model, prompt=prompt, config=config)

    def _start_with_first_frame():
        config = types.GenerateVideosConfig(
            aspect_ratio=aspect_ratio, number_of_videos=1, negative_prompt=neg, **extra,
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
        if uri.startswith("gs://"):
            return _download_gcs(uri)
        import requests
        key = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY") or ""
        sep = "&" if "?" in uri else "?"
        r = requests.get(f"{uri}{sep}key={key}" if key else uri, timeout=300)
        r.raise_for_status()
        return r.content

    raise RuntimeError("Veo trả về video nhưng không lấy được dữ liệu.")


def _download_gcs(gs_uri: str) -> bytes:
    """Tải bytes 1 object từ gs://bucket/path (dùng ADC — cần google-cloud-storage)."""
    try:
        from google.cloud import storage
    except ImportError:
        raise RuntimeError(
            "Thiếu thư viện google-cloud-storage để tải video Veo từ GCS. "
            "Cài bằng: uv add google-cloud-storage"
        )
    path = gs_uri[len("gs://"):]
    bucket_name, _, blob_path = path.partition("/")
    blob = storage.Client().bucket(bucket_name).blob(blob_path)
    return blob.download_as_bytes()


def _stitch_videos(clips: list[bytes]) -> bytes:
    """Nối nhiều clip MP4 thành 1 video liên tục bằng ffmpeg."""
    import os as _os
    import subprocess
    import tempfile

    clips = [c for c in clips if c]
    if not clips:
        raise RuntimeError("Không có clip nào để nối.")
    if len(clips) == 1:
        return clips[0]

    with tempfile.TemporaryDirectory() as td:
        paths = []
        for i, c in enumerate(clips):
            p = _os.path.join(td, f"clip_{i:02d}.mp4")
            with open(p, "wb") as f:
                f.write(c)
            paths.append(p)
        listf = _os.path.join(td, "list.txt")
        with open(listf, "w") as f:
            for p in paths:
                f.write(f"file '{p}'\n")
        out = _os.path.join(td, "out.mp4")
        # Thử nối nhanh (copy codec); nếu lỗi thì re-encode cho đồng nhất.
        base = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf]
        try:
            subprocess.run(base + ["-c", "copy", out], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            subprocess.run(
                base + ["-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", out],
                check=True, capture_output=True,
            )
        with open(out, "rb") as f:
            return f.read()


def generate_review_video(
    client: genai.Client,
    *,
    product_images: list[tuple[bytes, str]],
    scene_images: list[tuple[bytes, str]] | None = None,
    idea: str,
    clips: int = DEFAULT_VIDEO_CLIPS,
    aspect_ratio: str = "9:16",
) -> bytes:
    """Sinh video review NHIỀU CẢNH liên tục như cách Gemini app: mỗi cảnh 1 frame góc quay
    (Nano Banana, giữ sản phẩm) → image-to-video Veo 1080p → nối lại.

    Mỗi clip ~8s → tổng ≈ clips × 8s. clips tối đa MAX_VIDEO_CLIPS (tiết kiệm token).
    """
    from concurrent.futures import ThreadPoolExecutor

    clips = max(1, min(clips, MAX_VIDEO_CLIPS))
    product, steps = _plan_steps(
        client, product_images=product_images, idea=idea, panels=clips,
    )
    if not steps:
        steps = [f"the {product} shown and used by faceless hands in a tidy home"] * clips
    steps = (steps + steps)[:clips]  # đủ số cảnh

    # 1) Sinh 1 frame góc quay cho MỖI cảnh (giữ đúng sản phẩm, bám realism ảnh scene) — song song.
    with ThreadPoolExecutor(max_workers=clips) as ex:
        frames = list(ex.map(
            lambda s: _scene_image_banana(
                client, product_images=product_images, scene_images=scene_images,
                subject_desc=product, scene=s,
            ),
            steps,
        ))

    # 2) image-to-video từ mỗi frame + prompt (như Gemini app) — song song.
    def _clip(frame_scene: tuple[bytes, str]) -> bytes:
        frame, scene = frame_scene
        prompt = (
            f"Vertical TikTok UGC product-review shot. ONE single slow, smooth action: {scene} "
            "Faceless: hands/forearms only, no human face. Realistic physics — solid objects with weight, "
            "hands touch the product naturally and NEVER pass through or clip into it, no morphing or warping, "
            "the product keeps its exact shape. Clean premium lifestyle look, soft natural daylight, calm "
            "steady camera, minimal natural motion. No on-screen text, no logo, no watermark."
        )
        return generate_video_veo(
            client, prompt=prompt, product_images=[],
            storyboard_image=frame, aspect_ratio=aspect_ratio,
        )

    with ThreadPoolExecutor(max_workers=clips) as ex:
        clip_bytes = list(ex.map(_clip, list(zip(frames, steps))))
    return _stitch_videos(clip_bytes)


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
    """Trả về {'image': bytes (storyboard lưới), 'prompt': str (template video UGC)}.

    Dùng Nano Banana: nó nhận trực tiếp ảnh sản phẩm nên GIỮ ĐÚNG sản phẩm
    (Imagen customization hay bịa ra sản phẩm khác — đã bỏ).
    """
    image_bytes = generate_storyboard_banana(
        client,
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

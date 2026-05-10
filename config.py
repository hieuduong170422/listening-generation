from dataclasses import dataclass

TEXT_MODEL = "gemini-2.5-flash"
TTS_MODEL = "gemini-2.5-flash-preview-tts"

TEXT_MODEL_OPTIONS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.5-flash-lite",
]

AUDIENCE_LEVELS: dict[str, str] = {
    "beginner": (
        "Beginner English learners (A2-B1). Use simple, common vocabulary and short sentences. "
        "Briefly explain any uncommon word with a quick everyday example."
    ),
    "intermediate": (
        "Intermediate English learners (B1-B2). Use natural conversational vocabulary. "
        "When you use a useful phrase or idiom, briefly explain it once with a short example."
    ),
    "advanced": (
        "Advanced English learners (B2-C1). Rich vocabulary, idioms welcome, faster register. "
        "Still keep enunciation clear and pacing comfortable."
    ),
}
DEFAULT_AUDIENCE = "intermediate"

TONES: dict[str, str] = {
    "warm_friendly": "warm, friendly, encouraging — like two friends chatting",
    "energetic": "high-energy, enthusiastic, lots of genuine reactions",
    "calm_clear": "calm, clear, measured — like a thoughtful teacher",
    "humorous": "light-hearted, with gentle humor and natural laughter",
}
DEFAULT_TONE = "warm_friendly"

DURATION_PRESETS: list[int] = [5, 10, 15, 20, 30, 45, 60]
DEFAULT_TOTAL_MINUTES = 20

SPEECH_PACES: dict[str, str] = {
    "normal": "Read the following conversation in a natural, conversational pace:",
    "slow": (
        "Read the following conversation slowly and clearly, with calm pacing and "
        "slightly longer pauses between sentences, as if speaking to English learners. "
        "Pronounce each word distinctly. Do not rush:"
    ),
    "very_slow": (
        "Read the following conversation very slowly, deliberately, and clearly, with "
        "noticeable pauses between sentences and clear enunciation of every word. "
        "Imagine you are teaching beginner English learners — patient and unhurried:"
    ),
    "expressive": (
        "Read the following conversation with warm, expressive intonation, natural pacing, "
        "and genuine reactions — like a friendly podcast:"
    ),
}
DEFAULT_PACE = "slow"

PACE_WPM: dict[str, int] = {
    "normal": 175,
    "slow": 145,
    "very_slow": 120,
    "expressive": 165,
}

DEFAULT_HOST_1_NAME = "Emma"
DEFAULT_HOST_2_NAME = "James"
DEFAULT_HOST_3_NAME = "Sophia"
DEFAULT_HOST_4_NAME = "Daniel"

DEFAULT_NUM_SPEAKERS = 2
MAX_NUM_SPEAKERS = 4
DEFAULT_HOST_NAMES = [
    DEFAULT_HOST_1_NAME, DEFAULT_HOST_2_NAME, DEFAULT_HOST_3_NAME, DEFAULT_HOST_4_NAME,
]
DEFAULT_VOICES_BY_INDEX = ["Leda", "Iapetus", "Aoede", "Charon"]

DEFAULT_SPEAKER_1 = "Leda"
DEFAULT_SPEAKER_2 = "Iapetus"

DEFAULT_SHOW_NAME = "English Unlocked with Audivy"
DEFAULT_CHANNEL_NAME = "Audivy"

AVAILABLE_VOICES = [
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda",
    "Orus", "Aoede", "Callirrhoe", "Autonoe", "Enceladus", "Iapetus",
    "Umbriel", "Algieba", "Despina", "Erinome", "Algenib", "Rasalgethi",
    "Laomedeia", "Achernar", "Alnilam", "Schedar", "Gacrux", "Pulcherrima",
    "Achird", "Zubenelgenubi", "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
]


@dataclass
class Style:
    key: str
    label: str
    instruction: str


STYLES = {
    "podcast": Style(
        key="podcast",
        label="Podcast 2 người trò chuyện tự nhiên",
        instruction=(
            "Viết kịch bản podcast tiếng Việt giữa 2 người dẫn chương trình về chủ đề sau. "
            "Giọng văn tự nhiên, có cảm xúc, có chỗ cười nhẹ, có chỗ ngạc nhiên, có ví dụ cụ thể. "
            "Hai người nói qua lại, không độc thoại dài. Mỗi lượt nói 1-3 câu. "
            "Tổng độ dài khoảng 15-25 lượt thoại."
        ),
    ),
    "interview": Style(
        key="interview",
        label="Phỏng vấn (Speaker1 hỏi, Speaker2 trả lời chuyên gia)",
        instruction=(
            "Viết kịch bản phỏng vấn tiếng Việt. Speaker1 là người dẫn hỏi câu hỏi sâu, "
            "Speaker2 là chuyên gia trả lời chi tiết, có dẫn chứng. "
            "5-8 cặp hỏi-đáp. Câu hỏi rõ ràng, câu trả lời 2-4 câu mỗi lượt."
        ),
    ),
    "debate": Style(
        key="debate",
        label="Tranh luận 2 quan điểm trái chiều",
        instruction=(
            "Viết kịch bản tranh luận tiếng Việt. Speaker1 ủng hộ chủ đề, Speaker2 phản biện. "
            "Mỗi bên đưa ra luận điểm + ví dụ. Cuối cùng có đoạn tổng kết cân bằng. "
            "Khoảng 10-16 lượt thoại."
        ),
    ),
    "english_learning": Style(
        key="english_learning",
        label="English-learning podcast for YouTube (2 hosts)",
        instruction=(
            "Write a natural-sounding English podcast script between two hosts, designed for "
            "English learners listening to improve their listening skill. "
            "OUTPUT LANGUAGE: 100% English only. Do NOT use Vietnamese, Chinese, Spanish, French, "
            "or any other language — not even for greetings. Every single line must be entirely in English. "
            "Tone: warm, encouraging, conversational with light humor and genuine reactions. "
            "Use clear, everyday English. Avoid overly complex vocabulary or fast slang, but keep it natural — "
            "no robotic textbook lines. When introducing a useful word, phrase, or idiom, briefly explain it "
            "in English with a quick example. Each turn 1-3 sentences. Hosts trade turns frequently. "
            "Include practical, actionable tips and concrete real-life examples. "
            "Speaker1 acts as the friendly host guiding the topic; Speaker2 gives expert advice and examples."
        ),
    ),
}

# TTS Script Gen

Tool sinh kịch bản đối thoại 2 người + render thành audio bằng Gemini API.
Bạn chỉ cần nhập **chủ đề**, tool sẽ:

1. Gọi Gemini sinh kịch bản (`Speaker1` / `Speaker2`).
2. Gọi Gemini multi-speaker TTS render thành file WAV.
3. Lưu cả `.wav` + `.txt` transcript vào `history/`.

## Setup

```bash
cd ~/Desktop/tts-script-gen
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Mở .env, dán GEMINI_API_KEY (lấy ở https://aistudio.google.com/app/apikey)
```

## Dùng tương tác

```bash
python main.py
# → Nhập chủ đề
# → Chọn style (podcast / interview / debate)
# → Tool tự sinh + render
```

## Dùng qua CLI

```bash
python main.py --topic "Trí tuệ nhân tạo trong giáo dục" --style podcast
python main.py --topic "Bitcoin có phải bong bóng?" --style debate \
  --speaker1 Leda --speaker2 Iapetus \
  --out output/btc.wav
```

## Đổi giọng đọc

Speaker mặc định: **Leda** (Speaker1) + **Iapetus** (Speaker2).
Danh sách 30 voice xem trong [config.py](config.py).

## Đổi style hoặc thêm style mới

Mở [config.py](config.py), sửa `STYLES` dict — thêm `Style(...)` mới với `instruction` riêng.

## File output

- `history/<topic-slug>_<timestamp>.wav` — audio
- `history/<topic-slug>_<timestamp>.txt` — transcript

## Cấu trúc

- [config.py](config.py) — voices + styles
- [script_generator.py](script_generator.py) — topic → dialogue script
- [tts_renderer.py](tts_renderer.py) — script → WAV (multi-speaker)
- [main.py](main.py) — CLI entry

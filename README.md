# Audivy Studio

Streamlit app gộp 2 công cụ AI dùng Gemini:

1. **🎙️ TTS Script Gen** — sinh kịch bản hội thoại long-form + render audio (podcast học ngoại ngữ).
2. **📋 Prompt Templates** — tạo / quản lý / chạy các prompt template tái sử dụng với `{{placeholder}}`.

Cả 2 chạy chung 1 app, 1 login, điều hướng bằng menu sidebar.

## Setup

```bash
cd ~/Desktop/tts-script-gen
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Mở .env, dán GEMINI_API_KEY (lấy ở https://aistudio.google.com/apikey)
```

## Chạy

```bash
streamlit run app.py
```

→ Mở `http://localhost:8501`. Đăng nhập (nếu có `APP_PASSWORD`), rồi chọn trang từ sidebar.

## Cấu trúc

```
app.py                  → Entry: load .env, init DB, auth gate, st.navigation
auth.py                 → Login + admin check (dùng chung)
paths.py                → ROOT / HISTORY_DIR / UPLOADS_DIR

pages/
  ├── tts_studio.py      → TTS Script Gen (Generate + Stats tabs)
  ├── pt_home.py         → Prompt Templates: danh sách + CRUD
  ├── pt_create.py       → Tạo / sửa template
  ├── pt_run.py          → Chạy template → điền form → gọi API
  └── pt_history.py      → Lịch sử chạy template

# TTS Script Gen modules (flat at root)
config.py, script_generator.py, outline_generator.py,
tts_renderer.py, multi_part.py, topic_suggester.py,
api_utils.py, usage_logger.py

prompt_template/         → Package cho Prompt Templates
  ├── database.py        → SQLite schema (templates.db)
  ├── template_store.py  → CRUD template
  ├── history_store.py   → Lưu lịch sử chạy
  ├── llm_client.py      → Facade google-genai / openai / dashscope
  └── gemini_client.py   → Gemini wrapper

history/                 → Output TTS (.wav, .txt) + usage log
uploads/                 → File upload khi chạy template
templates.db             → SQLite (gitignored)
```

## Biến môi trường

| Biến | Bắt buộc | Mô tả |
|------|----------|-------|
| `GEMINI_API_KEY` | ✅ | Key Gemini, dùng cho cả 2 feature |
| `APP_PASSWORD` | — | Password gate toàn app. Trống = không cần login |
| `ADMIN_USERS` | — | Username (phẩy) được xem tab Stats của TTS. Mặc định `admin` |
| `SDK` | — | Prompt Templates: `google-genai` (mặc định) / `openai` / `dashscope` |

## Deploy

Streamlit Community Cloud — entry point `app.py`. Đặt `GEMINI_API_KEY`, `APP_PASSWORD`,
`ADMIN_USERS` trong Secrets. Lưu ý disk ephemeral: `templates.db` + `history/` mất khi
app restart — download định kỳ nếu cần lưu trữ.

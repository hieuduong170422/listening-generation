# src/prompt_template/ — Core Package

## OVERVIEW

Python package (`prompt_template`) implementing the backend: 3-provider LLM router, SQLite persistence, TTS/audio utils, and API call logging. Zero classes — all module-level functions.

## FILES

| File | Role |
|------|------|
| `llm_client.py` | **Unified facade** — merges model lists from all 3 providers, routes `generate()` to the correct provider based on model ID. Exports `AVAILABLE_MODELS` (~40+ entries) and `get_output_type()`. |
| `gemini_client.py` | Gemini/Veo wrapper. Text/image/video/audio generation. Veo video via async polling (`client.operations.get`). TTS via `speech_config`. |
| `dashscope_client.py` | DashScope native SDK wrapper. Routes to 4 endpoints: `Generation.call()` (text), `MultiModalConversation.call()` (multimodal/image/TTS), `VideoSynthesis.call()` (video). 3 model frozensets control routing. |
| `openai_client.py` | OpenAI-compatible wrapper. Supports text + image inputs via `client.chat.completions.create()`. Merges system prompt into user message for broad compatibility. |
| `gemini_mock.py` | Test double — `set_next_response()`/`set_next_error()` single-use queue. Also serves as self-testing module (runs 10 tests when executed directly). |
| `database.py` | SQLite connection factory (`get_connection()`), schema DDL (`init_db()`), schema migration (`migrate_db()`). WAL mode + FK enforcement. |
| `template_store.py` | CRUD for `templates` + `template_inputs` tables. `create_template()` accepts `output_type` param. `get_template()` returns dict with nested `inputs` list. |
| `history_store.py` | CRUD for `execution_history` table. `save_execution()` serializes `inputs_dict` as JSON. |
| `audio_utils.py` | PCM→WAV via stdlib `wave`. `download_and_save_audio()` via `requests`. `save_base64_audio()` for inline data. |
| `logger.py` | Singleton `get_api_logger()` — file handler to `logs/api.log`. `logging.DEBUG` level. |

## INTERNAL CONVENTIONS

- **Import pattern**: `from prompt_template.module import func` — never `from src.prompt_template`.
- **Response contract**: Every `generate()` returns `{"text": str, "type": str, "response_data": str, "candidates": ...}`.
- **Provider detection**: `get_output_type(model_id)` checks model ID substrings for `tts`→audio, `image`→image, `veo`/`wan`→video, else text.
- **Dotenv**: `dotenv.load_dotenv()` is called at module level in every client file (redundant — `app.py` loads it once). Each client reads its own key: `GEMINI_API_KEY`, `DASHCOPE_API_KEY`, `OPENAI_API_KEY`.
- **Module-level `__init__.py`**: Empty — no re-exports.
- **No classes, no type hints**: Package-wide convention (except `replace_variables()` in pages).

## ROUTING FLOW

```
llm_client.generate(model="gemini-2.5-pro", ...)
  → _get_provider(model) → "google-genai"
  → gemini_client.generate(...)
  → returns {"text": ..., "type": "text", ...}

llm_client.generate(model="qwen-max", ...)
  → _get_provider(model) → "dashscope"
  → dashscope_client.generate(...)
  → returns {"text": ..., "type": "text", ...}
```

## ANTI-PATTERNS (THIS PACKAGE)

- **`dotenv.load_dotenv()` at module level** — 4 of 5 calls are redundant. Causes side effects on import in non-app contexts.
- **`gemini_mock.py` lives in prod package** — test code mixed with production code.
- **`src/prompt_template/pages/`** — empty directory, no purpose.
- **`init_db()` never called from production** — `database.py` creates schema but no prod code invokes it. `templates.db` must pre-exist.

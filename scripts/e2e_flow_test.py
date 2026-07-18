"""E2E smoke test: outline 10 part → script từng part → audio từng part.

Chạy:  .venv/bin/python scripts/e2e_flow_test.py [--parts 10] [--out DIR]

- Sinh outline + script THẬT qua Gemini (test đủ pipeline text).
- Trước khi render audio, cắt script còn AUDIO_MAX_LINES dòng đầu để
  tổng audio ~1 phút — tránh đốt credit ElevenLabs khi smoke test.
- Thành công = đủ N file audio trên disk, mỗi file > MIN_AUDIO_BYTES.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "http://localhost:8000"
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
AUDIO_MAX_LINES = 2          # số dòng thoại đầu mỗi part đem đi TTS
MIN_AUDIO_BYTES = 1_000      # file audio hợp lệ phải lớn hơn ngưỡng này
REQUEST_TIMEOUT = 180        # giây / request (script gen có thể chậm)


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def api(method: str, path: str, token: str | None = None, body: dict | None = None):
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as res:
        content_type = res.headers.get("Content-Type", "")
        raw = res.read()
    if "application/json" in content_type:
        return json.loads(raw)
    return raw


def fail(step: str, exc: Exception) -> None:
    detail = ""
    if isinstance(exc, urllib.error.HTTPError):
        try:
            detail = exc.read().decode()[:500]
        except Exception:
            pass
    print(f"\n❌ FAIL tại bước [{step}]: {exc}\n{detail}")
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parts", type=int, default=10)
    parser.add_argument("--out", type=str, default="")
    args = parser.parse_args()

    out_dir = Path(args.out) if args.out else Path(__file__).parent / "e2e_audio_out"
    out_dir.mkdir(parents=True, exist_ok=True)

    env = read_env(ENV_PATH)
    username = (env.get("ALLOWED_USERS", "").split(",")[0] or "admin").strip()
    password = env.get("APP_PASSWORD", "")

    t0 = time.time()
    print(f"── E2E flow test: {args.parts} parts × 1 phút, audio cắt {AUDIO_MAX_LINES} dòng/part ──")

    # 1. Login
    try:
        login = api("POST", "/api/auth/login", body={"username": username, "password": password})
        token = login["token"]
        print(f"[1] Login OK (user={username})")
    except Exception as exc:
        fail("login", exc)

    # 2. Voices
    try:
        voices = api("GET", "/api/elevenlabs/voices", token=token)["voices"]
        if not voices:
            raise RuntimeError("Không có voice nào từ ElevenLabs")
        voice_ids = [voices[0]["voice_id"], voices[1 % len(voices)]["voice_id"]]
        print(f"[2] Voices OK: {voices[0]['name']} + {voices[1 % len(voices)]['name']}")
    except Exception as exc:
        fail("voices", exc)

    # 3. Outline
    try:
        t = time.time()
        outline_res = api("POST", "/api/podcast/outline", token=token, body={
            "topic": "Mẹo tập trung khi làm việc tại nhà",
            "num_parts": args.parts,
            "minutes_per_part": 1,
            "text_model": "gemini-2.5-flash",
            "language": "vi",
        })
        outline = outline_res["outline"]
        n_parts = len(outline["parts"])
        print(f"[3] Outline OK: {n_parts} parts, total {outline['total_minutes']} phút ({time.time()-t:.1f}s)")
        if n_parts != args.parts:
            print(f"    ⚠ Outline trả {n_parts} parts thay vì {args.parts}")
    except Exception as exc:
        fail("outline", exc)

    # 4. Script từng part (tuần tự, truyền previous_scripts như UI)
    scripts: dict[str, str] = {}
    for part in outline["parts"]:
        idx = part["index"]
        try:
            t = time.time()
            res = api("POST", "/api/podcast/script", token=token, body={
                "outline": outline,
                "part_index": idx,
                "text_model": "gemini-2.5-flash",
                "num_speakers": 2,
                "host_names": ["Nam", "Linh"],
                "language": "vi",
                "previous_scripts": scripts,
            })
            text = res["text"]
            scripts[str(idx)] = text
            n_lines = len([l for l in text.splitlines() if l.strip()])
            print(f"[4] Script part {idx}/{n_parts} OK: {n_lines} dòng, {len(text)} ký tự ({time.time()-t:.1f}s)")
        except Exception as exc:
            fail(f"script part {idx}", exc)

    # 5. Audio từng part (script cắt ngắn cho đỡ tốn credit)
    audio_files: list[Path] = []
    for part in outline["parts"]:
        idx = part["index"]
        short_script = "\n".join(scripts[str(idx)].splitlines()[:AUDIO_MAX_LINES])
        try:
            t = time.time()
            res = api("POST", "/api/podcast/audio", token=token, body={
                "part_index": idx,
                "script_text": short_script,
                "topic": outline["topic"],
                "voices": voice_ids,
            })
            audio_id = res["audio_id"]
            blob = api("GET", f"/api/podcast/audio/{audio_id}", token=token)
            path = out_dir / f"part-{idx:02d}.wav"
            path.write_bytes(blob)
            size_kb = len(blob) / 1024
            if len(blob) < MIN_AUDIO_BYTES:
                raise RuntimeError(f"File audio quá nhỏ ({len(blob)} bytes)")
            audio_files.append(path)
            print(f"[5] Audio part {idx}/{n_parts} OK: {size_kb:.0f} KB ({time.time()-t:.1f}s)")
        except Exception as exc:
            fail(f"audio part {idx}", exc)

    total = time.time() - t0
    print(f"\n✅ PASS: {n_parts} parts → {len(audio_files)} file audio riêng tại {out_dir}")
    print(f"   Tổng thời gian: {total:.0f}s")


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DEFAULT_LOG_PATH = Path(os.getenv("USAGE_LOG_PATH", "history/usage_log.jsonl"))
_LOG_LOCK = threading.Lock()


def log_path() -> Path:
    return _DEFAULT_LOG_PATH


def log_event(
    kind: str,
    action: str,
    prompt_tokens: int,
    output_tokens: int,
    cost_usd: float,
    user: str = "",
    topic: str = "",
    extra: dict | None = None,
    path: Path | None = None,
) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": user or "anonymous",
        "kind": kind,
        "action": action,
        "topic": topic,
        "prompt_tokens": int(prompt_tokens),
        "output_tokens": int(output_tokens),
        "cost_usd": float(cost_usd),
    }
    if extra:
        entry["extra"] = extra
    p = path or _DEFAULT_LOG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with _LOG_LOCK:
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_log(path: Path | None = None) -> list[dict]:
    p = path or _DEFAULT_LOG_PATH
    if not p.exists():
        return []
    out: list[dict] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def clear_log(path: Path | None = None) -> None:
    p = path or _DEFAULT_LOG_PATH
    with _LOG_LOCK:
        if p.exists():
            p.unlink()


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def filter_by_date(
    events: list[dict],
    start: datetime | None = None,
    end: datetime | None = None,
    user: str = "",
) -> list[dict]:
    out: list[dict] = []
    for e in events:
        ts = _parse_ts(e.get("ts", ""))
        if ts is None:
            continue
        if start and ts < start:
            continue
        if end and ts > end:
            continue
        if user and e.get("user") != user:
            continue
        out.append(e)
    return out


def aggregate_by_period(
    events: list[dict],
    period: str = "day",
    tz_offset_hours: int = 7,
) -> dict[str, dict]:
    buckets: dict[str, dict] = {}
    for e in events:
        ts = _parse_ts(e.get("ts", ""))
        if ts is None:
            continue
        local_ts = ts + timedelta(hours=tz_offset_hours)
        if period == "day":
            key = local_ts.strftime("%Y-%m-%d")
        elif period == "week":
            year, week, _ = local_ts.isocalendar()
            key = f"{year}-W{week:02d}"
        elif period == "month":
            key = local_ts.strftime("%Y-%m")
        else:
            key = "all"
        b = buckets.setdefault(key, {
            "prompt": 0, "output": 0, "cost_usd": 0.0,
            "calls": 0, "users": set(), "kinds": {},
        })
        b["prompt"] += e.get("prompt_tokens", 0)
        b["output"] += e.get("output_tokens", 0)
        b["cost_usd"] += e.get("cost_usd", 0.0)
        b["calls"] += 1
        if e.get("user"):
            b["users"].add(e["user"])
        k = e.get("kind", "?")
        b["kinds"][k] = b["kinds"].get(k, 0) + 1
    return buckets


def aggregate_by_user(events: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for e in events:
        u = e.get("user", "anonymous") or "anonymous"
        b = out.setdefault(u, {
            "prompt": 0, "output": 0, "cost_usd": 0.0, "calls": 0,
            "first_ts": None, "last_ts": None,
        })
        b["prompt"] += e.get("prompt_tokens", 0)
        b["output"] += e.get("output_tokens", 0)
        b["cost_usd"] += e.get("cost_usd", 0.0)
        b["calls"] += 1
        ts = _parse_ts(e.get("ts", ""))
        if ts:
            if b["first_ts"] is None or ts < b["first_ts"]:
                b["first_ts"] = ts
            if b["last_ts"] is None or ts > b["last_ts"]:
                b["last_ts"] = ts
    return out


def events_to_csv(events: list[dict]) -> str:
    lines = ["timestamp,user,kind,action,topic,prompt_tokens,output_tokens,cost_usd"]
    for e in events:
        topic = (e.get("topic", "") or "").replace('"', '""').replace("\n", " ")
        action = (e.get("action", "") or "").replace('"', '""')
        lines.append(
            f'{e.get("ts","")},{e.get("user","")},{e.get("kind","")},'
            f'"{action}","{topic}",'
            f'{e.get("prompt_tokens",0)},{e.get("output_tokens",0)},{e.get("cost_usd",0.0):.6f}'
        )
    return "\n".join(lines)

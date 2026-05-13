import random
import time
from typing import Any, Callable, Optional

TEXT_INPUT_PRICE_PER_TOKEN = 0.075 / 1_000_000
TEXT_OUTPUT_PRICE_PER_TOKEN = 0.30 / 1_000_000
TTS_INPUT_PRICE_PER_TOKEN = 0.50 / 1_000_000
TTS_OUTPUT_PRICE_PER_TOKEN = 10.0 / 1_000_000
DEFAULT_USD_TO_VND = 25500


def extract_response_usage(response: Any, kind: str) -> dict:
    meta = getattr(response, "usage_metadata", None)
    prompt = 0
    output = 0
    if meta is not None:
        prompt = int(getattr(meta, "prompt_token_count", 0) or 0)
        output = int(getattr(meta, "candidates_token_count", 0) or 0)
    if kind == "tts":
        cost = (
            prompt * TTS_INPUT_PRICE_PER_TOKEN
            + output * TTS_OUTPUT_PRICE_PER_TOKEN
        )
    else:
        cost = (
            prompt * TEXT_INPUT_PRICE_PER_TOKEN
            + output * TEXT_OUTPUT_PRICE_PER_TOKEN
        )
    return {
        "kind": kind,
        "prompt_tokens": prompt,
        "output_tokens": output,
        "cost_usd": cost,
    }


def track_response(store: Optional[list], response: Any, kind: str) -> None:
    if store is None:
        return
    try:
        store.append(extract_response_usage(response, kind))
    except Exception:
        pass


def summarize_usage(store: Optional[list], usd_to_vnd: float = DEFAULT_USD_TO_VND) -> dict:
    if not store:
        return {
            "total_prompt": 0, "total_output": 0,
            "total_cost_usd": 0.0, "total_cost_vnd": 0,
            "by_kind": {}, "calls": 0,
        }
    by_kind: dict = {}
    total_cost = 0.0
    total_prompt = 0
    total_output = 0
    for e in store:
        k = e["kind"]
        if k not in by_kind:
            by_kind[k] = {"prompt": 0, "output": 0, "cost_usd": 0.0, "calls": 0}
        by_kind[k]["prompt"] += e["prompt_tokens"]
        by_kind[k]["output"] += e["output_tokens"]
        by_kind[k]["cost_usd"] += e["cost_usd"]
        by_kind[k]["calls"] += 1
        total_cost += e["cost_usd"]
        total_prompt += e["prompt_tokens"]
        total_output += e["output_tokens"]
    return {
        "total_prompt": total_prompt,
        "total_output": total_output,
        "total_cost_usd": total_cost,
        "total_cost_vnd": int(total_cost * usd_to_vnd),
        "by_kind": by_kind,
        "calls": len(store),
    }

_TRANSIENT_MARKERS = (
    "503",
    "UNAVAILABLE",
    "429",
    "RESOURCE_EXHAUSTED",
    "ResourceExhausted",
    "DeadlineExceeded",
    "Internal error",
    "500",
    "INTERNAL",
)


def is_transient_error(e: BaseException) -> bool:
    msg = str(e)
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


def call_with_retry(
    func: Callable,
    *args,
    max_attempts: int = 5,
    base_delay: float = 3.0,
    max_delay: float = 60.0,
    on_retry: Optional[Callable[[int, int, float, BaseException], None]] = None,
    **kwargs,
):
    last_err: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except BaseException as e:
            last_err = e
            if not is_transient_error(e) or attempt == max_attempts:
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1))) + random.uniform(0, 1.5)
            if on_retry is not None:
                try:
                    on_retry(attempt, max_attempts, delay, e)
                except Exception:
                    pass
            time.sleep(delay)
    if last_err is not None:
        raise last_err

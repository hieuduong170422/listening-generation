import random
import time
from typing import Callable, Optional

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

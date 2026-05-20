"""API debug logging — logs all LLM API calls and responses to logs/api.log."""

import logging
import os
from pathlib import Path

# Logs directory at project root (package lives at repo root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "api.log"

_api_logger = None


def get_api_logger():
    """Return the shared API logger (singleton, configures on first call)."""
    global _api_logger
    if _api_logger is not None:
        return _api_logger

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("api")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8", mode="a")
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    _api_logger = logger
    return logger

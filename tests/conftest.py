"""Đảm bảo package trong src/ (prompt_template, podcast_studio) import được khi chạy pytest."""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

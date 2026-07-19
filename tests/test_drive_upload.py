"""Tests cho drive_upload — sanitize tên folder, bật/tắt, best-effort."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from podcast_studio import drive_upload  # noqa: E402


class TestSanitizeFolderName:
    def test_keeps_vietnamese(self):
        assert drive_upload.sanitize_folder_name("Chậu cây giả decor") == "Chậu cây giả decor"

    def test_strips_forbidden_chars(self):
        assert drive_upload.sanitize_folder_name('a/b\\c:d*e?f"g<h>i|j') == "a b c d e f g h i j"

    def test_collapses_whitespace(self):
        assert drive_upload.sanitize_folder_name("  nhiều   khoảng \n trắng ") == "nhiều khoảng trắng"

    def test_caps_length(self):
        assert len(drive_upload.sanitize_folder_name("x" * 300)) == 80

    def test_empty_fallback(self):
        assert drive_upload.sanitize_folder_name("") == "san-pham"
        assert drive_upload.sanitize_folder_name('///"""') == "san-pham"


class TestEnabledFlag:
    def test_disabled_without_env(self, monkeypatch):
        monkeypatch.delenv("AFFILIATE_DRIVE_FOLDER_ID", raising=False)
        assert drive_upload.is_enabled() is False

    def test_enabled_with_env(self, monkeypatch):
        monkeypatch.setenv("AFFILIATE_DRIVE_FOLDER_ID", "abc123")
        assert drive_upload.is_enabled() is True

    def test_upload_returns_none_when_disabled(self, monkeypatch, tmp_path):
        monkeypatch.delenv("AFFILIATE_DRIVE_FOLDER_ID", raising=False)
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        assert drive_upload.upload_video_for_product(video, "sp") is None


class TestBestEffort:
    def test_upload_swallows_errors(self, monkeypatch, tmp_path):
        """Lỗi API (vd Drive API chưa bật) không được raise ra ngoài."""
        monkeypatch.setenv("AFFILIATE_DRIVE_FOLDER_ID", "abc123")

        def boom(*args, **kwargs):
            raise RuntimeError("Drive API disabled")

        monkeypatch.setattr(drive_upload, "find_or_create_folder", boom)
        video = tmp_path / "v.mp4"
        video.write_bytes(b"fake")
        assert drive_upload.upload_video_for_product(video, "sp") is None

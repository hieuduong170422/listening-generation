"""Tests cho _parse_lines — parser phải chịu được các biến thể format từ model."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from podcast_studio.script_generator import _parse_lines  # noqa: E402


class TestPlainFormat:
    def test_basic_speaker_lines(self):
        raw = "Speaker1: Xin chào mọi người.\nSpeaker2: Chào bạn!"
        lines = _parse_lines(raw)
        assert len(lines) == 2
        assert lines[0].speaker == "Speaker1"
        assert lines[0].text == "Xin chào mọi người."
        assert lines[1].speaker == "Speaker2"

    def test_speaker_with_space_before_number(self):
        raw = "Speaker 1: Hello there."
        lines = _parse_lines(raw)
        assert lines[0].speaker == "Speaker1"

    def test_fullwidth_colon(self):
        raw = "Speaker1： Nội dung với dấu hai chấm full-width."
        lines = _parse_lines(raw)
        assert len(lines) == 1

    def test_skips_non_dialogue_lines(self):
        raw = "Đây là tiêu đề\nSpeaker1: Thoại thật.\n\nGhi chú cuối."
        lines = _parse_lines(raw)
        assert len(lines) == 1
        assert lines[0].text == "Thoại thật."


class TestMarkdownVariants:
    def test_bold_speaker_tag(self):
        raw = "**Speaker1:** Chào mừng đến với podcast.\n**Speaker2:** Rất vui được ở đây."
        lines = _parse_lines(raw)
        assert len(lines) == 2
        assert lines[0].speaker == "Speaker1"
        assert lines[0].text == "Chào mừng đến với podcast."

    def test_bold_tag_colon_outside(self):
        raw = "**Speaker1**: Nội dung thoại."
        lines = _parse_lines(raw)
        assert len(lines) == 1
        assert lines[0].text == "Nội dung thoại."

    def test_bullet_prefix(self):
        raw = "- Speaker1: Gạch đầu dòng.\n* Speaker2: Sao đầu dòng."
        lines = _parse_lines(raw)
        assert len(lines) == 2

    def test_code_fences_stripped(self):
        raw = "```\nSpeaker1: Trong code fence.\nSpeaker2: Dòng hai.\n```"
        lines = _parse_lines(raw)
        assert len(lines) == 2

    def test_fence_with_language_tag(self):
        raw = "```text\nSpeaker1: Nội dung.\n```"
        lines = _parse_lines(raw)
        assert len(lines) == 1


class TestHostNameFallback:
    def test_host_names_mapped_to_speakers(self):
        raw = "Linh: Chào cả nhà!\nNam: Hôm nay nói gì đây?"
        lines = _parse_lines(raw, speaker_names=("Linh", "Nam"))
        assert len(lines) == 2
        assert lines[0].speaker == "Speaker1"
        assert lines[1].speaker == "Speaker2"

    def test_host_names_bold(self):
        raw = "**Linh:** Chào cả nhà!"
        lines = _parse_lines(raw, speaker_names=("Linh", "Nam"))
        assert lines[0].speaker == "Speaker1"

    def test_speaker_format_takes_priority_over_names(self):
        raw = "Speaker1: Ưu tiên định dạng chuẩn."
        lines = _parse_lines(raw, speaker_names=("Linh",))
        assert lines[0].speaker == "Speaker1"

    def test_names_case_insensitive(self):
        raw = "LINH: Viết hoa toàn bộ."
        lines = _parse_lines(raw, speaker_names=("Linh",))
        assert lines[0].speaker == "Speaker1"


class TestFailure:
    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _parse_lines("")

    def test_prose_without_tags_raises_with_snippet(self):
        raw = "Đây là một đoạn văn xuôi model trả về sai định dạng hoàn toàn."
        with pytest.raises(ValueError) as exc_info:
            _parse_lines(raw)
        assert "Đây là một đoạn văn xuôi" in str(exc_info.value)

    def test_names_fallback_does_not_match_random_prose(self):
        raw = "Chương trình hôm nay: rất hay."
        with pytest.raises(ValueError):
            _parse_lines(raw, speaker_names=("Linh", "Nam"))

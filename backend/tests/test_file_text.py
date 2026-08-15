"""Tests for Agent attachment text extraction."""
from __future__ import annotations

import pytest

from app.core.file_text import (
    extract_text_from_bytes,
    format_attachment_block,
)


def test_extract_txt():
    text, warn = extract_text_from_bytes("你好世界\n第二行".encode("utf-8"), "a.txt")
    assert "你好世界" in text
    assert warn is None


def test_reject_bad_ext():
    with pytest.raises(ValueError):
        extract_text_from_bytes(b"x", "evil.exe")


def test_format_attachment_block():
    block = format_attachment_block(
        [{"filename": "设定.md", "text": "林夏戒备周屿。"}]
    )
    assert "用户上传参考资料" in block
    assert "设定.md" in block
    assert "林夏" in block

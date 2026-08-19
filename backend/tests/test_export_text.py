"""Unit tests: submission exports (Markdown + Word)."""

from __future__ import annotations

from app.core.export_text import project_to_docx, project_to_markdown, safe_filename
from app.domain.types import VnProject


def _vn() -> VnProject:
    return VnProject.model_validate(
        {
            "id": "p",
            "title": "雨夜车站",
            "logline": "一个关于末班车与告别的故事。",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "characters": [{"id": "lx", "defineName": "lx", "displayName": "林夏"}],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "synopsis": "雨夜，末班车即将离站。",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {"type": "scene", "image": "bg station", "transition": "fade"},
                        {"type": "narration", "text": "雨声在空荡的站厅里回荡。"},
                        {
                            "type": "dialogue",
                            "characterId": "lx",
                            "text": "末班车已经开走了……",
                        },
                        {
                            "type": "menu",
                            "id": "m1",
                            "prompt": "怎么办？",
                            "choices": [{"text": "追上去", "jump": "a"}],
                        },
                    ],
                }
            ],
        }
    )


def test_markdown_structure():
    md = project_to_markdown(_vn())
    assert md.startswith("# 雨夜车站")
    assert "> 一个关于末班车与告别的故事。" in md
    assert "## 第一章" in md
    assert "[场景：bg station]（fade）" in md
    assert "> 雨声在空荡的站厅里回荡。" in md
    assert "**林夏**：末班车已经开走了……" in md
    assert "- 选项提示：怎么办？" in md
    assert "  - 追上去" in md
    # label blocks are skipped for readability
    assert "[label start]" not in md


def test_markdown_uses_prose_when_present():
    vn = _vn()
    vn.chapters[0].prose = "雨还在下。\n\n林夏没有追上去。"
    md = project_to_markdown(vn)
    assert "雨还在下。" in md
    assert "林夏没有追上去。" in md
    assert "**林夏**：末班车已经开走了……" not in md
    content = project_to_docx(_vn())
    assert content[:2] == b"PK"  # docx is a zip
    assert len(content) > 1000


def test_safe_filename():
    assert safe_filename("雨夜车站", ".md") == "雨夜车站.md"
    assert safe_filename("a/b*c?", ".docx") == "a_b_c_.docx"
    assert safe_filename("", ".md") == "vn.md"

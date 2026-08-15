"""update_bible patch normalization from attachments / bilingual keys."""
from __future__ import annotations

from app.core.agent import _normalize_bible_patch, apply_agent_actions
from app.core.demo import create_demo_project


def test_normalize_bible_patch_chinese_keys():
    patch = _normalize_bible_patch(
        {"世界观": "雨季都市", "大纲": "1. 月台\n2. 站厅", "主题": "信任"}
    )
    assert patch["world"] == "雨季都市"
    assert "月台" in patch["outline"]
    assert patch["themes"] == "信任"


def test_apply_update_bible_from_attachment_style_action():
    p = create_demo_project()
    res = apply_agent_actions(
        p,
        [
            {
                "op": "update_bible",
                "patch": {
                    "world": "测试世界观（附件）",
                    "background": "测试前情",
                },
            }
        ],
    )
    assert res.project.bible is not None
    assert res.project.bible.world == "测试世界观（附件）"
    assert res.project.bible.background == "测试前情"
    # untouched fields preserved from demo
    assert res.project.bible.outline

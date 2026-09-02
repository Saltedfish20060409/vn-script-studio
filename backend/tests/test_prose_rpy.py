"""Deterministic NL → RPY parse (no LLM)."""

import asyncio

from app.core.prose_rpy import (
    _rpy_has_structural_flaws,
    generate_rpy_from_prose,
    parse_prose_to_blocks,
)
from app.domain.types import Character, VnProject


def test_parse_colon_dialogue():
    people = [Character(id="lx", defineName="lx", displayName="林夏")]
    blocks = parse_prose_to_blocks("林夏：末班车已经开走了。\n雨还在下。", people)
    types = [b["type"] for b in blocks]
    assert "label" in types
    assert any(t in types for t in ("dialogue", "narration", "raw"))


def test_generate_without_llm():
    vn = VnProject.model_validate(
        {
            "id": "p",
            "title": "t",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "characters": [{"id": "lx", "defineName": "lx", "displayName": "林夏"}],
            "chapters": [{"id": "ch1", "title": "一", "blocks": []}],
        }
    )
    rpy, blocks = asyncio.run(
        generate_rpy_from_prose(vn, "林夏：你好。\n雨还在下。", None, use_llm=False)
    )
    assert blocks
    blob = rpy + "".join(str(b.get("text") or b.get("code") or "") for b in blocks)
    assert "你好" in blob


def test_structure_detector_bare_scene():
    """裸 scene（无图片名）必须被标记为结构缺陷。"""
    assert _rpy_has_structural_flaws("scene bg") == "scene 缺少图片名（裸 scene）"
    assert _rpy_has_structural_flaws("scene") == "scene 缺少图片名（裸 scene）"


def test_structure_detector_narrator_prefix():
    """「旁白」前缀被写进引号文本 → 缺陷。"""
    assert _rpy_has_structural_flaws('"旁白 雨下大了。"') is not None


def test_structure_detector_define_inside_label():
    """define 声明放进 label 内部 → 缺陷。"""
    rpy = 'label start:\n    define lx "林夏"\n    lx "你好"'
    assert _rpy_has_structural_flaws(rpy) is not None


def test_structure_detector_self_loop():
    """选项 jump start 自循环 → 缺陷。"""
    assert _rpy_has_structural_flaws("    jump start") is not None


def test_structure_detector_clean_output_passes():
    """结构正确的输出不应被误判。"""
    clean = """define lx = Character("林夏")

label start:
    scene bg_street
    lx "你好"
    return"""
    assert _rpy_has_structural_flaws(clean) is None

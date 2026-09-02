"""Deterministic NL → RPY parse (no LLM)."""

import asyncio
import types

from app.core.prose_rpy import (
    _rpy_has_structural_flaws,
    generate_rpy_from_prose,
    parse_prose_to_blocks,
)
from app.domain.types import Character, VnProject


def _proj():
    return VnProject.model_validate(
        {
            "id": "p",
            "title": "t",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "characters": [{"id": "lx", "defineName": "lx", "displayName": "林夏"}],
            "chapters": [{"id": "ch1", "title": "一", "blocks": []}],
        }
    )


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


def test_structure_detector_bad_define_top_level():
    """顶层 define 缺 = Character(...)（用户真实坏输出样本）→ 缺陷。"""
    assert _rpy_has_structural_flaws('define linxia "林夏"') is not None
    assert _rpy_has_structural_flaws('define linxia = "林夏"') is not None


def test_structure_detector_dup_label():
    """同文件重复 label → 缺陷（用户真实坏输出样本）。"""
    rpy = "label suggest_shelter:\n    return\nlabel suggest_shelter:\n    return"
    assert _rpy_has_structural_flaws(rpy) is not None


def test_structure_detector_menu_menu_without_jump():
    """menu menu: 双关键字（即使没有 jump start）→ 缺陷。"""
    rpy = 'menu menu:\n    "你要怎么试探？":\n        pass\nreturn'
    assert _rpy_has_structural_flaws(rpy) is not None


def test_structure_detector_clean_output_passes():
    """结构正确的输出不应被误判。"""
    clean = """define lx = Character("林夏")

label start:
    scene bg_street
    lx "你好"
    return"""
    assert _rpy_has_structural_flaws(clean) is None


def test_gate_rejects_user_real_output_end_to_end(monkeypatch):
    """用户真实坏输出（define/裸scene/menu menu/重复label）必须被拦截：
    即使 mock 的 LLM 原样返回坏文本，generate_rpy_from_prose 也必须
    回退到确定性解析，而不是把坏文本交给前端。"""
    import app.core.prose_rpy as pr

    bad = (
        'define linxia "林夏"\n'
        'define zhouyu "周屿"\n'
        "label start:\n"
        "scene bg\n"
        '"延误再次延长。"\n'
        'zhouyu "从月台往东。"\n'
        "menu menu:\n"
        '  "你要怎么试探？":\n'
        "    jump start\n"
        "return\n"
        "label suggest_shelter:\n"
        "scene bg\n"
        '"暖气发闷。"\n'
        "return\n"
        "label suggest_shelter:\n"
        '"重复了"\n'
        "return"
    )

    async def fake_llm(project, prose, config):
        return bad

    monkeypatch.setattr(pr, "llm_prose_to_rpy", fake_llm)
    cfg = types.SimpleNamespace(apiKey="k", baseUrl="", model="m")
    rpy, blocks = asyncio.run(
        generate_rpy_from_prose(_proj(), "雨夜，末班车站台。\n林夏：延误再次延长。", cfg)
    )
    # deterministic fallback: structurally sound output, no model junk
    assert "define linxia" not in rpy
    assert "scene bg" not in rpy
    assert "menu menu" not in rpy
    assert rpy.count("label suggest_shelter:") <= 1
    assert rpy.count("label start:") == 1
    assert blocks and any(b.get("type") == "label" for b in blocks)
    # fallback rpy must still carry the story text
    assert "延误再次延长" in rpy or "末班车" in rpy


def test_gate_keeps_good_llm_output(monkeypatch):
    """结构正确的 LLM 输出不被误伤：原样返回，不触发回退。"""
    import app.core.prose_rpy as pr

    good = (
        'define lx = Character("林夏")\n\n'
        "label start:\n"
        "    scene bg_street\n"
        '    lx "你好"\n'
        "    return\n"
    )

    async def fake_llm(project, prose, config):
        return good

    monkeypatch.setattr(pr, "llm_prose_to_rpy", fake_llm)
    cfg = types.SimpleNamespace(apiKey="k", baseUrl="", model="m")
    rpy, blocks = asyncio.run(
        generate_rpy_from_prose(_proj(), "林夏：你好。", cfg)
    )
    assert rpy == good
    assert blocks


APP_PROSE = """[场景：bg overpass_rain]

延误再次延长。伞沿外，天桥的灯灭了半边。

周屿：从月台往东，过天桥就能看见那家便利店。

林夏：你怎么知道？

选项：你要怎么试探？

- 追问他为何熟悉动线

- 提议去便利店避雨

林夏：过路人不会把换乘口背得这么熟。
"""

APP_CHARS = [
    Character(id="lx", defineName="linxia", displayName="林夏"),
    Character(id="zy", defineName="zhouyu", displayName="周屿"),
]


def test_app_prose_format_round_trip():
    """应用自己的剧本格式（[场景：]/[出现：]/选项：+ 列表项）必须能正确解析，
    否则确定性回退会给「选项：」生成单个假选项，再被编辑器渲染成 jump start。"""
    blocks = parse_prose_to_blocks(APP_PROSE, APP_CHARS)
    types = [b.get("type") for b in blocks]
    assert types[0] == "label"
    assert "scene" in types  # [场景：bg overpass_rain] → scene，而不是 raw
    scenes = [b for b in blocks if b.get("type") == "scene"]
    assert scenes[0].get("image") == "bg overpass_rain"
    menus = [b for b in blocks if b.get("type") == "menu"]
    assert len(menus) == 1
    m = menus[0]
    assert m.get("prompt") == "你要怎么试探？"
    texts = [c.get("text") for c in m.get("choices")]
    assert texts == ["追问他为何熟悉动线", "提议去便利店避雨"]
    # 两个真实选项在菜单里，而不是变成菜单外的旁白
    leftovers = [
        b
        for b in blocks
        if b.get("type") == "narration" and str(b.get("text", "")).startswith("-")
    ]
    assert not leftovers


def test_app_prose_format_fallback_no_self_loop(monkeypatch):
    """LLM 输出应用格式标注时被 gate 拦截 → 回退解析原稿 → 不再出现 jump start。"""
    import app.core.prose_rpy as pr

    echoed = '[场景：bg overpass_rain]\n选项：你要怎么试探？\n- 追问他为何熟悉动线'
    assert _rpy_has_structural_flaws(echoed) is not None

    async def fake_llm(project, prose, config):
        return echoed

    monkeypatch.setattr(pr, "llm_prose_to_rpy", fake_llm)
    cfg = types.SimpleNamespace(apiKey="k", baseUrl="", model="m")
    rpy, blocks = asyncio.run(
        generate_rpy_from_prose(_proj(), APP_PROSE, cfg)
    )
    assert "jump start" not in rpy
    menus = [b for b in blocks if b.get("type") == "menu"]
    assert menus and len(menus[0].get("choices")) >= 2


def test_gate_rejects_manuscript_markers():
    """LLM 原样回显剧本标注（[场景：/选项：/列表项）→ 一律按结构缺陷拦截。"""
    assert _rpy_has_structural_flaws("[场景：bg street]") is not None
    assert _rpy_has_structural_flaws("选项：A / B") is not None
    assert _rpy_has_structural_flaws("- 追问他为何熟悉动线") is not None


def test_export_keeps_spaced_image_names():
    """Ren'Py 图片名可含空格（bg overpass_rain / linxia neutral），
    导出不得降级成 unnamed。"""
    from app.core.renpy import export_to_renpy

    vn = VnProject.model_validate(
        {
            "id": "p",
            "title": "t",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "characters": [],
            "chapters": [
                {
                    "id": "c1",
                    "title": "一",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {"type": "scene", "image": "bg overpass_rain"},
                        {"type": "show", "image": "linxia neutral"},
                        {"type": "return"},
                    ],
                }
            ],
        }
    )
    out = export_to_renpy(vn)
    assert "scene bg overpass_rain" in out
    assert "show linxia neutral" in out
    assert "scene unnamed" not in out

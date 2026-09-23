"""块遍历工具的直接测试。

`core/blocks.py` 是声线量具、分支分析、跨章事实检测、全局记忆、自适应选项**共用的遍历基座**。
它出 bug 不会让任何一处报错，只会让所有分析静默少算内容——所以必须有直接的测试，
不能只靠"调用方各自的测试顺带覆盖"。

这里锁住的核心语义：**菜单选项正文与 if 分支正文都要算进去**。
少算这一层，"写在分支里的台词"会在统计里凭空消失（模块 docstring 里写明这是缺陷而非简化）。
"""

from __future__ import annotations

from app.core.blocks import iter_dialogue, iter_narration, iter_project_blocks, walk_blocks
from app.core.project import normalize_project


def _d(char_id: str, text: str) -> dict:
    return {"type": "dialogue", "characterId": char_id, "text": text}


def _n(text: str) -> dict:
    return {"type": "narration", "text": text}


def _project(chapters: list):
    return normalize_project(
        {
            "id": "p1",
            "title": "遍历测试",
            "characters": [
                {"id": "lin", "defineName": "lin", "displayName": "林夏"},
                {"id": "zhou", "defineName": "zhou", "displayName": "周屿"},
            ],
            "chapters": chapters,
        }
    )


def _ch(cid: str, blocks: list) -> dict:
    return {"id": cid, "title": cid, "blocks": blocks}


NESTED = [
    {"type": "label", "id": "start", "name": "start"},
    _n("顶层旁白"),
    {
        "type": "menu",
        "id": "m1",
        "choices": [
            {"text": "留下", "blocks": [_d("lin", "选项里的台词")]},
            {
                "text": "追问",
                "blocks": [
                    {
                        "type": "if",
                        "branches": [
                            {"condition": "a >= 1", "blocks": [_d("zhou", "条件分支里的台词")]},
                            {"blocks": [_n("否则分支的旁白")]},
                        ],
                    }
                ],
            },
        ],
    },
    _d("lin", "菜单之后的台词"),
    {"type": "return"},
]


# ------------------------------------------------------------------ 深度遍历


def test_walk_blocks_reaches_nested_branch_bodies():
    kinds = [b.get("type") for b in walk_blocks(NESTED)]
    assert "menu" in kinds and "if" in kinds
    texts = [b.get("text") for b in walk_blocks(NESTED)]
    assert "选项里的台词" in texts
    assert "条件分支里的台词" in texts
    assert "否则分支的旁白" in texts
    assert "菜单之后的台词" in texts


def test_walk_blocks_is_depth_first_and_skips_non_dicts():
    blocks = [None, "not-a-block", {"type": "return"}, 42, _n("尾")]
    out = [b.get("type") for b in walk_blocks(blocks)]
    assert out == ["return", "narration"]


def test_walk_blocks_handles_empty_and_none():
    assert list(walk_blocks([])) == []
    assert list(walk_blocks(None)) == []


def test_walk_blocks_survives_malformed_choices_and_branches():
    """菜单/分支字段写坏时不能抛：脏数据在编辑器里是常态。"""
    blocks = [
        {"type": "menu", "id": "m", "choices": [None, "x", {"text": "ok"}]},
        {"type": "if", "branches": [None, 5, {"blocks": [_n("好的")]}]},
        {"type": "menu", "id": "m2"},
    ]
    texts = [b.get("text") for b in walk_blocks(blocks) if b.get("text")]
    assert texts == ["好的"]


# -------------------------------------------------------------- 项目级遍历


def test_iter_project_blocks_keeps_chapter_and_block_order():
    project = _project(
        [
            _ch("c1", [_n("一")]),
            _ch("c2", [_n("二"), {"type": "return"}]),
        ]
    )
    rows = list(iter_project_blocks(project))
    assert [(cid, b.get("text")) for cid, b in rows] == [("c1", "一"), ("c2", "二"), ("c2", None)]


def test_iter_project_blocks_is_safe_on_an_empty_project():
    assert list(iter_project_blocks(normalize_project({"id": "p", "title": "空"}))) != []


def test_iter_dialogue_includes_branch_dialogue_and_keeps_chapter_ids():
    project = _project([_ch("c1", NESTED)])
    rows = list(iter_dialogue(project))
    assert [(cid, who, text) for cid, who, text in rows] == [
        ("c1", "lin", "选项里的台词"),
        ("c1", "zhou", "条件分支里的台词"),
        ("c1", "lin", "菜单之后的台词"),
    ]


def test_iter_dialogue_can_filter_one_character():
    project = _project([_ch("c1", NESTED)])
    only = list(iter_dialogue(project, character_id="zhou"))
    assert [t for _c, _w, t in only] == ["条件分支里的台词"]


def test_iter_dialogue_drops_blank_lines():
    """空白对白不是语言行为，进了统计只会把均值往 0 拉。"""
    project = _project([_ch("c1", [_d("lin", "  "), _d("lin", "嗯。"), _d("lin", "")])])
    assert [t for _c, _w, t in iter_dialogue(project)] == ["嗯。"]


def test_iter_dialogue_reports_missing_character_id_as_empty_string():
    """没写说话人的对白要**照常产出**（说话人是空串），不能静默丢掉。

    这是刻意的契约：`continuity_graph` 靠它报"未登记说话人"这类硬缺陷
    （导出后会被渲染成 narrator，属于真问题）。丢掉就等于把问题藏起来。
    """
    project = _project([_ch("c1", [{"type": "dialogue", "text": "没有说话人"}, _d("lin", "嗯。")])])
    rows = list(iter_dialogue(project))
    assert [(w, t) for _c, w, t in rows] == [("", "没有说话人"), ("lin", "嗯。")]
    # 但按角色过滤时，空说话人不该混进任何具体角色
    assert [t for _c, _w, t in iter_dialogue(project, character_id="lin")] == ["嗯。"]


def test_iter_narration_includes_branch_narration():
    project = _project([_ch("c1", NESTED)])
    texts = [t for _c, t in iter_narration(project)]
    assert "顶层旁白" in texts
    assert "否则分支的旁白" in texts
    assert all("台词" not in t for t in texts), "对白不该混进旁白流"


def test_iterators_do_not_cross_chapters():
    project = _project(
        [
            _ch("c1", [_d("lin", "第一章的台词")]),
            _ch("c2", [_d("lin", "第二章的台词")]),
        ]
    )
    pairs = [(cid, t) for cid, _w, t in iter_dialogue(project)]
    assert pairs == [("c1", "第一章的台词"), ("c2", "第二章的台词")]


def test_shared_walker_powers_the_real_analyzers():
    """交叉验证：遍历少算一层会让声线量具漏掉分支里的台词。

    这条不是重复测试 `voice_fingerprint`，而是钉住"共用基座与调用方一致"这件事：
    如果有人把 `walk_blocks` 改成只遍历顶层，这里会立刻红。
    """
    from app.core.voice_fingerprint import build_voice_profile

    project = _project([_ch("c1", NESTED)])
    profile = build_voice_profile(project, "lin")
    assert profile["utteranceCount"] == 2  # 选项里 1 句 + 菜单之后 1 句

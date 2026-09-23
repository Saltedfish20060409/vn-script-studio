"""自适应选项（读者倾向计数器）测试。

两个重点：

1. **`persistent.` 前缀必须存在**——少写它就是普通全局变量，存档之间各自独立，
   "读者一贯的倾向"根本记不住。实现时确实漏过一次，所以这里专门锁死。
2. **默认关闭时导出产物逐字不变**——这是个会改变产物语义的开关，
   同一份剧本两次导出结果不同会让作者困惑，所以默认路径必须走原样。
"""

from __future__ import annotations

from app.core.adaptive_reader import (
    TENDENCY_PREFIX,
    analyze_adaptive_opportunities,
    choice_increment_lines,
    choice_tendency_keys,
    condition_recipes,
    export_adaptive_prelude,
    tendency_counter_name,
    tendency_counter_ref,
    tendency_counters,
)
from app.core.project import normalize_project
from app.core.renpy import export_to_renpy


def _ch(cid: str, blocks: list) -> dict:
    return {"id": cid, "title": cid, "blocks": blocks}


def _label(name: str) -> dict:
    return {"type": "label", "id": name, "name": name}


def _project(choices: list, *, variables: list | None = None):
    return normalize_project(
        {
            "id": "p1",
            "title": "自适应测试",
            "characters": [{"id": "lin", "defineName": "lin", "displayName": "林夏"}],
            "variables": variables
            or [
                {"id": "v1", "name": "好感", "key": "affection", "type": "number", "value": 0},
                {"id": "v2", "name": "勇气", "key": "courage", "type": "number", "value": 0},
            ],
            "chapters": [
                _ch(
                    "ch1",
                    [
                        _label("start"),
                        {"type": "menu", "id": "m1", "prompt": "怎么办", "choices": choices},
                        _label("end"),
                        {"type": "return"},
                    ],
                )
            ],
        }
    )


AFFECT_CHOICE = {
    "text": "帮她",
    "blocks": [
        {"type": "set", "key": "affection", "op": "+=", "value": 1},
        {"type": "narration", "text": "她看了你一眼。"},
    ],
}
PLAIN_CHOICE = {"text": "走开", "jump": "end"}
EMPTY_CHOICE = {"text": "沉默", "blocks": []}


# ------------------------------------------------------------ 计数器派生


def test_only_variables_actually_changed_by_a_choice_get_a_counter():
    project = _project([AFFECT_CHOICE, PLAIN_CHOICE, EMPTY_CHOICE])
    assert list(tendency_counters(project)) == ["affection"]


def test_nested_set_blocks_are_counted():
    """条件分支里才加好感是最常见的写法，只扫顶层会漏。"""
    choice = {
        "text": "试着说点什么",
        "blocks": [
            {
                "type": "if",
                "branches": [
                    {"condition": "courage >= 1", "blocks": [{"type": "set", "key": "affection", "value": 1}]},
                    {"blocks": [{"type": "set", "key": "courage", "op": "+=", "value": 1}]},
                ],
            }
        ],
    }
    assert choice_tendency_keys(choice) == ["affection", "courage"]


def test_counter_name_is_sanitized_into_a_legal_identifier():
    assert tendency_counter_name("affection") == f"{TENDENCY_PREFIX}affection"
    # 中文 key 会被收敛成合法标识符（代码位置不能出现任意字符）
    weird = tendency_counter_name("好感度")
    assert weird.startswith(TENDENCY_PREFIX)
    assert weird[len(TENDENCY_PREFIX) :].replace("_", "a").isalnum()
    assert "-" not in weird and " " not in weird


def test_counter_ref_includes_the_persistent_prefix():
    """**回归闸**：漏掉 `persistent.` 就等于没做自适应（每次读档从 0 开始）。"""
    assert tendency_counter_ref("affection") == f"persistent.{TENDENCY_PREFIX}affection"
    assert choice_increment_lines(AFFECT_CHOICE) == [
        f"$ persistent.{TENDENCY_PREFIX}affection += 1"
    ]


def test_choices_without_set_blocks_get_no_increment():
    assert choice_increment_lines(PLAIN_CHOICE) == []
    assert choice_increment_lines(EMPTY_CHOICE) == []


# ---------------------------------------------------------------- 声明块


def test_prelude_declares_persistent_defaults():
    project = _project([AFFECT_CHOICE, PLAIN_CHOICE])
    prelude = export_adaptive_prelude(project)
    assert f"default persistent.{TENDENCY_PREFIX}affection = 0" in prelude
    assert "读者倾向" in prelude


def test_prelude_is_empty_when_nothing_to_count():
    project = _project([PLAIN_CHOICE])
    assert export_adaptive_prelude(project) == ""


def test_condition_recipes_reference_real_counters():
    project = _project([AFFECT_CHOICE])
    recipes = condition_recipes(project, threshold=3)
    assert len(recipes) == 1
    assert recipes[0]["counter"] == f"persistent.{TENDENCY_PREFIX}affection"
    assert recipes[0]["condition"] == f"persistent.{TENDENCY_PREFIX}affection >= 3"
    assert "affection" in recipes[0]["meaning"]


def test_condition_recipes_are_empty_for_projects_without_counters():
    assert condition_recipes(_project([PLAIN_CHOICE])) == []


# ------------------------------------------------------------ 导出器接线


def test_default_export_is_unchanged():
    """默认（不开自适应）产物必须逐字不变——同一份剧本两次导出不能不同。"""
    project = _project([AFFECT_CHOICE, PLAIN_CHOICE, EMPTY_CHOICE])
    out = export_to_renpy(project)
    assert TENDENCY_PREFIX not in out
    assert "persistent" not in out


def test_adaptive_export_injects_increment_and_declaration():
    project = _project([AFFECT_CHOICE, PLAIN_CHOICE])
    out = export_to_renpy(project, adaptive_reader=True)
    assert f"default persistent.{TENDENCY_PREFIX}affection = 0" in out
    assert f"$ persistent.{TENDENCY_PREFIX}affection += 1" in out
    # 原有语句一个都不能少
    assert "$ affection += 1" in out
    assert "jump end" in out


def test_increment_lands_inside_the_right_choice_and_before_the_body():
    project = _project([AFFECT_CHOICE, PLAIN_CHOICE])
    lines = export_to_renpy(project, adaptive_reader=True).splitlines()
    inc_idx = next(
        i for i, ln in enumerate(lines) if f"persistent.{TENDENCY_PREFIX}affection += 1" in ln
    )
    choice_line = next(i for i, ln in enumerate(lines) if '"帮她"' in ln)
    body_line = next(i for i, ln in enumerate(lines) if "她看了你一眼。" in ln)
    assert choice_line < inc_idx < body_line
    # 计数必须比正文里的 $ affection += 1 更早：先计倾向，再改状态
    effect_idx = next(i for i, ln in enumerate(lines) if "$ affection += 1" in ln)
    assert inc_idx < effect_idx
    # 另一个选项里不许出现计数
    plain_idx = next(i for i, ln in enumerate(lines) if '"走开"' in ln)
    assert all(
        "reader_tendency" not in ln for ln in lines[plain_idx : plain_idx + 3]
    )


def test_empty_option_body_gets_count_instead_of_bare_pass():
    """原本空正文的选项会输出 `pass`；加了计数之后不该再留一个多余的 pass。"""
    project = _project(
        [
            {"text": "只说一句", "blocks": [{"type": "set", "key": "courage", "value": 1}]},
            PLAIN_CHOICE,
        ]
    )
    out = export_to_renpy(project, adaptive_reader=True)
    assert f"$ persistent.{TENDENCY_PREFIX}courage += 1" in out
    block = out.split('"只说一句":', 1)[1].split('"走开"', 1)[0]
    assert "pass" not in block


def test_jump_only_choice_with_a_set_elsewhere_still_counts():
    """选项自己用 jump，但正文里有 set → 仍要计数（计数放在 jump 之前）。"""
    project = _project(
        [
            {
                "text": "跳着走",
                "jump": "end",
                "blocks": [{"type": "set", "key": "courage", "op": "+=", "value": 1}],
            },
            PLAIN_CHOICE,
        ]
    )
    lines = export_to_renpy(project, adaptive_reader=True).splitlines()
    inc = next(
        i for i, ln in enumerate(lines) if f"persistent.{TENDENCY_PREFIX}courage += 1" in ln
    )
    jump = next(i for i, ln in enumerate(lines) if ln.strip() == "jump end")
    assert inc < jump


def test_adaptive_export_is_deterministic():
    project = _project([AFFECT_CHOICE, PLAIN_CHOICE])
    a = export_to_renpy(project, adaptive_reader=True)
    b = export_to_renpy(project, adaptive_reader=True)
    assert a == b


def test_project_without_counters_is_unaffected_by_the_flag():
    project = _project([PLAIN_CHOICE])
    assert export_to_renpy(project) == export_to_renpy(project, adaptive_reader=True)


def test_bundle_passes_the_flag_through_to_script_rpy():
    """zip 导出（`export/bundle`）也要能开：否则作者只能手工改 .rpy。"""
    from app.core.renpy import export_project_bundle

    project = _project([AFFECT_CHOICE, PLAIN_CHOICE])
    off = export_project_bundle(project)["script.rpy"]
    on = export_project_bundle(project, adaptive_reader=True)["script.rpy"]
    assert TENDENCY_PREFIX not in off
    assert f"$ persistent.{TENDENCY_PREFIX}affection += 1" in on
    assert f"default persistent.{TENDENCY_PREFIX}affection = 0" in on
    # 其余文件不受影响
    assert export_project_bundle(project)["options.rpy"] == export_project_bundle(
        project, adaptive_reader=True
    )["options.rpy"]


def test_export_endpoint_exposes_the_switch():
    """回归闸：开关必须真的挂在导出端点上。

    此前 `export_to_renpy` 支持这个参数，但**没有任何调用方传它**——
    功能做完了却没人能打开（这正是"模块没有调用点等于没做"的老问题）。
    """
    from app.main import app

    spec = app.openapi()
    for path in (
        "/api/v1/projects/{project_id}/export/rpy",
        "/api/v1/projects/{project_id}/export/bundle",
    ):
        params = [p.get("name") for p in spec["paths"][path]["get"].get("parameters", [])]
        assert "adaptive_reader" in params, (path, params)


# ------------------------------------------------------------ 机会分析


def test_opportunities_flag_no_effect_menus():
    project = _project(
        [
            {"text": "留下", "blocks": [{"type": "narration", "text": "她没走。"}]},
            {"text": "也留下", "blocks": [{"type": "narration", "text": "她还在。"}]},
        ]
    )
    out = analyze_adaptive_opportunities(project)
    assert out["candidates"]
    assert "后果完全相同" in out["candidates"][0]["reason"]


def test_opportunities_use_reader_data_when_available():
    project = _project([AFFECT_CHOICE, PLAIN_CHOICE])
    analytics = {
        "choices": {
            "menus": [
                {
                    "menuId": "m1",
                    "options": [
                        {"index": 0, "share": 1.0},
                        {"index": 1, "share": 0.0},
                    ],
                }
            ]
        }
    }
    out = analyze_adaptive_opportunities(project, analytics=analytics)
    assert out["candidates"]
    assert "几乎总是选同一个选项" in out["candidates"][0]["reason"]


def test_opportunities_suggest_creating_a_counter_first_when_there_are_none():
    project = _project(
        [
            {"text": "留下", "blocks": [{"type": "narration", "text": "她没走。"}]},
            {"text": "也留下", "blocks": [{"type": "narration", "text": "她还在。"}]},
        ]
    )
    out = analyze_adaptive_opportunities(project)
    assert out["candidates"]
    assert "改变量" in out["candidates"][0]["suggestion"]


def test_opportunities_skip_menus_with_a_real_choice():
    project = _project(
        [
            {"text": "帮她", "blocks": [{"type": "set", "key": "affection", "value": 1}]},
            {"text": "走开", "jump": "end"},
        ]
    )
    out = analyze_adaptive_opportunities(project)
    assert out["candidates"] == []
    assert out["tendencyCounters"] == {"affection": f"{TENDENCY_PREFIX}affection"}


def test_opportunities_notes_state_the_default_is_off():
    out = analyze_adaptive_opportunities(_project([AFFECT_CHOICE, PLAIN_CHOICE]))
    joined = " ".join(out["notes"])
    assert "adaptive_reader=True" in joined
    assert "试玩器" in joined

"""`patch_script`：改现有正文里的某几句，其余一字不动。

为什么要有这个 op（2026-10 线上取证，项目《拟合少女》／作者「搁浅de咸鱼」）：
在此之前只有 `append_script`（只能接末尾）与 `replace_script`（整章替换）两条路，
于是"按这几条建议改"落到工具面上就只剩"把整章重新打一遍"。用户圈定了 **7 处**定点修改，
模型给出的动作是 `replace_script`，改后与改前**逐段完全相同的只剩 5%**——
"改 7 处"实际执行成了"重写全章"。

这组测试钉住它真正承诺的那件事：**只改点到的地方**，以及**改不动时响亮拒绝**。
"""
from __future__ import annotations

from app.core.agent import MAX_PATCH_EDITS, apply_agent_actions
from app.core.agent_context import chapter_plain
from app.core.project import normalize_project


def _prose_project(text: str):
    """一个"正文档有正文"的工程（权威读文本 = prose）。"""
    return normalize_project(
        {
            "id": "p1",
            "title": "定点改",
            "chapters": [{"id": "ch1", "title": "第一章", "prose": text}],
        }
    )


def _script_project(blocks):
    """一个"只有脚本档"的工程（权威读文本 = blocks 渲染）。"""
    return normalize_project(
        {
            "id": "p2",
            "title": "脚本档",
            "chapters": [{"id": "ch1", "title": "第一章", "blocks": blocks}],
        }
    )


def _patch(project, edits, **extra):
    action = {"op": "patch_script", "chapterRef": "第一章", "edits": edits, **extra}
    return apply_agent_actions(project, [action])


# ---- 核心承诺：只改点到的地方 --------------------------------------------------

PROSE = (
    "（她把碗端在手里，没动筷子。）\n"
    "雪菜：「热的。」\n"
    "（她往怀里挪了一点。）\n"
    "雪菜：「所里的汤，一直是温的。」\n"
    "你：「（把碗搁上架）你碗洗了没有。」\n"
)


def test_only_the_matched_sentence_changes():
    before = _prose_project(PROSE)
    res = _patch(
        before,
        [{"find": "雪菜：「热的。」", "replace": "雪菜：「这个是热的。」"}],
    )
    assert res.skipped == []
    assert res.applied and "定点改写" in res.applied[0]

    # 最精确的"只改了点到的地方"：改后的读文本 == 改前读文本做了那一次替换
    before_text = chapter_plain(before.chapters[0], None)
    after_text = chapter_plain(res.project.chapters[0], None)
    assert after_text == before_text.replace("雪菜：「热的。」", "雪菜：「这个是热的。」")
    assert len(after_text) == len(before_text) + len("这个是")


def test_multiple_edits_apply_in_order():
    res = _patch(
        _prose_project(PROSE),
        [
            {"find": "没动筷子", "replace": "没拿筷子"},
            {"find": "（她往怀里挪了一点。）", "replace": "（她把碗往怀里挪了一点。）"},
        ],
    )
    assert res.skipped == []
    after = res.project.chapters[0].prose
    assert "没拿筷子" in after and "没动筷子" not in after
    assert "（她把碗往怀里挪了一点。）" in after


def test_later_edit_searches_the_result_of_earlier_ones():
    """逐条按顺序应用：后一条在前一条的结果上找（`_apply_edits_to_text` 的语义）。"""
    res = _patch(
        _prose_project(PROSE),
        [
            {"find": "雪菜：「热的。」", "replace": "雪菜：「温的。」"},
            {"find": "雪菜：「温的。」", "replace": "雪菜：「温的，比这里暖。」"},
        ],
    )
    assert res.skipped == []
    assert "温的，比这里暖。」" in res.project.chapters[0].prose


def test_empty_replace_deletes_the_sentence():
    res = _patch(_prose_project(PROSE), [{"find": "（她往怀里挪了一点。）\n", "replace": ""}])
    assert res.skipped == []
    assert "往怀里挪" not in res.project.chapters[0].prose
    assert "没动筷子" in res.project.chapters[0].prose


# ---- 改不动时响亮拒绝（不静默、更不退回整章替换）-----------------------------

def test_missing_find_rejects_the_whole_op_and_touches_nothing():
    before = _prose_project(PROSE)
    res = _patch(
        before,
        [
            {"find": "雪菜：「热的。」", "replace": "雪菜：「这是热的。」"},
            {"find": "这句原文里根本没有", "replace": "x"},
        ],
    )
    assert res.applied == []
    assert len(res.skipped) == 1
    assert "找不到" in res.skipped[0]
    assert "逐字" in res.skipped[0], "要告诉模型怎么改对（照抄原文），而不是只说「失败」"
    # 第一条**不许**先落地：半落地的稿子是静默错误
    assert res.project.chapters[0].prose == before.chapters[0].prose


def test_ambiguous_find_is_rejected_instead_of_patching_the_wrong_place():
    text = "你：「走吧。」\n（沉默。）\n你：「走吧。」\n"
    res = _patch(_prose_project(text), [{"find": "你：「走吧。」", "replace": "你：「走。」"}])
    assert res.applied == []
    assert "匹配到 2 处" in res.skipped[0]
    assert res.project.chapters[0].prose == text


def test_empty_chapter_is_rejected_with_a_pointer_to_the_right_op():
    res = _patch(_prose_project("   "), [{"find": "a", "replace": "b"}])
    assert res.applied == []
    assert "append_script" in res.skipped[0] and "replace_script" in res.skipped[0]


def test_too_many_edits_is_rejected_and_points_at_replace_script():
    res = _patch(
        _prose_project(PROSE),
        [{"find": f"不存在的{i}", "replace": "x"} for i in range(MAX_PATCH_EDITS + 1)],
    )
    assert res.applied == []
    assert "最多" in res.skipped[0] and "整章重写" in res.skipped[0]


def test_op_without_edits_is_rejected():
    res = apply_agent_actions(
        _prose_project(PROSE), [{"op": "patch_script", "chapterRef": "第一章"}]
    )
    assert res.applied == []
    assert "find" in res.skipped[0]


# ---- 输入形态容错 -------------------------------------------------------------

def test_top_level_shorthand_and_aliases_are_accepted():
    """模型可能把 find/replace 直接写在同一层，或用 from/to 这类别名。"""
    res = apply_agent_actions(
        _prose_project(PROSE),
        [{"op": "patch_script", "chapterRef": "第一章", "find": "热的", "replace": "烫的"}],
    )
    assert res.skipped == []
    assert "烫的" in res.project.chapters[0].prose

    res2 = apply_agent_actions(
        _prose_project(PROSE),
        [
            {
                "op": "patch_script",
                "chapterRef": "第一章",
                "edits": [{"from": "热的", "to": "凉的"}],
            }
        ],
    )
    assert res2.skipped == []
    assert "凉的" in res2.project.chapters[0].prose


def test_patch_alias_for_the_edits_field():
    res = apply_agent_actions(
        _prose_project(PROSE),
        [
            {
                "op": "patch_script",
                "chapterRef": "第一章",
                "patch": [{"find": "热的", "replace": "温的"}],
            }
        ],
    )
    assert res.skipped == []
    assert "温的" in res.project.chapters[0].prose


# ---- 面：正文档 vs 脚本档 -----------------------------------------------------

def test_prose_surface_is_patched_first_because_reads_prefer_prose():
    """读侧是"正文优先"（`chapter_plain`），所以改也必须改那一份。"""
    p = normalize_project(
        {
            "id": "p3",
            "title": "两面",
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "prose": "正文档这一句。还有这一句。",
                    "blocks": [{"type": "raw", "code": "脚本档这一句。还有这一句。"}],
                }
            ],
        }
    )
    res = _patch(p, [{"find": "还有这一句", "replace": "改成新的一句"}])
    ch = res.project.chapters[0]
    assert "改成新的一句" in ch.prose, "权威面必须改到"
    # 另一面能干净匹配时一并同步：作者切过去不该看到旧文
    assert "改成新的一句" in ch.blocks[0]["code"]
    assert "脚本档同步" in res.applied[0]


def test_script_only_chapter_keeps_block_types():
    """纯脚本档 + find 落在单块内 → 逐块就地改，手调的 scene/show 不许退化成 raw。"""
    blocks = [
        {"type": "label", "id": "start", "name": "start"},
        {"type": "scene", "image": "bg_apartment"},
        {"type": "raw", "code": "雪菜：「热的。」"},
        {"type": "show", "image": "yukina", "at": "center"},
    ]
    res = _patch(_script_project(blocks), [{"find": "热的", "replace": "烫的"}])
    assert res.skipped == []
    after = res.project.chapters[0].blocks
    assert [b["type"] for b in after] == ["label", "scene", "raw", "show"], after
    assert after[2]["code"] == "雪菜：「烫的。」"
    assert after[1] == {"type": "scene", "image": "bg_apartment"}
    assert "逐块" in res.applied[0]


def test_patch_writes_back_to_the_same_text_field():
    """`narration` / `dialogue` 用 `text` 而不是 `code`。

    一律写回 `code` 会给这些块**多加**一个字段，而渲染器仍读 `text`——
    补丁看上去成功了，实际一个字没改。这条钉住"按原字段写回"。
    """
    blocks = [
        {"type": "narration", "text": "雨落在站台上。"},
        {"type": "dialogue", "characterId": "lin", "text": "你来了。"},
    ]
    res = _patch(_script_project(blocks), [{"find": "雨落在站台上", "replace": "雨已经停了"}])
    assert res.skipped == []
    after = res.project.chapters[0].blocks
    assert after[0] == {"type": "narration", "text": "雨已经停了。"}
    assert "code" not in after[0], "不许给 narration 块塞一个多余的 code 字段"
    assert after[1] == {"type": "dialogue", "characterId": "lin", "text": "你来了。"}


def test_prose_chapter_is_never_replaced_by_script_blocks():
    """只改正文档时，不该顺手把 blocks 换成重排结果（那是另一种"多改"）。"""
    res = _patch(_prose_project(PROSE), [{"find": "热的", "replace": "烫的"}])
    ch = res.project.chapters[0]
    assert "烫的" in ch.prose
    assert list(ch.blocks or []) == [], "没给 blocks 就不该凭空造出来"


# ---- 提案阶段的就读：整章替换会丢多少原文 -------------------------------------
#
# 为什么要有它：作者只有**还没点确认**时才知道"这次会重写 95% 的段落"。写完了再提醒，
# 他只剩"撤回"这一条路。线上那次的教训就是"改 7 处"被 replace_script 执行成了"重写全章"。

LONG_PROSE = "".join(f"第{i}段：他把手举到眼前，停了半息。\n" for i in range(1, 25))


def test_audit_warns_before_writing_when_replace_would_throw_away_the_chapter():
    from app.core.agent import audit_script_actions

    proj = _prose_project(LONG_PROSE)
    warnings = audit_script_actions(
        proj, [{"op": "replace_script", "chapterRef": "第一章", "text": "他停了半息。\n"}]
    )
    assert len(warnings) == 1
    assert "第一章" in warnings[0]
    assert "整章替换" in warnings[0]
    assert "patch_script" in warnings[0], "要指出去哪儿做定点改，不能只说「你丢了很多」"


def test_audit_is_quiet_for_patching_and_for_light_replacement():
    from app.core.agent import audit_script_actions

    proj = _prose_project(LONG_PROSE)
    # patch_script 不报
    assert audit_script_actions(
        proj, [{"op": "patch_script", "chapterRef": "第一章", "edits": [{"find": "停了半息", "replace": "停了半息。"}]}]
    ) == []
    # 几乎照原样替换（只动了其中一段）也不报：那不算重写
    lines = LONG_PROSE.splitlines()
    lines[0] = lines[0].replace("停了半息", "停了半息，又放下")
    near = "\n".join(lines) + "\n"
    assert audit_script_actions(
        proj, [{"op": "replace_script", "chapterRef": "第一章", "text": near}]
    ) == []

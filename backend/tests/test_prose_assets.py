"""正文资产计量（`core/prose_assets.py`）与打分对称性。

背景是第一章那次实测：改稿链路每一级都在做减法（诊断标 cut → 规则删说明书段 → 缝合跳切 →
必要时压缩），而**打分表里只有罚分项**——删字能让每一项都变好，"删掉了什么"没有任何一项在管。
于是"把整场戏删掉"成了最优解。

这组测试钉住修好后的形状：删掉内容是**可计量的违规**，只是措辞变紧则不算。
"""
from __future__ import annotations

from app.core.mark_revise import check_replacement
from app.core.pipeline.candidates import SOFT_WEIGHTS, W_LINT_ERROR, score_candidate
from app.core.prose_assets import (
    REWRITE_LOSS_THRESHOLD,
    asset_preservation,
    asset_problems,
    extract_assets,
    rewrite_loss_note,
    text_preservation,
)
from app.domain.types import VnProject

DINNER = """（她把碗端在手里，没动筷子。）
她：「热的。」
（她往怀里挪了一点。）
她：「所里的汤，一直是温的。」
我：「（把碗搁上架）你碗洗了没有。」
她：「为什么要分开？」
"""


def _project() -> VnProject:
    return VnProject.model_validate(
        {
            "id": "p1",
            "title": "雨夜",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [
                {"id": "c1", "defineName": "yukina", "displayName": "雪菜", "voice": "惜话"}
            ],
            "chapters": [
                {"id": "ch1", "title": "第一章", "blocks": [{"type": "narration", "text": "雨。"}]}
            ],
        }
    )


# ---- 计量本身 -----------------------------------------------------------------


def test_extract_counts_structural_assets():
    a = extract_assets(DINNER)
    assert a["actions"] == 3
    assert a["dialogues"] == 4
    assert a["questions"] == 1


def test_identical_text_loses_nothing():
    r = asset_preservation(DINNER, DINNER)
    assert r["loss"] == 0.0
    assert r["note"] == ""


def test_deleting_a_scene_is_a_big_loss():
    r = asset_preservation(DINNER, "她把汤喝了。\n")
    assert r["loss"] == 1.0
    assert r["worst"] == "actions"
    assert "对白少 4" in r["note"]
    assert asset_problems(DINNER, "她把汤喝了。\n"), "整场删掉必须报出来"


def test_tightening_the_wording_is_not_a_loss():
    """只是把两句并成一句，不该报——否则改稿会变成噪声。"""
    tight = """（她端着碗。）
她：「热的。所里的汤，一直是温的。」
我：「（把碗搁上架）你碗洗了没有。」
她：「为什么要分开？」
"""
    r = asset_preservation(DINNER, tight)
    assert 0 < r["loss"] < 0.34
    assert asset_problems(DINNER, tight) == []


def test_adding_content_is_never_penalised():
    """只罚丢、不奖多：多写不算加分，那属于长度项的事。"""
    r = asset_preservation(DINNER, DINNER + DINNER)
    assert r["loss"] == 0.0


def test_proper_nouns_are_tracked():
    r = asset_preservation("雪菜看着《外部观察日志》。", "她看着那本册子。", names=["雪菜"])
    assert r["ratios"]["proper"] == 0.0
    assert "雪菜" in r["note"] or "专名" in r["note"]


def test_signals_absent_from_the_source_do_not_participate():
    """原稿本来没有问句，就不该拿"问句没少"来算分。"""
    r = asset_preservation("（他站着。）\n他：「嗯。」\n", "（他站着。）\n")
    assert r["ratios"]["questions"] is None
    # 动作一份没少（1→1），对白全没了 → 最惨的是对白
    assert r["worst"] == "dialogues"
    assert r["loss"] == 1.0


# ---- 逐字重合度：分辨"定点改"与"整章重写" -------------------------------------


def test_text_preservation_separates_patching_from_rewriting():
    """两个量具分工不同，别混用。

    `asset_preservation` 量**信息类别**（对白/动作/问句/专名）——整章重写时它可能完全正常
    （对白还是那么多、专名一个没丢），于是会得出"没问题"的错误结论。
    线上那次就是这样：模型自述"改了 7 处"，实际逐字保留只剩个位数百分比。
    """
    src = "（她端着碗。）\n她：「热的。」\n（她往怀里挪了一点。）\n她：「所里的汤，一直是温的。」\n你：「你碗洗了没有。」\n"

    # 定点改一处 → 逐字保留率很高
    patched = src.replace("她：「热的。」", "她：「这个是热的。」")
    assert text_preservation(src, patched)["ratio"] >= 0.8
    assert rewrite_loss_note(src, patched) is None

    # 整章重写（段落数差不多、信息类别也差不多）→ 逐字保留率掉下来
    rewritten = (
        "（她端着碗，手指搭在碗沿上。）\n她：「这个东西是热的。」\n"
        "（她把它往身前带了带。）\n她：「研究所的汤从来不烫。」\n你：「碗洗了没有。」\n"
    )
    report = text_preservation(src, rewritten)
    assert report["ratio"] == 0.0
    assert report["beforeLines"] == 5 and report["lostLines"] == 5
    # 关键对照：信息类别几乎没变，所以只有逐字重合度能抓出"这是重写"
    assert asset_preservation(src, rewritten)["loss"] < REWRITE_LOSS_THRESHOLD
    assert rewrite_loss_note(src, rewritten)


def test_rewrite_loss_note_stays_quiet_on_small_samples():
    """原文不到 5 段就不报：那点量算出来的比例没有意义。"""
    assert rewrite_loss_note("a\nb\nc\n", "完全换掉的内容\n") is None
    assert rewrite_loss_note("", "任何内容\n") is None


# ---- 打分对称性 ---------------------------------------------------------------


def test_soft_weights_still_sum_to_the_hard_error_weight():
    """加了 `assets` 项也必须维持这条算术前提，否则"一票否决"就不成立。"""
    assert abs(sum(SOFT_WEIGHTS.values()) - W_LINT_ERROR) < 1e-9
    assert "assets" in SOFT_WEIGHTS


def test_style_skill_hits_are_not_double_counted():
    """style_skill 的命中归 `aiFlavor` 一项；`lintWarn` 只数其余来源。

    双重计罚的后果不是"更严"，而是误报的代价翻倍（一处 warn ≈0.088 分），
    于是越贴近指南范例的稿子越吃亏。反过来，**两边都不算**同样是错的——
    那会让"点了点头"这类命中变成免费。
    """
    row = score_candidate("他点了点头，轻轻一笑。\n", _project(), instruction="续写")
    assert row["lintWarn"] >= 1, "诊测前提：这段确实命中了禁用项"
    assert row["penalties"]["lintWarn"] == 0.0, "禁用项的 warn 不该再进 lintWarn 项"
    assert row["aiFlavor"]["count"] >= 1, "它该在 AI 味项里被计一次（不能两边都不算）"
    assert row["penalties"]["aiFlavor"] > 0
    assert any("此处不重复计罚" in n for n in row["notes"])


def test_assets_term_is_absent_without_a_source():
    """生成侧没有原稿 → 这一项缺席、不参与，权重在其余项之间重新归一化。"""
    row = score_candidate(DINNER, _project(), instruction="续写")
    assert row["penalties"]["assets"] is None
    assert row["assetKeep"] is None
    assert "assets" not in row["weights"]
    assert abs(sum(row["weights"].values()) - 1.0) < 1e-6
    assert not any("资产" in n for n in row["notes"])


def test_assets_term_kicks_in_when_a_source_is_given():
    """同一份"把整场删成一句"的稿子：不给原稿时看着很干净，给了原稿就要挨罚。"""
    thin = "她把汤喝了。\n"
    without = score_candidate(thin, _project(), instruction="续写")
    with_src = score_candidate(thin, _project(), instruction="续写", source=DINNER)

    assert with_src["penalties"]["assets"] == 1.0
    assert "assets" in with_src["weights"]
    assert with_src["score"] < without["score"], "删掉整场必须比不删更吃亏"
    assert any("资产流失" in n for n in with_src["notes"])


def test_asset_check_is_wired_into_mark_revise():
    """改稿自检是 `variant_select` 的约束轴：删掉内容要变成一条会被计罚的问题。"""
    problems = check_replacement(DINNER, "她把汤喝了。\n")
    assert any("删掉了原稿的内容" in p for p in problems), problems
    # 措辞变紧不该被报
    assert not [
        p
        for p in check_replacement(
            DINNER,
            "（她端着碗。）\n她：「热的。」\n我：「（把碗搁上架）你碗洗了没有。」\n她：「为什么要分开？」\n",
        )
        if "删掉了原稿的内容" in p
    ]

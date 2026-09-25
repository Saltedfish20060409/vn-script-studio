"""文体剖面（读数）：句长、叙述人称、以及对白驱动程度——**只读不判**。

依据（2026-09 核对，见 docs/references.md「视觉小说 / 轻小说实务（参考层）」）：
- 《轻浅的美学：论日本轻小说的文体特征与审美价值》（硕士论文）：短句、对白占比高、
  第一人称、拟声/拟态词与注音是轻小说文体的构成要素；
- 《ライトノベル表現論：会話・創造・遊びのディスコースの考察》：轻小说以会话为文体中心；
- 《日本轻小说模式的演变及特征》（出版发行研究 2017(08)）：连载/文库本形态决定节奏。

这个文件钉住三件事，都是"读数不能变成评分"的具体形态：
1. 没有正文时给 `None` 而不是 0（"没有句子" ≠ "句长 0 字"）；
2. 人称只统计**地の文**（对白里的「我/你」是常态，混进来会把读数带偏）；
3. 读数带 `basis` 且**不产出建议**——界面按 `kind="reading"` 与问题/建议分开显示。
"""

from __future__ import annotations

from app.core.novel_craft import (
    LONG_SENTENCE_CHARS,
    SHORT_SENTENCE_CHARS,
    STYLE_BASIS,
    ProseUnit,
    analyze_novel_craft,
    chapter_readability,
    person_stats,
    sentence_stats,
    style_readings,
)
from app.core.project import normalize_project

KIND_DIALOGUE = "dialogue"
KIND_NARRATION = "narration"


def _units(*texts):
    return [ProseUnit(KIND_NARRATION, "「我」在这个镇上住了三年。", None)]  # placeholder


# ---- 句长 --------------------------------------------------------------------


def test_sentence_stats_splits_on_cjk_enders_and_reports_percentiles():
    units = [
        ProseUnit(KIND_NARRATION, "短句。这是一个稍微长一点的句子，用来把中位数推上去一些。", None),
        ProseUnit(KIND_NARRATION, "中等长度的句子在这里出现，用于观察分位。", None),
    ]
    out = sentence_stats(units)
    assert out["count"] == 3
    assert out["p50"] is not None and out["p90"] >= out["p50"]
    assert out["shortThreshold"] == SHORT_SENTENCE_CHARS
    assert out["longThreshold"] == LONG_SENTENCE_CHARS
    # 短句比 + 长句比 = 两条互补的读数，都在 0..1
    assert 0.0 <= out["shortRatio"] <= 1.0


def test_sentence_stats_counts_short_and_long():
    short = ProseUnit(KIND_NARRATION, "雨停了。她笑了。天亮了。", None)
    long_text = ProseUnit(KIND_NARRATION, "他" + "走" * 60 + "。", None)
    out = sentence_stats([short, long_text])
    assert out["count"] == 4
    assert out["shortRatio"] == 0.75
    assert out["longRatio"] == 0.25


def test_sentence_stats_on_empty_text_is_none_not_zero():
    out = sentence_stats([])
    assert out["count"] == 0
    assert out["p50"] is None and out["shortRatio"] is None and out["longRatio"] is None


def test_commas_do_not_split_sentences():
    """逗号/顿号不分句：分错了句长读数会整体偏小。"""
    units = [ProseUnit(KIND_NARRATION, "他停下来，看了看天，又走了。", None)]
    assert sentence_stats(units)["count"] == 1


# ---- 人称 --------------------------------------------------------------------


def test_person_stats_counts_narration_only():
    """对白里的「我」「你」是常态，混进来会把读数带偏——只统计地の文。"""
    units = [
        ProseUnit(KIND_NARRATION, "我抬头看他。她也看了我一眼。", None),
        ProseUnit(KIND_DIALOGUE, "我我我我你你你你他他他他", "雨宫澪"),
    ]
    out = person_stats(units)
    assert out["first"] == 2  # 地の文里两个「我」
    assert out["third"] == 2  # 「他」+「她」各一次（对白里的「他他他他」完全不计）
    assert out["firstRatio"] == round(2 / 4, 3)
    assert out["checked"] is True


def test_person_stats_without_markers_is_unmeasured():
    units = [ProseUnit(KIND_NARRATION, "雨停了。钟声响了。", None)]
    out = person_stats(units)
    assert out["first"] == 0 and out["third"] == 0
    assert out["firstRatio"] is None, "没有人称标记 ≠ 第一人称占 0%"


# ---- 整书读数 ----------------------------------------------------------------


def _project(*chapters):
    return normalize_project(
        {
            "id": "p-style",
            "title": "文体",
            "chapters": [
                {"id": f"c{i + 1}", "title": f"第{i + 1}章", "prose": text}
                for i, text in enumerate(chapters)
            ],
        }
    )


def _dialogue_heavy() -> str:
    return "\n".join(
        [
            "「你等很久了？」我问他。",
            "「没有。」他摇头。「刚到。」",
            "「那就走吧。」",
            "钟声响了两下。",
            "「走吧。」",
        ]
    )


def _narration_heavy() -> str:
    return (
        "雨停了，天光从云缝里漏下来，落在积水的路面上，晃出一层很薄的金色。"
        "他站在屋檐下，把伞收拢，水珠沿着伞骨一颗一颗掉下去，砸在石阶上，溅起细小的水花。"
        "远处有人在收摊，木轮碾过石板，发出很钝的响声。"
    )


def test_style_profile_readings_are_descriptive_and_carry_basis():
    out = analyze_novel_craft(_project(_dialogue_heavy(), _narration_heavy()))
    profile = out["styleProfile"]
    labels = [r["label"] for r in profile["readings"]]
    assert "对白 / 叙述" in labels
    assert "句长" in labels
    assert "叙述人称（地の文）" in labels
    for row in profile["readings"]:
        assert row["kind"] == "reading", "读数不能与问题混在一起"
        assert row["basis"].strip(), "每条读数都要说得出依据"
        assert "建议" not in row["value"]  # 读数里不该出现建议口吻


def test_dialogue_and_narration_driven_books_get_different_readings():
    """分档描述要真的跟着文本走：全对白驱动的书 vs 全叙述的书，读数不该一样。"""
    dialogue = analyze_novel_craft(_project(_dialogue_heavy()))["styleProfile"]["readings"]
    narration = analyze_novel_craft(_project(_narration_heavy()))["styleProfile"]["readings"]
    d_value = next(r["value"] for r in dialogue if r["label"] == "对白 / 叙述")
    n_value = next(r["value"] for r in narration if r["label"] == "对白 / 叙述")
    assert "对白驱动" in d_value, d_value
    assert "叙述驱动" in n_value, n_value
    # 一书的读数只描述它自己，不做跨书比较
    assert d_value != n_value


def test_style_profile_summary_has_medians_and_empty_project_returns_nothing():
    out = analyze_novel_craft(_project(_dialogue_heavy()))
    summary = out["styleProfile"]["summary"]
    assert summary["avgChapterWords"] > 0
    assert summary["onomatopoeiaPer1000"] is not None

    empty = analyze_novel_craft(normalize_project({"id": "p", "title": "空"}))
    assert empty["styleProfile"]["readings"] == []
    assert empty["styleProfile"]["note"].strip()


def test_style_readings_do_not_emit_suggestions():
    """读数就是读数：`style_readings` 的返回值里不能出现"应该/建议/必须"。"""
    out = analyze_novel_craft(_project(_dialogue_heavy(), _narration_heavy()))
    for row in out["styleProfile"]["readings"]:
        assert not any(word in row["value"] for word in ("应该", "建议", "必须", "改成"))


def test_style_basis_names_the_sources():
    """依据表要指向具体文献（否则几个月后没人知道这个阈值哪来的）。"""
    assert "轻浅的美学" in STYLE_BASIS["sentence"]
    assert "ライトノベル表現論" in STYLE_BASIS["dialogue"]
    assert "出版发行研究" in STYLE_BASIS["serialization"]


def test_chapter_row_exposes_sentence_and_person():
    out = analyze_novel_craft(_project(_dialogue_heavy()))
    row = out["perChapter"][0]
    assert row["sentence"]["count"] > 0
    assert "firstRatio" in row["person"]
    # 读数与既有的可读性口径并存（对白占比仍是同一个数）
    assert row["ratio"]["dialogue"] is not None
    assert chapter_readability([ProseUnit(KIND_NARRATION, "一句话。", None)])["words"]["total"] == 3


def test_short_sentence_threshold_is_a_named_constant():
    """阈值必须是命名常量（改它要能一眼看到，而不是散在 f-string 里）。"""
    assert 5 <= SHORT_SENTENCE_CHARS <= 25
    assert LONG_SENTENCE_CHARS > SHORT_SENTENCE_CHARS

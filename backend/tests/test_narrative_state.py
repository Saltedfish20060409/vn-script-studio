"""因果层（`core/narrative_state.py`）的判定口径。

这一层存在的理由只有一条：**窗口法在远端结构上看不见因果矛盾**——"两张章要同时
在场"才对得上，而同窗距离上界是 overlap（60 章实测 16-30 桶同窗率 0.00）。
`narrative_state` 绕开的办法是"按新章的断言去索引历史断言"：查询跨度与章距无关。

所以本文件钉的不是"能跑"，而是**判定口径的两个方向**：

- 正方向：明写"不知道 → 知道"而中间没有交代、明写"结果发生而前提动作没发生"，
  必须报出来（而且报在**冲突章**上，这样基准才能按章归因）；
- 反方向：有交代的知情转变、已满足的条款、代词主题、没有条款的否定动作，
  **一条都不能报**——多报一条就是 precision 掉一格，而 precision 目前是 1.00。

其中 `test_grant_about_something_else_must_not_suppress` 是一条**真缺陷的回归闸**：
最初的实现只按"这一章里出现过告诉/说明"来抑制，于是与本事无关的一句「说明」
把一条真的无因事件给漏掉了（第 13 章埋、第 46 章兑现，中间第 23 章因为别处的
交代而被当成已交代）。修法是要求那句话**提到同一主语或主题相近**。
"""

from __future__ import annotations

from app.core.eval_longrange import (
    build_synthetic_novel,
    detect_deterministic,
    evaluate_detections,
)
from app.core.narrative_state import (
    analyze_narrative_state,
    build_state,
)
from app.core.project import normalize_project


def _proj(texts: list[str]):
    """把一串"每章一句旁白"拼成一个工程，用来隔离地测判定口径。"""
    return normalize_project(
        {
            "id": "p",
            "title": "因果层用例",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "characters": [
                {"id": "lin", "defineName": "lin", "displayName": "林夏"},
                {"id": "chen", "defineName": "chen", "displayName": "陈默"},
            ],
            "chapters": [
                {
                    "id": f"ch{i + 1}",
                    "title": f"第{i + 1}章",
                    "blocks": [{"type": "narration", "text": t}],
                }
                for i, t in enumerate(texts)
            ],
        }
    )


def _codes(project, kind: str) -> list[str]:
    return [
        f["chapterId"]
        for f in analyze_narrative_state(project)["findings"]
        if f["code"] == kind
    ]


# ------------------------------------------------------------ A：知情转变

NOT_KNOW = "林夏还不知道那扇门后面是什么。"
NOW_KNOW = "林夏径直走向那扇门，她已经知道了门后的一切。"
FILLER = "雨还在下。"


def test_unenabled_event_is_reported_at_the_conflict_chapter():
    """远距离也照样报：这一层不靠窗口，第 2 章与第 20 章对上不需要任何"同窗"。"""
    texts = [NOT_KNOW] + [FILLER] * 18 + [NOW_KNOW]
    project = _proj(texts)
    assert _codes(project, "unenabled_event") == ["ch20"]


def test_a_grant_between_suppresses_the_finding():
    """有交代就不报——这是反方向，也是这一层敢报的前提。"""
    texts = [NOT_KNOW] + [FILLER] * 8 + ["陈默告诉了她那扇门后面是什么。"] + [FILLER] * 8 + [NOW_KNOW]
    project = _proj(texts)
    assert _codes(project, "unenabled_event") == []


def test_grant_in_the_same_chapter_suppresses_the_finding():
    """把交代与结果写在同一章是常见写法，不能因为"章号相同"就当成没交代。"""
    texts = [NOT_KNOW] + [FILLER] * 5 + ["陈默告诉了她那扇门后面是什么。林夏知道了门后的一切。"]
    project = _proj(texts)
    assert _codes(project, "unenabled_event") == []


def test_grant_about_something_else_must_not_suppress():
    """回归闸：与本事无关的交代不能把真的无因事件压掉。

    第一版实现只按"这一章里出现过告诉/说明"抑制，于是中间随便一句
    「他说明了来意」就会把它压掉——实测漏了一条真的。
    """
    texts = [
        NOT_KNOW,
        FILLER,
        "陈默说明了来意。",  # 与"门后是什么"无关的一句交代
        FILLER,
        NOW_KNOW,
    ]
    project = _proj(texts)
    assert _codes(project, "unenabled_event") == ["ch5"], (
        "无关的交代不该抑制；抑制必须看那句话讲的是不是同一件事"
    )


def test_pronoun_topic_is_never_asserted():
    """主题是指代时判不了所指，不建断言——硬凑只会制造误报。"""
    project = _proj(["林夏还不知道这些。", FILLER, "林夏知道了这些。"])
    state = build_state(project)
    assert state.knowledge == []
    assert _codes(project, "unenabled_event") == []


def test_different_subject_does_not_pair_up():
    """不同角色的知情不能互相顶包。"""
    project = _proj([NOT_KNOW, FILLER, "陈默已经知道了门后的一切。"])
    assert _codes(project, "unenabled_event") == []


def test_unrelated_topic_does_not_pair_up():
    """同一个角色的两件不相干的事，不能凑成一条。"""
    project = _proj([NOT_KNOW, FILLER, "林夏已经知道了末班车几点到。"])
    assert _codes(project, "unenabled_event") == []


# ------------------------------------------------------------ B：条款不符

COND = "售票员说过，只有她亲口叫出那个名字，钟才会停。"
MISMATCH = "钟停了。她始终没有开口。"
SATISFIED = "她开口叫出了那个名字，钟停了。"


def test_payoff_terms_mismatch_is_reported():
    texts = [COND] + [FILLER] * 15 + [MISMATCH]
    project = _proj(texts)
    assert _codes(project, "payoff_terms_mismatch") == ["ch17"]


def test_satisfied_condition_is_not_reported():
    """前提动作明写发生了 → 条款被满足，不该报。"""
    texts = [COND] + [FILLER] * 5 + [SATISFIED]
    project = _proj(texts)
    assert _codes(project, "payoff_terms_mismatch") == []


def test_negation_without_any_condition_is_not_reported():
    """没有写过任何条款时，"结果出现 + 某动作没发生"只是巧合，不报。"""
    project = _proj([FILLER, FILLER, MISMATCH])
    assert _codes(project, "payoff_terms_mismatch") == []


def test_condition_is_only_looked_at_after_it_was_stated():
    """条款之前的章不算：因果方向不能反。"""
    texts = [MISMATCH] + [FILLER] * 3 + [COND]
    project = _proj(texts)
    assert _codes(project, "payoff_terms_mismatch") == []


# ------------------------------------------------------------------ 通用性质


def test_findings_are_warn_level_so_nothing_blocks():
    """这一层是**推断**不是证明，所以只提示、不挡任何东西（与 write_gate 的分工）。"""
    project = _proj([NOT_KNOW, FILLER, NOW_KNOW, COND, FILLER, MISMATCH])
    findings = analyze_narrative_state(project)["findings"]
    assert findings
    assert {f["severity"] for f in findings} == {"warn"}


def test_every_finding_carries_its_evidence():
    """给作者的每条结论都要能自己核对（引用原句 + 章 id）。"""
    project = _proj([NOT_KNOW, FILLER, NOW_KNOW])
    for f in analyze_narrative_state(project)["findings"]:
        assert f["chapterId"]
        assert f["message"]
        assert f["evidence"]


def test_empty_project_is_safe():
    project = normalize_project({"id": "p", "title": "空", "chapters": []})
    out = analyze_narrative_state(project)
    assert out["findings"] == []


def test_layer_is_wired_into_the_deterministic_detector():
    """基准要能给它记分，否则做了也不知道有没有用。"""
    project, _gt = build_synthetic_novel(chapters=60, seed=20260409)
    kinds = {d["kind"] for d in detect_deterministic(project)}
    assert {"unenabled_event", "payoff_terms_mismatch"} <= kinds


def test_benchmark_causal_recall_is_perfect_with_no_false_positives():
    """头条读数：因果层把"现有确定性检测器一条也抓不到"这个缺口补上了。

    这条同时是一致性闸——哪天检测器被改坏，或者埋点/诱导项被改动导致它开始误报，
    这里会红。它刻意**不钉具体召回数字**，只钉"因果类全中且零误报"：
    数字会随分桶可放下与否浮动，而"全中且不误报"才是这一层的契约。
    """
    for seed in (20260409, 3, 14, 21):
        project, gt = build_synthetic_novel(chapters=60, seed=seed)
        out = evaluate_detections(gt, detect_deterministic(project))
        assert out["byTier"]["causal"]["recall"] == 1.0, (seed, out["byTier"])
        assert out["precision"] == 1.0, (seed, out["falsePositives"])
        assert out["fp"] == 0, (seed, out["falsePositives"])


def test_causal_distractors_never_fire():
    """诱导项是这一层的**精度闸**：形似因果但写法正常的三种情况，一条都不许报。"""
    for seed in (20260409, 3, 14, 21):
        project, gt = build_synthetic_novel(chapters=60, seed=seed)
        causal_d = [d for d in gt["distractors"] if d.get("tier") == "causal"]
        assert len(causal_d) == 3, (seed, gt["counts"].get("causalDistractorSkipped"))
        chapters = {d["chapter"] for d in causal_d}
        fired = [
            (d["kind"], d["chapterIds"])
            for d in detect_deterministic(project)
            if d["kind"] in ("unenabled_event", "payoff_terms_mismatch")
            and set(d["chapterIds"]) & chapters
        ]
        assert fired == [], (seed, fired)


def test_causal_distractor_skips_are_reported_not_silent():
    """章不够时摆不下的诱导项要如实计数（静默少一条等于把精度闸关掉一半）。"""
    _, gt = build_synthetic_novel(chapters=48, seed=14)
    placed = len([d for d in gt["distractors"] if d.get("tier") == "causal"])
    skipped = len(gt["counts"].get("causalDistractorSkipped") or [])
    assert placed + skipped == 3, (placed, skipped)

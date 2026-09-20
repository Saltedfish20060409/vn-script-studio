"""提示词工程化：文风样例进上下文、每个任务有输出契约、文风记忆自动学习（默认开）。

依据都来自同一个实测结论：**样例比规则管用，默认开比让作者去点管用**。
（同类功能的线上使用率：需要主动下命令的 agent_jobs 只有 2 次，而挂在保存路径上的
章节摘要 159/159 全覆盖。）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.agent_context import (
    TASK_OUTPUT_CONTRACT,
    build_agent_context,
    output_contract,
    task_key_rules,
)
from app.core.project import normalize_project
from app.services.style_memory_auto import (
    CHAPTER_STRIDE,
    MIN_CHAPTERS,
    MIN_PROSE_CHARS,
    should_auto_learn_style,
)


def _project(style_memory=None):
    chapters = [
        {
            "id": f"c{i}",
            "title": f"第{i}章",
            "prose": "雨落在站台上。" * 40,
            "blocks": [{"type": "label", "id": "start", "name": "start"}],
        }
        for i in range(1, 5)
    ]
    data = {
        "id": "p1",
        "title": "样例测试",
        "chapters": chapters,
        "bible": {"world": "多雨的城市。"},
    }
    if style_memory is not None:
        data["styleMemory"] = style_memory
    return normalize_project(data)


# ---------------------------------------------------------------------------
# ④b 文风样例
# ---------------------------------------------------------------------------


def test_style_samples_are_injected_next_to_the_guide():
    project = _project(
        {
            "guide": "你习惯短句，少用形容词。",
            "samples": ["雨落在站台上。", "他把手举到眼前，停了半息。"],
        }
    )
    ctx = build_agent_context(project, chapterId="c1", userMessage="接着写", task="continue")
    assert "作者文风记忆" in ctx.text
    assert "作者原文样例" in ctx.text
    assert "雨落在站台上。" in ctx.text
    assert any("文风样例" in x for x in ctx.included)


def test_style_guide_without_samples_still_works():
    project = _project({"guide": "你习惯短句。"})
    ctx = build_agent_context(project, chapterId="c1", userMessage="接着写", task="continue")
    assert "作者文风记忆" in ctx.text
    assert "作者原文样例" not in ctx.text


def test_style_samples_are_capped_at_three():
    project = _project({"guide": "习惯短句。", "samples": [f"样例{i}。" for i in range(9)]})
    ctx = build_agent_context(project, chapterId="c1", userMessage="接着写", task="continue")
    assert "样例0。" in ctx.text and "样例2。" in ctx.text
    assert "样例3。" not in ctx.text


# ---------------------------------------------------------------------------
# ④a 输出契约
# ---------------------------------------------------------------------------


def test_every_agent_task_has_an_output_contract():
    from app.core.agent_context import AGENT_TASKS

    for task in AGENT_TASKS:
        contract = output_contract(task)
        assert len(contract) >= 10, task
    # 写作类任务都要明确"只输出正文"
    for task in ("continue", "rewrite", "polish", "scene"):
        assert "只输出" in TASK_OUTPUT_CONTRACT[task], task


def test_output_contract_is_placed_at_the_end_of_context():
    project = _project()
    ctx = build_agent_context(project, chapterId="c1", userMessage="接着写", task="continue")
    tail = ctx.text[-500:]
    assert "输出契约" in tail
    assert "输出契约" in ctx.included
    # 硬规则与输出契约都在末尾：长上下文里中间的要求最容易被忽略
    assert "本次硬规则" in tail


# ---------------------------------------------------------------------------
# ⑨ 「证明它记得」：这次到底读了什么
# ---------------------------------------------------------------------------


def test_included_details_list_what_was_read():
    project = _project()
    ctx = build_agent_context(project, chapterId="c1", userMessage="接着写", task="continue")
    labels = [d["label"] for d in ctx.includedDetails]
    assert any("当前章" in x for x in labels)
    assert any("章节目录" in x for x in labels)
    # 每条都要带摘录，不能只有标题（否则"可点开看原文"就是空话）
    previews = [d["preview"] for d in ctx.includedDetails]
    assert all(p for p in previews), ctx.includedDetails
    assert any("第1章" in p or "第2章" in p for p in previews)


def test_included_details_include_style_samples_when_present():
    project = _project({"guide": "短句。", "samples": ["雨落在站台上。"]})
    ctx = build_agent_context(project, chapterId="c1", userMessage="接着写", task="continue")
    assert any(d["label"] == "文风样例" and "雨落在站台上" in d["preview"] for d in ctx.includedDetails)


def test_included_details_skip_what_the_author_dropped():
    project = _project()
    ctx = build_agent_context(
        project, chapterId="c1", userMessage="接着写", task="continue", exclude=["index"]
    )
    assert not any("章节目录" in d["label"] for d in ctx.includedDetails)


# ---------------------------------------------------------------------------
# ④c 文风记忆自动学习
# ---------------------------------------------------------------------------


def test_auto_learn_waits_until_there_is_enough_text():
    ok, why = should_auto_learn_style(MIN_CHAPTERS - 1, MIN_PROSE_CHARS * 2, None)
    assert ok is False and "章节" in why
    ok, why = should_auto_learn_style(MIN_CHAPTERS, MIN_PROSE_CHARS - 1, None)
    assert ok is False and "内容" in why


def test_auto_learn_runs_when_never_learned():
    ok, why = should_auto_learn_style(MIN_CHAPTERS, MIN_PROSE_CHARS, None)
    assert ok is True and "还没学过" in why


def test_auto_learn_skips_right_after_learning():
    memory = {
        "guide": "短句。",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "learnedChapterCount": 4,
    }
    ok, why = should_auto_learn_style(5, MIN_PROSE_CHARS * 3, memory)
    assert ok is False and "刚学过" in why


def test_auto_learn_reruns_after_enough_new_chapters():
    memory = {
        "guide": "短句。",
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "learnedChapterCount": 4,
    }
    ok, why = should_auto_learn_style(4 + CHAPTER_STRIDE, MIN_PROSE_CHARS * 3, memory)
    assert ok is True and "若干章" in why


def test_auto_learn_reruns_when_memory_is_stale():
    old = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    memory = {"guide": "短句。", "updatedAt": old, "learnedChapterCount": 4}
    ok, why = should_auto_learn_style(6, MIN_PROSE_CHARS * 3, memory)
    assert ok is True and "过期" in why


def test_auto_learn_retries_when_previous_attempt_learned_nothing():
    ok, why = should_auto_learn_style(6, MIN_PROSE_CHARS * 3, {"guide": "", "samples": []})
    assert ok is True and "没学到" in why

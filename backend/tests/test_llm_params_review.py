"""采样参数分档 + 生成后自检（纯函数，不碰数据库、不调模型）。"""

from __future__ import annotations

from app.core.llm_params import (
    MARK_ADVICE_TEMPERATURE,
    MARK_REVISE_TEMPERATURE,
    STRUCTURED_TEMPERATURE,
    STYLE_MEMORY_TEMPERATURE,
    clamp_temperature,
    sampling_for,
    task_temperature,
)
from app.core.mark_revise import build_retry_messages, check_replacement
from app.core.narrative_review import REVIEW_TASKS, should_self_review

# ---------------------------------------------------------------------------
# ⑥ 参数按任务分档
# ---------------------------------------------------------------------------


def test_writing_tasks_are_ordered_by_how_free_they_should_be():
    # 连续创作 > 改写 > 润色 > 一致性检查（温度必须单调，别把"要准"的任务调得比"要活"的还高）
    assert task_temperature("continue") > task_temperature("rewrite")
    assert task_temperature("rewrite") > task_temperature("polish")
    assert task_temperature("polish") > task_temperature("consistency")


def test_unknown_task_falls_back_to_writing_default():
    assert task_temperature("没这个任务") == task_temperature("continue")


def test_craft_mode_shifts_temperature_within_bounds():
    base = task_temperature("continue", "full")
    assert task_temperature("continue", "lite") < base
    assert task_temperature("continue", "off") > base
    # 极端值被夹住，不会出现 1.4 这种温度
    assert 0.2 <= task_temperature("consistency", "off") <= 1.0
    assert clamp_temperature(9) == 1.0
    assert clamp_temperature(-3) == 0.2


def test_fixed_task_tiers_are_conservative():
    # 结构化输出最稳，风格提炼次之，局部改写中等，只给建议最保守
    assert STRUCTURED_TEMPERATURE <= STYLE_MEMORY_TEMPERATURE <= MARK_ADVICE_TEMPERATURE
    assert MARK_ADVICE_TEMPERATURE < MARK_REVISE_TEMPERATURE
    assert sampling_for("chat").temperature == task_temperature("chat")


# ---------------------------------------------------------------------------
# ③ 生成后自检
# ---------------------------------------------------------------------------


def test_self_review_is_on_by_default_for_writing_tasks():
    """③ 的核心性质：写作类任务默认就过一遍"挑错责编"，不用作者去开。"""
    for task in ("continue", "rewrite", "polish"):
        assert task in REVIEW_TASKS
        assert should_self_review(task, "auto") is True
    # 明确关掉才不跑
    assert should_self_review("continue", "off") is False


def test_check_replacement_flags_length_runaway():
    problems = check_replacement("他把手举到眼前。", "他把手举到眼前。" * 5)
    assert any("长度" in p and "倍" in p for p in problems)


def test_check_replacement_flags_too_short():
    problems = check_replacement("雨落在站台上，他把手举到眼前，那双手不是他的。", "他没动。")
    assert any("短太多" in p for p in problems)


def test_check_replacement_protects_proper_nouns():
    problems = check_replacement(
        "林越把手举到眼前，《雨城志》从口袋里滑出来。",
        "他把手举起来看了看，书掉在地上。",
        names=["林越"],
    )
    assert any("林越" in p for p in problems)
    assert any("《雨城志》" in p for p in problems)


def test_check_replacement_passes_a_good_rewrite():
    quote = "他慢慢抬起手，举到眼前。"
    assert check_replacement(quote, "他把手举到眼前，停了半息。", names=["林越"]) == []


def test_check_replacement_rejects_empty():
    assert check_replacement("原文。", "   ") == ["改写结果为空"]


def test_retry_messages_carry_the_problems_and_keep_the_contract():
    base = [
        {"role": "system", "content": "系统要求"},
        {"role": "user", "content": "要改这一段"},
    ]
    messages = build_retry_messages(base, ["长度是原文的 3.0 倍"])
    assert messages[0]["content"] == "系统要求"
    assert "长度是原文的 3.0 倍" in messages[1]["content"]
    assert "只输出改写后的正文" in messages[1]["content"]

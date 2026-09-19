"""纯函数测试：标记批改的提示词拼装与模型输出清理（不碰数据库）。"""

from __future__ import annotations

from app.core.mark_revise import (
    _CONTEXT_CAP,
    _QUOTE_CAP,
    build_mark_messages,
    clean_model_text,
)


def _user_text(messages) -> str:
    return [m for m in messages if m["role"] == "user"][0]["content"]


def _system_text(messages) -> str:
    return [m for m in messages if m["role"] == "system"][0]["content"]


def test_rewrite_prompt_carries_context_and_asks_for_one_paragraph_only():
    messages = build_mark_messages(
        quote="他慢慢抬起手，举到眼前。",
        prefix="窗外的雾在退。",
        suffix="那双手不是他的。",
        instruction="改得更冷、更短",
        intent="rewrite",
        style_guide="你习惯短句，避免四字格。",
    )
    system = _system_text(messages)
    user = _user_text(messages)

    # 范围约束是这类批改的核心：只输出这一段
    assert "只输出" in system
    assert "其余一字不动" in system
    # 上下文与要求都要带上
    assert "窗外的雾在退。" in user
    assert "他慢慢抬起手，举到眼前。" in user
    assert "那双手不是他的。" in user
    assert "改得更冷、更短" in user
    # 作者文风记忆要被注入（贴作者自己的腔调）
    assert "你习惯短句" in user


def test_advice_mode_forbids_rewriting():
    messages = build_mark_messages(quote="他感到一阵说不清的恐惧。", intent="advice")
    system = _system_text(messages)
    assert "不要改写正文" in system
    assert "只输出建议本身" in system
    # 建议模式不该出现"输出改写后的这一段"这类指令
    assert "只输出正文那一段" not in system


def test_missing_instruction_falls_back_to_default_goal():
    user = _user_text(build_mark_messages(quote="随便一句。"))
    assert "没写具体要求" in user
    assert "更具体" in user


def test_long_inputs_are_clipped_to_bounds():
    user = _user_text(
        build_mark_messages(
            quote="字" * 5000,
            prefix="前" * 5000,
            suffix="后" * 5000,
            instruction="要" * 5000,
            style_guide="风" * 5000,
        )
    )
    assert "字" * _QUOTE_CAP in user
    assert "字" * (_QUOTE_CAP + 1) not in user
    assert "前" * (_CONTEXT_CAP + 1) not in user
    assert "后" * (_CONTEXT_CAP + 1) not in user


def test_clean_model_text_strips_common_wrappers():
    assert clean_model_text("改后：他把手举到眼前。") == "他把手举到眼前。"
    assert clean_model_text("```\n他把手举到眼前。\n```") == "他把手举到眼前。"
    assert clean_model_text("“他把手举到眼前。”") == "他把手举到眼前。"
    assert clean_model_text("「他把手举到眼前。」") == "他把手举到眼前。"
    # 正常文本不动
    assert clean_model_text("他把手举到眼前。") == "他把手举到眼前。"
    # 只有一侧有引号时不剥（避免误伤正文里的引号）
    assert clean_model_text("“他说。") == "“他说。"

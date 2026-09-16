"""本轮身份块：界面选了哪几位透镜，模型就必须知道是哪几位。

线上真实问题：Agent 面板显示「村上春树 · 东野圭吾 · 渡航」，但问「你现在是谁的思维？」
模型只答"我是驻场责编"，三位透镜一个字都不提 —— 界面与回答对不上。
"""

from __future__ import annotations

from app.core.agent import AGENT_SYSTEM, agent_identity_block
from app.core.lenses import resolve_lenses
from app.core.mentors import resolve_project_mentors


class _Pack:
    def __init__(self, name: str) -> None:
        self.name = name


def test_identity_lists_active_lenses_by_name():
    block = agent_identity_block(
        [_Pack("轻小说×视觉小说写作导师")],
        [_Pack("村上春树"), _Pack("东野圭吾"), _Pack("渡航")],
    )
    assert "村上春树" in block
    assert "东野圭吾" in block
    assert "渡航" in block
    assert "轻小说×视觉小说写作导师" in block
    # 固定身份 + 不许冒充
    assert "责编" in block
    assert "不是" in block and "作家本人" in block
    # 明确了遇到身份类问题怎么答
    assert "是谁" in block or "你是谁" in block


def test_identity_without_lenses_says_so():
    block = agent_identity_block([_Pack("导师")], [])
    assert "没有启用" in block
    assert "透镜" in block


def test_identity_block_is_not_empty_with_nothing():
    """两个都为空也要给出一句明确的话，不能让模型自由发挥。"""
    block = agent_identity_block(None, None)
    assert block.strip()
    assert "责编" in block


def test_identity_block_placed_with_system_prompt():
    """身份块是跟着 AGENT_SYSTEM 一起进 system 的（顺序不能反）。"""
    block = agent_identity_block([], [_Pack("东野圭吾")])
    assert "Editor Agent" in AGENT_SYSTEM
    assert block not in AGENT_SYSTEM  # 动态拼装，不是写死在常量里


def test_identity_names_match_what_lens_packs_resolve_to():
    """真实内置透镜包的中文名要能进身份块（防止 id 与显示名不一致）。"""
    packs = resolve_lenses(["author-murakami", "author-higashino", "author-watari"])
    assert [p.name for p in packs] == ["村上春树", "东野圭吾", "渡航"]
    block = agent_identity_block(resolve_project_mentors(None), packs)
    for p in packs:
        assert p.name in block


def test_identity_block_dedupes_and_skips_blank():
    block = agent_identity_block([_Pack(""), _Pack("导师")], [_Pack("东野圭吾"), _Pack("东野圭吾")])
    assert block.count("东野圭吾") == 1
    assert "导师" in block


def test_compose_puts_identity_right_after_system_prompt():
    """真实拼装顺序：AGENT_SYSTEM 之后紧跟身份块。

    这条顺序就是线上问题的根因——身份块缺席时，模型只看得见"我是驻场责编"。
    这里直接用 run_agent_loop 调用的同一个函数来断言，避免"测试和线上两套拼装"。
    """
    from app.core.agent_loop import compose_agent_system

    identity = agent_identity_block([_Pack("轻小说×视觉小说写作导师")], [_Pack("村上春树")])
    system = compose_agent_system(
        identity_block=identity,
        task="chat",
        craft_block="## 工艺\n- 示例",
        mentor_block="## 写作导师：轻小说×视觉小说写作导师",
        lens_block="—— 作家思维透镜 ——\n村上春树",
        context_text="（本轮上下文）",
    )
    assert system.index(AGENT_SYSTEM) < system.index(identity)
    assert system.index(identity) < system.index("## 写作导师")
    assert system.index(identity) < system.index("作家思维透镜")
    assert "村上春树" in system
    # 参考资料提示只有真的带附件时才出现（协议里另有泛指"用户上传参考资料"的段落，
    # 所以这里比对的是这条注入语句独有的措辞）
    assert "本轮含用户上传参考资料" not in system
    with_docs = compose_agent_system(
        identity_block=identity, task="chat", has_reference_docs=True
    )
    assert "本轮含用户上传参考资料" in with_docs


def test_compose_includes_context_and_memory_blocks():
    from app.core.agent_loop import compose_agent_system

    system = compose_agent_system(
        identity_block="x",
        task="chat",
        context_text="第三章：雨夜",
        chat_memory_block="早前聊过伏笔",
    )
    assert "作品上下文" in system and "第三章：雨夜" in system
    assert "对话记忆归档" in system and "早前聊过伏笔" in system

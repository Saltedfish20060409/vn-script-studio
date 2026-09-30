"""要正文的说法要走进"写"的条件，而作者要的篇幅不许被我们自己的短拍口径吃掉。

两件事都在 2026-09-30 与网页版的对比里露过面（作者账号「搁浅de咸鱼」）：

1. **路由**：作者说「请你先尝试帮我续写一段」和「写到设计完的情节」，两条都落进了
   普通对话档——那一档的提示词写着"正文不要写进 message、message 超过 600 字基本就是
   走错了路"，等于用规则劝模型别写正文。而问方向那句
   （"可以怎么续写？给点方向？顺便检查有没有矛盾"）反而被"矛盾"两个字送进了
   一致性检查档（契约是"先列冲突、不要重写正文"）。所以：
   - "要正文"→ continue（前端另有一条写作通道，见 agentIntent.test.ts）；
   - "问办法 / 要方向"→ chat，且**优先于**关键词。
2. **篇幅**：短拍默认（180–450 字）写在硬规则、任务提示、输出契约**三处**，
   还在上下文末尾重复一次；作者明确说"写完整 / 写到 X"时，三处一起让位——
   否则作者的一句话压不过我们自己的三条默认值，正文就比网页版短一半以上。
"""

from __future__ import annotations

from app.core.agent_context import (
    LONG_PROSE_RULE,
    build_agent_context,
    infer_agent_task,
    output_contract,
    prose_ask,
    task_hint,
    task_key_rules_for,
    wants_full_prose,
)
from app.core.project import normalize_project

# ---- 1. 路由 -----------------------------------------------------------------


def test_writing_requests_are_routed_to_a_writing_task():
    for m in [
        "帮我续写一段",
        "续写",
        "接着往下写",
        "继续写下一段",
        "请你先尝试帮我续写一段",
        "第一章太长我认为不是问题，剧情按我设计的来写就行。请你先尝试帮我续写一段",
        "写到设计完的情节",
        "把这一章写完",
    ]:
        assert infer_agent_task(m) == "continue", m


def test_asking_for_direction_or_critique_stays_in_chat():
    """线上那句原话：句子里有"矛盾"，但它其实是在问方向。"""
    ask = (
        "你认为这个第一章可以怎么续写？能不能提供一些方向？也请你先帮我先检查这部分的"
        "情节跟人物设定是否对的上、前后有没有矛盾、是否符合视觉小说的特点等等。"
    )
    assert infer_agent_task(ask) == "chat"
    assert infer_agent_task("续写的方向有哪些？") == "chat"
    assert infer_agent_task("帮我看看这段续写怎么样") == "chat"
    assert prose_ask("帮我看看这段续写怎么样") is False


def test_prose_ask_needs_a_writing_verb_not_just_the_word():
    """只出现"续写"这两个字不算要正文（讨论稿子时它只是个名词）。"""
    assert prose_ask("这一章的续写我觉得还行") is False
    assert prose_ask("续写的部分我改过了") is False


# ---- 2. 篇幅：短拍让位 --------------------------------------------------------


def test_length_ask_is_recognised():
    assert wants_full_prose("写到设计完的情节")
    assert wants_full_prose("请把这一章写完整")
    assert wants_full_prose("一次写完，不要停")
    assert not wants_full_prose("帮我续写一段")
    assert not wants_full_prose(None)


def test_contract_and_rules_yield_to_the_author():
    short = output_contract("continue")
    long = output_contract("continue", None, "写到设计完的情节")
    assert "180–450" in short
    assert "180–450" not in long, "作者要了篇幅，短拍口径必须让位"
    assert "一次写完" in long

    # 硬规则里那条"不要一次写长章"要被换成覆盖条，而不是并排（并排时模型挑默认值执行）
    default_rules = task_key_rules_for("continue")
    asked_rules = task_key_rules_for("continue", None, "写到设计完的情节")
    assert any("不要一次写长章" in r for r in default_rules)
    assert not any("不要一次写长章" in r for r in asked_rules)
    assert asked_rules[0] == LONG_PROSE_RULE

    # 任务提示（system 里那块）也要跟着翻
    assert "默认短拍不适用" in task_hint("continue", "写到设计完的情节")
    assert "默认短拍不适用" not in task_hint("continue")


def test_no_message_keeps_the_old_behaviour():
    """没给消息的老调用方（含 CLI / 评测）读到的东西一个字都不变。"""
    assert output_contract("continue") == output_contract("continue", None, None)
    assert task_key_rules_for("continue") == task_key_rules_for("continue", None, None)
    assert task_hint("continue") == task_hint("continue", None)


def test_context_tail_carries_the_length_override():
    """端到端：作者要了篇幅时，上下文头尾两处都不再出现 180–450 的短拍口径。"""
    project = _project()
    ctx = build_agent_context(
        project,
        chapterId="ch1",
        userMessage="写到设计完的情节",
        task="continue",
    )
    assert "180–450" not in ctx.text, "短拍口径还在上下文里，模型会照它截断"
    assert "一次写完" in ctx.text
    # 覆盖条要在**头部硬规则**与**末尾硬规则**各出现一次
    head, tail = ctx.text[:1200], ctx.text[-1200:]
    assert "作者本轮明确要了篇幅" in head
    assert "作者本轮明确要了篇幅" in tail

    # 没要篇幅时照旧（回归：别把默认口径改掉）
    plain = build_agent_context(
        project, chapterId="ch1", userMessage="接着写", task="continue"
    )
    assert "180–450" in plain.text


def test_system_prompt_task_hint_also_yields(monkeypatch):
    """system 里那块任务提示（`compose_agent_system`）也要认人话。

    loop 的 checkpoint 会把每块字数记下来——那里用的是同一个调用口径，
    所以 `taskHint` 的字节数跟着作者的话变，作者事后可查。
    """
    from app.core.agent_loop import compose_agent_system

    short = compose_agent_system(identity_block="", task="continue")
    asked = compose_agent_system(
        identity_block="", task="continue", user_message="写到设计完的情节"
    )
    assert "默认短拍不适用" not in short
    assert "默认短拍不适用" in asked
    assert len(asked) > len(short)


# ---- 3. 写正文时，作者上传的参考资料不排第一个让位 ---------------------------


def _project():
    return normalize_project(
        {
            "id": "p-prose",
            "title": "篇幅",
            "bible": {"world": "雨城。"},
            "characters": [{"id": "c1", "displayName": "雪菜", "defineName": "yukina"}],
            "chapters": [
                {"id": "ch1", "title": "第一章", "prose": "她坐在沙发上。" * 20},
                {"id": "ch2", "title": "第二章", "synopsis": "第二章的梗概"},
            ],
        }
    )


def _dropped_keys(ctx) -> set:
    return {row["key"] for row in ctx.budgetReport["droppedSections"]}


def test_reference_docs_survive_longer_while_writing():
    """写正文三档里，参考资料排在让位表**最后**（设计稿就是这一场要照着写的东西）。"""
    docs = "囧" * 40000  # 单块上限 12000，必然超预算
    writing = build_agent_context(
        _project(), chapterId="ch1", userMessage="接着写", task="continue",
        referenceDocs=docs, maxChars=6000,
    )
    chat = build_agent_context(
        _project(), chapterId="ch1", userMessage="这一章写得怎么样", task="chat",
        referenceDocs=docs, maxChars=6000,
    )
    # 两档都不会静默丢东西
    assert "篇幅说明" in writing.text and "篇幅说明" in chat.text
    # 但"先丢谁"不同：讨论档先丢参考资料，写正文档先丢其它量大的块
    writing_included = [x for x in writing.included if x.startswith("篇幅省去:")]
    assert writing_included[0] != "篇幅省去:referenceDocs", writing_included
    assert "篇幅省去:referenceDocs" in writing_included, (
        "真装不下时它还是可以被丢，只是不能排第一个"
    )
    assert "篇幅省去:referenceDocs" in [x for x in chat.included if x.startswith("篇幅省去:")]
    assert _dropped_keys(chat) and _dropped_keys(writing)

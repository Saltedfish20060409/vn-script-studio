"""上下文裁剪：按任务丢掉噪音块、按作者要求摘掉某类资料、硬规则在末尾重复。

针对的问题：工具比"网页端裸聊"差的常见原因不是模型，而是**塞了太多无关资料**——
聊天里用户只贴相关那一段，工具却把 bible、台账、立绘、变量一起灌进去，模型反而分心。
所以这里要能：① 按任务默认裁剪机制类资料；② 让作者手动"本次不带"；③ 硬规则放末尾再出现一次。
"""

from __future__ import annotations

from app.core.agent_context import (
    EXCLUDABLE_SECTIONS,
    build_agent_context,
    sections_to_drop,
    task_key_rules,
)
from app.core.project import normalize_project


def _project():
    return normalize_project(
        {
            "id": "p1",
            "title": "裁剪测试",
            "chapters": [
                {
                    "id": "c1",
                    "title": "第一章",
                    "prose": "雨落在站台上。他慢慢抬起手。",
                    "blocks": [{"type": "label", "id": "start", "name": "start"}],
                },
                {
                    "id": "c2",
                    "title": "第二章",
                    "prose": "末班车开走了。",
                    "blocks": [{"type": "label", "id": "start", "name": "start"}],
                },
            ],
            "variables": [
                {
                    "id": "v1",
                    "name": "好感度",
                    "key": "affection",
                    "type": "number",
                    "value": 0,
                    "initial": 0,
                }
            ],
            "sprites": [{"id": "s1", "characterId": "ch1", "name": "默认", "imageTag": "lin_normal"}],
            "bible": {"world": "一个多雨的城市。", "outline": "他逐渐接受新的身体。"},
        }
    )


# ---------------------------------------------------------------------------
# 裁剪规则
# ---------------------------------------------------------------------------


def test_continue_task_drops_mechanism_sections_by_default():
    drop = sections_to_drop("continue")
    assert "sprites" in drop and "variables" in drop
    # 人设/地点/摘要这类"必须有"的绝不在默认裁剪里
    for keep in ("characters", "locations", "index", "bible", "lore"):
        assert keep not in drop


def test_chat_task_drops_other_chapter_excerpts():
    assert "otherChapters" in sections_to_drop("chat")
    assert "otherChapters" not in sections_to_drop("continue")


def test_author_exclusions_are_unioned_with_task_defaults():
    drop = sections_to_drop("continue", ["bible", "lore"])
    assert {"bible", "lore", "sprites", "variables"} <= drop


def test_unknown_exclusion_keys_are_ignored():
    drop = sections_to_drop("chat", ["不存在的东西", "", "SPRITES"])
    assert drop == {"otherChapters"}


def test_every_excludable_key_has_a_human_label():
    for key, label in EXCLUDABLE_SECTIONS.items():
        assert key and label, key
        assert len(label) >= 2, key


# ---------------------------------------------------------------------------
# 真的不进上下文
# ---------------------------------------------------------------------------


def test_excluded_section_is_absent_from_context_text():
    project = _project()
    full = build_agent_context(project, chapterId="c1", userMessage="接着写", task="continue")
    trimmed = build_agent_context(
        project, chapterId="c1", userMessage="接着写", task="continue", exclude=["bible"]
    )
    assert "## Story Bible" in full.text
    assert "## Story Bible" not in trimmed.text
    assert "bible" in trimmed.excluded
    # 裁剪后必须变短（否则说明没真去掉）
    assert trimmed.charsUsed < full.charsUsed


def test_default_trimming_keeps_context_smaller_and_reports_what_was_dropped():
    project = _project()
    raw = build_agent_context(project, chapterId="c1", userMessage="接着写", task="continue")
    # 续写任务默认不带立绘/变量：这两个块在完整上下文里存在时，裁剪后应消失
    assert "## Sprites" not in raw.text
    assert "## Variables / 状态机" not in raw.text
    assert any(x.startswith("省去:") for x in raw.included)


def test_hard_rules_are_repeated_at_the_end():
    project = _project()
    ctx = build_agent_context(project, chapterId="c1", userMessage="接着写", task="continue")
    tail = ctx.text[-400:]
    assert "本次硬规则" in tail
    for rule in task_key_rules("continue"):
        assert rule in ctx.text
    # 第一条硬规则也出现在末尾（长上下文里中间会被忽略）
    assert task_key_rules("continue")[0] in tail


def test_hard_rules_appear_once_at_each_end():
    """⑦ 关键约束首尾各出现一次：开头一次、结尾一次，中间不重复。"""
    project = _project()
    for task in ("continue", "rewrite", "chat"):
        ctx = build_agent_context(project, chapterId="c1", userMessage="接着写", task=task)
        first_rule = task_key_rules(task)[0]
        # 开头（前 800 字内）必须有
        assert first_rule in ctx.text[:800], task
        assert "本次硬规则" in ctx.text[:800], task
        # 结尾（后 800 字内）必须有
        assert first_rule in ctx.text[-800:], task
        # 恰好两次：不在中间再夹一次（否则等于噪音）
        assert ctx.text.count(first_rule) == 2, task


def test_hard_rules_are_always_injected_and_cannot_be_dropped():
    """硬规则是任务契约，不是「可摘掉的资料块」——即使作者摘了一堆资料也仍在。"""
    from app.core.agent_context import EXCLUDABLE_SECTIONS

    assert "rules" not in EXCLUDABLE_SECTIONS
    project = _project()
    ctx = build_agent_context(
        project,
        chapterId="c1",
        userMessage="接着写",
        task="continue",
        exclude=["bible", "lore", "characters", "index", "style"],
    )
    assert task_key_rules("continue")[0] in ctx.text[:800]
    assert "本次硬规则" in ctx.text


def test_hard_rules_are_reported_as_included():
    """「证明它记得」也要能看到硬规则这次确实注入了。"""
    project = _project()
    ctx = build_agent_context(project, chapterId="c1", userMessage="接着写", task="continue")
    assert "本次硬规则" in ctx.included


def test_task_key_rules_exist_for_every_agent_task():
    from app.core.agent_context import AGENT_TASKS

    for task in AGENT_TASKS:
        rules = task_key_rules(task)
        assert rules, task
        assert len(rules) <= 5, task  # 硬规则必须短，否则等于没写


def test_task_key_rules_are_task_specific_not_fallen_back_to_chat():
    """回归闸：旧实现是 `TASK_KEY_RULES.get(task, chat)`，所以 branch/scene/outline/voice
    拿到的其实是 chat 的「除非我明确要求，否则不要改工程」——而它们本该 append_script。
    旧测试只查"非空"，回落也非空，于是这个矛盾一直躺在线上 prompt 里。"""
    from app.core.agent_context import AGENT_TASKS, TASK_KEY_RULES

    chat_rules = TASK_KEY_RULES["chat"]
    for task in AGENT_TASKS:
        if task == "chat":
            continue
        assert task in TASK_KEY_RULES, f"{task} 没有专属硬规则，会回落成 chat"
        assert task_key_rules(task) != chat_rules, f"{task} 回落到 chat 硬规则"


def test_unknown_task_falls_back_without_raising():
    """API 传了没登记的任务名时，不能抛 KeyError 把整轮对话打断。"""
    assert task_key_rules("no-such-task") == task_key_rules("chat")
    from app.core.agent_context import output_contract, task_hint

    assert task_hint("no-such-task") == task_hint("chat")
    assert output_contract("no-such-task") == output_contract("chat")

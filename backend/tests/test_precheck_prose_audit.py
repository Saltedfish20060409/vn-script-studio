"""续写前对账的第二组：焦点章正文自身的确定性硬伤（文风级）。

为什么单独一个文件：
这一组**必须**与事实级对账分开。合在一起时，文风条目数量多、每次都可能不同，会把
`dead_character_present` 这类事实级对账挤出 `_MAX_WARNINGS` 配额——那正是
`agent_context._SECTION_ORDER` 当初修过的同一类回归（参考文档占住头部、把角色/关系
挤进被压缩的中段）。所以这里钉的不是"能不能报出来"，而是**报出来之后有没有把事实级挤走**。
"""
from __future__ import annotations

from app.core.agent_context import build_agent_context
from app.core.harness.audit_codes import DRAFT_LOCAL_CODES
from app.core.project import normalize_project
from app.core.write_gate import gate_continue_draft
from app.core.write_precheck import (
    _MAX_PROSE_WARNINGS,
    _PROSE_MSG_MAX,
    precheck_before_continue,
)

#: 能触发多种确定性文风硬伤的正文（副词堆砌 / 纠偏句式 / 万能回应 / 禁用词）
DIRTY_PROSE = (
    "他缓缓地抬起头，缓缓地开口，缓缓地说了一句。\n\n"
    "不是害怕，是别的。不是逃避，是等待。\n\n"
    "原来如此。我明白了。愣了一下。\n"
)

CLEAN_PROSE = "门开着，屋里没有声音。他在门口站了一会儿，然后走进去。"

#: 账本里记成已故的角色（用于造事实级 issue）
_DEAD_STATE = {
    "characterName": "顾沉",
    "characterId": "c1",
    "chapterId": "ch1",
    "chapterTitle": "一",
    "body": "已故",
    "emotion": "—",
    "relations": "—",
}


def _project(focus_prose: str, *, dead: bool = False):
    # 事实级对账的 haystack 是「焦点章正文 + 本稿」，所以已故角色必须出现在**焦点章**里，
    # 否则报不出来（放在 ch2 只有焦点是 ch2 时才算数）。
    prose = f"顾沉推门进来。\n\n{focus_prose}" if dead else focus_prose
    return normalize_project(
        {
            "id": "p-prose",
            "title": "文风对账",
            "characters": [{"id": "c1", "displayName": "顾沉", "defineName": "gu"}],
            "chapters": [
                {"id": "ch1", "title": "一", "prose": prose},
                {"id": "ch2", "title": "二", "prose": "顾沉推门进来。"},
            ],
            "writingLedger": {
                "characterStates": [_DEAD_STATE] if dead else [],
                "foreshadows": [],
                "chapterFacts": [],
            },
        }
    )


def test_prose_audit_reports_focus_chapter_hard_issues():
    report = precheck_before_continue(_project(DIRTY_PROSE), chapter_id="ch1")
    assert report.prose, "焦点章的确定性文风硬伤没有被报出来"
    codes = {i.code for i in report.prose}
    # 每一组码都必须登记过，且必须属于"稿属性"那一类
    assert codes <= DRAFT_LOCAL_CODES, f"报出了非稿属性的码：{sorted(codes - DRAFT_LOCAL_CODES)}"


def test_prose_audit_ignores_clean_prose():
    report = precheck_before_continue(_project(CLEAN_PROSE), chapter_id="ch1")
    assert report.prose == []
    assert report.as_context_block() == ""


def test_prose_issues_are_warn_only_and_do_not_affect_ok():
    """文风级不挡任何东西：全部 warn，且 `ok` 只看事实级。"""
    report = precheck_before_continue(_project(DIRTY_PROSE), chapter_id="ch1")
    assert report.prose
    assert all(i.severity == "warn" for i in report.prose)
    assert report.ok is True, "焦点章有文风硬伤不该让对账判失败"
    assert report.issues == []


def test_prose_issues_have_their_own_quota():
    """独立配额：条数封顶，且消息不重复。"""
    report = precheck_before_continue(_project(DIRTY_PROSE), chapter_id="ch1")
    assert 0 < len(report.prose) <= _MAX_PROSE_WARNINGS
    messages = [i.message for i in report.prose]
    assert len(messages) == len(set(messages)), f"prose 里有重复消息：{messages}"


def test_prose_messages_are_bounded_for_the_prompt_head():
    """进的是上下文头部（无裁剪保留区），消息长度必须有界。"""
    report = precheck_before_continue(_project(DIRTY_PROSE), chapter_id="ch1")
    for issue in report.prose:
        assert len(issue.message) <= _PROSE_MSG_MAX


def test_prose_issues_never_evict_fact_level_issues():
    """**这条是这个特性的核心不变量。**

    焦点章同时有"账本记已故的人仍出场"（事实级 error）和一堆文风硬伤时，
    事实级必须原样留着——文风抱怨不许把它挤走。
    """
    report = precheck_before_continue(_project(DIRTY_PROSE, dead=True), chapter_id="ch1")
    assert report.prose, "fixture 没触发文风硬伤，这条测试等于没测"
    assert any(i.code == "dead_character_present" for i in report.issues), (
        "文风级把事实级对账挤掉了"
    )
    assert report.ok is False


def test_context_block_keeps_the_two_groups_in_separate_sections():
    report = precheck_before_continue(_project(DIRTY_PROSE, dead=True), chapter_id="ch1")
    block = report.as_context_block()
    assert "续写前对账" in block
    assert "焦点章正文已有硬伤" in block
    # 事实级在前、文风级在后：事实级是"这轮绝不能写错"的东西
    assert block.index("续写前对账") < block.index("焦点章正文已有硬伤")
    # 文风级不打 ✖（它不挡任何东西），只有事实级会
    fact_part, prose_part = block.split("焦点章正文已有硬伤", 1)
    assert "✖" in fact_part
    assert "✖" not in prose_part


def test_prose_audit_can_be_switched_off():
    """`write_gate` 依赖这个开关：那边已经对产出稿跑过同一次体检。"""
    report = precheck_before_continue(
        _project(DIRTY_PROSE), chapter_id="ch1", prose_audit=False
    )
    assert report.prose == []


def test_write_gate_does_not_re_report_the_focus_chapter_prose():
    """写后闸报的是"这一段新正文"，不该把焦点章旧正文的文风硬伤再报一遍。"""
    p = _project(DIRTY_PROSE)
    result = gate_continue_draft(CLEAN_PROSE, project=p, chapter_id="ch1")
    codes = {str(i.get("code") or "") for i in result.issues}
    assert "ai_adverb_pile" not in codes
    assert "style_universal_ack" not in codes


def test_agent_context_carries_the_prose_block_for_continue():
    """端到端：续写任务下，焦点章的文风硬伤真的进了上下文。"""
    p = _project(DIRTY_PROSE)
    ctx = build_agent_context(p, chapterId="ch1", userMessage="接着写", task="continue")
    assert "焦点章正文已有硬伤" in ctx.text
    assert "缓缓" in ctx.text


def test_agent_context_omits_the_prose_block_when_chapter_is_clean():
    p = _project(CLEAN_PROSE)
    ctx = build_agent_context(p, chapterId="ch1", userMessage="接着写", task="continue")
    assert "焦点章正文已有硬伤" not in ctx.text


def test_prose_audit_does_not_run_for_chat_tasks():
    """文风对账是**写路径**的东西：聊天任务不该多付这次体检。"""
    p = _project(DIRTY_PROSE)
    ctx = build_agent_context(p, chapterId="ch1", userMessage="这本书讲什么", task="chat")
    assert "焦点章正文已有硬伤" not in ctx.text

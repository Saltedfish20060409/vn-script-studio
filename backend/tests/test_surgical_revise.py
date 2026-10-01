"""定点落实：按建议改 → 关工艺、硬拒 replace_script。"""
from __future__ import annotations

from app.core.agent import apply_agent_actions, audit_script_actions
from app.core.agent_context import task_hint
from app.core.project import normalize_project
from app.core.surgical_revise import is_surgical_revise
from app.core.writing_craft import select_craft_mode


def _proj(text: str = "他停了半息。\n雨还在下。\n"):
    return normalize_project(
        {
            "id": "p1",
            "title": "定点",
            "chapters": [{"id": "ch1", "title": "第一章", "prose": text}],
        }
    )


def test_surgical_phrases_are_detected():
    for msg in (
        "按建议改",
        "按你的意见改一下",
        "落实这些建议",
        "把这些建议落实到正文",
        "修改意见我同意，请帮我改",
        "帮我改这几处，其他地方不动",
        "把改动写进正文",
    ):
        assert is_surgical_revise(msg), msg


def test_full_rewrite_and_stop_are_not_surgical():
    assert not is_surgical_revise("整章重写一遍")
    assert not is_surgical_revise("帮我重写这一章，其他地方不动")
    assert not is_surgical_revise("先别改，我先看看")
    assert not is_surgical_revise("这一章怎么改")


def test_craft_turns_off_for_surgical_rewrite_even_if_pref_full():
    craft = select_craft_mode(
        task="rewrite",
        user_message="按建议改，写入正文",
        preference="full",
    )
    assert craft.mode == "off"
    assert "定点" in craft.reason or "patch" in craft.reason


def test_rewrite_hint_carries_surgical_completion_criteria():
    hint = task_hint("rewrite", "落实这些建议")
    assert "patch_script" in hint
    assert "禁止" in hint or "拒绝" in hint or "不许" in hint or "不要" in hint


def test_apply_rejects_replace_when_forbidden():
    before = "他停了半息。\n雨还在下。\n"
    proj = _proj(before)
    res = apply_agent_actions(
        proj,
        [{"op": "replace_script", "chapterRef": "第一章", "text": "全章被重写了。\n"}],
        forbid_replace_script=True,
    )
    assert res.applied == []
    assert any("定点落实" in s or "patch_script" in s for s in res.skipped)
    assert res.project.chapters[0].prose == before
    assert list(res.project.chapters[0].blocks or []) == []


def test_audit_always_warns_on_replace_when_surgical_message():
    proj = _proj("第1段。\n第2段。\n第3段。\n第4段。\n第5段。\n")
    # 几乎照抄也会告警——定点落实下整章替换本身就不该出现
    warnings = audit_script_actions(
        proj,
        [{"op": "replace_script", "chapterRef": "第一章", "text": proj.chapters[0].prose}],
        user_message="按建议改",
    )
    assert len(warnings) == 1
    assert "patch_script" in warnings[0]

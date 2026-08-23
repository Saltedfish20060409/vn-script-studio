"""narrative_lint 边界集回归测试。

来源：`app eval` 边界用例（《深入理解 AI Agent》第7章"生产失败案例
沉淀为新回归用例"）——确保审稿对已知问题类型不再漏检。
"""

from __future__ import annotations

from app.core.narrative_lint import (
    lint_has_blockers,
    lint_narrative_draft,
)


def _codes(text: str) -> list[str]:
    return [i.code for i in lint_narrative_draft(text)]


def test_multi_question_is_error():
    """同一角色本拍主动追问多次 → 一票否决级 error。"""
    text = (
        "周屿：「她在哪？」\n"
        "林夏：「我不知道。」\n"
        "周屿：「她到底在哪？」\n"
        "林夏：「说了不知道。」\n"
        "周屿：「那你总该知道她去哪了吧？」"
    )
    codes = _codes(text)
    assert "multi_question" in codes
    assert lint_has_blockers(lint_narrative_draft(text))


def test_qa_pingpong_is_error():
    """问→答→再问乒乓 → error。"""
    text = (
        "林夏：「你叫什么？」\n"
        "周屿：「周屿。」\n"
        "林夏：「为什么在这？」\n"
        "周屿：「等人。」\n"
        "林夏：「等谁？」\n"
        "周屿：「一个朋友。」"
    )
    codes = _codes(text)
    assert "qa_pingpong" in codes
    assert lint_has_blockers(lint_narrative_draft(text))


def test_exposition_dump_is_error():
    """刚认识的人讲解世界观/履历 → error。"""
    text = (
        "周屿：「这个组织成立于十年前，我是第七代负责人。"
        "我们的世界观建立在三个法则之上……」"
    )
    codes = _codes(text)
    assert "exposition" in codes
    assert lint_has_blockers(lint_narrative_draft(text))


def test_talk_heavy_warns_on_long_stranger_beat():
    """陌生人戏对白轮次偏多 → warn（非阻塞）。"""
    lines = []
    for i in range(9):
        lines.append(f"林夏：「第{i}句。」")
    text = "\n".join(lines)
    codes = _codes(text)
    assert "talk_heavy" in codes
    assert not lint_has_blockers(lint_narrative_draft(text))


def test_clean_dialogue_passes():
    """正常短对话：无 error 无 warn。"""
    text = (
        "林夏：「你在等人。」\n"
        "周屿：「嗯。末班车走了。」\n"
        "林夏：「那我陪你等一会儿。」"
    )
    issues = lint_narrative_draft(text)
    assert not lint_has_blockers(issues)
    assert not [i for i in issues if i.severity == "warn"]

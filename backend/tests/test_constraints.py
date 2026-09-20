"""约束分层与冲突提示（纯函数）。

两件事都会让输出"不如裸聊"：约束混在一起（模型分不清红线与建议）、约束互相打架
（模型只写"不会违规的空话"）。这里把两类问题变成可检查、可提示的东西。
"""

from __future__ import annotations

from app.core.constraints import (
    audit_constraints,
    author_hard_rules,
    classify_line,
    detect_conflicts,
    iter_constraint_lines,
)


def test_lines_are_split_and_bullets_stripped():
    text = "1. 必须用第一人称\n- 尽量短句\n\n· 世界观是多雨的城市"
    assert iter_constraint_lines(text) == [
        "必须用第一人称",
        "尽量短句",
        "世界观是多雨的城市",
    ]


def test_classify_hard_soft_info():
    assert classify_line("必须用第一人称") == "hard"
    assert classify_line("不要出现现代词汇") == "hard"
    assert classify_line("禁止解释超自然机制") == "hard"
    assert classify_line("尽量短句") == "soft"
    assert classify_line("建议每章 3000 字") == "soft"
    assert classify_line("主角叫林越") == "info"


def test_conflict_detected_between_opposite_rules():
    conflicts = detect_conflicts(["不要解释超自然", "要把设定讲清楚"])
    assert conflicts and conflicts[0]["topic"] == "是否解释超自然"
    assert conflicts[0]["hint"]


def test_no_conflict_when_rules_agree():
    assert detect_conflicts(["尽量短句", "克制，少形容词"]) == []


def test_person_conflict_caught_across_info_lines():
    """实测里最常见的一类：硬规则说第一人称，世界观句子却要求全知。"""
    audit = audit_constraints(
        bible_text="必须用第一人称\n全知视角交代所有人的想法\n世界观是一座多雨的城市"
    )
    topics = [c["topic"] for c in audit.conflicts]
    assert "叙述人称" in topics or "视角信息量" in topics


def test_audit_reports_layers_and_notes():
    audit = audit_constraints(
        bible_text="\n".join(
            [
                "必须用第一人称",
                "不要出现现代词汇",
                "尽量短句",
                "主角叫林越，住在雨城",
            ]
        )
    )
    assert audit.hard == ["必须用第一人称", "不要出现现代词汇"]
    assert audit.soft == ["尽量短句"]
    assert audit.info == ["主角叫林越，住在雨城"]
    # 有硬规则但没有样例 → 提醒补样例
    assert audit.needs_samples is True
    assert any("样例" in n for n in audit.notes)


def test_too_many_hard_rules_is_flagged():
    audit = audit_constraints(bible_text="\n".join(f"必须遵守第{i}条" for i in range(12)))
    assert any("偏多" in n for n in audit.notes)


def test_no_samples_hint_disappears_when_samples_exist():
    audit = audit_constraints(bible_text="必须用第一人称", has_style_samples=True)
    assert audit.needs_samples is False


def test_entries_contribute_their_explanation_part():
    audit = audit_constraints(
        entry_texts=["雨工：必须保持称呼为「雨工」，不要改写成别的说法。", "蒸汽：世界观里的动力来源"]
    )
    assert any("必须保持称呼" in r for r in audit.hard)
    assert any("动力来源" in r for r in audit.info)


def test_author_hard_rules_are_capped_and_clean():
    rules = author_hard_rules(
        bible_text="\n".join(f"必须遵守第{i}条" for i in range(12)), limit=5
    )
    assert len(rules) == 5
    assert all(r.startswith("必须") for r in rules)


def test_to_dict_shape_is_frontend_friendly():
    payload = audit_constraints(bible_text="必须用第一人称").to_dict()
    assert set(payload) == {"hard", "soft", "info", "conflicts", "needsSamples", "notes"}


# ---------------------------------------------------------------------------
# 接入上下文：作者的硬规则要进「本次硬规则」并在末尾重复
# ---------------------------------------------------------------------------


def test_author_hard_rules_land_in_the_context_tail():
    from app.core.agent_context import build_agent_context
    from app.core.project import normalize_project

    project = normalize_project(
        {
            "id": "p1",
            "title": "约束测试",
            "chapters": [
                {
                    "id": "c1",
                    "title": "第一章",
                    "prose": "雨落在站台上。" * 5,
                    "blocks": [{"type": "label", "id": "start", "name": "start"}],
                }
            ],
            "bible": {
                "world": "多雨的城市。",
                "notes": "必须用第一人称叙述\n不要出现现代网络词汇\n尽量短句",
            },
        }
    )
    ctx = build_agent_context(project, chapterId="c1", userMessage="接着写", task="continue")
    assert "作者自己的硬规则" in ctx.text
    assert "必须用第一人称叙述" in ctx.text
    assert "不要出现现代网络词汇" in ctx.text
    # 软规则不进硬规则区
    assert "尽量短句" not in ctx.text.split("作者自己的硬规则")[1].split("##")[0]
    assert any("作者硬约束" in x for x in ctx.included)
    # 位置：硬规则区在上下文末尾附近（和任务硬规则一起"当场生效"）
    assert "作者自己的硬规则" in ctx.text[-900:]

"""动笔前问几句：问题质量与「永不拦路」的兜底。

对照 WenShape 后补的：它会在写整章前先问关键推进点与角色动机变化。
我们的定位是**可选**，所以最关键的性质是——**没有 key / 模型挂了也要能返回问题**，
不能让"问问题"这一步变成写作的拦路虎。
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.ai import DeepSeekConfig
from app.core.demo import create_demo_project
from app.core.pre_questions import (
    MAX_QUESTIONS,
    _clean,
    generate_pre_questions,
)

GOAL = "雨夜站台，末班车广播之后，两人沉默。以一句台词收尾。"


def _run(coro):
    return asyncio.run(coro)


def test_template_questions_when_no_key():
    """没配 key 也必须给出可用问题，而不是报错。"""
    project = create_demo_project()
    cfg = DeepSeekConfig(apiKey="", baseUrl="", model="deepseek-chat")
    out = _run(generate_pre_questions(cfg, project, goal=GOAL))
    assert out["source"] == "template"
    qs = out["questions"]
    assert 2 <= len(qs) <= MAX_QUESTIONS
    # 三条必要信息：推进点、角色变化、收尾落点
    joined = " ".join(qs)
    assert "推进" in joined
    assert "变化" in joined
    assert "结尾" in joined or "收尾" in joined


def test_template_mentions_character_names():
    project = create_demo_project()
    cfg = DeepSeekConfig(apiKey="", baseUrl="", model="deepseek-chat")
    out = _run(generate_pre_questions(cfg, project, goal=GOAL))
    names = [c.displayName for c in project.characters if c.displayName]
    assert names, "示例项目应该有角色"
    assert any(n in " ".join(out["questions"]) for n in names[:2])


def test_model_failure_falls_back_instead_of_raising(monkeypatch):
    """模型报错时也要回退模板，而不是把异常抛给接口。"""
    project = create_demo_project()
    cfg = DeepSeekConfig(apiKey="sk-test", baseUrl="https://x", model="m")

    async def _boom(*_a, **_k):
        raise RuntimeError("upstream 500")

    monkeypatch.setattr("app.core.llm_http.chat_completions", _boom)
    out = _run(generate_pre_questions(cfg, project, goal=GOAL))
    assert out["source"] == "template"
    assert out["questions"]


def test_model_questions_are_used_when_available(monkeypatch):
    import json

    project = create_demo_project()
    cfg = DeepSeekConfig(apiKey="sk-test", baseUrl="https://x", model="m")

    class _Resp:
        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "questions": [
                                        "这场里林夏最关键的一步是什么？",
                                        "周屿为什么这次没有开玩笑？",
                                        "最后一句台词留给谁？",
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
                "model": "m",
            }

    async def _ok(*_a, **_k):
        return _Resp()

    monkeypatch.setattr("app.core.llm_http.chat_completions", _ok)
    out = _run(generate_pre_questions(cfg, project, goal=GOAL))
    assert out["source"] == "llm"
    assert len(out["questions"]) == 3
    assert out["questions"][0].startswith("这场里林夏")


def test_model_junk_falls_back(monkeypatch):
    """模型回了空/垃圾 JSON：不能用一串空问题糊弄作者。"""
    project = create_demo_project()
    cfg = DeepSeekConfig(apiKey="sk-test", baseUrl="https://x", model="m")

    class _Resp:
        def json(self):
            return {"choices": [{"message": {"content": '{"questions": []}'}}], "model": "m"}

    async def _ok(*_a, **_k):
        return _Resp()

    monkeypatch.setattr("app.core.llm_http.chat_completions", _ok)
    out = _run(generate_pre_questions(cfg, project, goal=GOAL))
    assert out["source"] == "template"
    assert len(out["questions"]) >= 2


@pytest.mark.parametrize(
    "raw,expected",
    [
        (["  - 第一条问题是什么？  "], ["第一条问题是什么？"]),
        ([{"text": "对象形式的问题？"}], ["对象形式的问题？"]),
        (["too"], []),  # 太短，丢弃
        (["重复的问题？", "重复的问题？"], ["重复的问题？"]),
        ([f"问题{i}是什么？" for i in range(9)], [f"问题{i}是什么？" for i in range(MAX_QUESTIONS)]),
        ("不是列表", []),
    ],
)
def test_clean_questions(raw, expected):
    assert _clean(raw) == expected

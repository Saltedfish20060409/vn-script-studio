"""测试 LLM 对话记忆归档（summarize_chat_memory）。"""
from __future__ import annotations

import asyncio

from app.core.longform_memory import compress_chat_history, summarize_chat_memory
from app.domain.types import AgentChatMessage


def _msg(role: str, content: str) -> AgentChatMessage:
    return AgentChatMessage(role=role, content=content)


class _FakeProvider:
    """返回固定摘要文本的假 provider。"""

    def __init__(self, text: str = "【关键决定】\n- 主角决定去车站\n- 采用雨夜氛围"):
        self.text = text
        self.calls = 0

    async def chat_completions(self, **kwargs):
        self.calls += 1
        payload = {"choices": [{"message": {"content": self.text}}], "model": "fake"}
        return type("Resp", (), {"json": lambda self: payload})()


class _FailProvider:
    async def chat_completions(self, **kwargs):
        raise RuntimeError("network down")


def test_summarize_uses_llm():
    older = [_msg("user", "我们定一下主角性格吧，冷一点"), _msg("assistant", "好，克制型")]
    p = _FakeProvider()
    out = asyncio.run(summarize_chat_memory(p, older))
    assert "关键决定" in out or "主角" in out
    assert p.calls == 1


def test_summarize_merges_prior_memory():
    older = [_msg("user", "第一章基调：雨夜")] * 4
    p = _FakeProvider()
    out = asyncio.run(summarize_chat_memory(p, older, prior_memory="既有：主角叫林夏"))
    assert out  # 非空即可


def test_summarize_falls_back_on_failure():
    """LLM 失败时回退抽取式（不丢信息）。"""
    older = [_msg("user", "第一条设定：世界观是雨城"), _msg("assistant", "好的")]
    p = _FailProvider()
    out = asyncio.run(summarize_chat_memory(p, older))
    assert "雨城" in out


def test_summarize_empty_returns_prior():
    out = asyncio.run(summarize_chat_memory(_FakeProvider(), [], prior_memory="既有记忆"))
    assert out == "既有记忆"


def test_extractive_fallback_structure():
    """抽取式回退保留 bullet 结构（compress_chat_history 兼容性）。"""
    many = [_msg("user", f"设定{i}：内容内容") for i in range(30)]
    bundle = compress_chat_history(many, keep_recent=6, summarize_after=22)
    assert bundle.summarizedCount > 0
    assert len(bundle.recentMessages) == 6

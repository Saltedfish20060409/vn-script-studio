"""Agent 的空 message 失败模式：**不许把"失败提示"当成模型说的话**。

用户反馈：附上第一章正文问「帮我审查一下第一章……男主把雪菜带回公寓之后的情节我都还不是很
满意，有没有别的思路？」，拿到的回复却是

    我这一轮没产出可用的文字说明。请换个问法再试：例如「先不要改工程，只根据上文给第一章
    修改意见」。

那句话**不是模型说的**，是 `agent.py` 里 `_parse_agent_json` 给单轮老路径用的兜底文案。
根因在 `agent_loop._agent_steps`：模型这一步没写 `message` 时它去调 `_parse_agent_json`
"补一句"，于是——
1. **工具步**（协议只要求 `done=false`，本来就不写 message）也被补上这句道歉，混进思考流；
2. **最后一步**若同样没写 message，这句道歉就**直接变成给作者的最终答复**，而这一轮明明
   已经取回了工具证据、本该给出审查意见。

修法：没写就是没写（`_step_message` 返回空串），收尾由 `_force_final_message` **再问一次**，
而不是"编一句"。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from app.core.agent_loop import _agent_steps, _step_message
from app.domain.types import AgentRequest, VnProject

#: 单轮老路径那句兜底文案（`agent.py::_parse_agent_json`）。它**永远不该**出现在循环
#: 给作者的答复或思考流里。注意它和循环自己那句话只差一个字（"没"vs"没有"），
#: 所以这里按整句前缀比对，不用模糊的子串。
_SINGLE_PASS_APOLOGY = "我这一轮没产出可用的文字说明"
#: 循环自己在"补写也没拿到东西"时给的那句：准确，且不假设作者该怎么问。
_LOOP_HONEST = "本轮没有产出可用说明"
#: 老路径那句还带一个具体建议，用它区分两者。
_APOLOGY_HINT = "例如"


class _ScriptedProvider:
    """按顺序吐响应的假 provider；队列用完后重复最后一条。"""

    def __init__(self, *replies: str):
        self.replies = list(replies) or ["{}"]
        self.calls: List[List[Dict[str, str]]] = []

    async def chat_completions(self, **kwargs: Any) -> Any:
        self.calls.append(list(kwargs.get("messages") or []))
        idx = min(len(self.calls) - 1, len(self.replies) - 1)
        payload = {"choices": [{"message": {"content": self.replies[idx]}}], "model": "fake"}
        return type("Resp", (), {"json": lambda self: payload})()


def _demo() -> VnProject:
    return VnProject.model_validate(
        {
            "id": "p1",
            "title": "雨夜",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [
                {
                    "id": "c1",
                    "defineName": "linxia",
                    "displayName": "霖夏",
                    "voice": "克制",
                    "bio": "雨夜车站的人",
                }
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "车站",
                    "blocks": [
                        {"type": "narration", "text": "雨很大。"},
                        {"type": "dialogue", "characterId": "c1", "text": "伞借你。"},
                    ],
                }
            ],
        }
    )


def _run_steps(provider: _ScriptedProvider, *, steps: int = 3):
    """跑一遍 `_agent_steps`，返回 (trace, final_message)。"""
    trace: List[Dict[str, Any]] = []

    async def emit(evt: Dict[str, Any]) -> None:
        return None

    async def _go():
        return await _agent_steps(
            provider,
            request=AgentRequest(project=_demo(), task="chat", chapterId="ch1"),
            messages=[{"role": "user", "content": "帮我审查一下第一章，有没有别的思路？"}],
            working=_demo(),
            accumulated=[],
            trace=trace,
            final_message="",
            last_tool_text="",
            start_step=0,
            steps=steps,
            temperature=0.3,
            emit=emit,
        )

    # `_agent_steps` 返回 7 元组：第 7 个是"这次有没有撞输出上限"（2026-09-30 加）
    _, _, trace, final_message, _, _, _ = asyncio.run(_go())
    return trace, final_message


def _thoughts(trace: List[Dict[str, Any]]) -> List[str]:
    return [str(t.get("text") or "") for t in trace if t.get("type") == "thought"]


# ---- 纯函数：没有 message 就是没有 -------------------------------------------


def test_step_message_does_not_invent_an_apology():
    """缺 message 时返回空串，绝不返回那句给用户看的失败提示。"""
    for parsed in (
        {"tool_calls": [{"name": "get_chapter"}], "done": False},
        {"tool_calls": [{"name": "get_chapter"}], "done": True},
        {},
        {"message": "   "},
        {"message": None},
        {"message": 123},
    ):
        assert _step_message(parsed) == "", f"{parsed} 不该被补出一句话"


def test_step_message_keeps_real_text():
    assert _step_message({"message": "  这段的反应可以更有层次 "}) == "这段的反应可以更有层次"


# ---- 循环：工具步不该被塞进道歉 ---------------------------------------------


def test_tool_step_without_message_does_not_inject_the_apology():
    """模型先调工具再给意见（最常见的 2 步）：道歉不许出现在任何地方。"""
    provider = _ScriptedProvider(
        '{"tool_calls":[{"id":"t1","name":"get_chapter","arguments":{}}],"done":false}',
        '{"message":"第一章的问题：把雪菜带回公寓之后缺少阻力。","done":true}',
    )
    trace, final_message = _run_steps(provider, steps=3)

    assert "缺少阻力" in final_message
    assert _SINGLE_PASS_APOLOGY not in final_message
    assert not any(_SINGLE_PASS_APOLOGY in t for t in _thoughts(trace)), (
        f"工具步被塞进了道歉，思考流：{_thoughts(trace)}"
    )


def test_forces_one_final_answer_when_the_model_never_writes_one():
    """跑完工具却始终不写 message：再问一次，而不是甩一句"换个问法"。"""
    provider = _ScriptedProvider(
        '{"tool_calls":[{"id":"t1","name":"get_chapter","arguments":{}}],"done":false}',
        "{}",  # 第 2 步依旧没有 message
        '{"message":"建议：让雪菜主动拒绝一次，矛盾就立起来了。","done":true}',  # 收尾补写
    )
    trace, final_message = _run_steps(provider, steps=2)

    assert "主动拒绝" in final_message
    assert _SINGLE_PASS_APOLOGY not in final_message
    # 2 步 + 1 次收尾补写
    assert len(provider.calls) == 3, f"应当恰好多问一次，实际调用 {len(provider.calls)} 次"
    # 收尾那次必须明确禁止再调工具，否则模型会一直在工具里打转
    assert "不要再调用任何工具" in provider.calls[-1][-1]["content"]
    assert _thoughts(trace)[-1].startswith("收尾补写")


def test_honest_message_when_even_the_nudge_fails():
    """补写也拿不到东西时，给循环自己那句**准确**的话，而不是老路径的兜底。"""
    provider = _ScriptedProvider("{}")
    _, final_message = _run_steps(provider, steps=2)

    assert _LOOP_HONEST in final_message
    # 不是单轮老路径那句：它把失败说成"换个问法就好"，还替作者假设了该怎么问
    assert _SINGLE_PASS_APOLOGY not in final_message
    assert _APOLOGY_HINT not in final_message


def test_done_with_tool_calls_does_not_silently_drop_the_tools():
    """模型自相矛盾（done=true 又给 tool_calls）：证据要取回来，不能静默丢掉。"""
    provider = _ScriptedProvider(
        '{"tool_calls":[{"id":"t1","name":"get_chapter","arguments":{}}],"done":true}',
        '{"message":"读到的是雨夜车站与借伞。","done":true}',
    )
    trace, final_message = _run_steps(provider, steps=3)

    ran = [t.get("name") for t in trace if t.get("type") == "tool_call"]
    assert ran == ["get_chapter"], "模型要的证据被静默丢掉了"
    assert "雨夜车站" in final_message or "借伞" in final_message

"""模型输出里嵌了代码围栏时，**不许把围栏当成整份回复**。

症状（作者反馈）：附上第一章问「帮我审查一下第一章……应该怎么改合适？」，Agent 回的是
214 字的一段示例对白（"（她在中岛台边站了很久……"），两千多字的审稿意见一个字都没有，
看起来像"模型理解不了我的指令"。

根因不在模型：同一条 messages、同一个模型（作者设置里的 deepseek-v4-flash）重跑一次，
**一次调用**就返回了 2427 字的完整意见。丢在解析上——模型的 `message` 里嵌了一段
```` ```renpy ```` 示例改法（`AGENT_SYSTEM` 第 9 条本来就写着"可摘改写示例对白"），
而解析器是"先找围栏、拿第一段围栏内容当 JSON、再配平括号"，`_FENCE_RE` 用
`[\\s\\S]*?` 非贪婪地从第一个围栏取到第二个，于是字符串值里那段示例被当成了整份输出；
它不是合法 JSON（围栏体里是正文），于是落到"纯文本当回复"的兜底，JSON 里真正的回复被
静默丢掉。`completion_tokens` 是此刻的物证：1837 个 token 的产出，作者只看到 214 字。

修法：`llm_text.extract_json_object` 统一解析顺序——整段 JSON → 配平括号切对象 →
最后才认"整段被一层围栏包着"。围栏只做兜底，字符串值里的围栏永远不会劫持解析。

守卫（本文件）：
1. 围栏在 `message` **里面** → 分析必须活下来，示例也在；
2. 整个输出被一层围栏包着 → 照旧能解析（`test_agent_loop_tools` 里那条也要继续过）；
3. JSON 前后夹着解释文字 → 靠配平括号救回来；
4. `message` 里出现花括号/转义引号 → 配平扫描不能被带跑；
5. 纯文本、纯围栏正文这两条老兜底行为不变。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

from app.core.agent import _parse_agent_json
from app.core.agent_loop import (
    _agent_steps,
    _force_final_message,
    _parse_loop_json,
    _step_message,
)
from app.core.llm_text import extract_json_object
from app.domain.types import AgentRequest, VnProject

#: 审稿意见（真正的回复）与它引用的示例改法。示例必须留在回复里，但**不能取代**意见。
ANALYSIS = (
    "先说结论：第一章的问题不在「写得不好」，而在后半段从「戏」退化成了"
    "「说明书 + 流程演示」。公寓段只保留一个主冲突，其余全部砍成背景。"
)
SAMPLE = (
    "（她在中岛台边站了很久。你切菜的时候，余光瞥见她伸手，指尖悬在砧板边缘，没落下去。）\n\n"
    '雪菜："这个……"\n\n'
    '你："嗯？"'
)


def _raw_with_fence_in_message() -> str:
    """真实形状：一个合法 JSON，`message` 里嵌着 ```renpy 示例。"""
    message = f"{ANALYSIS}\n\n示例改法：\n```renpy\n{SAMPLE}\n```\n\n要不要我按这个思路重写一版？"
    return json.dumps({"message": message, "actions": [], "tool_calls": [], "done": True}, ensure_ascii=False)


class _ScriptedProvider:
    """按顺序吐响应的假 provider（队列用完后重复最后一条）。"""

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
            "title": "拟合少女",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [
                {"id": "c1", "defineName": "male_lead", "displayName": "男主", "voice": "惜话"},
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "blocks": [{"type": "narration", "text": "他把雪菜带回了公寓。"}],
                }
            ],
        }
    )


# ---- 1. 围栏在 message 里：分析必须活下来 ------------------------------------


def test_loop_parse_keeps_the_analysis_when_message_contains_a_fence():
    """这一条就是线上症状的复现：旧逻辑只留下示例，分析被吞。"""
    parsed = _parse_loop_json(_raw_with_fence_in_message())
    msg = _step_message(parsed)

    assert ANALYSIS in msg, "审稿意见被围栏劫持掉了（旧 bug 回来了）"
    assert "示例改法" in msg, "模型引用在回复里的示例不该被删掉"
    assert "```renpy" in msg, "示例的围栏标记应原样保留"
    assert parsed.get("actions") == []
    assert parsed.get("done") is True


def test_single_pass_parse_keeps_the_analysis_too():
    message, actions = _parse_agent_json(_raw_with_fence_in_message())
    assert ANALYSIS in message
    assert "雪菜" in message
    assert actions == []


def test_agent_loop_final_message_is_the_whole_review():
    """走完整的多步循环：交给作者的答复必须是完整意见，不是一段示例。"""
    provider = _ScriptedProvider(_raw_with_fence_in_message())
    trace: List[Dict[str, Any]] = []

    async def emit(_evt: Dict[str, Any]) -> None:
        return None

    async def _go():
        return await _agent_steps(
            provider,
            request=AgentRequest(project=_demo(), task="chat", chapterId="ch1"),
            messages=[{"role": "user", "content": "帮我审查一下第一章，应该怎么改合适？"}],
            working=_demo(),
            accumulated=[],
            trace=trace,
            final_message="",
            last_tool_text="",
            start_step=0,
            steps=3,
            temperature=0.3,
            emit=emit,
        )

    _, _, _, final_message, _, _ = asyncio.run(_go())
    assert ANALYSIS in final_message
    assert "```renpy" in final_message


def test_force_final_message_keeps_the_analysis():
    """收尾补写这条路也曾有同一处围栏劫持。"""
    provider = _ScriptedProvider(_raw_with_fence_in_message())
    trace: List[Dict[str, Any]] = []
    msg = asyncio.run(
        _force_final_message(
            provider,
            messages=[{"role": "user", "content": "帮我审查一下第一章"}],
            temperature=0.3,
            trace=trace,
        )
    )
    assert ANALYSIS in msg
    assert msg.startswith("先说结论"), "不该只剩下围栏里的示例"


# ---- 2. 老路径不能被修坏 -----------------------------------------------------


def test_whole_output_wrapped_in_a_json_fence_still_parses():
    raw = '```json\n{"message": "已按意见修改", "actions": [{"op": "rewrite_chapter", "chapterId": "ch1"}]}\n```'
    assert extract_json_object(raw) is not None
    message, actions = _parse_agent_json(raw)
    assert "已按意见修改" in message
    assert actions and actions[0]["op"] == "rewrite_chapter"


def test_prose_around_the_json_still_parses():
    """前后夹着解释文字也能靠配平括号切出对象。"""
    raw = '我看了这一章，意见如下：\n{"message": "第一段该砍", "actions": []}\n需要我直接改吗？'
    parsed = extract_json_object(raw)
    assert parsed == {"message": "第一段该砍", "actions": []}


def test_braces_and_escaped_quotes_inside_message_do_not_break_the_scan():
    message = '他问 {"名字" 是什么}，她答 "就叫这个 \\"吧\\"。"'
    raw = json.dumps({"message": message, "actions": []}, ensure_ascii=False)
    parsed = extract_json_object(raw)
    assert parsed is not None
    assert parsed["message"] == message


def test_plain_prose_still_falls_back_to_the_text():
    msg, actions = _parse_agent_json("好的，我来帮你审查并续写这个剧本。首先我需要通读第一章……")
    assert "审查" in msg
    assert actions == []


def test_plain_fenced_script_still_falls_back_to_the_script():
    """模型没吐 JSON、只给了一段围栏正文：正文照收，围栏标记剥掉。"""
    message, _ = _parse_agent_json("```renpy\\n旁白：雨还在下。\\n```")
    assert "```" not in message
    assert "旁白：雨还在下。" in message


def test_empty_response_keeps_its_own_message():
    msg, actions = _parse_agent_json("")
    assert "无法解析" in msg
    assert actions == []


def test_json_that_is_not_an_object_is_not_treated_as_an_object():
    assert extract_json_object("[1, 2, 3]") is None
    assert extract_json_object("没有任何 JSON") is None

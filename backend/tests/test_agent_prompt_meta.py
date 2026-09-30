"""线上跑过什么必须可查：提示词构成要写进检查点（`agent_sessions.run_state`）。

为什么单独钉这一条（2026-09-27 的排查现场）：想回答"craft 3.3k token / 导师 1.2k token
到底有没有进过模型"，当时只能把 run_state 里的 messages 拼起来**搜字符串**
（`写作工艺：本轮关闭` vs `写作工艺 Skills（详述`），因为检查点里根本没有 craftMode。

顺带修掉一个静默错误的读数：续跑分支读 `resume.get("craftMode") or "off"`
（`agent_loop.py` 的 resume 段），而检查点以前从不存这个键——于是**任何断点续跑都会被报成
「工艺关」**，界面上那行状态跟着错。本文件把两件事一起钉住：
1. 检查点必须带 `craftMode` 与各块实测字符数 `promptMeta.blocks`；
2. 拿它当 resume 输入回放时，报出来的 craftMode 必须是当初那个，而不是 off。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from app.core.agent_loop import run_agent_loop
from app.core.ai import DeepSeekConfig
from app.domain.types import AgentRequest, VnProject

BLOCK_KEYS = {
    "agentSystem",
    "identity",
    "taskHint",
    "craft",
    "mentor",
    "lens",
    "loopProtocol",
    "toolCatalog",
    "chatMemory",
    "context",
}


def _demo() -> VnProject:
    return VnProject.model_validate(
        {
            "id": "p1",
            "title": "雨夜",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [
                {"id": "c1", "defineName": "linxia", "displayName": "霖夏", "voice": "克制"}
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "车站",
                    "blocks": [{"type": "narration", "text": "雨很大。"}],
                }
            ],
            "bible": {"world": "近未来雨城", "outline": "车站邂逅"},
        }
    )


async def _fake_chat_json(*_args: Any, **_kwargs: Any) -> tuple[str, bool]:
    # `_chat_json` 返回 (内容, 是否撞输出上限)：第二个元素是 2026-09-30 加的，
    # 用来把"输出被截断"这件事冒泡到作者那一侧。
    return (
        '{"message":"先看设定与当前章。","actions":[],"tool_calls":[],"done":true}',
        False,
    )


def _run_once(monkeypatch, *, task: str, prompt: str = "续写") -> Dict[str, Any]:
    """跑一次完整 loop，返回最后一个检查点快照。"""
    from app.core import agent_loop as al

    monkeypatch.setattr(al, "_chat_json", _fake_chat_json)
    checkpoints: List[Dict[str, Any]] = []

    async def on_checkpoint(state: Dict[str, Any]) -> None:
        checkpoints.append(state)

    async def _go():
        return await run_agent_loop(
            DeepSeekConfig(apiKey="test-key", baseUrl="http://x", model="m"),
            AgentRequest(
                project=_demo(),
                messages=[{"role": "user", "content": prompt}],  # type: ignore[arg-type]
                task=task,
            ),
            on_checkpoint=on_checkpoint,
        )

    res = asyncio.run(_go())
    assert checkpoints, "loop 至少要写一次检查点"
    return {"checkpoint": checkpoints[-1], "result": res, "all": checkpoints}


def test_checkpoint_records_prompt_composition(monkeypatch):
    """chat 任务：工艺关（但占位那句在），导师块在，各块都有实测字数。"""
    out = _run_once(monkeypatch, task="chat", prompt="这章有什么问题？")
    cp = out["checkpoint"]
    meta = cp["promptMeta"]
    blocks = meta["blocks"]

    assert set(blocks) == BLOCK_KEYS
    assert cp["craftMode"] == "off"
    assert meta["craftMode"] == "off"
    assert blocks["craft"] == 35, "「本轮关闭」那句占位是 35 字，与线上一致"
    assert blocks["mentor"] > 800, "写作导师块线上恒在，不该是 0"
    assert blocks["agentSystem"] > 2000
    assert blocks["loopProtocol"] > 0 and blocks["toolCatalog"] > 0
    # 检查点里的 craftMode 必须与返回给界面的 contextMeta 一致——两处读数不能分叉
    assert out["result"].contextMeta.craftMode == cp["craftMode"]
    assert meta["systemChars"] > blocks["context"]


def test_continue_task_records_full_craft(monkeypatch):
    """续写任务：工艺档是 full，craft 块明显更大（这正是"值不值 3.3k token"要量的那块）。"""
    out = _run_once(monkeypatch, task="continue")
    meta = out["checkpoint"]["promptMeta"]
    assert meta["craftMode"] == "full"
    assert meta["blocks"]["craft"] > 2000
    assert meta["craftReason"], "档位理由要留痕，否则事后无法解释为什么开了"


def test_resume_reports_the_recorded_craft_mode_not_off(monkeypatch):
    """续跑不能再把 craftMode 说成 off——检查点里现在真有这个键了。"""
    first = _run_once(monkeypatch, task="continue")
    recorded = first["checkpoint"]["craftMode"]
    assert recorded == "full"

    from app.core import agent_loop as al

    monkeypatch.setattr(al, "_chat_json", _fake_chat_json)
    events: List[Dict[str, Any]] = []

    async def sink(evt: Dict[str, Any]) -> None:
        events.append(evt)

    async def _go():
        return await run_agent_loop(
            DeepSeekConfig(apiKey="test-key", baseUrl="http://x", model="m"),
            AgentRequest(
                project=_demo(),
                messages=[{"role": "user", "content": "续写"}],  # type: ignore[arg-type]
                task="continue",
            ),
            on_event=sink,
            resume=first["checkpoint"],
        )

    asyncio.run(_go())
    task_evt = next(e for e in events if e["type"] == "task")
    assert task_evt["craftMode"] == "full", "续跑把 craftMode 报成 off 了（旧 bug 回来了）"

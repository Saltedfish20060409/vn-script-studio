"""「JSON 破了就当纯文本」这条老路线的守卫测试。

背景（2026-09-30 线上实盘）：作者两次让 Agent「写完整的第一章」，模型把整章正文塞进 JSON 的
`message` 里返回，输出一断，`extract_json_object` 所有候选都失败，于是走"原文当回复"的兜底——
屏幕上是一坨被截到 2000 字的裸 JSON（看起来像模型胡说），而 `actions` 一起丢掉，
稿子里一个字都没写、撤回栈也是空的。作者的原话是"续写效果这么差"。

这里钉住修复后的行为：
1. 能从写坏/被截断的信封里救回 message（救回来的只是文本，**动作必须为空**）；
2. 救不回来时给一句人话，且明确"本轮没有改动工程"；
3. 真正的纯文本回复（模型忽略协议）仍照旧当回复用——不误伤既有路径。
"""

from __future__ import annotations

from app.core.agent import _looks_like_json_envelope, _parse_agent_json
from app.core.llm_text import (
    _repair_unterminated_json,
    salvage_message_from_broken_json,
)


def test_repair_closes_truncated_object():
    text = '{"message": "前半段还在写'
    repaired = _repair_unterminated_json(text)
    assert repaired is not None
    assert repaired.endswith('"}')
    assert '"message"' in repaired


def test_repair_returns_none_when_already_closed():
    # 已闭合的不归它管：否则 `{...}后面还有一段` 会被当"截断"处理
    assert _repair_unterminated_json('{"message": "ok"}') is None


def test_salvage_message_from_truncated_envelope():
    raw = '{"message": "她锁门时说：这个动作，对我没有意义。\\n\\n但我会做。", "actions": [{"op": "append_script", "text": "她锁'
    out = salvage_message_from_broken_json(raw)
    assert out is not None
    assert "这个动作，对我没有意义" in out
    assert "但我会做" in out
    # 半截的动作不能跟着回来（宁可让作者重来）
    assert "append_script" not in out


def test_salvage_handles_cut_inside_escape():
    # 正切在转义字符中间：补不齐 JSON，就按字面量扫描把已写出来的部分交出去
    raw = '{"message": "第一句。第二句还没写完\\'
    out = salvage_message_from_broken_json(raw)
    assert out is not None
    assert "第一句" in out


def test_salvage_returns_none_for_plain_text():
    assert salvage_message_from_broken_json("这就是一段普通回复，没有 JSON。") is None


def test_looks_like_json_envelope():
    assert _looks_like_json_envelope('{"message": "x"')
    assert _looks_like_json_envelope('  [{"op": "append_script"')
    assert _looks_like_json_envelope('"message": "no braces"')
    assert not _looks_like_json_envelope("先给结论：这份改写稿方向是对的。")


def test_parse_agent_json_salvages_message_and_drops_actions():
    raw = '{"message": "正文：她望着你，比刚才久。\\n雪菜：「我记下了。」", "actions": [{"op": "append_script", "text": "半截'
    message, actions = _parse_agent_json(raw)
    assert "我记下了" in message
    assert "本轮没有改动工程" in message  # 必须说清没落盘
    assert actions == []  # 动作一律丢弃


def test_parse_agent_json_explains_unsalvageable_envelope():
    # 信封坏了、message 也救不出来（例如切在键名中间）
    message, actions = _parse_agent_json('{"mess')
    assert "本轮没有改动工程" in message
    assert "重试" in message
    assert actions == []


def test_parse_agent_json_keeps_plain_text_behaviour():
    message, actions = _parse_agent_json("先给结论：这份改写稿方向是对的。")
    assert message == "先给结论：这份改写稿方向是对的。"
    assert actions == []


def test_parse_agent_json_notes_truncation_for_long_plain_text():
    long = "正文" * 1600  # 3200 字，超过 2000 的显示上限
    message, actions = _parse_agent_json(long)
    assert len(message) > 2000
    assert message.startswith("正文")
    assert "本轮没有改动工程" in message
    assert "超过 2000 字" in message
    assert actions == []


def test_parse_agent_json_still_parses_good_envelope():
    message, actions = _parse_agent_json(
        '{"message": "写好了。", "actions": [{"op": "append_script", "text": "正文"}]}'
    )
    assert message == "写好了。"
    assert any(a.get("op") == "append_script" for a in actions)


# ---------------------------------------------------------------------------
# 撞输出上限要**冒泡到作者那一侧**，不能只写日志
# ---------------------------------------------------------------------------


def _demo_project():
    from app.domain.types import VnProject

    return VnProject.model_validate(
        {
            "id": "p1",
            "title": "雨夜",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [{"id": "c1", "defineName": "linxia", "displayName": "霖夏"}],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "车站",
                    "blocks": [{"type": "narration", "text": "雨很大。"}],
                }
            ],
            "bible": {"world": "近未来雨城"},
        }
    )


def _run_loop(monkeypatch, *, truncated: bool) -> str:
    import asyncio

    from app.core import agent_loop as al
    from app.core.agent_loop import run_agent_loop
    from app.core.ai import DeepSeekConfig
    from app.domain.types import AgentRequest

    async def fake_chat_json(*_a, **_k):
        payload = '{"message":"先写到这里。","actions":[],"tool_calls":[],"done":true}'
        return payload, truncated

    monkeypatch.setattr(al, "_chat_json", fake_chat_json)
    cfg = DeepSeekConfig(apiKey="k", baseUrl="http://x", model="m")
    req = AgentRequest(
        project=_demo_project(),
        messages=[{"role": "user", "content": "续写"}],  # type: ignore[arg-type]
        task="continue",
    )
    return asyncio.run(run_agent_loop(cfg, req)).message


def test_truncated_output_is_surfaced_in_the_reply(monkeypatch):
    """撞上限时回复里必须带提醒：否则作者只看到"怎么只写了一点"。"""
    message = _run_loop(monkeypatch, truncated=True)
    assert "先写到这里" in message
    assert "截断" in message
    assert "继续" in message  # 给出可执行的下一步


def test_no_note_when_output_was_not_truncated(monkeypatch):
    """没撞上限就别加这句（否则每次回复都挂一句无用的提醒）。"""
    message = _run_loop(monkeypatch, truncated=False)
    assert message.strip() == "先写到这里。"

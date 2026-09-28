"""流式调用的用量记账：补上这个洞之前，走流式的调用**一条都不记**。

原缺陷（两处成因，缺一不可）
----------------------------
1. `record_usage_later` 在整个 `backend/app` 里只被调用过一次，位置在**非流式**的
   `chat_completions` 里。而流式才是主路径：`AgentChat` 调的是 `/agent/stream`，
   流式章节写作也走它。`ensure_under_quota` 只读 `llm_usage`，于是每日额度与共享
   免费档的 cap 只被**检查**、从不被**累加**——等于形同虚设，而"额度没生效"这件事
   平时看不出来（线上跑的正是免费档）。
2. SSE 的 usage 放在**最后一块**（`choices` 为空、`usage` 有值），而解析循环里写着
   `if not choices: continue`，所以即使上游回传了也读不到。

本文件钉住四件事：
1. 上游回传 usage 时，流式调用会计账，数值与上游一致；
2. 只带 usage 的那一块不被 `choices` 判空跳过；
3. 上游不认 `stream_options` 时报的是 400——**不能因此把流式弄挂**，
   要摘掉参数重试一次，并记住该模型；
4. 没标的档位不发这个参数（未知参数会把整个请求打成 400）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core import llm_http
from app.core.ai import DeepSeekConfig


def _cfg(model: str = "deepseek-flash", base_url: str = "https://api.deepseek.com"):
    return DeepSeekConfig(apiKey="sk-test", baseUrl=base_url, model=model)


def _delta(text: str) -> Dict[str, Any]:
    return {"choices": [{"delta": {"content": text}}]}


def _usage_chunk(prompt: int, completion: int, total: int) -> Dict[str, Any]:
    return {
        "choices": [],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
        },
    }


def _stream_response(chunks: List[Dict[str, Any]]) -> MagicMock:
    """`client.stream(...)` 的替身（异步上下文管理器 + aiter_lines）。"""
    lines = [f"data: {json.dumps(c)}" for c in chunks] + ["data: [DONE]"]

    async def _aiter_lines():
        for line in lines:
            yield line

    res = MagicMock()
    res.status_code = 200
    res.headers = {}
    res.aiter_lines = _aiter_lines
    res.aread = AsyncMock(return_value=b"")
    res.__aenter__ = AsyncMock(return_value=res)
    res.__aexit__ = AsyncMock(return_value=None)
    return res


def _client(stream_returns) -> MagicMock:
    """假 AsyncClient：`stream()` 每次调用返回下一个响应，并记录请求体。"""
    sent: List[Dict[str, Any]] = []
    queue = list(stream_returns)

    def _stream(method, url, headers=None, json=None):  # noqa: A002
        # 存**快照**而不是引用：自愈分支会就地 pop 掉 stream_options，
        # 存引用的话第一次请求的记录会被后来的修改追溯污染，读起来像"根本没发过"。
        sent.append(dict(json or {}))
        return queue[min(len(sent) - 1, len(queue) - 1)]

    client = MagicMock()
    client.stream = _stream
    client.sent = sent
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _drain(agen) -> str:
    async def _run():
        out = []
        async for chunk in agen:
            out.append(chunk)
        return "".join(out)

    return asyncio.run(_run())


class _Recorder:
    """替掉 `_record_usage_best_effort`：只看"记了什么"，不碰真队列。"""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, usage, model) -> None:
        self.calls.append({"usage": usage, "model": model})


# ------------------------------------------------------------------ 记账本身


def test_streamed_usage_is_recorded():
    """核心回归：上游回传 usage 时，流式调用必须记一笔。"""
    rec = _Recorder()
    client = _client([_stream_response([_delta("雨"), _delta("还在下"), _usage_chunk(120, 34, 154)])])

    with patch.object(llm_http, "_record_usage_best_effort", rec):
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=client):
            text = _drain(
                llm_http.stream_chat_completions(
                    _cfg(), messages=[{"role": "user", "content": "写"}]
                )
            )

    assert text == "雨还在下", "usage 那一块不该被当成正文吐出去"
    assert len(rec.calls) == 1, "一次流式调用必须记一笔账"
    assert rec.calls[0]["usage"] == {"prompt": 120, "completion": 34, "total": 154}
    assert rec.calls[0]["model"] == "deepseek-flash"


def test_usage_only_chunk_is_not_dropped_by_the_choices_guard():
    """第二处成因：`if not choices: continue` 会把只带 usage 的那一块整个跳过。"""
    rec = _Recorder()
    client = _client([_stream_response([_delta("x"), _usage_chunk(7, 8, 15)])])

    with patch.object(llm_http, "_record_usage_best_effort", rec):
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=client):
            _drain(
                llm_http.stream_chat_completions(
                    _cfg(), messages=[{"role": "user", "content": "写"}]
                )
            )

    assert rec.calls, "只带 usage 的那一块必须被读到"
    assert rec.calls[0]["usage"]["total"] == 15


def test_no_usage_means_no_recorded_row():
    """反方向：上游没回传就不能凭空记一笔（记账可以是少记，不可以是假账）。"""
    rec = _Recorder()
    client = _client([_stream_response([_delta("x")])])

    with patch.object(llm_http, "_record_usage_best_effort", rec):
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=client):
            _drain(
                llm_http.stream_chat_completions(
                    _cfg(), messages=[{"role": "user", "content": "写"}]
                )
            )

    assert rec.calls == []


def test_usage_from_payload_distinguishes_missing_from_zero():
    """None ≠ 零值：调用方靠这个区分"上游没给"与"给了但是 0"。"""
    assert llm_http.usage_from_payload({"choices": []}) is None
    assert llm_http.usage_from_payload({"choices": [], "usage": {}}) is None
    assert llm_http.usage_from_payload(
        {"choices": [], "usage": {"total_tokens": 5}}
    ) == {"prompt": 0, "completion": 0, "total": 5}


# ------------------------------------------------------- 请求参数：发还是不发


def test_stream_options_is_sent_for_supported_models():
    """支持的档位要主动索取——上游不带这个参数就不回传 usage。"""
    client = _client([_stream_response([_delta("x")])])

    with patch.object(llm_http, "_record_usage_best_effort", lambda *a, **k: None):
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=client):
            _drain(
                llm_http.stream_chat_completions(
                    _cfg(), messages=[{"role": "user", "content": "写"}]
                )
            )

    assert client.sent and client.sent[0].get("stream_options") == {"include_usage": True}


def test_stream_options_is_not_sent_for_unknown_models():
    """反方向：没标的档位不发——未知参数会把整个请求打成 400。"""
    client = _client([_stream_response([_delta("x")])])

    with patch.object(llm_http, "_record_usage_best_effort", lambda *a, **k: None):
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=client):
            _drain(
                llm_http.stream_chat_completions(
                    _cfg(model="qwen3:8b", base_url="http://127.0.0.1:11434"),
                    messages=[{"role": "user", "content": "写"}],
                )
            )

    assert client.sent and "stream_options" not in client.sent[0]


# ---------------------------------------------------------------- 自愈与边界


def test_rejected_stream_options_self_heals_instead_of_failing():
    """最难的一条：预设标错了也不能把流式弄挂——400 要摘掉参数重试一次。"""
    llm_http._STREAM_OPTIONS_REJECTED.clear()
    bad = MagicMock()
    bad.status_code = 400
    bad.headers = {}
    bad.aread = AsyncMock(
        return_value=b'{"error":{"message":"Unknown parameter: stream_options"}}'
    )
    bad.__aenter__ = AsyncMock(return_value=bad)
    bad.__aexit__ = AsyncMock(return_value=None)

    client = _client([bad, _stream_response([_delta("好"), _usage_chunk(1, 2, 3)])])

    with patch.object(llm_http, "_record_usage_best_effort", lambda *a, **k: None):
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=client):
            text = _drain(
                llm_http.stream_chat_completions(
                    _cfg(), messages=[{"role": "user", "content": "写"}]
                )
            )

    assert text == "好", "摘掉参数后必须真的把内容生成出来，而不是抛错"
    assert len(client.sent) == 2, "应当重试恰好一次"
    assert client.sent[0].get("stream_options") == {"include_usage": True}
    assert "stream_options" not in client.sent[1], "重试必须摘掉那个参数"
    assert "deepseek-flash" in llm_http._STREAM_OPTIONS_REJECTED, "要记住这个模型，别再白跑"


def test_other_400s_are_not_retried_as_a_param_problem():
    """反方向：内容审核之类别的 400 不该被当成参数问题白重试一次。"""
    bad = MagicMock()
    bad.status_code = 400
    bad.headers = {}
    bad.aread = AsyncMock(return_value=b'{"error":{"message":"content filtered"}}')
    bad.__aenter__ = AsyncMock(return_value=bad)
    bad.__aexit__ = AsyncMock(return_value=None)

    client = _client([bad, _stream_response([_delta("x")])])

    with patch.object(llm_http, "_record_usage_best_effort", lambda *a, **k: None):
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=client):
            with pytest.raises(RuntimeError):
                _drain(
                    llm_http.stream_chat_completions(
                        _cfg(), messages=[{"role": "user", "content": "写"}]
                    )
                )

    assert len(client.sent) == 1, "不是参数问题就不该重试"


def test_unknown_param_detector_does_not_fire_on_unrelated_errors():
    assert llm_http._looks_like_unknown_param("Unknown parameter: stream_options")
    assert llm_http._looks_like_unknown_param("extra fields not permitted")
    assert not llm_http._looks_like_unknown_param("rate limit exceeded")
    assert not llm_http._looks_like_unknown_param("")


def test_the_broken_old_behaviour_would_have_been_caught():
    """守卫：确认 `if not choices: continue` 那行确实曾经会吞掉 usage 块。

    这条不是在测实现，而是把"为什么需要上面那些用例"钉在测试里——
    将来有人清理这段逻辑时，能一眼看到它防的是什么。
    """
    chunk = _usage_chunk(1, 2, 3)
    choices = chunk.get("choices") or []
    assert not choices, "usage 块的 choices 是空的，所以旧的判空分支会 continue 掉它"
    assert httpx is not None  # 保持 import 语义（文件内其它用例要用 httpx）


# ------------------------------------------------------ 输出截断（finish_reason）


def test_finish_reason_is_read_from_a_non_streaming_response():
    res = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "x"}, "finish_reason": "length"}]},
        request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
    )
    assert llm_http.finish_reason_from_response(res) == "length"


def test_finish_reason_missing_does_not_raise():
    """上游没给这个字段时返回空串，不能因此炸掉。"""
    res = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "x"}}]},
        request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
    )
    assert llm_http.finish_reason_from_response(res) == ""
    res2 = httpx.Response(
        200,
        content=b"not json",
        request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
    )
    assert llm_http.finish_reason_from_response(res2) == ""


def test_truncation_is_warned_about_not_swallowed(caplog):
    """核心回归：撞输出上限时必须留下痕迹——此前全仓没有 finish_reason 检查，
    截断被当成正常完成，用户看到的是"AI 只写了一小段"而日志一切正常。"""
    with caplog.at_level("WARNING"):
        llm_http._warn_if_truncated("length", "deepseek-flash", streamed=False)
    assert "截断" in caplog.text
    assert "deepseek-flash" in caplog.text


def test_normal_finish_reasons_do_not_warn(caplog):
    """反方向：正常结束（stop / 空）不该刷日志。"""
    with caplog.at_level("WARNING"):
        llm_http._warn_if_truncated("stop", "deepseek-flash", streamed=False)
        llm_http._warn_if_truncated("", "deepseek-flash", streamed=True)
    assert caplog.text == ""


def test_streamed_truncation_is_warned_about(caplog):
    """流式路径同样要认这个字段（结束原因也在最后一块上）。"""
    client = _client([_stream_response([_delta("半截"), {"choices": [{"delta": {}, "finish_reason": "length"}]}])])

    with patch.object(llm_http, "_record_usage_best_effort", lambda *a, **k: None):
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=client):
            with caplog.at_level("WARNING"):
                _drain(
                    llm_http.stream_chat_completions(
                        _cfg(), messages=[{"role": "user", "content": "写"}]
                    )
                )

    assert "截断" in caplog.text, "流式撞上限也必须说一句"

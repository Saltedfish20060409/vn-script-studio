"""端到端验证超时链路：真实 socket + 真实 httpx 超时（不 mock 传输层）。

前面的单测只断言"传给 httpx 的 timeout 是多少"，那还是差一层；这里起一个本地
OpenAI 兼容假服务器，让它真的慢下来，验证三件事在**真实网络上**成立：

1. 预算小于模型耗时 → 如实报"模型响应超时"，且**不重试**（只有一个请求到达）；
2. 同一台慢服务器，预算够大 → 正常拿到结果（这正是修复要达成的效果）；
3. 思考档拿到的是放大后的预算：同一个 1s 基础预算，非思考档超时、思考档通过。

不需要 API Key，不发外网请求。
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.core import llm_budget
from app.core.ai import DeepSeekConfig
from app.core.llm_http import chat_completions

#: 假"慢模型"的生成耗时；预算 1s 会超时，2s/5s 能过。
MODEL_SECONDS = 1.5


class _SlowHandler(BaseHTTPRequestHandler):
    delay = MODEL_SECONDS
    hits = 0

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 约定
        type(self).hits += 1
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        time.sleep(type(self).delay)
        body = json.dumps(
            {
                "model": "slow-model",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # 安静
        return


@pytest.fixture()
def slow_server():
    _SlowHandler.hits = 0
    _SlowHandler.delay = MODEL_SECONDS
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _cfg(base_url: str, model: str) -> DeepSeekConfig:
    return DeepSeekConfig(apiKey="sk-test", baseUrl=base_url, model=model)


def test_budget_smaller_than_model_time_reports_honestly_and_does_not_retry(slow_server):
    """预算不够：如实说"模型响应超时"，且不重试（只发一个请求）。"""

    async def _run():
        with pytest.raises(RuntimeError) as err:
            await chat_completions(
                _cfg(slow_server, "deepseek-flash"),
                messages=[{"role": "user", "content": "hi"}],
                timeout=1,
            )
        return err.value

    err = asyncio.run(_run())
    assert "模型响应超时" in str(err)
    assert "网络失败" not in str(err)
    assert _SlowHandler.hits == 1, f"读超时被重试了（服务器收到 {_SlowHandler.hits} 次）"


def test_budget_larger_than_model_time_succeeds(slow_server):
    """预算够大：同一台慢服务器正常返回——这就是修复要达成的效果。"""

    async def _run():
        return await chat_completions(
            _cfg(slow_server, "deepseek-flash"),
            messages=[{"role": "user", "content": "hi"}],
            timeout=5,
        )

    res = asyncio.run(_run())
    assert res.status_code == 200


def test_thinking_tier_gets_the_longer_budget_on_the_wire(slow_server):
    """同一个 1s 基础预算：非思考档超时，思考档因为自动加时能过。

    这条是"慢思考模型必超时"的直接反证——加时确实作用在真实请求上，
    而不只是算了一个数。
    """
    factor = llm_budget.thinking_factor()
    assert MODEL_SECONDS < 1 * factor, "用例前提：思考档预算要够这次生成"

    async def _non_thinking():
        with pytest.raises(RuntimeError):
            await chat_completions(
                _cfg(slow_server, "deepseek-flash"),
                messages=[{"role": "user", "content": "hi"}],
                timeout=1,
            )

    async def _thinking():
        return await chat_completions(
            _cfg(slow_server, "deepseek-flash-think"),
            messages=[{"role": "user", "content": "hi"}],
            timeout=1,
        )

    asyncio.run(_non_thinking())
    res = asyncio.run(_thinking())
    assert res.status_code == 200

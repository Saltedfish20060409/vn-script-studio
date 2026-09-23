"""客户端断开 → 中止在飞的模型调用；后台作业不受影响。

背景（用户报障的延伸代价）：前端一旦放弃（关页/刷新/触发自己的超时），
连接就没了，但 FastAPI 不会因此取消处理器——思考档一次生成几十秒到几分钟，
会继续跑完：白烧 token，还占着 `_LLM_SEMAPHORE` 的并发额度。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.ai import DeepSeekConfig
from app.core.disconnect import DisconnectGuard, detach_guard, model_call_watch, set_guard
from app.core.llm_http import chat_completions, stream_chat_completions


class _FakeRequest:
    """只实现护栏用到的那一个方法。

    `gone_after=n` = 前 n 次探测说"还在"，之后说"走了"，用来区分
    「进窗口前就断了」与「等模型等到一半才断」两种路径。
    """

    def __init__(
        self,
        gone: bool,
        *,
        gone_after: int | None = None,
        raises: bool = False,
        delay: float = 0.0,
    ) -> None:
        self.gone = gone
        self.gone_after = gone_after
        self.raises = raises
        self.delay = delay
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises:
            raise RuntimeError("probe exploded")
        if self.gone_after is not None and self.calls > self.gone_after:
            return True
        return self.gone


def _cfg() -> DeepSeekConfig:
    return DeepSeekConfig(apiKey="sk-test", baseUrl="https://api.example.com", model="m")


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"model": "m", "choices": [{"message": {"content": "ok"}}]},
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
    )


def _client(post) -> MagicMock:
    c = MagicMock()
    c.post = post
    c.stream = MagicMock()
    c.__aenter__ = AsyncMock(return_value=c)
    c.__aexit__ = AsyncMock(return_value=None)
    return c


def _guard(request, *, enabled: bool = True, interval: float = 0.01) -> DisconnectGuard:
    return DisconnectGuard(request, interval=interval, enabled=enabled)


# --- 护栏本身 --------------------------------------------------------------


def test_watch_is_noop_without_guard():
    """CLI / 后台作业 / 测试里没有护栏，行为必须与改造前一模一样。"""
    posts = AsyncMock(return_value=_ok_response())

    async def _run():
        detach_guard()
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=_client(posts)):
            return await chat_completions(_cfg(), messages=[{"role": "user", "content": "hi"}])

    assert asyncio.run(_run()).status_code == 200


def test_watch_is_noop_when_disabled():
    """`disconnect_cancel_enabled=false` 时不许取消任何东西。"""
    posts = AsyncMock(return_value=_ok_response())

    async def _run():
        set_guard(_guard(_FakeRequest(gone=True), enabled=False))
        try:
            with patch("app.core.llm_http.httpx.AsyncClient", return_value=_client(posts)):
                return await chat_completions(_cfg(), messages=[{"role": "user", "content": "hi"}])
        finally:
            set_guard(None)

    assert asyncio.run(_run()).status_code == 200


def test_probe_failure_never_kills_a_live_request():
    """探测本身出错就按"还在"处理——绝不因为探测失败误杀正常请求。"""
    posts = AsyncMock(return_value=_ok_response())

    async def _run():
        set_guard(_guard(_FakeRequest(gone=True, raises=True)))
        try:
            with patch("app.core.llm_http.httpx.AsyncClient", return_value=_client(posts)):
                return await chat_completions(_cfg(), messages=[{"role": "user", "content": "hi"}])
        finally:
            set_guard(None)

    assert asyncio.run(_run()).status_code == 200


# --- 断开时中止 ------------------------------------------------------------


def test_disconnected_client_cancels_inflight_call():
    """等到一半客户端走了：不再把这次生成跑完，立刻取消。"""
    started = asyncio.Event()

    async def slow_post(*_a, **_kw):
        started.set()
        await asyncio.sleep(30)  # 模拟思考档的长生成
        return _ok_response()

    async def _run():
        # 进窗口时还在（第 1 次探测），之后探测到断开
        set_guard(_guard(_FakeRequest(gone=False, gone_after=1)))
        try:
            with patch("app.core.llm_http.httpx.AsyncClient", return_value=_client(slow_post)):
                with pytest.raises(asyncio.CancelledError):
                    await chat_completions(_cfg(), messages=[{"role": "user", "content": "hi"}])
        finally:
            set_guard(None)

    asyncio.run(_run())
    assert started.is_set(), "请求应已发出，随后被取消（而不是压根没发）"


def test_already_gone_client_never_sends_the_request():
    """进窗口前就断了：一个字节都不发——多轮端点尤其重要，别再开下一轮。"""
    posts = AsyncMock(return_value=_ok_response())

    async def _run():
        set_guard(_guard(_FakeRequest(gone=True)))
        try:
            with patch("app.core.llm_http.httpx.AsyncClient", return_value=_client(posts)):
                with pytest.raises(asyncio.CancelledError):
                    await chat_completions(_cfg(), messages=[{"role": "user", "content": "hi"}])
        finally:
            set_guard(None)

    asyncio.run(_run())
    assert posts.await_count == 0, "客户端已断开却仍然发起了模型调用"


def test_disconnect_midstream_stops_the_generation():
    """流式也一样：人走了就别继续等新 token。"""
    class _FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        @property
        def status_code(self):
            return 200

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"A"}}]}'
            await asyncio.sleep(30)  # 之后一直没新内容
            yield "data: [DONE]"

    c = MagicMock()
    c.stream = MagicMock(return_value=_FakeStream())
    c.__aenter__ = AsyncMock(return_value=c)
    c.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        set_guard(_guard(_FakeRequest(gone=False, gone_after=1)))
        got: list[str] = []
        try:
            with patch("app.core.llm_http.httpx.AsyncClient", return_value=c):
                with pytest.raises(asyncio.CancelledError):
                    async for delta in stream_chat_completions(
                        _cfg(), messages=[{"role": "user", "content": "hi"}]
                    ):
                        got.append(delta)
        finally:
            set_guard(None)
        return got

    got = asyncio.run(_run())
    assert got == ["A"], "已经产出的内容应保留，之后停止"


def test_second_call_after_disconnect_is_not_started():
    """多轮端点（如头脑风暴的"作家 → 责编"）不该在客户端走后开第二轮。"""
    posts = AsyncMock(return_value=_ok_response())

    async def _run():
        # 第一轮开始时还连着，之后断开 → 第二轮应当根本不发起
        set_guard(_guard(_FakeRequest(gone=False, gone_after=1)))
        try:
            with patch("app.core.llm_http.httpx.AsyncClient", return_value=_client(posts)):
                results = []
                for _ in range(3):
                    try:
                        results.append(
                            await chat_completions(
                                _cfg(), messages=[{"role": "user", "content": "hi"}]
                            )
                        )
                    except asyncio.CancelledError:
                        break
                return results
        finally:
            set_guard(None)

    out = asyncio.run(_run())
    # 第一轮正常完成；断开后的第二轮不该被发起（循环在 CancelledError 处 break）
    assert len(out) == 1, "断开后仍在继续跑后续轮次"


def test_watch_only_covers_the_model_call():
    """窗口之外（写库阶段）不取消——避免留下半截写入。"""
    fake = _FakeRequest(gone=False)

    async def _run():
        set_guard(_guard(fake, interval=0.01))
        try:
            async with model_call_watch():
                pass
            # 窗口已关闭后客户端才走：之后的等待不该被取消
            fake.gone = True
            await asyncio.sleep(0.05)
            return "reached"
        finally:
            set_guard(None)

    assert asyncio.run(_run()) == "reached"


# --- 后台作业必须活过客户端 ------------------------------------------------


def test_background_job_survives_client_disconnect():
    """管线/章节回炉的 async_mode 承诺"客户端走了也跑完"，所以必须 detach。"""
    from app.core.jobs import _detached

    posts = AsyncMock(return_value=_ok_response())

    async def _run():
        set_guard(_guard(_FakeRequest(gone=True)))
        try:
            async def work():
                return await chat_completions(
                    _cfg(), messages=[{"role": "user", "content": "hi"}]
                )

            task = asyncio.create_task(_detached(work()))
            return await asyncio.wait_for(task, timeout=5)
        finally:
            set_guard(None)

    with patch("app.core.llm_http.httpx.AsyncClient", return_value=_client(posts)):
        res = asyncio.run(_run())
    assert res.status_code == 200


def test_request_own_child_tasks_are_still_cancellable():
    """请求内 gather 出来的子任务（如头脑风暴的并发作家）仍应被取消。"""
    async def slow_post(*_a, **_kw):
        await asyncio.sleep(30)
        return _ok_response()

    async def _run():
        set_guard(_guard(_FakeRequest(gone=True)))
        try:
            with patch("app.core.llm_http.httpx.AsyncClient", return_value=_client(slow_post)):
                return await asyncio.gather(
                    chat_completions(_cfg(), messages=[{"role": "user", "content": "a"}]),
                    chat_completions(_cfg(), messages=[{"role": "user", "content": "b"}]),
                    return_exceptions=True,
                )
        finally:
            set_guard(None)

    out = asyncio.run(_run())
    assert all(isinstance(x, asyncio.CancelledError) for x in out), out

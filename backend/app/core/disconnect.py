"""客户端断开时，中止正在进行的上游模型调用。

## 为什么需要

前端一旦放弃（用户关页、刷新、切走，或达到自己的超时预算），HTTP 连接就没了；
但 FastAPI 不会因此取消正在运行的处理器——它会**继续把这次生成跑完**：
思考档动辄几十秒到几分钟，白烧 token、占用进程内的 16 个并发闸
（`llm_http._LLM_SEMAPHORE` 是为共享服务器 key 设的），而且结果用户也看不到。

## 做法与边界

- 中间件给每个请求挂一个 `DisconnectGuard`（ContextVar），很便宜；
- `llm_http` 在**真正等待上游**的那一小段时间外面套 `model_call_watch()`；
- 窗口内每 1 秒探测一次连接；探测到断开就 `cancel()` 掉**当前正在等模型的那个任务**
  （可能是请求任务，也可能是 `asyncio.gather` 派生的子任务）。
- 因此取消只会落在"某次模型调用进行中"，**不会**落在提交数据库写入的过程中：
  业务代码是先拿到模型结果、再去写库的。
- 后台作业（管线 / 章节回炉的 `async_mode`）必须活过客户端，所以
  `jobs._spawn` 会在新任务里 `detach_guard()` 主动脱离本护栏；
  它们另有自己的协作式取消（见 `api/v1/pipeline.py` 的取消标志）。

探测用 `Request.is_disconnected()`（Starlette 的非阻塞实现）。若部署在
"客户端走了但代理不告诉我们"的链路上，探测永远不触发，行为与改造前一致——
只是少省了 token，不会误杀正常请求。
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from typing import Any, AsyncIterator, Optional

logger = logging.getLogger(__name__)

# 探测间隔：1 秒足够快（最坏多跑 1 秒），又不会给每个请求压上负担。
_POLL_SECONDS = 1.0


class DisconnectGuard:
    """一个请求的"客户端还在吗"护栏。由中间件创建，随请求结束丢弃。"""

    __slots__ = ("_request", "_interval", "_enabled", "lost")

    def __init__(self, request: Any, *, interval: float = _POLL_SECONDS, enabled: bool = True):
        self._request = request
        self._interval = interval
        self._enabled = enabled
        #: 探测到断开后置 True（供测试与日志使用）
        self.lost = False

    async def _gone(self) -> bool:
        """探一次连接。探测本身出错时按"还在"处理——绝不误杀正常请求。"""
        try:
            return bool(await self._request.is_disconnected())
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 探测失败不该影响业务
            logger.debug("is_disconnected 探测失败", exc_info=True)
            return False

    async def _poll(self, owner: Optional[asyncio.Task]) -> None:
        """每 interval 秒探一次；断开就取消 owner（正在等模型的那个任务）。"""
        first = True
        while True:
            if not first:
                await asyncio.sleep(self._interval)
            first = False
            try:
                gone = await self._gone()
            except asyncio.CancelledError:
                raise
            if gone:
                self.lost = True
                if owner is not None and not owner.done():
                    logger.info("客户端已断开，中止进行中的模型调用")
                    owner.cancel()
                return


_guard: ContextVar[Optional[DisconnectGuard]] = ContextVar("disconnect_guard", default=None)


def set_guard(guard: Optional[DisconnectGuard]) -> None:
    _guard.set(guard)


def current_guard() -> Optional[DisconnectGuard]:
    return _guard.get()


def detach_guard() -> None:
    """让当前任务脱离请求的取消域。

    后台作业（管线、章节回炉的 async_mode）必须在客户端离开后继续跑完并落库，
    否则"结果能在运行记录里找到"这条承诺就不成立。
    """
    _guard.set(None)


@asynccontextmanager
async def model_call_watch() -> AsyncIterator[None]:
    """包住一次模型调用：窗口内客户端断开 → 取消当前任务。

    没有护栏（后台作业、CLI、测试）或护栏未启用时是零开销的空实现。

    进入窗口时先探一次连接：客户端已经走了就**一个字节都不发**。
    这对多轮端点（头脑风暴的"作家 → 责编"、章节回炉的两段）尤其重要——
    与其把第二轮也跑完再丢弃，不如根本不发起。
    """
    guard = _guard.get()
    if guard is None or not guard._enabled:
        yield
        return
    if guard.lost or await guard._gone():
        guard.lost = True
        # 手动抛 CancelledError：asyncio 会把本任务记为"已取消"（正常终止，
        # 不会当成未处理异常打日志），业务层的 `except Exception` 也不会吞掉它。
        raise asyncio.CancelledError("客户端已断开，未发起模型调用")
    owner = asyncio.current_task()
    watcher = asyncio.create_task(guard._poll(owner), name="disconnect-watch")
    try:
        yield
    finally:
        watcher.cancel()
        # CancelledError 是 BaseException，suppress(Exception) 盖不到它
        with suppress(asyncio.CancelledError, Exception):
            await watcher

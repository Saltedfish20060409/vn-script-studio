"""本次请求的执行档：**客户端在不在看着**（决定我们能给多长的等待）。

## 为什么需要它

"上下文能放多大"与"一次调用能等多久"这两个数，取决于**等待的那个人是谁**：

- **同步端点**（`/agent`、审稿、回信、门禁…）：前端按"这个 HTTP 请求"计时，
  有明确的阶梯预算（`frontend/src/api/timeouts.ts`）。我们必须在它之前如实报错，
  所以单次预算收得比较紧（预填充加时上限 60s、上下文天花板 96k 字符）。
- **流式端点**（`/agent/stream`、`/pipeline/run?stream`）：SSE 有心跳（20s 一跳），
  前端**不设总超时**、靠"多久没有新字节"判活。等第一个字节等两三分钟不会把连接掐掉，
  所以这里可以给出更宽的预填充加时（240s）与更高的上下文天花板（240k 字符）。

用 ContextVar 而不是给每个函数加参数：调用链很深（路由 → agent_loop → 每个工具/每轮模型
调用），一路透传会把签名搞脏；而且它天然是**请求级**的——FastAPI 每个请求在自己的任务
上下文里跑，路由里 set 一次就够（与 `core/usage.py` 的 `set_usage_kind` 同一套做法）。

## 默认值必须是"最保守"的那一档

没设置时一律按 `sync` 处理：同步档的预算更紧，宁可让流式路径少等一会儿，
也不能让同步路径拿到宽预算——那会让前端先掐断并弹出误导文案（用户报障过的那类问题）。
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

#: 同步端点：前端有总超时，预算必须收在它之内
PROFILE_SYNC = "sync"
#: 流式端点：SSE + 心跳，客户端看得见进度，没有总超时
PROFILE_STREAMED = "streamed"

PROFILES = (PROFILE_SYNC, PROFILE_STREAMED)

_profile: ContextVar[str] = ContextVar("execution_profile", default=PROFILE_SYNC)


def normalize_profile(name: Optional[str]) -> str:
    """认不出来的值一律当 `sync`（保守）。"""
    value = (name or "").strip().lower()
    return value if value in PROFILES else PROFILE_SYNC


def set_profile(name: Optional[str]) -> str:
    """设置本次请求的执行档；返回规范化后的值。"""
    value = normalize_profile(name)
    _profile.set(value)
    return value


def current_profile() -> str:
    return normalize_profile(_profile.get())


def is_streamed() -> bool:
    return current_profile() == PROFILE_STREAMED


def reset_profile() -> None:
    """回到默认档（测试与后台任务用：后台作业不该继承某个请求的宽松预算）。"""
    _profile.set(PROFILE_SYNC)

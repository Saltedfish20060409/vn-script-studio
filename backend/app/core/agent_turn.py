"""Agent Writing Turn（ADR 0001 P1）：SSE 协议层软超时 / 硬取消。

P1 对 write 是透传代理：真实上下文与 prompt 改造从 P2 开始。
本模块只负责：

1. 命名超时常量（与 ADR §13.1：软 180s / 硬 210s 对齐）；
2. 可单测的「下一拍该等多久、是否该发 soft_timeout / hard_cancel」调度；
3. 供 `/agent/turn`（及兼容层 `/agent/write`）复用的 SSE 事件构造。

不要在这里拼写作 prompt——那是 P2 / P2.5 的事。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

#: 软上限（秒）：到点发 `soft_timeout` 事件，**不**中止生成（ADR：提示可取消）。
WRITE_SOFT_TIMEOUT_S = 180.0

#: 硬取消（秒）：到点取消 runner，发 `error`（code=hard_timeout）。
WRITE_HARD_CANCEL_S = 210.0

#: SSE 心跳间隔（秒）。与 `projects._SSE_KEEPALIVE_SECONDS` 同值；
#: 这里再钉一份是为了 turn 调度单测不依赖 API 模块。
TURN_SSE_KEEPALIVE_S = 15.0


@dataclass(frozen=True)
class TurnDeadlinePlan:
    """一次 wait 循环的决策（纯函数，便于单测）。"""

    wait_s: float
    emit_soft_timeout: bool = False
    hard_cancel: bool = False


def plan_next_wait(
    *,
    elapsed_s: float,
    soft_timeout_s: float = WRITE_SOFT_TIMEOUT_S,
    hard_cancel_s: float = WRITE_HARD_CANCEL_S,
    keepalive_s: float = TURN_SSE_KEEPALIVE_S,
    soft_already_emitted: bool = False,
) -> TurnDeadlinePlan:
    """根据已流逝时间决定下一拍 wait 多久、是否触发软/硬超时。

    硬取消优先于软超时。软超时只发一次（由调用方传 soft_already_emitted）。
    """
    if hard_cancel_s > 0 and elapsed_s >= hard_cancel_s:
        return TurnDeadlinePlan(wait_s=0.0, hard_cancel=True)
    if (
        soft_timeout_s > 0
        and not soft_already_emitted
        and elapsed_s >= soft_timeout_s
    ):
        return TurnDeadlinePlan(wait_s=0.0, emit_soft_timeout=True)

    remaining_hard = (
        max(0.0, hard_cancel_s - elapsed_s) if hard_cancel_s > 0 else keepalive_s
    )
    remaining_soft = (
        max(0.0, soft_timeout_s - elapsed_s)
        if soft_timeout_s > 0 and not soft_already_emitted
        else keepalive_s
    )
    wait = min(keepalive_s, remaining_hard, remaining_soft)
    # 避免 0 忙等：若下一边界就在眼前，至少让出一点事件循环
    if wait <= 0:
        wait = 0.05
    return TurnDeadlinePlan(wait_s=wait)


def turn_meta_event(
    *,
    capability: str = "write",
    write_op: Optional[str] = None,
    soft_timeout_s: float = WRITE_SOFT_TIMEOUT_S,
    hard_cancel_s: float = WRITE_HARD_CANCEL_S,
    passthrough: bool = True,
    scope: Optional[str] = None,
    delegated: bool = False,
) -> Dict[str, Any]:
    """流开始时的协议元信息（前端可据此显示剩余时间 / 取消提示）。"""
    out: Dict[str, Any] = {
        "type": "meta",
        "capability": capability,
        "writeOp": write_op,
        "softTimeoutS": soft_timeout_s,
        "hardCancelS": hard_cancel_s,
        "passthrough": passthrough,
    }
    if scope is not None:
        out["scope"] = scope
    if delegated:
        out["delegated"] = True
    return out


def soft_timeout_event(*, elapsed_s: float, hard_cancel_s: float) -> Dict[str, Any]:
    return {
        "type": "soft_timeout",
        "elapsedS": round(elapsed_s, 1),
        "hardCancelS": hard_cancel_s,
        "message": (
            f"本轮写作已超过软上限（{int(elapsed_s)}s）。"
            "可以继续等待，或取消后缩小范围重试。"
        ),
    }


def hard_timeout_error(*, elapsed_s: float, hard_cancel_s: float) -> Dict[str, Any]:
    return {
        "type": "error",
        "code": "hard_timeout",
        "message": (
            f"写作已超过硬取消上限（{int(hard_cancel_s)}s），已中止以免无限等待。"
            "请缩小范围或换非思考档后重试。"
        ),
        "elapsedS": round(elapsed_s, 1),
    }

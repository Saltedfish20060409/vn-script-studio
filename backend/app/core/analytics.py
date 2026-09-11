"""最小产品埋点：事件名常量 + 写入助手。

设计原则（见 docs/roadmap-2026-09.md 方向 B）：
- 只记「动作是否发生」，**不记正文、设定、Key 等创作内容**；
- 事件名在这里集中定义，避免以后名字满天飞；
- 写入失败绝不影响主流程（调用方 await，但异常吞掉并记 debug 日志）；
- 前端也能上报（POST /events），走后端同样的事件名白名单。

漏斗关心的关键节点：
    signup          注册成功（props.source = 渠道）
    sample_created  自动/手动创建示例项目
    project_created 用户自建项目
    prose_saved     首次保存有内容的正文
    ai_call         首次成功调用 AI（由 llm_usage 侧记录）
    rpy_generated   首次生成 RPY
    playtest_opened 首次试玩
    export_done     首次导出（Word/Markdown/RPY/工程包）
    share_created   首次生成分享链接
    invite_sent     首次邀请协作
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tables import ProductEvent

logger = logging.getLogger(__name__)

# 事件名白名单（前后端共用同一套；未知名字一律拒绝）
SIGNUP = "signup"
SAMPLE_CREATED = "sample_created"
PROJECT_CREATED = "project_created"
PROSE_SAVED = "prose_saved"
AI_CALL = "ai_call"
RPY_GENERATED = "rpy_generated"
PLAYTEST_OPENED = "playtest_opened"
EXPORT_DONE = "export_done"
SHARE_CREATED = "share_created"
INVITE_SENT = "invite_sent"
MEMORY_ARCHIVED = "memory_archived"

EVENT_NAMES = frozenset(
    {
        SIGNUP,
        SAMPLE_CREATED,
        PROJECT_CREATED,
        PROSE_SAVED,
        AI_CALL,
        RPY_GENERATED,
        PLAYTEST_OPENED,
        EXPORT_DONE,
        SHARE_CREATED,
        INVITE_SENT,
        MEMORY_ARCHIVED,
    }
)

# props 只允许这些键（避免前端不小心把正文/密钥带上来）
_ALLOWED_PROP_KEYS = frozenset(
    {"template", "is_sample", "kind", "step", "from", "chars", "model"}
)
_MAX_PROPS = 6
_MAX_VALUE_LEN = 64


def sanitize_props(props: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """留下白名单键，值一律转成短字符串（防注入、防隐私外泄）。"""
    out: Dict[str, str] = {}
    if not isinstance(props, dict):
        return out
    for key, value in list(props.items())[:_MAX_PROPS]:
        if key not in _ALLOWED_PROP_KEYS:
            continue
        if value is None or isinstance(value, (dict, list, tuple, set)):
            continue
        out[str(key)] = str(value)[:_MAX_VALUE_LEN]
    return out


async def record_event(
    db: AsyncSession,
    user_id: Optional[str],
    name: str,
    props: Optional[Dict[str, Any]] = None,
) -> None:
    """写一条事件；未知事件名或任何异常都不影响主流程。"""
    if name not in EVENT_NAMES:
        logger.debug("analytics: rejected unknown event name %r", name)
        return
    try:
        db.add(
            ProductEvent(
                user_id=user_id,
                name=name,
                props=sanitize_props(props),
            )
        )
        await db.flush()
    except Exception as exc:  # noqa: BLE001 - 埋点绝不能弄坏业务
        logger.debug("analytics: record_event failed (%s)", exc)


async def has_event(db: AsyncSession, user_id: str, name: str) -> bool:
    """该用户是否已经发生过某事件（用于「首次」语义）。"""
    try:
        found = await db.scalar(
            select(func.count())
            .select_from(ProductEvent)
            .where(ProductEvent.user_id == user_id, ProductEvent.name == name)
        )
        return bool(found)
    except Exception:  # noqa: BLE001
        return False


async def record_first_event(
    db: AsyncSession,
    user_id: str,
    name: str,
    props: Optional[Dict[str, Any]] = None,
) -> None:
    """只在用户首次发生该事件时写入（省行数，也让漏斗"首次"口径天然成立）。"""
    if await has_event(db, user_id, name):
        return
    await record_event(db, user_id, name, props)


async def record_events(
    db: AsyncSession,
    user_id: Optional[str],
    events: Iterable[tuple[str, Optional[Dict[str, Any]]]],
) -> int:
    """批量写入；返回实际写入条数。"""
    written = 0
    for name, props in events:
        if name not in EVENT_NAMES:
            continue
        await record_event(db, user_id, name, props)
        written += 1
    return written

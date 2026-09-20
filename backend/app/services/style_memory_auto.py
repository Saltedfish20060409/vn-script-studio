"""文风记忆自动学习（默认开）。

为什么默认开：文风样例与风格指南**必须每次都在上下文里**才有效，而"让作者记得去点一下学习"
在实测里等于没人用（同类功能的线上使用率：需要主动下命令的 agent_jobs 只有 2 次，
而挂在保存路径上的章节摘要 159/159 全覆盖）。所以这里按"攒够跨度 + 没学过/过期"自动跑一次。

两条自我约束：
1. **只用作者自己的 Key**：站内免费档是共享额度，自动学习会静默吃掉作者的每日额度，所以不代跑；
2. **按跨度触发 + 结果里记章节数**：不重复学同一批内容，也不会每次保存都跑一次模型。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

# 触发门槛：内容太少学了也没意义
MIN_CHAPTERS = 3
MIN_PROSE_CHARS = 3000
# 每次学习后至少再过这么多章才重学（避免每章都跑一次模型）
CHAPTER_STRIDE = 5
# 距上次学习超过这个天数，且内容又长了几章 → 重学
STALE_DAYS = 30


def _prose_chars(vn) -> int:
    total = 0
    for ch in vn.chapters or []:
        prose = str(getattr(ch, "prose", None) or "")
        if prose.strip():
            total += len(prose)
        else:
            for block in list(getattr(ch, "blocks", None) or []):
                if (block or {}).get("type") in ("narration", "dialogue"):
                    total += len(str(block.get("text") or ""))
    return total


def should_auto_learn_style(
    chapter_count: int,
    prose_chars: int,
    style_memory: Optional[Dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> Tuple[bool, str]:
    """要不要现在自动学一次文风。返回 (是否学, 原因/跳过原因)。"""
    if chapter_count < MIN_CHAPTERS:
        return False, "章节还不够"
    if prose_chars < MIN_PROSE_CHARS:
        return False, "内容还不够"
    memory = style_memory if isinstance(style_memory, dict) else None
    if not memory:
        return True, "还没学过文风"
    guide = str(memory.get("guide") or "").strip()
    if not guide:
        return True, "上次没学到东西"

    learned_chapters = int(memory.get("learnedChapterCount") or 0)
    if chapter_count - learned_chapters >= CHAPTER_STRIDE:
        return True, "又写了若干章"

    updated = str(memory.get("updatedAt") or "")
    if updated:
        try:
            when = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            reference = now or datetime.now(timezone.utc)
            if reference - when > timedelta(days=STALE_DAYS) and chapter_count > learned_chapters:
                return True, "文风记忆过期"
        except ValueError:
            pass
    return False, "刚刚学过"


async def maybe_auto_learn_style(
    db,
    state,
    vn,
    settings,
    *,
    user_id: str,
    now: Optional[datetime] = None,
) -> Tuple[bool, str]:
    """按需自动学一次文风；成功则把结果写进工程。返回 (是否写入, 说明)。

    失败一律静默（自动学习不该让保存失败），但要能把原因返回给调用方便于诊断。
    """
    if not getattr(settings, "style_auto_learn", True):
        return False, "已关闭自动学习"

    from app.services.settings import user_llm_credentials

    # 只用作者自己的 Key：免费档是共享额度，不代作者花
    try:
        own = await user_llm_credentials(db, user_id, settings)
    except Exception:  # noqa: BLE001
        own = {}
    if not (own or {}).get("api_key"):
        return False, "未配置自己的 Key（自动学习不占用站内额度）"

    chapter_count = len(vn.chapters or [])
    prose_chars = _prose_chars(vn)
    should, why = should_auto_learn_style(
        chapter_count, prose_chars, getattr(vn, "styleMemory", None), now=now
    )
    if not should:
        return False, why

    from app.core.ai import DeepSeekConfig
    from app.core.style_memory import learn_style_memory

    config = DeepSeekConfig(
        apiKey=str(own.get("api_key") or ""),
        baseUrl=str(own.get("base_url") or settings.deepseek_base_url),
        model=str(own.get("model") or settings.deepseek_model),
    )
    result = await learn_style_memory(config, vn)
    if result.error or not result.guide:
        return False, result.error or "没学到内容"

    from datetime import datetime as _dt
    from datetime import timezone as _tz

    next_memory = {
        "guide": result.guide,
        "samples": result.samples,
        "updatedAt": _dt.now(_tz.utc).isoformat(),
        # 记下这批内容的章节数：下一次按"又写了若干章"触发，避免每章都跑
        "learnedChapterCount": chapter_count,
        "auto": True,
    }
    next_vn = vn.model_copy(deep=True)
    next_vn.styleMemory = next_memory

    from app.services.projects import sync_chapter_rows_from_vn

    await sync_chapter_rows_from_vn(db, state, next_vn)
    await db.commit()
    return True, why

"""写作页「标记批改」端点：对作者标出来的一处做局部改写（或只给建议）。

为什么单开一个模块、单开一个端点：整章回炉（`chapter_revise`）走的是后台任务 + 全章重写，
成本和副作用都大；标记批改是**一次一处、即时返回**的小请求，塞进 agent 流程里既慢又贵。
这里只做一件事：给定「上文 / 这一段 / 下文 / 要求」，返回改写稿或建议。
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.ai import DeepSeekConfig
from app.core.mark_revise import revise_marked_text
from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services.projects import get_owned_project, resolve_llm_credentials, row_to_vn

router = APIRouter(prefix="/projects", tags=["marks"])


class MarkReviseIn(BaseModel):
    chapter_id: str = ""
    quote: str = Field(default="", max_length=4000)
    prefix: str = Field(default="", max_length=1000)
    suffix: str = Field(default="", max_length=1000)
    instruction: str = Field(default="", max_length=1000)
    intent: Literal["rewrite", "advice"] = "rewrite"
    # 一次给几版改写（1–3）。多版让作者挑一版，比反复点"重来"省事也更省 token。
    candidates: int = Field(default=1, ge=1, le=3)


@router.post("/{project_id}/marks/revise")
async def revise_mark(
    project_id: str,
    body: MarkReviseIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """处理一个标记：返回 {replacement}（改写）或 {advice}（只给建议）。"""
    from app.core.rate_limit import require_rate
    from app.core.usage import ensure_under_quota

    if not body.quote.strip():
        raise HTTPException(status_code=400, detail="标记内容为空，请重新选中要改的文字")

    require_rate(
        user.id,
        "llm_write",
        240,
        enabled=settings.rate_limit_enabled,
        window=3600,
        detail="AI 调用过于频繁，请稍后再试",
    )
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    creds = await resolve_llm_credentials(db, user.id, settings)
    if not creds.get("api_key"):
        raise HTTPException(
            status_code=400,
            detail="没有可用的模型密钥：请到「设置 → 模型」填自己的 Key（或使用站内免费档）",
        )
    await ensure_under_quota(db, user.id, settings, creds)

    config = DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )
    # 作者自己的文风记忆（如果学过）：让改写贴 ta 的腔调，而不是模型的默认腔调
    style_guide = ""
    style = vn.styleMemory or {}
    if isinstance(style, dict):
        style_guide = str(style.get("guide") or "")

    result = await revise_marked_text(
        config,
        quote=body.quote,
        prefix=body.prefix,
        suffix=body.suffix,
        instruction=body.instruction,
        intent=body.intent,
        style_guide=style_guide,
        candidates=body.candidates,
    )
    if result.error:
        raise HTTPException(status_code=502, detail=result.error)

    changed = bool(result.replacement) and result.replacement.strip() != body.quote.strip()
    return {
        "replacement": result.replacement,
        # 多候选：作者在卡片上挑一版（第一版即 replacement，兼容旧前端）
        "candidates": result.candidates or ([result.replacement] if result.replacement else []),
        "advice": result.advice,
        "changed": changed,
        "model": result.model,
        "styleUsed": bool(style_guide),
        "intent": body.intent,
        "chapterId": body.chapter_id,
    }


@router.get("/{project_id}/marks/hint")
async def marks_hint(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """标记面板要显示的一句提示：有没有可用的文风记忆（决定"按你的文风改"是否生效）。"""
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    style = vn.styleMemory or {}
    guide: Optional[str] = str(style.get("guide") or "") if isinstance(style, dict) else ""
    return {"hasStyleMemory": bool(guide.strip())}

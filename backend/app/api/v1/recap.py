"""卷首「前情提要」端点：把已写过的章节压成一段可读的回述。

与 agent 流程分开：这是一次性的生成任务（作者点一下、拿走一段文本），
不需要工具调用、不需要写进工程；生成结果由作者自己决定放哪里。
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.ai import DeepSeekConfig
from app.core.recap import resolve_recap_targets, run_recap
from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services.projects import get_owned_project, resolve_llm_credentials, row_to_vn

router = APIRouter(prefix="/projects", tags=["recap"])


class RecapIn(BaseModel):
    # "" 表示「未分卷」；None 表示不按卷（给不分卷的作品用"写到现在"）
    volume_id: Optional[str] = None
    mode: Literal["before", "volume"] = "before"
    up_to_chapter_id: Optional[str] = Field(default=None, max_length=64)


@router.post("/{project_id}/recap")
async def project_recap(
    project_id: str,
    body: RecapIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """生成前情提要：{ text, model, chaptersUsed, archivesUsed, label }。"""
    from app.core.rate_limit import require_rate
    from app.core.usage import ensure_under_quota

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

    chapter_ids, label, err = resolve_recap_targets(
        vn,
        volume_id=body.volume_id,
        mode=body.mode,
        up_to_chapter_id=body.up_to_chapter_id,
    )
    if err:
        raise HTTPException(status_code=400, detail=err)

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

    # 已归档的"连续性要点"当压缩材料；但它必须落在回述范围之内（不能把后面的剧情提上来）。
    archives: list[str] = []
    try:
        from app.services.novel_memory import get_latest_continuity

        continuity = await get_latest_continuity(db, project_id)
        if continuity and str(continuity.get("continuityText") or "").strip():
            order = [c.id for c in (vn.chapters or [])]
            last_in_scope = order.index(chapter_ids[-1]) + 1 if chapter_ids else 0
            range_to = int(continuity.get("rangeTo") or 0)
            if range_to and range_to <= last_in_scope:
                archives.append(str(continuity["continuityText"]))
    except Exception:  # noqa: BLE001 - 归档读取失败不该挡住生成
        archives = []

    result = await run_recap(
        config,
        project=vn,
        chapter_ids=chapter_ids,
        target_label=label,
        archives=archives,
    )
    if result.error:
        raise HTTPException(status_code=502, detail=result.error)

    return {
        "text": result.text,
        "model": result.model,
        "chaptersUsed": result.chapters_used,
        "archivesUsed": result.archives_used,
        "included": result.included,
        "label": label,
        "mode": body.mode,
        "volumeId": body.volume_id,
    }

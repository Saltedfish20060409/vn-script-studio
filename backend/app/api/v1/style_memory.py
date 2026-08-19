from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.ai import DeepSeekConfig
from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services.projects import (
    get_owned_project,
    project_to_dict,
    resolve_llm_credentials,
    row_to_vn,
    sync_chapter_rows_from_vn,
)

router = APIRouter(prefix="/projects", tags=["style-memory"])


@router.post("/{project_id}/style-memory/learn")
async def learn_style_memory_endpoint(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """LLM distils a writing-style guide from the author's own chapters and
    stores it on the project; the agent context injects it on later turns."""
    from app.core.style_memory import learn_style_memory

    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    creds = await resolve_llm_credentials(db, user.id, settings)
    if not creds.get("api_key"):
        raise HTTPException(status_code=400, detail="服务端未配置 DEEPSEEK_API_KEY")
    from app.core.usage import ensure_under_quota

    await ensure_under_quota(db, user.id, settings, creds)
    config = DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )
    result = await learn_style_memory(config, vn)
    if result.error:
        raise HTTPException(status_code=502, detail=result.error)
    if not result.guide:
        raise HTTPException(status_code=502, detail="模型未产出风格指南")

    from datetime import datetime, timezone

    next_vn = vn.model_copy(deep=True)
    next_vn.styleMemory = {
        "guide": result.guide,
        "samples": result.samples,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    }
    next_vn.updatedAt = datetime.now(timezone.utc).isoformat()
    await sync_chapter_rows_from_vn(db, row, next_vn)
    await db.commit()
    await db.refresh(row)
    return {
        "project": project_to_dict(row_to_vn(row)),
        "guide": result.guide,
        "samples": result.samples,
        "model": result.model,
    }


@router.delete("/{project_id}/style-memory")
async def clear_style_memory_endpoint(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Forget the learned style guide."""
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    next_vn = vn.model_copy(deep=True)
    next_vn.styleMemory = None
    from datetime import datetime, timezone

    next_vn.updatedAt = datetime.now(timezone.utc).isoformat()
    await sync_chapter_rows_from_vn(db, row, next_vn)
    await db.commit()
    await db.refresh(row)
    return {"project": project_to_dict(row_to_vn(row))}

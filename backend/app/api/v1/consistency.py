from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.ai import DeepSeekConfig
from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services.projects import get_project_readable, resolve_llm_credentials, row_to_vn

router = APIRouter(prefix="/projects", tags=["consistency"])


class ConsistencyAuditIn(BaseModel):
    """Cross-chapter audit request. Empty focus = whole-novel default scan."""

    focus: str = Field(default="", max_length=300)
    chapter_id: Optional[str] = None


class ConsistencyIssueOut(BaseModel):
    category: str
    severity: str
    chapterIds: List[str] = Field(default_factory=list)
    quote: str = ""
    description: str
    suggestion: str = ""


class ConsistencyAuditOut(BaseModel):
    issues: List[ConsistencyIssueOut] = Field(default_factory=list)
    summary: str = ""
    scanned_chapters: int = 0
    model: str = ""
    error: Optional[str] = None


@router.post("/{project_id}/consistency/audit", response_model=ConsistencyAuditOut)
async def consistency_audit(
    project_id: str,
    body: ConsistencyAuditIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Scan the whole novel against the authoritative setting for conflicts."""
    from app.core.consistency_audit import run_consistency_audit

    row = await get_project_readable(db, user, project_id)
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
    result = await run_consistency_audit(
        config,
        vn,
        focus=body.focus,
        chapter_texts=None,
    )
    return ConsistencyAuditOut(
        issues=[
            ConsistencyIssueOut(
                category=i.category,
                severity=i.severity,
                chapterIds=i.chapterIds,
                quote=i.quote,
                description=i.description,
                suggestion=i.suggestion,
            )
            for i in result.issues
        ],
        summary=result.summary,
        scanned_chapters=result.scanned_chapters,
        model=result.model,
        error=result.error,
    )

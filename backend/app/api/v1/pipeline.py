"""Engineering writing pipeline API — style skill, ledger, plan/write/check/revise, gate."""
from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.ai import DeepSeekConfig
from app.core.harness.pipeline import audit_draft
from app.core.pipeline.gate import finalize_chapter, run_quality_gate
from app.core.pipeline.ledger import (
    digest_chapter_into_ledger,
    format_ledger_for_agent,
    get_ledger,
    set_ledger,
)
from app.core.pipeline.orchestrator import run_pipeline, stage_check
from app.core.pipeline.style_skill import (
    load_style_skill,
    merge_audit_with_style,
    style_skill_meta,
)
from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services.projects import (
    get_owned_project,
    project_to_dict,
    row_to_vn,
    server_llm_credentials,
    sync_row_from_vn,
)

router = APIRouter(tags=["pipeline"])


def _cfg(settings: Settings) -> DeepSeekConfig:
    creds = server_llm_credentials(settings)
    if not creds["api_key"]:
        raise HTTPException(status_code=400, detail="服务端未配置 DEEPSEEK_API_KEY")
    return DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )


class PipelineRunIn(BaseModel):
    instruction: str = ""
    draft: str = ""
    selection: str = ""
    chapter_id: Optional[str] = None
    stages: Optional[
        List[Literal["plan", "write", "check", "revise"]]
    ] = None


class GateIn(BaseModel):
    draft: str = ""
    chapter_id: Optional[str] = None
    require_zero_warn: bool = False
    finalize: bool = False
    update_ledger: bool = True


class LedgerDigestIn(BaseModel):
    chapter_id: str


@router.get("/pipeline/meta")
async def pipeline_meta():
    from app.core.mentors import default_active_ids, list_builtin_meta

    skill = load_style_skill()
    return {
        "layers": [
            "写作风格 Skill（Do NOTs / Do's / Structural Rules）",
            "写作导师包（方法论；不得推翻风格 Skill）",
            "长期记忆账本（章事实 / 角色状态 / 伏笔）",
            "生成-检查工作流（Plan→Write→Check→Revise）",
            "质量门禁（定稿前硬错误为零）",
        ],
        "styleSkill": style_skill_meta(),
        "styleConfirm": skill.confirm_preamble(),
        "mentors": {
            "builtin": list_builtin_meta(),
            "defaultActiveIds": default_active_ids(),
        },
        "defaultStages": ["plan", "write", "check", "revise", "check"],
    }


@router.get("/pipeline/style-guide")
async def pipeline_style_guide():
    skill = load_style_skill()
    return {"markdown": skill.raw, "meta": style_skill_meta()}


@router.post("/projects/{project_id}/pipeline/run")
async def pipeline_run(
    project_id: str,
    body: PipelineRunIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    cfg = _cfg(settings)
    stages = body.stages
    # If client sends one check only etc., honor it; else full loop with trailing check
    if stages is None:
        run_stages = ["plan", "write", "check", "revise", "check"]
    else:
        run_stages = list(stages)
    try:
        out = await run_pipeline(
            cfg,
            vn,
            instruction=body.instruction,
            chapter_id=body.chapter_id,
            selection=body.selection,
            draft=body.draft,
            stages=run_stages,
            db=db,
            project_id=project_id,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return out


@router.post("/projects/{project_id}/pipeline/check")
async def pipeline_check(
    project_id: str,
    body: GateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    draft = body.draft
    if not draft.strip() and body.chapter_id:
        row = await get_owned_project(db, user, project_id)
        vn = row_to_vn(row)
        from app.core.agent_context import _blocks_to_plain

        ch = next((c for c in vn.chapters if c.id == body.chapter_id), None)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        draft = _blocks_to_plain(ch.blocks, vn.characters) or ""
    if not draft.strip():
        raise HTTPException(status_code=400, detail="需要 draft 或 chapter_id")
    check = merge_audit_with_style(audit_draft(draft), draft)
    # stage_check already merges; use it for gateReady
    full = stage_check(draft)
    return full


@router.post("/projects/{project_id}/pipeline/gate")
async def pipeline_gate(
    project_id: str,
    body: GateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    if body.finalize:
        if not body.chapter_id:
            raise HTTPException(status_code=400, detail="定稿需要 chapter_id")
        try:
            result = finalize_chapter(
                vn,
                body.chapter_id,
                draft_override=body.draft or None,
                require_zero_warn=body.require_zero_warn,
                update_ledger=body.update_ledger,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if result["gate"].get("pass"):
            sync_row_from_vn(row, result["project"])
            await db.commit()
            await db.refresh(row)
            result["project"] = project_to_dict(row_to_vn(row))
        else:
            result["project"] = None
        return result

    draft = body.draft
    if not draft.strip() and body.chapter_id:
        from app.core.agent_context import _blocks_to_plain

        ch = next((c for c in vn.chapters if c.id == body.chapter_id), None)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        draft = _blocks_to_plain(ch.blocks, vn.characters) or ""
    if not draft.strip():
        raise HTTPException(status_code=400, detail="需要 draft 或 chapter_id")
    return run_quality_gate(draft, require_zero_warn=body.require_zero_warn)


@router.get("/projects/{project_id}/pipeline/ledger")
async def pipeline_ledger_get(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    ledger = get_ledger(vn)
    return {
        "ledger": ledger,
        "agentBlock": format_ledger_for_agent(ledger),
    }


@router.post("/projects/{project_id}/pipeline/ledger/digest")
async def pipeline_ledger_digest(
    project_id: str,
    body: LedgerDigestIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    try:
        ledger = digest_chapter_into_ledger(vn, body.chapter_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    vn2 = set_ledger(vn, ledger)
    sync_row_from_vn(row, vn2)
    await db.commit()
    await db.refresh(row)
    return {
        "ledger": ledger,
        "agentBlock": format_ledger_for_agent(ledger),
        "project": project_to_dict(row_to_vn(row)),
    }

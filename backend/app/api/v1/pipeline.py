"""Engineering writing pipeline API — style skill, ledger, plan/write/check/revise, gate."""
from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.ai import DeepSeekConfig
from app.core.pipeline.gate import (
    finalize_chapter_async,
    run_quality_gate_async,
)
from app.core.pipeline.ledger import (
    digest_chapter_into_ledger,
    format_ledger_for_agent,
    get_ledger,
    set_ledger,
)
from app.core.pipeline.orchestrator import run_pipeline, stage_check_async
from app.core.pipeline.run_history import list_harness_runs
from app.core.pipeline.style_skill import load_style_skill, style_skill_meta
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
    apply_to_chapter: bool = True
    apply_mode: Literal["replace", "append"] = "replace"
    max_revise_rounds: int = Field(default=2, ge=0, le=5)
    voice_check: bool = True
    voice_hard: bool = False
    semantic_beats: bool = True
    # When true, return { jobId } immediately and run in background
    async_mode: bool = False


class GateIn(BaseModel):
    draft: str = ""
    chapter_id: Optional[str] = None
    require_zero_warn: bool = False
    finalize: bool = False
    update_ledger: bool = True
    apply_draft: bool = True
    enrich_ledger: bool = True
    voice_check: bool = True
    voice_hard: bool = False
    semantic_beats: bool = True
    beat_sheet: Optional[dict] = None


class LedgerDigestIn(BaseModel):
    chapter_id: str
    enrich: bool = True


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
        "defaults": {
            "maxReviseRounds": 2,
            "voiceCheck": True,
            "semanticBeats": True,
            "enrichLedgerOnFinalize": True,
        },
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
    from app.core.usage import quota_exceeded

    if await quota_exceeded(db, user.id, settings.llm_daily_token_cap):
        raise HTTPException(status_code=429, detail="今日 LLM 用量已达上限，请明日再试")
    stages = body.stages
    if stages is None:
        run_stages = ["plan", "write", "check", "revise", "check"]
    else:
        run_stages = list(stages)

    if body.async_mode:
        from types import SimpleNamespace

        from app.core.jobs import create_job
        from app.db import AsyncSessionLocal

        payload = body.model_dump()
        owner = SimpleNamespace(id=user.id)

        async def _runner(job):
            await job.touch(stage="pipeline", progress=0.1, message="流水线运行中…")
            async with AsyncSessionLocal() as session:
                row2 = await get_owned_project(session, owner, project_id)
                vn2 = row_to_vn(row2)
                out = await run_pipeline(
                    cfg,
                    vn2,
                    instruction=payload.get("instruction") or "",
                    chapter_id=payload.get("chapter_id"),
                    selection=payload.get("selection") or "",
                    draft=payload.get("draft") or "",
                    stages=run_stages,
                    db=session,
                    project_id=project_id,
                    apply_to_chapter=bool(
                        payload.get("apply_to_chapter") and payload.get("chapter_id")
                    ),
                    apply_mode=payload.get("apply_mode") or "replace",
                    max_revise_rounds=int(payload.get("max_revise_rounds") or 2),
                    voice_check=bool(payload.get("voice_check", True)),
                    voice_hard=bool(payload.get("voice_hard", False)),
                    semantic_beats=bool(payload.get("semantic_beats", True)),
                )
                if out.get("project") is not None:
                    sync_row_from_vn(row2, out["project"])
                    await session.commit()
                    await session.refresh(row2)
                    out["project"] = project_to_dict(row_to_vn(row2))
                await job.set_result(out)
                await job.touch(
                    stage="done",
                    progress=0.95,
                    message="流水线完成" if out.get("gate", {}).get("pass") else "流水线结束（门禁未过）",
                )

        job = await create_job(
            db,
            kind="pipeline",
            project_id=project_id,
            user_id=user.id,
            runner=_runner,
        )
        return {"jobId": job.id, "async": True, "status": job.status}

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
            apply_to_chapter=body.apply_to_chapter and bool(body.chapter_id),
            apply_mode=body.apply_mode,
            max_revise_rounds=body.max_revise_rounds,
            voice_check=body.voice_check,
            voice_hard=body.voice_hard,
            semantic_beats=body.semantic_beats,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if out.get("project") is not None:
        sync_row_from_vn(row, out["project"])
        await db.commit()
        await db.refresh(row)
        out["project"] = project_to_dict(row_to_vn(row))
    return out


@router.get("/projects/{project_id}/jobs/{job_id}")
async def project_job_status(
    project_id: str,
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    from app.core.jobs import get_job

    job = await get_job(db, job_id)
    if not job or job.project_id != project_id or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job.to_dict(include_result=job.status in ("done", "error"))


@router.post("/projects/{project_id}/pipeline/check")
async def pipeline_check(
    project_id: str,
    body: GateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    draft = body.draft
    if not draft.strip() and body.chapter_id:
        from app.core.agent_context import _blocks_to_plain

        ch = next((c for c in vn.chapters if c.id == body.chapter_id), None)
        if not ch:
            raise HTTPException(status_code=404, detail="章节不存在")
        draft = _blocks_to_plain(ch.blocks, vn.characters) or ""
    if not draft.strip():
        raise HTTPException(status_code=400, detail="需要 draft 或 chapter_id")
    cfg = None
    try:
        cfg = _cfg(settings)
    except HTTPException:
        pass
    return await stage_check_async(
        draft,
        cfg=cfg,
        beat_sheet=body.beat_sheet,
        semantic_beats=body.semantic_beats and cfg is not None,
        project=vn,
        chapter_id=body.chapter_id,
        voice_check=body.voice_check and cfg is not None,
        voice_hard=body.voice_hard,
    )


@router.post("/projects/{project_id}/pipeline/gate")
async def pipeline_gate(
    project_id: str,
    body: GateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    cfg = None
    try:
        cfg = _cfg(settings)
    except HTTPException:
        pass

    if body.finalize:
        if not body.chapter_id:
            raise HTTPException(status_code=400, detail="定稿需要 chapter_id")
        try:
            result = await finalize_chapter_async(
                vn,
                body.chapter_id,
                cfg=cfg,
                draft_override=body.draft or None,
                require_zero_warn=body.require_zero_warn,
                update_ledger=body.update_ledger,
                apply_draft=body.apply_draft,
                enrich_ledger=body.enrich_ledger,
                beat_sheet=body.beat_sheet,
                semantic_beats=body.semantic_beats,
                voice_check=body.voice_check,
                voice_hard=body.voice_hard,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        # Always persist harnessRuns; chapter apply only when gate passes
        if result.get("project") is not None:
            sync_row_from_vn(row, result["project"])
            await db.commit()
            await db.refresh(row)
            result["project"] = project_to_dict(row_to_vn(row))
        if not result["gate"].get("pass"):
            # still return stamped project with failed qualityGate / run history
            pass
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
    return await run_quality_gate_async(
        draft,
        cfg=cfg,
        beat_sheet=body.beat_sheet,
        require_zero_warn=body.require_zero_warn,
        semantic_beats=body.semantic_beats,
        project=vn,
        chapter_id=body.chapter_id,
        voice_check=body.voice_check,
        voice_hard=body.voice_hard,
    )


@router.get("/projects/{project_id}/pipeline/runs")
async def pipeline_runs_list(
    project_id: str,
    limit: int = 12,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    return {"runs": list_harness_runs(vn, limit=min(max(limit, 1), 24))}


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
    settings: Settings = Depends(get_settings),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    enrich_meta: dict = {"enrich": False, "error": None}
    kwargs = {}
    if body.enrich:
        from app.core.pipeline.ledger_enrich import enrich_chapter_ledger_payload

        try:
            cfg = _cfg(settings)
            payload = await enrich_chapter_ledger_payload(cfg, vn, body.chapter_id)
            kwargs = {
                "llm_facts": payload.get("llm_facts"),
                "llm_states": payload.get("llm_states"),
                "llm_foreshadows": payload.get("llm_foreshadows"),
            }
            enrich_meta = {
                "enrich": True,
                "factCount": len(payload.get("llm_facts") or []),
                "stateCount": len(payload.get("llm_states") or []),
                "foreshadowCount": len(payload.get("llm_foreshadows") or []),
                "error": None,
            }
        except (RuntimeError, ValueError, HTTPException) as e:
            enrich_meta = {"enrich": False, "error": str(getattr(e, "detail", e))}
    try:
        ledger = digest_chapter_into_ledger(vn, body.chapter_id, **kwargs)
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
        "enrichMeta": enrich_meta,
    }

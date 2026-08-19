"""Harness HTTP API — audit + Architect/Writer/Editor runs."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.ai import DeepSeekConfig
from app.core.harness import (
    ROLE_PROMPTS,
    build_writer_user_prompt,
    harness_editor_pass,
    run_harness_llm,
)
from app.core.harness.roles import otaku_skill_bodies
from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services.novel_memory import get_latest_continuity
from app.services.projects import (
    get_owned_project,
    resolve_llm_credentials,
    row_to_vn,
)

router = APIRouter(tags=["harness"])


class HarnessLintIn(BaseModel):
    draft: str = Field(min_length=1)


class HarnessRunIn(BaseModel):
    role: Literal["architect", "writer", "editor"] = "writer"
    instruction: str = ""
    draft: str = ""
    selection: str = ""
    chapter_id: Optional[str] = None
    # editor: lint+LLM; writer/architect: generation
    mode: Literal["generate", "audit", "audit_and_fix"] = "generate"


async def _cfg(settings: Settings, db: AsyncSession, user_id: str) -> DeepSeekConfig:
    creds = await resolve_llm_credentials(db, user_id, settings)
    if not creds["api_key"]:
        raise HTTPException(
            status_code=400,
            detail="服务端未配置 DEEPSEEK_API_KEY",
        )
    from app.core.usage import ensure_under_quota

    await ensure_under_quota(db, user_id, settings, creds)
    return DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )


@router.get("/harness/meta")
async def harness_meta():
    """Harness catalogue — LN/VN, de-AI, otaku craft."""
    return {
        "roles": list(ROLE_PROMPTS.keys()),
        "goals": [
            "辅助轻小说 / 视觉小说文本",
            "去 AI 味（纠偏句、叠喻梯、电报对白、套话）",
            "深耕二次元文化（类型落地为戏，拒绝标签念经）",
        ],
        "otakuSkills": otaku_skill_bodies(),
    }


@router.post("/projects/{project_id}/harness/lint")
async def harness_lint(
    project_id: str,
    body: HarnessLintIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    from app.core.harness.audit_full import full_audit_draft

    return full_audit_draft(body.draft)


@router.post("/projects/{project_id}/harness/run")
async def harness_run(
    project_id: str,
    body: HarnessRunIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    from app.core.rate_limit import require_rate

    require_rate(
        user.id,
        "harness_run",
        120,
        enabled=settings.rate_limit_enabled,
        window=3600,
        detail="Harness 调用过于频繁，请稍后再试",
    )
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    cfg = await _cfg(settings, db, user.id)

    if body.mode == "audit" or (
        body.role == "editor" and body.mode == "generate" and body.draft
    ):
        if not body.draft.strip():
            raise HTTPException(status_code=400, detail="audit 需要 draft")
        if body.mode == "audit":
            from app.core.harness.audit_full import full_audit_draft

            return {"role": "editor", **full_audit_draft(body.draft)}
        return await harness_editor_pass(cfg, body.draft, project=vn)

    if body.mode == "audit_and_fix":
        if not body.draft.strip():
            raise HTTPException(status_code=400, detail="需要 draft")
        return await harness_editor_pass(cfg, body.draft, project=vn)

    # generate
    chapter_tail = ""
    if body.chapter_id:
        ch = next((c for c in vn.chapters if c.id == body.chapter_id), None)
        if ch:
            # plain-ish tail from raw export of last blocks
            from app.core.agent_context import _blocks_to_plain

            plain = _blocks_to_plain(ch.blocks, vn.characters)
            chapter_tail = plain[-1200:] if plain else ""

    mem = await get_latest_continuity(db, project_id)
    long_mem = (mem or {}).get("agentBlock") or ""

    from app.services.lore import resolve_lore_block

    lore = await resolve_lore_block(
        db,
        project_id,
        vn,
        user_message=body.instruction or body.selection or "",
        limit=3,
    )
    lore_block = lore.get("agentBlock") or ""

    if body.role == "writer":
        prompt = build_writer_user_prompt(
            body.instruction or "续写下一小段，去AI味，二次元语感落地。",
            selection=body.selection,
            chapter_tail=chapter_tail,
            long_memory=long_mem,
            lore_craft=lore_block,
        )
    elif body.role == "architect":
        prompt = body.instruction or (
            "基于当前工程设定，给出架构师确认清单与下一阶段建议（条目制）。"
        )
        if body.draft:
            prompt += f"\n\n用户素材：\n{body.draft[:6000]}"
    else:
        prompt = body.instruction or "请责编审稿。"
        if body.draft:
            prompt += f"\n\n原文：\n{body.draft[:8000]}"

    result = await run_harness_llm(
        cfg,
        role=body.role,
        user_prompt=prompt,
        project=vn,
        temperature=0.55 if body.role == "editor" else 0.75,
    )
    pre = None
    if body.draft.strip():
        from app.core.harness.audit_full import full_audit_draft

        pre = full_audit_draft(body.draft)
    return {**result, "preAudit": pre}

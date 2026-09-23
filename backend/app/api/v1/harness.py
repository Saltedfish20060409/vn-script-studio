"""Harness HTTP API — 确定性体检 + 模型目录。

历史说明：这里原本还有 `POST /projects/{id}/harness/run`（角色 architect/writer/editor ×
模式 generate/audit/audit_and_fix）。它已经被更好的路径取代，而且**在仓库里没有任何消费者**
（前端、CLI、测试都不调用它），所以删掉了。能力一件没少，只是搬到了真正会被用到的地方：

- **生成**：Agent（带工具、账本、检索、手艺提示）与 `/projects/{id}/ai`（CLI 在用）；
- **确定性体检**：本文件的 `/harness/lint`，以及 Agent 的 `lint_draft` 工具；
- **编辑润色**（原 editor 角色）：Agent 工具 `polish_prose`（见 `app/core/agent_tools.py`）——
  它同样先跑确定性体检、体检全过时不调模型（省 token）。

删它的理由不只是"没人用"：一个能直接生成正文的 HTTP 端点会绕开 Agent 的检索/账本/工艺链路，
留着就是第二条容易走歪的生成路径。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.harness import ROLE_PROMPTS
from app.core.harness.roles import otaku_skill_bodies
from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services.projects import get_owned_project

router = APIRouter(tags=["harness"])


class HarnessLintIn(BaseModel):
    draft: str = Field(min_length=1)


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

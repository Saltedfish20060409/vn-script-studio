"""读者/玩家行为建模 API —— 试玩选择的采集、开关与行为分析。

路径与既有风格一致（``/projects/{project_id}/...``，与 collab / marks 同构）。

鉴权边界（重要取舍）
------------------
- ``record`` / ``analytics`` / ``settings`` 读：要求调用者是工程 owner / editor /
  **viewer**（``get_project_readable``）。也就是说当前**只有工程成员**能上报试玩。
  读者从分享链接（``/shares/{token}``）匿名进入的那条路径**故意没有接**：只凭
  project_id 就允许匿名写，任何拿到工程 id 的人都能量产假数据、把行为分析污染成
  噪声。分享 token → 匿名上报是后续工作（需要 token 校验 + 更严的限流），现在不做。
- ``settings`` 写：要求 owner / editor（``get_owned_project``），viewer 只读。
- 落库的行里**没有 user_id**：一次试玩只对应客户端随机生成的 ``client_run_id``，
  所以即便调用者已登录，库里也查不到"是谁在玩"。

隐私
----
- 默认关闭：工程没显式开启遥测时 record 直接 **403 且不落任何行**（理由见
  ``app/services/playtest_telemetry.py``）。
- 字段白名单 + ASCII 标识符白名单：未知字段（例如有人塞 ``text``）被丢弃并回显字段名，
  文案类字符串在净化阶段就没了。响应里也不含任何选项文案。
- 不记 IP / UA / 指纹；限流用的是登录用户 id，不落库。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.rate_limit import check_rate
from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services import playtest_telemetry as telemetry
from app.services.projects import get_owned_project, get_project_readable, row_to_vn

router = APIRouter(prefix="/projects", tags=["playtest"])

_RECORD_LIMIT_PER_HOUR = 300


class RecordIn(BaseModel):
    """一次试玩的上报体（信封层）。

    ``run`` 与 ``choices`` 的元素刻意声明成自由 dict / Any，而不是逐字段的模型：
    试玩上报是**读者侧**的弱信任输入，"某一个子字段类型不对"不应该让整批 2000 条
    选择以 422 退回。所以信封只保证"结构是对象 + 条数有上限"，每个字段的类型强转与
    白名单全部交给 ``app/services/playtest_telemetry.sanitize_*``（那一层是纯函数，
    可单测；``extra="allow"`` 让未知字段也能被看见、被计数、被丢弃）。
    """

    model_config = ConfigDict(extra="allow")

    run: Dict[str, Any] = Field(default_factory=dict)
    choices: List[Any] = Field(default_factory=list, max_length=telemetry.MAX_CHOICES_PER_RUN)


class TelemetrySettingsIn(BaseModel):
    enabled: bool


@router.post("/{project_id}/playtest/record")
async def playtest_record(
    project_id: str,
    body: RecordIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Dict[str, Any]:
    """批量上报一次试玩：运行信息 + 选择序列。

    幂等：``(project_id, client_run_id)`` 唯一，重复上报只补缺失的 seq。
    未开启遥测 → 403，且一行都不落。
    """
    if not check_rate(
        user.id,
        "playtest_record",
        limit=_RECORD_LIMIT_PER_HOUR,
        enabled=settings.rate_limit_enabled,
        window=3600,
    ):
        raise HTTPException(status_code=429, detail="上报过于频繁")

    row = await get_project_readable(db, user, project_id)
    result = await telemetry.record_playtest(db, project_id=row.id, payload=body.model_dump())
    # 信封层的未知字段也算"被丢弃"，一并回显，方便前端自查
    extra = telemetry.dropped_field_names(body.model_extra or {})
    if extra:
        merged = list(result["droppedFields"])
        for name in extra:
            if name not in merged:
                merged.append(name)
        result["droppedFields"] = merged
    return result


@router.get("/{project_id}/playtest/settings")
async def playtest_get_settings(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """读采集开关。没有设置行 = 关闭（默认关闭），这里把默认口径明示给前端。"""
    row = await get_project_readable(db, user, project_id)
    return {
        "projectId": row.id,
        "enabled": await telemetry.get_telemetry_enabled(db, row.id),
        "defaultEnabled": False,
    }


@router.put("/{project_id}/playtest/settings")
async def playtest_put_settings(
    project_id: str,
    body: TelemetrySettingsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """写采集开关（需工程写权限：owner / editor；viewer 403，非成员 404）。"""
    row = await get_owned_project(db, user, project_id)
    enabled = await telemetry.set_telemetry_enabled(db, row.id, body.enabled)
    return {"projectId": row.id, "enabled": enabled}


@router.get("/{project_id}/playtest/analytics")
async def playtest_analytics(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """读者行为分析：选项占比 / 章级漏斗 / 结局分布与对账 / 运行统计 / 读者侧覆盖率。

    与 ``/analysis/branch-report`` 的分工：那边回答"剧本**写成了**什么样"（静态推理），
    这边回答"玩家**实际怎么玩**"（动态观测），两者用同一套 menu_id / label / 结局登记
    对齐，所以"哪些选项从没被选""哪个结局没人走到"才能对得上账。
    """
    from app.core.branch_analysis import analyze_branches

    row = await get_project_readable(db, user, project_id)
    project = row_to_vn(row)
    # 与 projects.py 的 analysis 端点同样直接同步调用（纯本地静态分析，不调模型）
    branch = analyze_branches(project)
    chapter_order = [str(getattr(ch, "id", "") or "") for ch in (project.chapters or [])]
    return await telemetry.load_reader_analytics(
        db, row.id, branch=branch, chapter_order=chapter_order
    )


@router.get("/{project_id}/playtest/recommendations")
async def playtest_recommendations(
    project_id: str,
    min_runs: int = 10,
    include_readers: bool = True,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """分支改进建议：把静态结构分析与读者实际行为**融成可执行的改稿建议**。

    为什么需要融合：单看任何一边都只是事实，作者要的是"该怎么办"。
    典型例子——某个选项条件可满足、路径可达（静态没问题），但 12 次试玩里 0 次被选：
    只看读者数据只能说"没人选"，只有配上静态结构才知道改法完全不同——
    如果它和其它选项**后果相同**，就该删掉；如果它只是**文案不吸引人**，就该改文案。

    ``min_runs`` 是经验判断的门槛：低于它只出静态建议，并在 ``basis`` / ``sampleNote``
    里如实说明"不是没问题，是还看不出来"。``include_readers=false`` 可强制只看静态。
    """
    from app.core.branch_analysis import analyze_branches
    from app.core.branch_recommendations import recommend_branch_improvements

    row = await get_project_readable(db, user, project_id)
    project = row_to_vn(row)
    branch = analyze_branches(project)
    analytics: Optional[Dict[str, Any]] = None
    if include_readers:
        chapter_order = [str(getattr(ch, "id", "") or "") for ch in (project.chapters or [])]
        analytics = await telemetry.load_reader_analytics(
            db, row.id, branch=branch, chapter_order=chapter_order
        )
    return recommend_branch_improvements(
        project,
        branch=branch,
        analytics=analytics,
        min_runs=max(1, min(int(min_runs), 10_000)),
    )

"""删号：把一个账号及其名下数据从库里彻底抹掉（不可恢复）。

由 `DELETE /api/v1/auth/me` 调用。分层取舍写在这里，免得以后有人"顺手"改坏：

- **一次事务**：中途失败整体回滚，不会留下「项目删了、账号还在」的半截状态。
- **交给数据库级联的**：`projects`（→ 章节行、成员、批注、锁、快照、分享、
  记忆档案与切片、作业、用量、试玩遥测等全部子表）、`user_settings`、
  `auth_email_tokens`、`product_events` 都是 ON DELETE CASCADE；
  `error_reports` 是 SET NULL —— 错误报告要留在库里做诊断，只脱敏作者。
  这几条外键的行为见迁移 `0032_account_delete_cascade`。
- **必须显式清理的**：`agent_jobs` / `llm_usage` / `project_members` /
  `chapter_locks` / `project_comments` 的 `user_id` 以及 `project_invites.created_by`
  都是**没有外键的软引用**。不清理的话，界面上会出现"作者/成员不存在"的幽灵行
  （批注、成员列表、作业记录），而且他人项目的成员表会一直挂着一个已删账号。
- **别人的回复不陪葬**：本人在项目里留下的批注随号删除（那是他的内容），但**别人**
  挂在这些批注下面的回复会被提升为顶层批注，而不是跟着 `parent_id` 的 CASCADE 一起
  消失 —— 删号不该顺手销毁第三方的写作痕迹。
- **管理员的弹药库**：最后一位管理员不允许自删，判定在端点里做（见 auth.py），
  否则站点会失去唯一的管理入口。
"""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentJob,
    ChapterLock,
    LlmUsage,
    ProjectComment,
    ProjectInvite,
    ProjectMember,
    User,
)


async def delete_account(db: AsyncSession, user: User) -> None:
    """删除 ``user`` 及其名下全部数据，并在同一个事务里提交。"""
    uid = user.id

    # 别人的回复先摘下来（提升为顶层），否则删本批注时会连带删掉它们。
    mine = (
        await db.execute(select(ProjectComment.id).where(ProjectComment.user_id == uid))
    ).scalars().all()
    if mine:
        await db.execute(
            update(ProjectComment)
            .where(ProjectComment.parent_id.in_(list(mine)))
            .values(parent_id=None)
        )
    await db.execute(delete(ProjectComment).where(ProjectComment.user_id == uid))

    # 无外键的软引用：属于这个人的行直接删，只是留了个 ID 的字段抹成空串。
    await db.execute(delete(ProjectMember).where(ProjectMember.user_id == uid))
    await db.execute(delete(ChapterLock).where(ChapterLock.user_id == uid))
    await db.execute(delete(AgentJob).where(AgentJob.user_id == uid))
    await db.execute(delete(LlmUsage).where(LlmUsage.user_id == uid))
    await db.execute(
        update(ProjectInvite)
        .where(ProjectInvite.created_by == uid)
        .values(created_by="")
    )

    # Core DELETE：不能走 `db.delete(user)` —— User.projects 关系没配 cascade /
    # passive_deletes，ORM 会先试着把 projects.owner_id 置 NULL（非空列，直接报错）。
    # 交给数据库按 0032 的外键级联处理才是正确路径。
    await db.execute(delete(User).where(User.id == uid))
    await db.commit()

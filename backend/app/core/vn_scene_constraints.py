"""可演场景硬约束：假选择 / 选项代价 / 地点一致性 — 写时注入，而非只事后 lint。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.domain.types import VnProject

#: 始终注入写路径的短硬约束（与 write_gate 假选择判定对齐）
STAGEABLE_HARD_RULES = """## 可演场景硬约束（VN/轻小说）
- 对白一行一句 + 短旁白；括号写动作，不要说明书导览腔。
- 若写选择：选项须有**不同剧情代价**；禁止「全是整齐解释」的假选择；至少保留一条犹豫/沉默/说不清的毛边。
- 出场角色须与账本状态一致（已故/不在场者不得无故说话）。
- 地点：不要引入未设定且无法从上下文推断的新场景标签。
- 本场推进至少一个可感知变化（关系/信息/危机），避免空转寒暄。"""


def focus_menu_findings(project: VnProject, chapter_id: Optional[str]) -> List[str]:
    """若焦点章脚本里已有无后果菜单，写前提醒。"""
    cid = (chapter_id or "").strip()
    if not cid:
        return []
    try:
        from app.core.branch_analysis import analyze_branches

        report = analyze_branches(project)
    except Exception:  # noqa: BLE001
        return []
    out: List[str] = []
    for f in report.get("findings") or []:
        if not isinstance(f, dict):
            continue
        code = str(f.get("code") or "")
        if code not in {"menu_no_effect", "choice_never_available", "choice_never_traversed"}:
            continue
        # 尽量用 chapter 字段过滤
        fcid = str(f.get("chapterId") or f.get("chapter") or "")
        if fcid and fcid != cid:
            continue
        msg = str(f.get("message") or f.get("title") or code)
        out.append(f"{code}: {msg}")
        if len(out) >= 4:
            break
    return out


def format_vn_scene_constraints_block(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
) -> str:
    parts = [STAGEABLE_HARD_RULES]
    findings = focus_menu_findings(project, chapter_id)
    if findings:
        parts.append("### 本场脚本已检出的分支隐患（续写时勿再加重）")
        parts.extend(f"- {x}" for x in findings)
    return "\n".join(parts)


def scene_constraints_meta(project: VnProject, chapter_id: Optional[str]) -> Dict[str, Any]:
    findings = focus_menu_findings(project, chapter_id)
    return {"menuFindingCount": len(findings), "codes": [f.split(":", 1)[0] for f in findings]}

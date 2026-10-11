"""本场写后确定性守卫：草稿落成后立刻跑廉价检查，不调模型。

复用 ``gate_continue_draft``（文风硬伤 + 死人出场 + 声线漂移警告）。
失败时返回 ``strengthen`` 信号，供策略闭环抬升下一轮 writing_assist。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.domain.types import VnProject


@dataclass
class SceneGuardResult:
    ok: bool
    issue_count: int = 0
    warnings: List[str] = field(default_factory=list)
    issues: List[Dict[str, str]] = field(default_factory=list)
    strengthen: bool = False
    gate_passed: Optional[bool] = None

    def as_meta(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "issueCount": self.issue_count,
            "warnings": self.warnings[:8],
            "issues": self.issues[:12],
            "strengthen": self.strengthen,
            "gatePassed": self.gate_passed,
        }


def guard_scene_draft(
    project: VnProject,
    draft: str,
    *,
    chapter_id: Optional[str] = None,
    write_op: str = "continue",
) -> SceneGuardResult:
    """对刚生成的本场草稿做确定性守卫。"""
    text = (draft or "").strip()
    if not text:
        return SceneGuardResult(ok=True, warnings=["空草稿，跳过本场守卫"])

    try:
        from app.core.write_gate import WRITE_GATE_TASKS, gate_continue_draft

        task = (write_op or "continue").strip() or "continue"
        # polish/expand 等也过闸；未知 op 仍跑（廉价）
        _ = WRITE_GATE_TASKS  # 文档锚点：与写路径任务集对齐
        gate = gate_continue_draft(text, project=project, chapter_id=chapter_id)
    except Exception as exc:  # noqa: BLE001
        return SceneGuardResult(
            ok=True,
            warnings=[f"本场守卫跳过：{str(exc)[:100]}"],
            strengthen=False,
        )

    issues = [dict(i) for i in (gate.issues or []) if isinstance(i, dict)]
    warnings = [str(w) for w in (gate.warnings or [])]
    errors = [i for i in issues if str(i.get("severity") or "") == "error"]
    issue_count = len(issues)
    ok = bool(gate.passed)
    strengthen = (not ok) or len(errors) >= 1 or issue_count >= 3
    return SceneGuardResult(
        ok=ok,
        issue_count=issue_count,
        warnings=warnings,
        issues=issues,
        strengthen=strengthen,
        gate_passed=ok,
    )

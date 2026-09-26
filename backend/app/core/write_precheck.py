"""续写前跨章廉价对账：只读账本 + 连续性子集，不调模型。

红了先提示再写——解决的是"账本里已死的人又出场 / 伏笔埋了很久 / 废弃地点仍出现 /
场景图无地点认领"这类可证伪缺口，不是文学判断。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.pipeline.ledger import foreshadow_report, get_ledger
from app.domain.types import VnProject

#: 账本身/情字段里表示"已不在场"的廉价标记
_DEAD_RE = re.compile(r"死|身亡|已故|阵亡|遇害|牺牲|去世|毙命|亡故|永眠")
#: 地点描述里表示"不该再去"的标记
_LOC_GONE_RE = re.compile(r"已毁|废弃|不存在|倒塌|焚毁|封死|禁止进入")
#: 未回收伏笔埋了至少这么多章才提醒（太短会吵）
_FORESHADOW_AGE_WARN = 3
_MAX_WARNINGS = 8
#: 续写前从连续性体检里捞出的、与本场相关的码
_CONTINUITY_FOCUS_CODES = frozenset({"unknown_location_tag", "death_then_speaks"})


@dataclass
class PrecheckIssue:
    code: str
    severity: str  # warn | error
    message: str
    #: 可选：相关角色名 / 钩子原文，便于前端跳转
    subject: str = ""


@dataclass
class PrecheckReport:
    issues: List[PrecheckIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def warnings(self) -> List[str]:
        return [i.message for i in self.issues[:_MAX_WARNINGS]]

    def as_meta(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "issueCount": len(self.issues),
            "issues": [
                {
                    "code": i.code,
                    "severity": i.severity,
                    "message": i.message,
                    "subject": i.subject,
                }
                for i in self.issues[:_MAX_WARNINGS]
            ],
        }

    def as_context_block(self) -> str:
        if not self.issues:
            return ""
        lines = ["\n## 续写前对账（账本确定性；红了先看再写）"]
        for i in self.issues[:_MAX_WARNINGS]:
            tag = "⚠" if i.severity == "warn" else "✖"
            lines.append(f"- {tag} {i.message}")
        return "\n".join(lines)


def _latest_states_by_name(ledger: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """同一角色保留最新一条状态快照（列表后写覆盖先写）。"""
    out: Dict[str, Dict[str, Any]] = {}
    for s in ledger.get("characterStates") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("characterName") or "").strip()
        if not name:
            continue
        out[name] = s
    return out


def _looks_dead(state: Dict[str, Any]) -> bool:
    blob = " ".join(
        str(state.get(k) or "") for k in ("body", "emotion", "relations")
    )
    return bool(_DEAD_RE.search(blob))


def _gone_locations_in_text(project: VnProject, haystack: str) -> List[PrecheckIssue]:
    """设定里已标废弃/已毁的地点若仍出现在焦点章/本稿 → warn。"""
    out: List[PrecheckIssue] = []
    if not haystack.strip():
        return out
    for loc in project.locations or []:
        name = str(getattr(loc, "name", "") or "").strip()
        if len(name) < 2 or name not in haystack:
            continue
        blob = " ".join(
            [
                str(getattr(loc, "description", "") or ""),
                " ".join(str(t) for t in (getattr(loc, "tags", None) or [])),
            ]
        )
        if not _LOC_GONE_RE.search(blob):
            continue
        out.append(
            PrecheckIssue(
                code="gone_location_present",
                severity="warn",
                message=(
                    f"地点「{name}」在设定里已标废弃/已毁等，但当前章或本稿仍出现该地名。"
                ),
                subject=name,
            )
        )
    return out


def _continuity_focus_issues(
    project: VnProject, chapter_id: Optional[str]
) -> List[PrecheckIssue]:
    """复用 continuity_graph：只捞与焦点章相关的地点图 / 死人说话。"""
    if not chapter_id:
        return []
    try:
        from app.core.continuity_graph import analyze_continuity
    except Exception:
        return []
    report = analyze_continuity(project)
    out: List[PrecheckIssue] = []
    for f in report.get("findings") or []:
        if not isinstance(f, dict):
            continue
        code = str(f.get("code") or "")
        if code not in _CONTINUITY_FOCUS_CODES:
            continue
        cid = str(f.get("chapterId") or "")
        if cid and cid != chapter_id:
            continue
        msg = str(f.get("message") or "").strip()
        if not msg:
            continue
        sev = str(f.get("severity") or "warn")
        # 续写前对账：连续性的 error 也降成 warn（提示不挡落地）
        if sev == "error":
            sev = "warn"
        out.append(
            PrecheckIssue(
                code=code,
                severity=sev,
                message=msg[:200],
                subject=str(f.get("label") or "")[:40],
            )
        )
        if len(out) >= 4:
            break
    return out


def precheck_before_continue(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    draft: str = "",
) -> PrecheckReport:
    """续写前 / 写后均可调用。

    - 账本记为已故的角色若在焦点章或本稿出现 → error
    - 未回收伏笔 age ≥ 阈值 → warn
    - 废弃地点仍出现 / 焦点章场景图无地点认领 / 死人说话 → warn
    """
    issues: List[PrecheckIssue] = []
    ledger = get_ledger(project)
    chapters = list(project.chapters or [])
    focus = next(
        (c for c in chapters if str(getattr(c, "id", "")) == (chapter_id or "")),
        chapters[0] if chapters else None,
    )
    focus_id = (
        str(getattr(focus, "id", "") or "") if focus is not None else (chapter_id or "")
    )
    focus_plain = ""
    if focus is not None:
        from app.core.agent_context import chapter_plain

        focus_plain = chapter_plain(focus, project.characters)
    haystack = f"{focus_plain}\n{draft or ''}"

    for name, state in _latest_states_by_name(ledger).items():
        if not _looks_dead(state):
            continue
        if name and name in haystack:
            ch_title = str(state.get("chapterTitle") or state.get("chapterId") or "")
            issues.append(
                PrecheckIssue(
                    code="dead_character_present",
                    severity="error",
                    message=(
                        f"账本记「{name}」已故/不在场"
                        + (f"（@{ch_title}）" if ch_title else "")
                        + "，但当前章或本稿仍出现该名。"
                    ),
                    subject=name,
                )
            )

    for fo in foreshadow_report(project):
        if str(fo.get("status") or "") == "paid":
            continue
        age = fo.get("ageChapters")
        if age is None or int(age) < _FORESHADOW_AGE_WARN:
            continue
        hook = str(fo.get("hook") or "").strip() or "（未命名钩子）"
        planted = str(fo.get("plantedChapterTitle") or fo.get("plantedChapter") or "")
        issues.append(
            PrecheckIssue(
                code="foreshadow_stale",
                severity="warn",
                message=(
                    f"伏笔「{hook[:40]}」已埋 {int(age)} 章未回收"
                    + (f"（自「{planted}」）" if planted else "")
                    + "。"
                ),
                subject=hook[:40],
            )
        )

    issues.extend(_gone_locations_in_text(project, haystack))
    issues.extend(_continuity_focus_issues(project, focus_id or None))

    return PrecheckReport(issues=issues[:_MAX_WARNINGS])

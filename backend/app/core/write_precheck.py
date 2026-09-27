"""续写前跨章廉价对账：只读账本 + 连续性子集，不调模型。

红了先提示再写——解决的是"账本里已死的人又出场 / 伏笔埋了很久 / 废弃地点仍出现 /
场景图无地点认领"这类可证伪缺口，不是文学判断。

## 两组，刻意分开

1. **事实级**（`PrecheckReport.issues`）：账本 / 连续性对不上。是"这一轮绝不能写错"的东西，
   进 `ok`，占 `_MAX_WARNINGS` 配额，排在上下文头部（`_SECTION_ORDER` 的 `precheck`）。
2. **文风级**（`PrecheckReport.prose`）：焦点章**已有正文**自身的确定性硬伤
   （`full_audit_draft`：AI 味 / 套话 / 神谕腔 / 说明书硬伤…）。进续写前视野是为了
   "别把上一段的毛病顺着写下去"。

**为什么不合成一组**：文风级的条目多、每次都可能不同，混进同一个列表会把
`dead_character_present` 这类事实级对账挤出配额——那正是 `agent_context._SECTION_ORDER`
当初修过的同一类回归（参考文档占住头部、把角色/关系挤进被压缩的中段）。所以两组各有
自己的列表、配额与表头，且文风级**不参与 `ok`、不挡任何东西**。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.core.pipeline.ledger import foreshadow_report, get_ledger
from app.domain.types import VnProject

#: 账本身/情字段里表示"已不在场"的廉价标记
_DEAD_RE = re.compile(r"死|身亡|已故|阵亡|遇害|牺牲|去世|毙命|亡故|永眠")
#: 地点描述里表示"不该再去"的标记
_LOC_GONE_RE = re.compile(r"已毁|废弃|不存在|倒塌|焚毁|封死|禁止进入")
#: 未回收伏笔埋了至少这么多章才提醒（太短会吵）
_FORESHADOW_AGE_WARN = 3
_MAX_WARNINGS = 8
#: 焦点章文风体检最多报几条。**独立配额**：不与事实级的 `_MAX_WARNINGS` 抢位置
#: （文风抱怨把"死人对账"挤掉，正是 `_SECTION_ORDER` 当初修过的同一类回归）。
_MAX_PROSE_WARNINGS = 4
#: 单条文风提示截多长进上下文：`full_audit_draft` 的消息常带多处例子，进头部要克制
_PROSE_MSG_MAX = 120
#: 严重度排序（error 先报；同级保持体检给出的顺序 → 同样正文永远同样输出）
_SEVERITY_RANK = {"error": 0, "warn": 1, "info": 2}
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
    #: 事实级：账本 / 连续性对不上。进 `ok`，会挡写后闸（见 `write_gate`）。
    issues: List[PrecheckIssue] = field(default_factory=list)
    #: 文风级：焦点章已有正文自身的确定性硬伤。**与 `issues` 分开**——不进 `ok`、
    #: 不占事实级配额、独立表头（理由见模块 docstring）。
    prose: List[PrecheckIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # 只看事实级：文风硬伤不是"这轮能不能写"的条件
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
            "proseCount": len(self.prose),
            "prose": [
                {"code": i.code, "message": i.message} for i in self.prose
            ],
        }

    def as_context_block(self) -> str:
        if not self.issues and not self.prose:
            return ""
        lines: List[str] = []
        if self.issues:
            lines.append("\n## 续写前对账（账本确定性；红了先看再写）")
            for i in self.issues[:_MAX_WARNINGS]:
                tag = "⚠" if i.severity == "warn" else "✖"
                lines.append(f"- {tag} {i.message}")
        if self.prose:
            # 单独一块、单独表头：这一组是"焦点章正文本来就带的硬伤"，
            # 既不是账本事实对不上，也不是对模型刚写那句话的评价。
            # 因此不打 ✖ 标记（它不挡任何东西），也不与上面那块共享配额。
            lines.append("\n## 焦点章正文已有硬伤（确定性体检；续写时别顺着延续）")
            for i in self.prose:
                lines.append(f"- {i.message}")
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


def _prose_focus_issues(focus_plain: str) -> List[PrecheckIssue]:
    """对焦点章**已有正文**跑一次确定性全量体检（`full_audit_draft`）。

    为什么要单开一组：事实级那组只覆盖账本 / 连续性（`dead_character_present` /
    `foreshadow_stale` / `gone_location_present` / 连续性两个码），而 `full_audit_draft`
    报的文风码（AI 味、套话、神谕腔、说明书硬伤…）在续写前**完全看不见**——
    它们恰恰是"接着写会把上一段的毛病延续下去"的那类信号。

    为什么要独立列表 / 配额 / 表头：见模块 docstring（防的是文风抱怨挤掉事实级对账）。

    只读焦点章、**不读 `draft`**：`write_gate.gate_continue_draft` 已经对产出稿跑过
    同一次体检，这里再报一遍是重复劳动（所以 `write_gate` 传 `prose_audit=False`）。

    严重度一律降成 `warn`：这一组**不挡任何东西**（`PrecheckReport.ok` 只看事实级），
    所以不该带 `error` 出来吓人。error 优先排序保留了"哪些更该先看"的信息。
    """
    if not focus_plain.strip():
        return []
    from app.core.harness.audit_full import full_audit_draft

    rows: List[tuple] = []
    seen: Set[str] = set()
    for raw in full_audit_draft(focus_plain).get("issues") or []:
        if not isinstance(raw, dict):
            continue
        severity = str(raw.get("severity") or "warn")
        # info 只作 FYI（如 `vn_dialogue_sparse`），进头部属于噪声
        if severity == "info":
            continue
        code = str(raw.get("code") or "").strip()
        message = str(raw.get("message") or "").strip()
        if not code or not message or message in seen:
            continue
        seen.add(message)
        rows.append((_SEVERITY_RANK.get(severity, 1), code, message))

    # 排序键只有严重度：Python 的 sort 稳定，同级保持体检给出的顺序 → 确定性可复现
    rows.sort(key=lambda row: row[0])
    return [
        PrecheckIssue(code=code, severity="warn", message=message[:_PROSE_MSG_MAX])
        for _, code, message in rows[:_MAX_PROSE_WARNINGS]
    ]


def precheck_before_continue(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    draft: str = "",
    prose_audit: bool = True,
) -> PrecheckReport:
    """续写前 / 写后均可调用。

    事实级（进 `issues`，影响 `ok`）：
    - 账本记为已故的角色若在焦点章或本稿出现 → error
    - 未回收伏笔 age ≥ 阈值 → warn
    - 废弃地点仍出现 / 焦点章场景图无地点认领 / 死人说话 → warn

    文风级（进 `prose`，不影响 `ok`）：
    - 焦点章已有正文的 `full_audit_draft` 硬伤；`prose_audit=False` 可关掉
      （`write_gate` 关掉它，因为那边已经对产出稿跑过同一次体检）。
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

    report = PrecheckReport(issues=issues[:_MAX_WARNINGS])
    if prose_audit:
        report.prose = _prose_focus_issues(focus_plain)
    return report

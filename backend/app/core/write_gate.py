"""续写写后廉价闸：确定性体检，不调模型。

定位（与提示词 / 责编分工）：
- 本闸只做**可证伪**检查（narrative lint + 说明书硬伤），失败就标红。
- 责编自检（LLM）是可选的下一层；自检关时本闸仍跑，只警告、不挡落地。
- 失败时给出可送进「标记批改」的短 quote，不全章重写。
- 不宣称文学好坏；通过 ≠ 写得好，只表示硬伤没被确定性规则抓到。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.chapter_revise import _hard_fail_snippets
from app.core.harness.audit_full import full_audit_draft
from app.core.narrative_lint import NarrativeLintIssue, lint_has_blockers

#: 写路径任务：产出正文后默认过闸
WRITE_GATE_TASKS = frozenset({"continue", "scene", "rewrite", "polish"})

_ANTIPATTERN_LABEL = {
    "task_summary_ack": "任务总结腔",
    "respect_lecture": "尊重定义课",
    "apartment_tour": "场景导览说明书",
    "process_faq": "工序/百科问答",
    "inner_os": "内心 OS 标签",
    "fake_choice": "假选择（选项全是整齐解释）",
}

#: 与 chapter_revise._hard_fail_snippets 同源，用来抽可标记的行
_ANTIPATTERN_LINE_RES: Dict[str, re.Pattern[str]] = {
    "task_summary_ack": re.compile(
        r"为了达成.{0,12}(要求|任务)|当成任务来完成|一本正经的总结"
    ),
    "respect_lecture": re.compile(r"私人空间.{0,20}尊重"),
    "apartment_tour": re.compile(
        r"这里是(?:厨房|客厅|卧室|工作区|房间)|带你熟悉一下|熟悉一下这个空间|"
        r"那边是(?:吃饭|睡觉|办公)的地方|我来给你介绍一下这里"
    ),
    "process_faq": re.compile(
        r"为什么要(?:这样|分开|这么做)|什么时候(?:放|加|设置|调整|开始)|"
        r"原理是什么|简单来说就是|换句话说就是|需要先了解|先(?:焯水|这样|做这个)再"
    ),
}


@dataclass
class WriteGateResult:
    passed: bool
    issues: List[Dict[str, str]] = field(default_factory=list)
    #: 给人看的短句（Agent 脚注 / contextMeta）
    warnings: List[str] = field(default_factory=list)
    #: 可送进标记批改的失败段（不全章重写）
    markHints: List[Dict[str, str]] = field(default_factory=list)

    def as_meta(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "issueCount": len(self.issues),
            "issues": self.issues[:12],
            "warnings": self.warnings[:6],
            "markHints": self.markHints[:4],
        }


def _mark_hints_for_antipatterns(text: str, codes: Sequence[str]) -> List[Dict[str, str]]:
    """从硬伤代码抽可标记的原文行，供标记批改一次一处改。"""
    hints: List[Dict[str, str]] = []
    seen: set[str] = set()
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for code in codes:
        label = _ANTIPATTERN_LABEL.get(code, code)
        pat = _ANTIPATTERN_LINE_RES.get(code)
        quote = ""
        if pat is not None:
            for ln in lines:
                if pat.search(ln):
                    quote = ln[:240]
                    break
            if not quote:
                m = pat.search(text or "")
                if m:
                    # 取命中附近一小段
                    start = max(0, m.start() - 20)
                    end = min(len(text), m.end() + 40)
                    quote = (text[start:end] or "").strip()[:240]
        if not quote and code == "fake_choice":
            for ln in lines:
                if re.match(r"^[ \t]*[ABC]\.\s*.+$", ln):
                    quote = ln[:240]
                    break
        if not quote:
            continue
        key = quote[:80]
        if key in seen:
            continue
        seen.add(key)
        hints.append(
            {
                "quote": quote,
                "reason": f"说明书硬伤：{label}",
                "instruction": f"去掉「{label}」，改成可演的动作或对白，不要扩写全章。",
                "code": f"antipattern:{code}",
            }
        )
        if len(hints) >= 4:
            break
    return hints


def _voice_drift_hints(
    project: Any,
    draft: str,
    *,
    chapter_id: Optional[str] = None,
) -> Tuple[List[Dict[str, str]], List[str], List[Dict[str, str]]]:
    """写后声线指纹：画像就绪且本段对白明显跑偏时，只出 warn + markHints。

    不挡闸（severity=warn）：声线是风格量具，不是说明书硬伤；作者可点标记批改只改跑偏句。
    样本不足 / 本段切不出对白 → 静默跳过（宁可不算，也不给错分）。
    """
    from app.core.pipeline.candidates import _lines_for
    from app.core.voice_fingerprint import build_voice_profile, score_voice

    issues: List[Dict[str, str]] = []
    warnings: List[str] = []
    hints: List[Dict[str, str]] = []
    for char in getattr(project, "characters", None) or []:
        lines = _lines_for(char, draft)
        if len(lines) < 2:
            # 短拍续写常只有一句；单句相对画像噪声大，等至少两句再喊
            continue
        cid = str(getattr(char, "id", "") or "")
        name = str(getattr(char, "displayName", "") or cid)
        if not cid:
            continue
        profile = build_voice_profile(project, cid)
        if not profile.get("ready"):
            continue
        result = score_voice(profile, lines, chapter_id=chapter_id)
        if not result.get("ready"):
            continue
        level = str(result.get("level") or "")
        if level != "drift":
            continue
        reasons = list(result.get("reasons") or [])[:2]
        reason_bit = "；".join(reasons) if reasons else "句长/节奏偏离习惯"
        msg = f"声线跑偏：{name}（{reason_bit}）"
        issues.append(
            {
                "severity": "warn",
                "code": "voice_drift",
                "message": msg,
            }
        )
        warnings.append(msg)
        for fl in list(result.get("flaggedLines") or [])[:2]:
            quote = str(fl.get("text") or "").strip()
            if not quote:
                continue
            # 尽量找回含说话人前缀的原文行，方便标记定位
            full_line = quote
            for ln in draft.splitlines():
                if quote in ln or quote[:40] in ln:
                    full_line = ln.strip()[:240]
                    break
            hints.append(
                {
                    "quote": full_line[:240],
                    "reason": msg,
                    "instruction": (
                        f"把「{name}」这句改回其惯用口吻（更短/更克制或对照语料），"
                        "只改本句，不要扩写全章。"
                    ),
                    "code": "voice_drift",
                }
            )
        if len(warnings) >= 3:
            break
    return issues, warnings, hints


def gate_continue_draft(
    draft: str,
    *,
    project: Any = None,
    chapter_id: Optional[str] = None,
) -> WriteGateResult:
    """对续写/改写产出的正文做确定性闸。

    空稿直接通过（没有东西可检）；有稿则合并 harness 全量体检与说明书硬伤。
    若传入 project，再叠一层账本对账（已故角色出场等）与声线指纹（跑偏只警告）。
    """
    text = (draft or "").strip()
    if not text:
        return WriteGateResult(passed=True)

    issues: List[Dict[str, str]] = []
    warnings: List[str] = []
    mark_hints: List[Dict[str, str]] = []

    audit = full_audit_draft(text)
    lint_issues: List[NarrativeLintIssue] = []
    for raw in audit.get("issues") or []:
        if not isinstance(raw, dict):
            continue
        msg = str(raw.get("message") or "").strip()
        if not msg:
            continue
        sev = str(raw.get("severity") or "warn")
        code = str(raw.get("code") or "harness")
        issues.append({"severity": sev, "code": code, "message": msg})
        lint_issues.append(NarrativeLintIssue(severity=sev, code=code, message=msg))

    anti_codes = _hard_fail_snippets(text)
    for code in anti_codes:
        label = _ANTIPATTERN_LABEL.get(code, code)
        msg = f"说明书硬伤：{label}"
        issues.append({"severity": "error", "code": f"antipattern:{code}", "message": msg})
        lint_issues.append(
            NarrativeLintIssue(severity="error", code=f"antipattern:{code}", message=msg)
        )
    mark_hints.extend(_mark_hints_for_antipatterns(text, anti_codes))

    if project is not None:
        from app.core.write_precheck import precheck_before_continue

        pre = precheck_before_continue(project, chapter_id=chapter_id, draft=text)
        for i in pre.issues:
            if i.code != "dead_character_present":
                # 伏笔陈旧在写后只作提醒，不挡闸
                if i.severity == "warn":
                    warnings.append(i.message)
                continue
            issues.append(
                {
                    "severity": "error",
                    "code": i.code,
                    "message": i.message,
                }
            )
            lint_issues.append(
                NarrativeLintIssue(severity="error", code=i.code, message=i.message)
            )
            if i.subject:
                # 抽含该名的一行给标记批改
                for ln in text.splitlines():
                    if i.subject in ln:
                        mark_hints.append(
                            {
                                "quote": ln.strip()[:240],
                                "reason": i.message,
                                "instruction": (
                                    f"账本记「{i.subject}」已不在场，改掉或删掉本行出场，不要扩写全章。"
                                ),
                                "code": i.code,
                            }
                        )
                        break

        # 声线指纹：画像就绪且本段对白明显跑偏 → 只警告 + 标记 hint，不挡落地
        voice_issues, voice_warns, voice_hints = _voice_drift_hints(
            project, text, chapter_id=chapter_id
        )
        issues.extend(voice_issues)
        warnings.extend(voice_warns)
        mark_hints.extend(voice_hints)

    blockers = lint_has_blockers(lint_issues) or any(
        i.get("severity") == "error" for i in issues
    )
    if blockers:
        for i in issues:
            if i.get("severity") == "error":
                warnings.append(str(i.get("message") or ""))
        if not warnings:
            warnings.append("写后闸未通过（确定性规则）")
    # 去重 markHints
    dedup: List[Dict[str, str]] = []
    seen_q: set[str] = set()
    for h in mark_hints:
        q = str(h.get("quote") or "")[:80]
        if not q or q in seen_q:
            continue
        seen_q.add(q)
        dedup.append(h)
    return WriteGateResult(
        passed=not blockers,
        issues=issues,
        warnings=warnings[:6],
        markHints=dedup[:4],
    )


def should_write_gate(task: str) -> bool:
    return (task or "") in WRITE_GATE_TASKS

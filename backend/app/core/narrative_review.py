"""Ported from packages/core/src/narrativeReview.ts"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional

from app.domain.types import AgentAction, VnProject

from .ai import DeepSeekConfig
from .llm_http import chat_completions, content_from_response
from .narrative_lint import NarrativeLintIssue, lint_has_blockers, lint_narrative_draft

SelfReviewPreference = str  # "auto" | "on" | "off"


@dataclass
class NarrativeReviewResult:
    ok: bool
    issues: List[str]
    revisedText: Optional[str] = None
    # short note for UI
    note: str = ""
    # rule-engine hits
    lintIssues: Optional[List[NarrativeLintIssue]] = None


REVIEW_TASKS: List[str] = ["continue", "scene", "rewrite", "polish"]

# Adversarial critic: assume draft is flawed; different role from writer
CRITIC_SYSTEM = """你是「挑错责编」，不是作者本人。默认假设草稿有社交/叙事问题，你的KPI是找出问题；只有确实干净才 ok=true。

禁止：为作者辩护、把「推进剧情需要」当成连问盘人的借口、只夸氛围不查对白。

硬性否决项（命中任一项 → ok 必须 false，并给 revised_text）：
- 同一角色本拍主动追问≥2次
- 问→答→再问的乒乓推进
- 陌生人/克制人设过熟倾诉或无偿讲解完整路线
- 设定/履历宣讲

审查清单：
1. 社交温度与常理
2. 盘问串 / 问答乒乓
3. 信息动机（失言/恐惧/炫耀 vs 被审讯）
4. 惜话与沉默是否被写满
5. 是否违背 voice
6. 能否用环境/动作替代多余对白

若下方提供「规则引擎已检出」，那些项视为已坐实，必须改写，不得 ok=true 无视。

输出唯一 JSON：
{
  "ok": false,
  "issues": ["..."],
  "revised_text": "改写后的完整片段（与草稿同风格）",
  "note": "一句话"
}

ok=true 时 issues 应为空且可省略 revised_text。改写保留钩子与推进意图，对白更少更尖。"""


def should_self_review(task: str, preference: str = "auto") -> bool:
    if preference == "off":
        return False
    if preference == "on":
        return task in REVIEW_TASKS
    # auto: writing tasks that produce script
    return task in REVIEW_TASKS


@dataclass
class ScriptExtraction:
    op: Optional[str]
    text: str
    index: int


def extract_script_from_actions(actions: List[AgentAction]) -> ScriptExtraction:
    for i, a in enumerate(actions):
        op = a.get("op")
        text = a.get("text")
        if op in ("append_script", "replace_script") and isinstance(text, str) and text.strip():
            return ScriptExtraction(op=op, text=text, index=i)
    return ScriptExtraction(op=None, text="", index=-1)


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def _parse_review_json(raw: str) -> NarrativeReviewResult:
    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
        issues_raw = parsed.get("issues")
        issues = [str(x) for x in issues_raw if str(x)] if isinstance(issues_raw, list) else []
        revised_raw = parsed.get("revised_text")
        if not isinstance(revised_raw, str):
            revised_raw = parsed.get("revisedText")
        revised_raw = revised_raw if isinstance(revised_raw, str) else ""
        revised = revised_raw.strip()
        note_raw = parsed.get("note")
        note = note_raw.strip() if isinstance(note_raw, str) and note_raw.strip() else ""

        fail = parsed.get("ok") is False or (len(issues) > 0 and len(revised) > 0)
        if fail and revised:
            return NarrativeReviewResult(
                ok=False,
                issues=issues,
                revisedText=revised,
                note=note or f"自检未通过（{'；'.join(issues[:2]) or '需改写'}）",
            )
        return NarrativeReviewResult(
            ok=True,
            issues=issues,
            note=note or (f"自检通过（备注：{issues[0]}）" if issues else "自检通过"),
        )
    except (json.JSONDecodeError, AttributeError, TypeError):
        return NarrativeReviewResult(
            ok=False,
            issues=["critic_parse_failed"],
            note="自检 JSON 解析失败，不得静默放行；请重试或人工改稿",
        )


def _character_voice_brief(project: VnProject) -> str:
    lines = []
    for c in project.characters[:8]:
        bio_head = (c.bio or "")[:60]
        lines.append(f"- {c.displayName}: voice={c.voice or '（无）'} | bio要点={bio_head}")
    return "\n".join(lines)


async def run_narrative_self_review(
    config: DeepSeekConfig,
    draft: str,
    task: str,
    project: VnProject,
    chapterTail: Optional[str] = None,
    lintIssues: Optional[List[NarrativeLintIssue]] = None,
) -> NarrativeReviewResult:
    """Second-pass critic: prefers a *different* model/config when provided."""
    lint_issues = lintIssues if lintIssues is not None else lint_narrative_draft(draft)
    lint_msgs = [f"[{i.severity}] {i.message}" for i in lint_issues]

    if not config.apiKey or "your-key" in config.apiKey:
        # No LLM critic — still block on rule engine
        if lint_has_blockers(lint_issues):
            return NarrativeReviewResult(
                ok=False,
                issues=lint_msgs,
                lintIssues=lint_issues,
                note="规则引擎未通过（无责编模型可改写，请人工改或配置 Key）",
            )
        return NarrativeReviewResult(
            ok=True,
            issues=lint_msgs,
            lintIssues=lint_issues,
            note="规则引擎通过；无 Key 跳过模型责编",
        )

    user = "\n\n".join(
        p
        for p in [
            f"任务类型: {task}",
            f"章末前文钩子:\n{chapterTail}" if chapterTail else "",
            f"角色声线（须尊重）:\n{_character_voice_brief(project) or '（无）'}",
            (
                "规则引擎已检出（必须处理，不得无视）:\n" + "\n".join(f"- {m}" for m in lint_msgs)
                if lint_msgs
                else "规则引擎未检出硬伤；仍请对抗式审查社交常理。"
            ),
            f"草稿:\n{draft}",
            "请输出 JSON。若规则引擎有 error 级问题，ok 必须为 false 并给出 revised_text。",
        ]
        if p
    )

    try:
        res = await chat_completions(
            config,
            messages=[
                {"role": "system", "content": CRITIC_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.25,
            response_format={"type": "json_object"},
            timeout=120,
        )
    except RuntimeError as exc:
        if lint_has_blockers(lint_issues):
            return NarrativeReviewResult(
                ok=False,
                issues=lint_msgs,
                lintIssues=lint_issues,
                note=f"责编模型失败；规则引擎未通过（{exc}）",
            )
        return NarrativeReviewResult(
            ok=False,
            issues=["critic_unavailable"],
            lintIssues=lint_issues,
            note=f"责编请求失败，不得静默放行：{exc}",
        )

    content, _used = content_from_response(res)
    content = content.strip() or "{}"
    reviewed = _parse_review_json(content)
    reviewed.lintIssues = lint_issues

    # If lint blockers exist but critic wrongly approved without revise, force fail note
    if lint_has_blockers(lint_issues) and reviewed.ok and not reviewed.revisedText:
        return NarrativeReviewResult(
            ok=False,
            issues=[*lint_msgs, *reviewed.issues],
            lintIssues=lint_issues,
            revisedText=None,
            note="规则引擎未通过且责编未给出改写，沿用原稿但标记风险",
        )

    # Merge lint messages into issues for transparency
    if lint_msgs:
        merged = list(dict.fromkeys([*lint_msgs, *reviewed.issues]))
        reviewed.issues = merged
    if not reviewed.ok and reviewed.revisedText:
        reviewed.note = reviewed.note or (
            "规则+责编：已改写" if lint_has_blockers(lint_issues) else "责编自检：已改写"
        )
    return reviewed


def apply_reviewed_script(
    actions: List[AgentAction], index: int, revised_text: str
) -> List[AgentAction]:
    out: List[AgentAction] = []
    for i, a in enumerate(actions):
        if i != index:
            out.append(a)
            continue
        if a.get("op") in ("append_script", "replace_script"):
            out.append({**a, "text": revised_text})
        else:
            out.append(a)
    return out


def chapter_tail_plain(
    project: VnProject, chapterId: Optional[str] = None, maxChars: int = 600
) -> str:
    """Rough chapter tail for critic context"""
    ch = next((c for c in project.chapters if c.id == chapterId), None) or (
        project.chapters[0] if project.chapters else None
    )
    if not ch:
        return ""
    lines: List[str] = []
    char_by_id = {c.id: c for c in project.characters}
    for b in ch.blocks:
        btype = b.get("type")
        if btype == "dialogue":
            ch_obj = char_by_id.get(b.get("characterId"))
            name = ch_obj.displayName if ch_obj else b.get("characterId")
            lines.append(f"{name}: {b['text']}")
        elif btype == "narration":
            lines.append(f"旁白: {b['text']}")
        elif btype == "raw":
            lines.append(b.get("code", ""))
    plain = "\n".join(lines)
    if len(plain) <= maxChars:
        return plain
    return plain[len(plain) - maxChars :]

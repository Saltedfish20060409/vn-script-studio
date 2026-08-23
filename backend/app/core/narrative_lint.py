"""Ported from packages/core/src/narrativeLint.ts

Deterministic narrative lint — catches patterns LLMs often miss when
reviewing their own drafts (no model call).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

LintSeverity = str  # "error" | "warn"


@dataclass
class NarrativeLintIssue:
    severity: str
    code: str
    message: str


@dataclass
class _DialogueLine:
    speaker: str
    text: str
    isQuestion: bool


_SPEAKER_LINE_1 = re.compile(r"^([^\s:：\[\]「」]{1,24})\s*[:：]\s*(.*)$")
_SPEAKER_LINE_2 = re.compile(r'^([A-Za-z_]\w*)\s+"([^"]*)"')
_NARRATOR_LABEL = re.compile(r"^(旁白|narration|nv)$", re.IGNORECASE)
_LEADING_PAREN = re.compile(r"^[（(][^）)]*[）)]")
_QUESTION_START = re.compile(r"^(难道|是不是|怎么|为什么|何处|哪|吗|么)")


def _parse_dialogue_lines(draft: str) -> List[_DialogueLine]:
    lines = draft.replace("\r\n", "\n").split("\n")
    out: List[_DialogueLine] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        # 林夏: ... | linxia "..." | 林夏：...
        m = _SPEAKER_LINE_1.match(line) or _SPEAKER_LINE_2.match(line)
        if not m:
            continue
        speaker = m.group(1).strip()
        text = (m.group(2) or "").strip()
        if not text or _NARRATOR_LABEL.match(speaker):
            continue
        stripped = _LEADING_PAREN.sub("", text, count=1)
        is_question = bool(re.search(r"[?？]", text)) or bool(_QUESTION_START.match(stripped))
        out.append(_DialogueLine(speaker=speaker, text=text, isQuestion=is_question))
    return out


_DUMP_PATTERNS = [
    (re.compile(r"我是.{0,12}(岁|的人|学生|职员)"), "自我介绍履历腔"),
    (re.compile(r"作为一名"), "说明书腔「作为一名」"),
    (re.compile(r"好感度"), "报好感度"),
    (re.compile(r"拥有.{0,8}能力"), "能力清单"),
    (re.compile(r"世界观|设定上"), "元设定口吻"),
]

_CLICHES = ["微微一笑", "不禁", "涌上心头", "命运的齿轮", "空气突然安静", "复杂的眼神"]


def lint_narrative_draft(draft: str) -> List[NarrativeLintIssue]:
    """Rule engine: social/narrative hard fails without LLM."""
    issues: List[NarrativeLintIssue] = []
    t = draft.strip()
    if not t:
        return issues

    dialogues = _parse_dialogue_lines(t)

    # 1) Same speaker asks 2+ questions in one beat (not necessarily consecutive)
    q_count: dict[str, int] = {}
    for d in dialogues:
        if not d.isQuestion:
            continue
        q_count[d.speaker] = q_count.get(d.speaker, 0) + 1
    for speaker, n in q_count.items():
        if n >= 2:
            issues.append(
                NarrativeLintIssue(
                    severity="error",
                    code="multi_question",
                    message=f"「{speaker}」本拍主动追问 {n} 次（盘问串），宜≤1 次",
                )
            )

    # 2) Q-A-Q ping-pong: A?, B answers, A? again within 6 turns
    i = 0
    n_dialogues = len(dialogues)
    while i < n_dialogues - 2:
        a = dialogues[i]
        if not a.isQuestion:
            i += 1
            continue
        j_end = min(i + 6, n_dialogues)
        for j in range(i + 1, j_end):
            mid = dialogues[j]
            if mid.speaker == a.speaker:
                continue
            k_end = min(j + 5, n_dialogues)
            for k in range(j + 1, k_end):
                again = dialogues[k]
                if again.speaker == a.speaker and again.isQuestion:
                    issues.append(
                        NarrativeLintIssue(
                            severity="error",
                            code="qa_pingpong",
                            message=f"问答乒乓：{a.speaker} 提问后再次追问（夹着 {mid.speaker} 的回答）",
                        )
                    )
                    i = k
                    break
            break
        i += 1

    # 3) 超长台词堆叠：AI 爱让角色一口气说大段独白（人设克制时尤其出戏）。
    #    同角色 ≥3 句长台词 → error；≥2 句且合计很长 → warn。
    long_by_speaker: dict[str, list[int]] = {}
    for d in dialogues:
        if len(d.text) >= 60:
            long_by_speaker.setdefault(d.speaker, []).append(len(d.text))
    for speaker, lens in long_by_speaker.items():
        if len(lens) >= 3:
            issues.append(
                NarrativeLintIssue(
                    severity="error",
                    code="long_monologue",
                    message=f"「{speaker}」连续长台词 {len(lens)} 句（单句≥60字，最长 {max(lens)} 字）："
                    f"像念稿/独白腔，真人对话不会这样；拆短或穿插动作/对方回应",
                )
            )
        elif len(lens) >= 2 and sum(lens) >= 150:
            issues.append(
                NarrativeLintIssue(
                    severity="warn",
                    code="long_monologue",
                    message=f"「{speaker}」长台词偏多（{len(lens)} 句共 {sum(lens)} 字）："
                    f"易成独白腔，宜拆短或穿插反应",
                )
            )

    # 4) Too many dialogue lines for a short "stranger beat"
    if len(dialogues) >= 8:
        issues.append(
            NarrativeLintIssue(
                severity="warn",
                code="talk_heavy",
                message=f"对白轮次偏多（{len(dialogues)} 句），陌生人/克制戏宜更少更尖",
            )
        )

    # 4) Exposition / setting dump markers
    for pattern, label in _DUMP_PATTERNS:
        if pattern.search(t):
            issues.append(
                NarrativeLintIssue(
                    severity="error", code="exposition", message=f"疑似设定倾倒：{label}"
                )
            )

    # 5) AI cliché pile
    hit = [c for c in _CLICHES if c in t]
    if len(hit) >= 2:
        issues.append(
            NarrativeLintIssue(
                severity="warn", code="cliche", message=f"套话偏多：{'、'.join(hit[:3])}"
            )
        )

    # dedupe by code+message
    seen: set = set()
    out: List[NarrativeLintIssue] = []
    for x in issues:
        k = f"{x.code}:{x.message}"
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def lint_has_blockers(issues: List[NarrativeLintIssue]) -> bool:
    return any(i.severity == "error" for i in issues)

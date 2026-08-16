"""NovelMaster-inspired AI-flavor / cadence lint for VN & light-novel drafts.

Ported pattern detectors from necolo007/NovelMaster `style_checker.py`
(shared-standards banned AI prose), adapted to Ren'Py / script / 轻小说 plain text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple

from app.core.narrative_lint import lint_narrative_draft


@dataclass
class HarnessIssue:
    severity: str  # error | warn | info
    code: str
    message: str
    source: str = "harness"  # harness | narrative


def _count_chars(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


_NOT_BUT_INLINE = re.compile(
    r"不(?:是|像)(?![说吗嘛么啊呀])"
    r"[^。！？\n「」\"“”『』]{0,28}"
    r"(?:[，,、]|——|–|-)\s*"
    r"(?:而)?是"
)
_NOT_BUT_CROSS = re.compile(
    r"不(?:是|像)(?![说吗嘛么啊呀])"
    r"[^。！？\n]{1,36}[。！？]\s*"
    r"(?:\n\s*){0,3}"
    r"(?:是|而是)(?![否定非])"
    r"[^。！？\n]{0,48}[。！？]?"
)
_NOT_BUT_TRIPLE = re.compile(
    r"不是[^。！？\n]{1,20}，不是[^。！？\n]{1,20}，(?:而)?是"
)
_UNLIKE_LIKE_LADDER = re.compile(
    r"不(?:像|是)(?![说吗嘛么啊呀])"
    r"[^。！？\n「」\"“”『』]{1,24}"
    r"(?:[，,、；;]|\s*)?"
    r"(?:也)?不(?:像|是)(?![说吗嘛么啊呀])"
    r"[^。！？\n「」\"“”『』]{1,24}"
    r"[。！？，,、；;]?\s*"
    r"(?:而)?像"
)
_DIALOGUE_TWIN_LIKE = re.compile(
    r"[「“『\"][^」”』\"]{0,80}"
    r"像[^。！？\n「」”』\"]{1,20}"
    r"(?:，|、|；|;|——)\s*"
    r"(?:又|也|还)?像"
    r"[^」”』\"]{0,40}[」”』\"]"
)
_ROLE_TELEGRAM = re.compile(
    r"(?:[你我他她它]|[\u4e00-\u9fff]{1,4})"
    r"主?[\u4e00-\u9fff]{1,2}[。！？]\s*"
    r"(?:[你我他她它]|[\u4e00-\u9fff]{1,4})"
    r"主?[\u4e00-\u9fff]{1,2}[。！？]\s*"
    r"(?:[你我他她它]|[\u4e00-\u9fff]{1,4})"
    r"主?[\u4e00-\u9fff]{1,2}[。！？]"
)
_DASH_GLOSS = re.compile(
    r"——\s*(?:不是|不像|而是|像|要|要的是|说明|等于|其实|分明)"
)
_AI_CLICHE = [
    "微微一笑",
    "不禁",
    "涌上心头",
    "命运的齿轮",
    "空气突然安静",
    "复杂的眼神",
    "心中一动",
    "目光深邃",
    "嘴角勾起",
    "如同恶魔般",
    "宛如天使",
]
_OTAKU_FALSE_FRIENDS = [
    # AI 爱用的「伪二次元」空壳，真正同人/gal 文更忌
    (re.compile(r"命运的邂逅"), "伪二次元套话「命运的邂逅」"),
    (re.compile(r"青梅竹马的羁绊"), "说明书羁绊腔"),
    (re.compile(r"本大爷.?可是"), "滥用中二口头禅（需角色人设支撑）"),
    (re.compile(r"萌萌哒"), "过时网络萌语堆砌"),
    (re.compile(r"傲娇属性"), "元设定标签入文（写表现勿写词条）"),
    (re.compile(r"好感度(?:上升|增加|拉满)"), "系统好感度出戏"),
]


def _unique_hits(regexes: List[re.Pattern[str]], text: str, max_len: int = 60) -> List[str]:
    hits: List[str] = []
    seen: set[str] = set()
    for regex in regexes:
        for match in regex.finditer(text):
            snippet = re.sub(r"\s+", "", match.group(0))
            if len(snippet) < 4 or snippet in seen:
                continue
            seen.add(snippet)
            hits.append(snippet[:max_len])
    return hits


def lint_ai_flavor(draft: str) -> List[HarnessIssue]:
    """Deterministic de-AI / cadence checks (no LLM)."""
    issues: List[HarnessIssue] = []
    text = (draft or "").strip()
    if not text:
        return issues

    not_but = _unique_hits([_NOT_BUT_INLINE, _NOT_BUT_CROSS, _NOT_BUT_TRIPLE], text)
    if len(not_but) >= 2:
        issues.append(
            HarnessIssue(
                "error",
                "ai_not_but",
                f"纠偏句式「不是A，是B」过密（{len(not_but)}）：像在替读者下结论。例：{'；'.join(not_but[:2])}",
            )
        )
    elif not_but:
        issues.append(
            HarnessIssue(
                "warn",
                "ai_not_but",
                f"出现纠偏句式，建议改成动作/感官直写。例：{not_but[0]}",
            )
        )

    ladder = _unique_hits([_UNLIKE_LIKE_LADDER, _DIALOGUE_TWIN_LIKE], text, 72)
    if ladder:
        issues.append(
            HarnessIssue(
                "error" if len(ladder) >= 2 else "warn",
                "ai_unlike_like",
                f"双否一肯/叠喻梯（不像A也不像B像C）：{'；'.join(ladder[:2])}",
            )
        )

    role_hits = [
        re.sub(r"\s+", "", m.group(0))[:48] for m in _ROLE_TELEGRAM.finditer(text)
    ]
    role_hits = [h for h in role_hits if "主" in h or re.fullmatch(r"(?:[你我他她它][\u4e00-\u9fff][。！？]){3}", h)]
    if role_hits:
        issues.append(
            HarnessIssue(
                "error",
                "ai_telegram_dialogue",
                f"分工电报腔对白，须写完整口语。例：{'；'.join(role_hits[:2])}",
            )
        )

    gloss = [re.sub(r"\s+", "", m.group(0))[:40] for m in _DASH_GLOSS.finditer(text)]
    dash_n = len(re.findall(r"——", text))
    chars = max(_count_chars(text), 1)
    if gloss:
        issues.append(
            HarnessIssue(
                "error",
                "ai_dash_gloss",
                f"破折号纠偏腔「——不是/像…」{len(gloss)} 处。例：{'；'.join(gloss[:2])}",
            )
        )
    elif dash_n >= 8 or (dash_n >= 5 and dash_n / chars * 1000 >= 2.5):
        issues.append(
            HarnessIssue(
                "warn",
                "ai_dash_dense",
                f"破折号偏多（{dash_n}），易显 AI 文艺停顿；对话打断除外，叙述宜改逗号/句号",
            )
        )

    for c in _AI_CLICHE:
        n = text.count(c)
        if n >= 2:
            issues.append(
                HarnessIssue("warn", "ai_cliche", f"套话「{c}」出现 {n} 次，建议换成具体动作/物象")
            )

    for pat, label in _OTAKU_FALSE_FRIENDS:
        if pat.search(text):
            issues.append(HarnessIssue("warn", "otaku_shell", label))

    # Empty fragment stacking: many ultra-short paragraphs
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    short = [p for p in paras if _count_chars(p) <= 6]
    if len(short) >= 5 and len(short) >= len(paras) * 0.4:
        issues.append(
            HarnessIssue(
                "warn",
                "ai_fragment_stack",
                f"极短段堆叠偏多（{len(short)}/{len(paras)}），易成空心节奏腔",
            )
        )

    return issues


def lint_vn_harness(draft: str) -> List[HarnessIssue]:
    """Full deterministic harness lint = narrative_lint + AI-flavor + VN notes."""
    out: List[HarnessIssue] = []
    for issue in lint_narrative_draft(draft):
        out.append(
            HarnessIssue(
                severity=issue.severity,
                code=issue.code,
                message=issue.message,
                source="narrative",
            )
        )
    out.extend(lint_ai_flavor(draft))

    # VN-specific: long pure narration blocks without dialogue
    if draft.count('"') + draft.count("「") < 2 and _count_chars(draft) > 800:
        out.append(
            HarnessIssue(
                "info",
                "vn_dialogue_sparse",
                "长段几乎无对白：若目标是视觉小说脚本，可考虑拆成旁白+对白节拍",
            )
        )
    return out


def issues_to_dict(issues: List[HarnessIssue]) -> List[dict]:
    return [
        {
            "severity": i.severity,
            "code": i.code,
            "message": i.message,
            "source": i.source,
        }
        for i in issues
    ]


def summarize_issues(issues: List[HarnessIssue]) -> Tuple[int, int, int]:
    err = sum(1 for i in issues if i.severity == "error")
    warn = sum(1 for i in issues if i.severity == "warn")
    info = sum(1 for i in issues if i.severity == "info")
    return err, warn, info

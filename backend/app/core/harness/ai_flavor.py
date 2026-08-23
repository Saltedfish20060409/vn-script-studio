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
# 分工电报腔的另一种形态：不带「主」，短句连续「你X。我Y。」式指令对
# （如 trap-telegram 的「你查雨。我查人。你问灯。我问影。」），旧正则会因
# 缺少「主」字被过滤，这里按整篇短句数量兜底。
_TELEGRAM_UNIT = re.compile(r"(?:你|我)[\u4e00-\u9fff]{1,2}[。！？]")
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

# AI 高频「猜测腔」：不确定性模糊化——仿佛/似乎/好像/莫名/不知为何
# 单段 ≥2 处即告警（1 处可能是正常表达，2 处以上基本是 AI 回避下判断）
_GUESS_WORDS = [
    "仿佛", "似乎", "好像", "莫名", "不知为何", "说不清",
    "有种说不出的", "也说不上来", "隐隐觉得",
]

# AI 高频副词堆砌：缓缓/轻轻/微微/静静/默默/淡淡
# 单段 ≥2 处即告警（AI 爱用这些软副词制造"文艺感"）
_ADVERB_PILE = [
    "缓缓", "轻轻", "微微", "静静", "默默", "淡淡", "悄悄",
]

# 「说」标签副词：冷冷地说 / 温柔地说 / 低声说……
# 单段 ≥2 处即告警（AI 爱用"副词+说/道"给对白贴情绪标签，真人很少这样写）
_SAID_TAG_RE = re.compile(
    r"(?:冷冷|温柔|轻轻|低声|淡然|平静|坚定|无奈|苦笑|哽咽|沙哑|平静地|淡淡地)"
    r"(?:地)?(?:说|道|开口|问|答)"
)

# 情绪陈词：AI 概括情绪的套话（几乎必然 AI 味，1 处即告警）
_EMOTION_CLICHE = [
    "心中一动", "一股暖流", "眼眶微热", "心里一紧", "说不清道不明",
    "某种情绪", "异样的感觉", "无法言说的",
]

# 全知剧透揭示词：旁白/内心OS 里出现这些词，说明叙述越过了角色视角
# 强词：几乎必然剧透（凶手/尸体/真相…），1 处即 error
_OMNISCIENT_STRONG = [
    "凶手", "尸体", "真相", "瞒着", "没人知道", "不为人知",
]
# 弱词：单独出现可能是正常表述（计划/秘密…），需 ≥2 处或 1 强+1 弱才 error
_OMNISCIENT_WEAK = [
    "秘密", "计划", "阴谋", "早就知道", "从未告诉",
]


def _count_in(text: str, words: list[str]) -> int:
    return sum(text.count(w) for w in words)


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
    else:
        # 兜底：整篇「你X。我Y。」短句 ≥6 处才算分工电报腔（不一定带「主」）
        # ≥4 是正常短句对话（你说吧。我听着。），不误伤
        terse = _TELEGRAM_UNIT.findall(text)
        if len(terse) >= 6 and len(set(terse)) >= 3:
            issues.append(
                HarnessIssue(
                    "error",
                    "ai_telegram_dialogue",
                    f"电报式短句指令对过密（{len(terse)} 处，如「你查雨。我查人。」）："
                    f"须写完整口语。例：{'；'.join(terse[:4])}",
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

    # 按自然段统计软词密度（避免整篇计数误伤单段正常用法）
    for para in paras:
        guess = _count_in(para, _GUESS_WORDS)
        if guess >= 2:
            issues.append(
                HarnessIssue(
                    "warn",
                    "ai_guess_hedge",
                    f"猜测腔过密（{guess} 处：仿佛/似乎/莫名…）：AI 爱用不确定性词回避下判断，"
                    f"宜改成确定动作/感官。例段：{para[:40]}…",
                )
            )
            break  # 每段一次，避免刷屏
        adverb = _count_in(para, _ADVERB_PILE)
        if adverb >= 2:
            issues.append(
                HarnessIssue(
                    "warn",
                    "ai_adverb_pile",
                    f"软副词堆砌（{adverb} 处：缓缓/轻轻/微微…）：宜删到每段≤1，"
                    f"换成具体动作或干脆不加。例段：{para[:40]}…",
                )
            )
            break
        said = len(_SAID_TAG_RE.findall(para))
        if said >= 2:
            issues.append(
                HarnessIssue(
                    "warn",
                    "ai_said_tag",
                    f"「副词+说/道」标签过密（{said} 处：冷冷地说…）：真人很少给对白贴情绪标签，"
                    f"宜用动作或直接写对白。例段：{para[:40]}…",
                )
            )
            break
        emot = _count_in(para, _EMOTION_CLICHE)
        if emot >= 1:
            issues.append(
                HarnessIssue(
                    "warn",
                    "ai_emotion_cliche",
                    f"情绪陈词「{next((w for w in _EMOTION_CLICHE if w in para), '')}」："
                    f"概括情绪不如写具体反应。例段：{para[:40]}…",
                )
            )
            break

    # 整篇软副词累积：单段各 1 处、但整篇 ≥5 处同样是 AI 味（如 trap-adverb 的分散堆砌）
    adverb_total = _count_in(text, _ADVERB_PILE)
    if adverb_total >= 5 and not any(i.code == "ai_adverb_pile" for i in issues):
        issues.append(
            HarnessIssue(
                "error" if adverb_total >= 6 else "warn",
                "ai_adverb_pile",
                f"软副词整篇累积 {adverb_total} 处（缓缓/轻轻/微微…）：单段不密但全篇发腻，"
                f"宜整体删减到 ≤2 处，换具体动作。",
            )
        )

    # 全知剧透：带「旁白/内心OS」标签却直接揭示隐藏信息（凶手/真相/尸体/计划…）
    omni_label = bool(re.search(r"(?:旁白|内心OS)\s*[:：]", text))
    if omni_label:
        strong_n = sum(text.count(w) for w in _OMNISCIENT_STRONG)
        weak_n = sum(text.count(w) for w in _OMNISCIENT_WEAK)
        omni_n = strong_n + weak_n
        if strong_n >= 1 or omni_n >= 2:
            issues.append(
                HarnessIssue(
                    "error",
                    "ai_omniscient_spoil",
                    f"旁白/内心OS 全知剧透（强揭示词 {strong_n} + 弱揭示词 {weak_n}）："
                    f"叙述知道了角色不该知道的隐藏信息，须改为可上演的动作/对白线索。",
                )
            )
        elif omni_n == 1:
            issues.append(
                HarnessIssue(
                    "warn",
                    "ai_omniscient_spoil",
                    "旁白出现隐藏信息揭示词，检查是否越过了角色视角。",
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

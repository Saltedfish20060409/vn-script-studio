"""Load writing-style Skill from style_guide.md and apply as hard constraints."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

from app.core.harness.ai_flavor import HarnessIssue

_STYLE_PATH = Path(__file__).with_name("style_guide.md")

# Fallback seeds if markdown parse is thin
_SEED_BANNED = [
    "内心OS",
    "心声：",
    "吐槽：",
    "心想",
    "暗自",
    "不由得",
    "不由自主地",
    "感到温暖",
    "心里一紧",
    "莫名地",
    "涌上心头",
    "心头一暖",
    "空气突然安静",
    "复杂的眼神",
    "愣了一下",
    "微微一怔",
    "轻轻一笑",
    "点了点头",
    "叹了口气",
    "嘴角勾起",
    "不禁",
    "原来如此",
    "我明白了",
    "原来是这样",
    "那一刻，他忽然觉得",
    "他第一次意识到",
    "就这样，他们",
    "或许这就是",
    "命运的邂逅",
    "青梅竹马的羁绊",
    "好感度上升",
    "萌萌哒",
    "傲娇属性",
]


@dataclass
class StyleSkill:
    raw: str
    principles: List[str] = field(default_factory=list)
    do_nots: List[str] = field(default_factory=list)
    dos: List[str] = field(default_factory=list)
    structural: List[str] = field(default_factory=list)
    banned_phrases: List[str] = field(default_factory=list)
    pre_check: List[str] = field(default_factory=list)
    post_check: List[str] = field(default_factory=list)

    def prompt_block(self, *, max_chars: int = 4500) -> str:
        """Force-read block for LLM system / user prompts."""
        body = self.raw.strip()
        if len(body) > max_chars:
            # Prefer keeping principles + banned + post-check when truncating
            body = body[: max_chars - 24] + "\n\n…(Skill 正文截断，禁用词与检查清单仍须遵守)"
        return (
            "## 写作风格 Skill（硬约束·可执行清单）\n"
            "你已阅读并确认遵守：原则 → 规则 → 检查项。"
            "生成与改写不得违反核心原则与禁用词清单。\n\n"
            + body
        )

    def confirm_preamble(self) -> str:
        return (
            "【确认】我已阅读写作风格 Skill："
            f"原则 {len(self.principles) or 3} 条 / "
            f"禁用短语 {len(self.banned_phrases)} 条 / "
            f"生成后检查 {len(self.post_check)} 项。"
            "将在规则边界内写作。"
        )


def _bullets(text: str) -> List[str]:
    out: List[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- [ ]"):
            out.append(s[5:].strip())
        elif s.startswith("- [x]") or s.startswith("- [X]"):
            out.append(s[5:].strip())
        elif s.startswith("- "):
            out.append(s[2:].strip())
    return out


def _section_after(text: str, heading_substr: str) -> str:
    """Return body until next same-or-higher markdown heading."""
    lines = text.splitlines()
    start = None
    level = None
    for i, ln in enumerate(lines):
        if ln.startswith("#") and heading_substr in ln:
            start = i + 1
            level = len(ln) - len(ln.lstrip("#"))
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start, len(lines)):
        ln = lines[j]
        if ln.startswith("#"):
            lv = len(ln) - len(ln.lstrip("#"))
            if level is not None and lv <= level:
                end = j
                break
    return "\n".join(lines[start:end])


def _extract_banned(text: str) -> List[str]:
    banned_sec = _section_after(text, "禁用词")
    found = list(_SEED_BANNED)
    if banned_sec:
        found.extend(_bullets(banned_sec))
    # Also pull quoted phrases from 禁止 lines
    for m in re.findall(r"[「「]([^」」]{2,24})[」」]", text):
        found.append(m)
    for m in re.findall(r"\*\*禁止[：:]\*\*\s*(.+)", text):
        found.append(re.sub(r"[「」\"“”]", "", m).strip()[:40])
    seen: set[str] = set()
    out: List[str] = []
    for p in found:
        p = p.strip().strip("-").strip()
        if len(p) < 2 or p in seen:
            continue
        # skip long rule sentences
        if len(p) > 28:
            continue
        seen.add(p)
        out.append(p)
    return out


def _extract_principles(text: str) -> List[str]:
    sec = _section_after(text, "核心原则")
    titles: List[str] = []
    for ln in sec.splitlines():
        if ln.startswith("### "):
            titles.append(ln[4:].strip())
    return titles


@lru_cache(maxsize=1)
def load_style_skill() -> StyleSkill:
    text = _STYLE_PATH.read_text(encoding="utf-8")
    principles = _extract_principles(text)
    banned = _extract_banned(text)
    pre = _bullets(_section_after(text, "生成前检查"))
    post = _bullets(_section_after(text, "生成后检查"))
    structural = _bullets(_section_after(text, "Structural Rules"))
    if not structural:
        structural = _bullets(_section_after(text, "节奏规则"))
    # do_nots: compact list for meta / confirm
    do_nots = [p for p in banned if len(p) <= 16][:40]
    dos = [
        "对话要有毛边：允许不回答、跑题、动作代答",
        "男主用行动代替解释；回答尽量一行内",
        "情感用动作与环境写，不写标签式心理",
        "世界观被经过，不被告知；单场景一条信息",
    ]
    return StyleSkill(
        raw=text,
        principles=principles,
        do_nots=do_nots,
        dos=dos,
        structural=structural,
        banned_phrases=banned,
        pre_check=pre,
        post_check=post,
    )


def reload_style_skill() -> StyleSkill:
    load_style_skill.cache_clear()
    return load_style_skill()


def lint_style_skill(draft: str) -> List[HarnessIssue]:
    """Deterministic checks against banned phrase list."""
    skill = load_style_skill()
    text = draft or ""
    issues: List[HarnessIssue] = []
    if not text.strip():
        return issues

    hard = {
        "内心OS",
        "心声：",
        "吐槽：",
        "愣了一下",
        "微微一怔",
        "心想",
        "原来如此",
        "我明白了",
        "原来是这样",
    }
    for phrase in skill.banned_phrases:
        if phrase and phrase in text:
            sev = "error" if phrase in hard else "warn"
            issues.append(
                HarnessIssue(
                    sev,
                    "style_donot",
                    f"触犯风格 Skill 禁用项：出现「{phrase}」",
                )
            )

    if re.search(r"内心\s*OS|心声\s*[:：]|吐槽\s*[:：]", text):
        issues.append(
            HarnessIssue(
                "error",
                "style_os_tag",
                "禁止标签式心理描写（内心OS / 心声 / 吐槽）",
            )
        )
    if re.search(r"(?:就这样[，,].{0,12}他们|或许这就是|那一刻[，,].{0,8}忽然觉得)", text):
        issues.append(
            HarnessIssue(
                "warn",
                "style_author_summary",
                "疑似抒情升华 / 作者总结收束，建议改成具体画面",
            )
        )
    # Q→A→end soft heuristic: many 「」 pairs with 原来如此 style already covered
    if len(re.findall(r"原来如此|我明白了|原来是这样", text)) >= 1:
        issues.append(
            HarnessIssue(
                "error",
                "style_universal_ack",
                "出现万能回应（原来如此 / 我明白了），拆掉闭环",
            )
        )
    return issues


def style_skill_meta() -> Dict[str, Any]:
    skill = load_style_skill()
    return {
        "version": "1.0",
        "principleCount": len(skill.principles) or 3,
        "principles": skill.principles,
        "doNotCount": len(skill.do_nots),
        "bannedPhraseCount": len(skill.banned_phrases),
        "preCheckCount": len(skill.pre_check),
        "postCheckCount": len(skill.post_check),
        "structuralCount": len(skill.structural),
        "bannedSample": skill.banned_phrases[:24],
        "path": "app/core/pipeline/style_guide.md",
    }


def merge_audit_with_style(base: Dict[str, Any], draft: str) -> Dict[str, Any]:
    """Extend harness audit with style-skill issues."""
    extra = lint_style_skill(draft)
    issues = list(base.get("issues") or [])
    seen_msg = {i.get("message") for i in issues if isinstance(i, dict)}
    for iss in extra:
        if iss.message in seen_msg:
            continue
        issues.append(
            {
                "severity": iss.severity,
                "code": iss.code,
                "message": iss.message,
                "source": "style_skill",
            }
        )
        seen_msg.add(iss.message)
    err = sum(1 for i in issues if i.get("severity") == "error")
    warn = sum(1 for i in issues if i.get("severity") == "warn")
    info = sum(1 for i in issues if i.get("severity") == "info")
    return {
        **base,
        "issues": issues,
        "errorCount": err,
        "warnCount": warn,
        "infoCount": info,
        "pass": err == 0,
        "styleSkill": True,
    }

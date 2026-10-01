"""Load writing-style Skill from style_guide.md and apply as hard constraints."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

if TYPE_CHECKING:  # 只给类型检查用；运行时在函数里导入（见下面那段说明）
    from app.core.harness.ai_flavor import HarnessIssue

# 为什么 `HarnessIssue` 不在模块顶层导入（2026-09-28 修）：
#   `style_skill` ← `harness/__init__` → `harness.audit_full` → `style_skill`，是一个**循环导入**。
#   谁先被导入决定成败：`app.core.harness.*` 先加载时正常，而**先导入 `style_skill` 就直接
#   ImportError**。而调用方 `build_writing_craft_prompt` 用的是
#   `try: ... load_style_skill() ... except Exception: pass`——于是这条最硬的约束
#   （`style_guide.md` 约 2k 字的禁用词与自检清单）会**静默消失**，提示词看着正常、
#   实际少了规则。改到函数内部导入即断环：那时 harness 已经加载完了。

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


#: `prompt_block` 的装配优先级：预算不够时**先保这些**（按此顺序）。
#:
#: 这张表之所以存在，是因为旧实现用 `body[:max_chars-24]` 尾部切片，切掉的正好是
#: §三 禁用词与 §六 参考范例——而块尾还写着"禁用词与检查清单仍须遵守"。
#: 现在改成"整节取用 + 如实说明省了什么"，顺序就是这张表给的。
_MUST_KEEP: Tuple[str, ...] = ("核心原则", "禁用词", "生成后检查", "参考范例")


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
        """硬约束块：按优先级**整节**装配，不切半截。

        旧实现是 `body[:max_chars - 24]` 的尾部切片——它切掉的部分**正好是** §三 禁用词
        （offset 2679）与 §六 参考范例（3687），而块尾那句 "…(Skill 正文截断，禁用词与检查
        清单仍须遵守)" 却还在要求模型遵守它已经看不见的清单。注释里写的意图
        （Prefer keeping principles + banned + post-check）从来没实现过。
        """
        header = (
            "## 写作风格 Skill（硬约束·可执行清单）\n"
            "你已阅读并确认遵守：原则 → 规则 → 检查项。\n"
            "生成与改写不得违反核心原则与禁用词清单。\n\n"
        )
        sections = _split_sections(self.raw)
        ordered: List[Tuple[str, str]] = []
        seen_heads: set = set()
        for key in _MUST_KEEP:
            for head, body in sections:
                if key in head and head not in seen_heads:
                    ordered.append((head, body))
                    seen_heads.add(head)
        for head, body in sections:
            if head not in seen_heads:
                ordered.append((head, body))
                seen_heads.add(head)

        parts: List[str] = []
        omitted: List[str] = []
        used = len(header)
        must_heads = {head for head, _ in ordered if any(k in head for k in _MUST_KEEP)}
        dropped_must = False
        for head, body in ordered:
            block = f"{head}\n{body}".strip()
            # 第一节无条件进：预算压到极紧时也得交出一块真东西，不能是空壳。
            if parts and used + len(block) + 2 > max_chars:
                omitted.append(head.lstrip("# ").strip())
                if head in must_heads:
                    dropped_must = True
                continue
            # 必保项缺了就别再塞填充节：一份"有流水线摘要、却没有禁用清单"的检查块
            # 比短一点的块更糟——它让人以为要点都在。
            if dropped_must and head not in must_heads:
                omitted.append(head.lstrip("# ").strip())
                continue
            parts.append(block)
            used += len(block) + 2
        tail = ""
        if omitted:
            # 如实说明省了什么——"声称要守却没给"比"没给"更糟。
            # 分隔符用 `·` 而不是顿号：节名自己就含顿号（`三、禁用词 / 句式`），
            # 用顿号拼出来的清单没法被解析回节名。
            tail = (
                "\n\n…（预算所限未收入："
                + " · ".join(omitted)
                + "；完整清单见 app/core/pipeline/style_guide.md）"
            )
        return header + "\n\n".join(parts) + tail

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


def _split_sections(text: str) -> List[Tuple[str, str]]:
    """按**二级**标题切成 `[(标题行, 正文)]`，保持文档顺序。

    只切二级：三级标题（`### 原则一…`）是节内的段落，切出来会把"核心原则"拆散。
    一级标题（文档大标题）不单独成节——`prompt_block` 自带表头。
    """
    out: List[Tuple[str, str]] = []
    current: Optional[str] = None
    buf: List[str] = []
    for ln in text.splitlines():
        if ln.startswith("#"):
            level = len(ln) - len(ln.lstrip("#"))
            if level == 2:
                if current is not None:
                    out.append((current, "\n".join(buf).strip()))
                current = ln.strip()
                buf = []
                continue
            if level == 1:
                continue
        if current is not None:
            buf.append(ln)
    if current is not None:
        out.append((current, "\n".join(buf).strip()))
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


def _normalize_banned(phrase: str) -> str:
    """去掉**注释性**括号：`很多事都这样（单独成段的收尾金句）` → `很多事都这样`。

    括号里是说明，不是词本身。留着它的后果不是"更严格"，而是**这条规则从来没有生效过**——
    子串匹配永远匹配不到带括号的那串字，作者以为自己禁了，其实一直没禁。
    """
    p = (phrase or "").strip().strip("-").strip()
    return re.sub(r"[（(][^）)]*[）)]\s*$", "", p).strip()


def _extract_banned(text: str) -> List[str]:
    """禁用词表的**唯一**来源：内置种子 + `§三 禁用词 / 句式` 的条目。

    为什么不在这里"顺手把全文的「」引号内容也收进来"（2026-10 修）
    ------------------------------------------------------------------
    这里曾有一行 `re.findall(r"[「「]([^」」]{2,24})[」」]", text)`，把整份文档里所有
    「」引号内容都当成了禁用词。实测：33 条种子 → **108 条**，多出来的 75 条里包括

    - 指南自己树为标杆的句子：范例 A「雨很大。你肯定会淋湿。」、范例 B「走了。」、
      范例 C「伞……你拿去。」；
    - ✅ 正面例：「第二天早上。」「他手上的动作停了一下。」
      「他把那件外套挂在了她房间门口的挂钩上。」；
    - 章节小标题与被引用的普通词：「为什么」「解释」「经过」「目的」「温度」「毛边」「收尾」。

    于是 `lint_style_skill` 会对着**照着指南写出来的最好句子**报违规；再叠上打分表里
    style_skill 命中被双重计罚（见 `candidates._FLAVOR_SOURCES`），best-of-N 就会主动
    淘汰"最像范例"的那一稿——一个自我惩罚的闭环。

    禁用表必须是**手工维护的短表**：这里只认种子和 §三 的条目，不再从正文里抓。
    """
    found: List[str] = list(_SEED_BANNED)
    banned_sec = _section_after(text, "禁用词")
    if banned_sec:
        found.extend(_bullets(banned_sec))
    seen: set[str] = set()
    out: List[str] = []
    for raw in found:
        p = _normalize_banned(raw)
        if len(p) < 2 or p in seen:
            continue
        # 跳过整条规则句（禁用表收的是"词/短语"，不是句子）
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


def lint_style_skill(draft: str) -> List[HarnessIssue]:
    """Deterministic checks against banned phrase list."""
    from app.core.harness.ai_flavor import HarnessIssue  # 见文件头：断循环导入

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

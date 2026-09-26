"""约束分层与冲突检测。

作者写设定时最常犯的两个错，都会让"工具写得不如裸聊"：

1. **约束混在一起**：世界观背景、"必须有"的硬规则、"尽量"的风格偏好全堆在 notes 里。
   模型分不清哪条是红线、哪条是建议，于是按最省事的方式写。这里把它们分开，
   并把**硬规则挑出来放到上下文末尾**（长上下文里中间的要求最容易被忽略）。
2. **互相打架**：一边写"不要解释超自然"，一边写"要把设定讲清楚"；一边要"短句冷峻"，
   一边要"绵长抒情"。冲突的约束会让模型只写"不会违规的空话"——这正是"读起来很平"的常见成因。

只做**能确定判断**的检查，不做文风评价；全部为纯函数，便于测试。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

# 硬规则标志词（作者自己写的"必须有/不许"）
_HARD_MARKERS = (
    "必须",
    "务必",
    "一定要",
    "不要",
    "不许",
    "不得",
    "禁止",
    "严禁",
    "一律",
    "绝",
    "只能",
    "唯一",
)
# 软规则标志词（偏好、倾向）
_SOFT_MARKERS = ("尽量", "最好", "建议", "倾向", "可以", "希望", "偏好", "适度")

# 冲突对：同一维度上互斥的说法（左边一组 vs 右边一组）
_CONFLICT_PAIRS: List[Dict[str, object]] = [
    {
        "topic": "是否解释超自然",
        "a": ("不要解释", "不解释", "不要说明", "别解释", "不能解释"),
        "b": ("要解释清楚", "必须解释", "讲清楚设定", "把设定讲清", "要说明白"),
        "hint": "克系/神秘类写法里「不解释」是恐怖来源；如果要解释，就把它写成体系探秘，别两头都要。",
    },
    {
        "topic": "句子长短",
        "a": ("短句", "简洁", "克制", "干脆"),
        "b": ("长句", "绵长", "华丽", "铺陈", "抒情"),
        "hint": "两种节奏可以分场合用（叙述短、氛围长），别在同一条里同时要求。",
    },
    {
        "topic": "叙述人称",
        "a": ("第一人称", "一人称", "我视角", "见证书"),
        "b": ("第三人称", "三人称", "全知", "多视角"),
        "hint": "人称必须在同一章里唯一；换人称请按章切换。",
    },
    {
        "topic": "视角信息量",
        "a": ("限制视角", "不知道全貌", "只写主角知道的"),
        "b": ("全知", "上帝视角", "交代所有人的想法"),
        "hint": "限制视角与全知互斥，同一场景只能选一个。",
    },
    {
        "topic": "情绪浓度",
        "a": ("不要抒情", "克制", "冷静", "客观"),
        "b": ("煽情", "催泪", "浓烈", "情绪饱满"),
        "hint": "要浓郁就允许抒情，要克制就去掉抒情句，别同时要求。",
    },
    {
        "topic": "对白比例",
        "a": ("少对白", "对白少", "以叙述为主"),
        "b": ("多对白", "对白为主", "以对话推进"),
        "hint": "挑一个主基调，其余当调剂。",
    },
]


@dataclass
class ConstraintAudit:
    hard: List[str] = field(default_factory=list)
    soft: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)
    conflicts: List[Dict[str, str]] = field(default_factory=list)
    # 只有禁令、没有样例时的提醒
    needs_samples: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "hard": self.hard,
            "soft": self.soft,
            "info": self.info,
            "conflicts": self.conflicts,
            "needsSamples": self.needs_samples,
            "notes": self.notes,
        }


def iter_constraint_lines(text: str) -> List[str]:
    """把一段设定文本切成"一条一条"的约束候选。"""
    out: List[str] = []
    for raw in re.split(r"[\n\r]+", text or ""):
        line = raw.strip()
        if not line:
            continue
        # 去掉列表符号与序号
        line = re.sub(r"^[-*·•\d]+[.、)．]?\s*", "", line).strip()
        if line:
            out.append(line)
    return out


def classify_line(line: str) -> str:
    """hard / soft / info。"""
    if any(m in line for m in _HARD_MARKERS):
        return "hard"
    if any(m in line for m in _SOFT_MARKERS):
        return "soft"
    return "info"


def detect_conflicts(rules: Sequence[str]) -> List[Dict[str, str]]:
    """找出互相打架的约束对。"""
    out: List[Dict[str, str]] = []
    for pair in _CONFLICT_PAIRS:
        topic = str(pair["topic"])
        a_hits = [r for r in rules if any(k in r for k in pair["a"])]  # type: ignore[operator]
        b_hits = [r for r in rules if any(k in r for k in pair["b"])]  # type: ignore[operator]
        if a_hits and b_hits:
            out.append(
                {
                    "topic": topic,
                    "a": a_hits[0][:80],
                    "b": b_hits[0][:80],
                    "hint": str(pair["hint"]),
                }
            )
    return out


def audit_constraints(
    *,
    bible_text: str = "",
    entry_texts: Optional[Iterable[str]] = None,
    has_style_samples: bool = False,
    max_rules: int = 40,
) -> ConstraintAudit:
    """体检作者的约束：分层 + 冲突 + 缺样例提醒。"""
    lines: List[str] = []
    lines.extend(iter_constraint_lines(bible_text))
    for text in entry_texts or []:
        # 设定条目通常是"名字：说明"，取说明部分
        body = str(text or "").strip()
        if not body:
            continue
        head, _, tail = body.partition("：")
        lines.append(tail.strip() if tail.strip() else head.strip())

    audit = ConstraintAudit()
    for line in lines:
        kind = classify_line(line)
        if kind == "hard":
            if len(audit.hard) < max_rules:
                audit.hard.append(line)
        elif kind == "soft":
            if len(audit.soft) < max_rules:
                audit.soft.append(line)
        else:
            if len(audit.info) < max_rules:
                audit.info.append(line)

    # 冲突要扫**全部行**：世界观句子（info）也可能和硬规则打架，
    # 只扫 hard+soft 会漏掉最常见的那类（"必须第一人称" vs "全知视角交代所有人"）。
    audit.conflicts = detect_conflicts(audit.hard + audit.soft + audit.info)
    if audit.hard and not has_style_samples:
        audit.needs_samples = True
        audit.notes.append(
            "有硬规则但还没有文风样例：模型模仿「看得见的句子」远比遵守规则稳，"
            "建议让它学一下你的文风（2–3 段样例即可）。"
        )
    if len(audit.hard) > 8:
        audit.notes.append(
            f"硬规则有 {len(audit.hard)} 条，偏多：模型一次能稳定遵守的大概是 8 条以内，"
            "建议合并同类项，其余降为「尽量」。"
        )
    if audit.conflicts:
        audit.notes.append(
            "检测到互相冲突的约束：冲突会让模型只写「不会违规的空话」，读起来就会很平。"
        )
    return audit


def author_hard_rules(
    *,
    bible_text: str = "",
    entry_texts: Optional[Iterable[str]] = None,
    limit: int = 5,
) -> List[str]:
    """挑出作者自己的硬规则（放进上下文末尾的「本次硬规则」里一起重复）。"""
    audit = audit_constraints(bible_text=bible_text, entry_texts=entry_texts)
    # 去掉内部标记符号，保持短
    cleaned = [re.sub(r"^[-*·•\s]+", "", r).strip() for r in audit.hard]
    return [r[:120] for r in cleaned if r][:limit]


# 可执行硬规则：只有**结构上能证伪**的才进校验；其余仍只靠提示词（软约束）。
_POV_FIRST = ("第一人称", "一人称", "我视角", "见证书")
_POV_THIRD = ("第三人称", "三人称", "全知视角", "全知")
# 地の文人称标记太少时不下结论（避免短段误报）
_POV_MIN_MARKERS = 8
# 主导人称占比阈值：低于此视为明显偏离作者硬规则
_POV_MIN_RATIO = 0.28


def check_executable_hard_rules(
    hard_rules: Sequence[str],
    *,
    first: int,
    third: int,
    first_ratio: Optional[float],
) -> List[Dict[str, str]]:
    """对照作者硬规则做**可证伪**检查（目前：叙述人称）。

    返回 ``[{code, severity, message, rule}]``。
    - 不做文风评价；标记不足时返回空（"未测量" ≠ "合规"）。
    - 硬规则里同时**正面要求**第一与第三人称时跳过（冲突由 ``detect_conflicts`` 管）。
    - 「不要/禁止第一人称」计为要求第三人称，不会误判成要求第一人称。
    """
    rules = [str(r).strip() for r in hard_rules if str(r).strip()]
    if not rules:
        return []

    def _mentions(rule: str, keys: tuple[str, ...]) -> bool:
        return any(k in rule for k in keys)

    def _negated(rule: str, keys: tuple[str, ...]) -> bool:
        """「不要用第一人称」这类：命中人称词且同句带禁令标记。"""
        if not _mentions(rule, keys):
            return False
        return any(m in rule for m in ("不要", "不许", "不得", "禁止", "严禁", "别用", "勿"))

    wants_first = False
    wants_third = False
    matched = ""
    for rule in rules:
        if _negated(rule, _POV_FIRST):
            wants_third = True
            matched = matched or rule
        elif _negated(rule, _POV_THIRD):
            wants_first = True
            matched = matched or rule
        elif _mentions(rule, _POV_FIRST):
            wants_first = True
            matched = matched or rule
        elif _mentions(rule, _POV_THIRD):
            wants_third = True
            matched = matched or rule

    if wants_first and wants_third:
        return []
    if not wants_first and not wants_third:
        return []
    markers = int(first) + int(third)
    if markers < _POV_MIN_MARKERS or first_ratio is None:
        return []

    out: List[Dict[str, str]] = []
    if wants_first and first_ratio < _POV_MIN_RATIO:
        out.append(
            {
                "code": "hard_rule_pov_first",
                "severity": "warn",
                "message": (
                    f"作者硬规则要求第一人称叙述，但地の文里第一人称标记只占 "
                    f"{first_ratio:.0%}（共 {markers} 处标记）。"
                    "这是结构对照，不是文笔评分。"
                ),
                "rule": matched[:120],
            }
        )
    if wants_third and first_ratio > (1.0 - _POV_MIN_RATIO):
        out.append(
            {
                "code": "hard_rule_pov_third",
                "severity": "warn",
                "message": (
                    f"作者硬规则要求第三人称叙述，但地の文里第一人称标记占 "
                    f"{first_ratio:.0%}（共 {markers} 处标记）。"
                    "这是结构对照，不是文笔评分。"
                ),
                "rule": matched[:120],
            }
        )
    return out

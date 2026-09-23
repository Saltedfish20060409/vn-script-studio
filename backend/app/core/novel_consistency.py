"""轻小说文体一致性：表记写法（确定性）+ 视角与称呼（启发式）。

为什么要有这个模块
------------------
书稿写到几十万字之后，"这一章里有个半角逗号"这类问题靠人眼抓不住，靠 LLM 审稿同样
抓不住：模型看得见情节矛盾，看不见「你好,世界」里的那个逗号，而且每多跑一次就多付
一份 token 与等待。**确认性**问题（这个字符到底写错没有）恰恰是规则比模型更擅长的一类，
所以这里把表记检查做成纯规则：不联网、不调模型、结果可复现，因此能进单测、能进 CI。

两组检查的性质完全不同（这一点很重要）
--------------------------------------
- A 组（表记/写法）：**确定性**。同一份稿子每次跑出完全一样的结果，每条都能指出原文位置。
- B 组（视角 / 称呼）：**启发式**。视角靠"我/我们"与"他/她/角色名作主语"的词频对比推断；
  称呼漂移靠一份可维护的称呼模式表按章序比对敬称层级。它们给的是线索，不是结论——
  视角切换本身可能是作者刻意为之，敬称变化可能正是剧情推进。所以这一组的 message 与
  返回里的 ``notes`` 都会写明"启发式"，由作者决定改不改。

为什么正文有两个取法
--------------------
``agent_context._blocks_to_plain`` 把一章的块渲染成纯文本时会加上 ``旁白: `` / ``林夏: `` 这类
**结构标记**，if 块还会渲染成 ``[如果 条件(好感度 >= 3) { … }]``。这些标记是工具自己写的，
不是作者写的；拿它们去跑标点规则，会把渲染器里的 ``:`` ``(`` 报成"作者半角标点混用"——
那是纯粹的误报。所以本模块分两份视图：

- ``_chapter_text``（内部就走 ``_blocks_to_plain``）：**整章纯文本**，只用于视角词频这类统计；
- ``_author_lines``：**逐行取作者自己写的字段**（prose 的各行，或旁白/对白/选项文案，
  脚本工程里一块一行），所有表记与人名检查都跑在这一份上，行号也来自它。

两份视图都只扫正文：注释与 raw 代码不算正文（它们本来就允许半角与各种符号），不参与检查。

已知边界（诚实清单，全部体现在返回的 ``notes`` 里）
--------------------------------------------------
- 人名变体只报"**首字相同**、与已知名字只差一个字符"的写法。首字不同时（``初夏`` 之于
  ``林夏``）无法与正常的另一个词区分，宁可不报。已知别名 / defineName 一律豁免。
- 引号只查 ``「」『』“”‘’（）``；ASCII 的 ``"`` ``'`` 不查（无法与英文引用、代码区分）。
- 视角统计把对白也算进去（对白里的"我"很常见），因此对白密集的章节天然偏"第一人称"。
- 称呼的"收话人"是**推断**出来的（对白里出现的名字 → 本章另一个说话人 → 上一句的说话人），
  推错就会把两段不同关系并成一对；``evidence.resolution`` 里记了每条是怎么推出来的。
- 每章默认只扫前 ``MAX_CHAPTER_CHARS`` 字；被截断的章节会列进 ``coverage``，不假装扫全了。
- 本模块任何路径都不抛异常：坏数据只降级为 coverage 里的一条如实记录。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.agent_context import _blocks_to_plain
from app.core.blocks import walk_blocks
from app.domain.types import VnProject

# --------------------------------------------------------------------------- 参数

MAX_ISSUES_DEFAULT = 200
"""``issues`` 列表的默认条数上限。超出的部分不静默丢弃，而是记进 ``coverage``。"""

MAX_CHAPTER_CHARS = 20000
"""单章参与扫描的正文上限（超出部分不扫，并在 coverage 里如实列出）。

与 ``consistency_scan`` 的"每章截断"同源口径：整本导入的长文本会让逐行正则的开销随章长
线性上涨，而作者更需要知道"尾巴没扫"，而不是拿到一份看起来"全书干净"的报告。
"""

MAX_SAMPLES = 3
"""每条问题里最多引用几个原文片段：够定位即可，不必把 message 撑成一份清单。"""

MIN_VARIANT_COUNT = 2
"""一个"与已知名字只差一个字"的写法至少出现这么多次才报：只出现一次的多半是巧合。"""

MIN_VARIANT_COUNT_SUSPECT = 3
"""没有与正确写法同章并存时，要求更高的出现次数才降级为提示（见 ``name_char_variant_suspect``）。"""

MIN_POV_SIGNAL = 6
"""一章里"第一人称标记 + 第三人称标记"少于这个数就不判视角：样本太少，判了也是噪声。"""

POV_DOMINANCE_RATIO = 1.5
"""一侧标记数达到另一侧的这么多倍，才算"这一章用的是这个视角"。"""

MIN_ADDRESS_EVENTS = 2
MIN_ADDRESS_CHAPTERS = 2
"""一对关系至少要有这么多条称呼证据、且跨这么多章，才谈得上"漂移"。"""

#: severity 排序（error 最前）。数字越小越靠前。
_SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}

#: 只用于「这几条到底算哪一类」的统计分组，不影响判定。
_CATEGORY_LABELS = {
    "typography": "表记",
    "name": "人名",
    "pov": "视角",
    "address": "称呼",
}

# ------------------------------------------------------------- 字符集与正则

_CJK = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_CJK_CHAR_RE = re.compile(f"[{_CJK}]")
_CJK_RUN_RE = re.compile(f"[{_CJK}]+")

#: 参与"半角混用"判断的半角标点。不含引号与破折号/省略号（它们各有单独规则）。
_HALF_PUNCT = ",.;:!?"
#: 与上一行一一对应的全角写法。
_FULL_PUNCT = "，。；：！？"

#: 半角与全角**直接连用**（`,。` / `！?`）：这是最强的混用信号，比"半角挨着汉字"更确定。
_MIXED_PUNCT_RE = re.compile(f"([{_HALF_PUNCT}])([{_FULL_PUNCT}])|([{_FULL_PUNCT}])([{_HALF_PUNCT}])")

#: 半角标点紧贴汉字：中文正文里混用半角标点的典型形态。
_HALF_PUNCT_NEAR_CJK_RE = re.compile(
    f"([{_CJK}])([{_HALF_PUNCT}])|([{_HALF_PUNCT}])([{_CJK}])"
)

_DOTS_RE = re.compile(r"\.{2,}")
_FW_PERIOD_RUN_RE = re.compile(r"。{2,}")
_ELLIPSIS_CJK_RE = re.compile("…{2}")

_DASH_ASCII_RE = re.compile(r"--+")
#: 单独一个 `—`（左右都不是 `—`），且至少有一侧贴着汉字：中文里破折号应写成 `——`。
_SINGLE_EM_DASH_RE = re.compile(f"(?<=[{_CJK}])—(?!—)|(?<!—)—(?=[{_CJK}])")

_FW_DIGIT_RE = re.compile(r"[０-９]")
_HW_DIGIT_RE = re.compile(r"[0-9]")
_FW_LATIN_RE = re.compile(r"[Ａ-Ｚａ-ｚ]")
_HW_LATIN_RE = re.compile(r"[A-Za-z]")

#: 引号/括号配对表。ASCII 的 `"` `'` 不在此列：无法与英文引用、代码区分（见模块说明）。
_QUOTE_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("「", "」"),
    ("『", "』"),
    ("“", "”"),
    ("‘", "’"),
    ("（", "）"),
)
_OPEN_TO_CLOSE = {o: c for o, c in _QUOTE_PAIRS}
_CLOSE_TO_OPEN = {c: o for o, c in _QUOTE_PAIRS}

#: 可以出现在名字前的间隔符（半角空格 / 全角空格 / 各种间隔号）。
_NAME_GAP_CHARS = " 　·・•"

#: 判定"角色名作主语"时，名字前面算作小句开头的字符。
_CLAUSE_BOUNDARY = set("\n。！？…，、；：「『（(」』）)\"'“” \t—")

_FIRST_PERSON_RE = re.compile(r"咱们|我们|咱|我")
#: `其他` / `其它` 里的"他/它"不是第三人称代词，用后顾断言排除。
_THIRD_PERSON_RE = re.compile(r"他们|她们|它们|(?<!其)他|(?<!其)她|(?<!其)它")

#: `_blocks_to_plain` 渲染出来的行首说话人标记（`林夏: ` / `旁白: `）。
_SPEAKER_PREFIX_RE = re.compile(r"^[^:：\n]{1,24}: ")
#: `_blocks_to_plain` 渲染出来的结构标记行（`[scene bg room]`）：不是作者的文字。
_MARKER_LINE_RE = re.compile(r"^\[.*\]$")

# ----------------------------------------------------------------- 称呼模式表

#: 称呼模式表：``(正则, 层级, 展示名)``。
#:
#: 这张表就是"可维护"的那一份：想加一个称呼（比如某个世界观里的「大人」变体），加一行即可。
#: 层级只有两级——``polite``（敬称）/ ``plain``（普通），因为"敬称层级不一致"这件事本身
#: 只需要"更客气 / 不那么客气"的区分；把亲昵度也塞进来只会让误报变多。
ADDRESS_PATTERNS: Tuple[Tuple[str, str, str], ...] = (
    (r"您", "polite", "您"),
    (r"你们", "plain", "你们"),
    (r"你(?!好)", "plain", "你"),
    (
        r"前辈|老师|先生|小姐|女士|大人|殿下|阁下|学长|学姐|部长|社长|课长|教官|医生|大夫",
        "polite",
        "敬称",
    ),
    (r"同学|君|氏|桑", "plain", "同学/君"),
)

#: 能直接跟在名字后面的敬称后缀（`林夏前辈` / `陆然君`）：用来把称呼落到具体的人身上。
_NAME_SUFFIXES: Tuple[Tuple[str, str], ...] = (
    ("前辈", "polite"),
    ("老师", "polite"),
    ("先生", "polite"),
    ("小姐", "polite"),
    ("女士", "polite"),
    ("大人", "polite"),
    ("殿下", "polite"),
    ("阁下", "polite"),
    ("学长", "polite"),
    ("学姐", "polite"),
    ("同学", "plain"),
    ("君", "plain"),
    ("氏", "plain"),
)

_ADDRESS_COMPILED: Tuple[Tuple[re.Pattern, str, str], ...] = tuple(
    (re.compile(p), level, label) for p, level, label in ADDRESS_PATTERNS
)

_LEVEL_LABELS = {"polite": "敬称", "plain": "普通"}
#: 同票时的先后：更客气的一档优先（"这一章到底有没有用敬称"这个判断上，敬称是更明确的信号）。
_LEVEL_RANK = {"polite": 0, "plain": 1}

# ------------------------------------------------------- 问题的 severity/文案

#: 表记类规则的 severity 与固定文案。``headline`` 说明"哪里不对"，``advice`` 说明"怎么改"。
_TYPO_RULES: Dict[str, Dict[str, str]] = {
    "punct_half_full_adjacent": {
        "severity": "warn",
        "headline": "半角与全角标点连用",
        "advice": "同一个标点位置只留一种宽度：中文正文一般用「，」「。」「！」「？」",
    },
    "punct_halfwidth_near_cjk": {
        "severity": "warn",
        "headline": "中文里混入了半角标点",
        "advice": "中文句子里统一用全角标点；英文/数字内部才用半角",
    },
    "digit_width_mixed": {
        "severity": "info",
        "headline": "全角数字与半角数字混用",
        "advice": "数字宽度从全书统一（正文里通常用半角 0-9，随正文风格定）",
    },
    "letter_width_mixed": {
        "severity": "info",
        "headline": "全角字母与半角字母混用",
        "advice": "拉丁字母统一用半角（全角字母只在极少数排版场景才用）",
    },
    "name_spaced_variant": {
        "severity": "warn",
        "headline": "名字内部多了空格或间隔号",
        "advice": "把间隔去掉，写成角色卡里的正式写法",
    },
    "quote_unbalanced": {
        "severity": "error",
        "headline": "引号/括号没有配对",
        "advice": "补齐缺的那一半（对白漏掉收尾引号在导出时会把后面的正文一起吞进台词）",
    },
    "quote_order_illegal": {
        "severity": "warn",
        "headline": "闭合引号出现在对应开引号之前",
        "advice": "检查这一段的引号嵌套顺序",
    },
    "dash_ascii_double": {
        "severity": "warn",
        "headline": "破折号写成了两个半角连字符 `--`",
        "advice": "中文破折号写作「——」（两个全角破折号）",
    },
    "dash_single_em": {
        "severity": "warn",
        "headline": "破折号只写了一个「—」",
        "advice": "中文破折号是「——」两个字符",
    },
    "ellipsis_ascii_dots": {
        "severity": "warn",
        "headline": "省略号写成了半角点号",
        "advice": "中文省略号写作「……」（六个点省略为两个字符）",
    },
    "ellipsis_fullwidth_period": {
        "severity": "warn",
        "headline": "省略号写成了连用的句号",
        "advice": "「。。。」不是省略号：改成「……」",
    },
    "ellipsis_style_mixed": {
        "severity": "info",
        "headline": "同一章里省略号出现了多种写法",
        "advice": "全书统一成「……」一种",
    },
    "name_char_variant": {
        "severity": "warn",
        "headline": "出现了与角色名只差一个字、且与正确写法同章并存的写法",
        "advice": "多半是错别字：改回角色卡里的正式写法（若确实是另一个人，请把他加进角色卡）",
    },
    "name_char_variant_suspect": {
        "severity": "info",
        "headline": "出现了一个与角色名只差一个字的写法（未与正确写法同章出现）",
        "advice": "可能是同一个人的另一种写法，也可能是另一个词：请自行确认",
    },
    "pov_shift": {
        "severity": "warn",
        "headline": "这一章的视角与全书主导视角不一致",
        "advice": "检查是否视角串了；若是有意的视角切换，忽略即可（本判断为启发式）",
    },
    "address_level_drift": {
        "severity": "warn",
        "headline": "同一对关系的敬称层级来回摆",
        "advice": "确认是否有剧情理由（关系变化、场合变化）；若无，统一成一种称呼",
    },
}


def _rule(code: str) -> Dict[str, str]:
    return _TYPO_RULES.get(code) or {
        "severity": "info",
        "headline": code,
        "advice": "",
    }


# ------------------------------------------------------------------- 文本视图


def _chapter_text(ch: Any, project: VnProject) -> str:
    """一章的整章纯文本：优先 ``prose``，没有正文才回落到 ``_blocks_to_plain``。

    与 ``consistency_scan._chapter_source_text`` 同一约定——本作品的主写作面是散文正文，
    只读块会让"用大白话写的章节"整章变成空章（那不是作者没写，是没被看见）。
    """
    prose = str(getattr(ch, "prose", None) or "").strip()
    if prose:
        return prose
    blocks = [b for b in (getattr(ch, "blocks", None) or []) if isinstance(b, dict)]
    if not blocks:
        return ""
    characters = list(getattr(project, "characters", None) or [])
    return str(_blocks_to_plain(blocks, characters) or "").strip()


def _block_author_lines(b: Dict[str, Any]) -> List[str]:
    """一个块里**作者自己写的**文本行（结构标记与 raw 代码都不算）。"""
    btype = str(b.get("type") or "")
    if btype in ("narration", "dialogue"):
        return [str(b.get("text") or "")]
    if btype == "menu":
        out = [str(b.get("prompt") or "")]
        for choice in b.get("choices") or []:
            if isinstance(choice, dict):
                out.append(str(choice.get("text") or ""))
        return out
    return []


def _author_lines(ch: Any) -> List[Tuple[int, str]]:
    """(行号, 原文行) 序列，只含作者写下的文字。

    prose 工程的"行号"就是 prose 的行号；脚本工程的"行号"是块序号（含菜单/分支里的块）。
    两种口径都在问题里如实标出，作者照着能找到位置。
    """
    prose = str(getattr(ch, "prose", None) or "")
    if prose.strip():
        return [(i, line) for i, line in enumerate(prose.splitlines(), start=1) if line.strip()]
    blocks = [b for b in (getattr(ch, "blocks", None) or []) if isinstance(b, dict)]
    out: List[Tuple[int, str]] = []
    for seq, block in enumerate(walk_blocks(blocks), start=1):
        for line in _block_author_lines(block):
            if line.strip():
                out.append((seq, line))
    return out


def _pov_corpus(text: str) -> str:
    """视角统计用的语料：去掉块渲染器的结构标记与行首说话人标记。

    为什么要在意这两个标记：``林夏: 「……」`` 里的名字是**说话人标注**，不是"角色名作主语"；
    不去掉的话，对白越多的章节越会被算成"第三人称作主语多"，而这与实际视角无关。
    """
    out: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _MARKER_LINE_RE.match(line):
            continue
        out.append(_SPEAKER_PREFIX_RE.sub("", line))
    return "\n".join(out)


def _quote_span(line: str, start: int, end: int, *, pad: int = 6) -> str:
    """取匹配处的上下文片段（原样引用给作者看）。换行折成空格，压掉连续空白。"""
    lo = max(0, start - pad)
    hi = min(len(line), end + pad)
    fragment = line[lo:hi]
    return re.sub(r"\s+", " ", fragment).strip()


def _near_cjk(line: str, start: int, end: int, *, gap: int = 2) -> bool:
    """匹配片段的左右邻域里有没有汉字。

    用来把"英文句子里的 ``...``"排除掉：省略号/破折号规则只对中文语境成立，
    英文里 ``wait...`` 是正常写法，报出来就是误报。
    """
    left = line[max(0, start - gap):start]
    right = line[end:end + gap]
    return bool(_CJK_CHAR_RE.search(left) or _CJK_CHAR_RE.search(right))


# --------------------------------------------------------------------- 已知专名


def _known_terms(project: VnProject) -> Dict[str, str]:
    """已知专名：归一化写法 → 规范名。

    来源就是作者已经声明过的地方——角色卡的 displayName / defineName / aliases，
    以及世界观条目的 title / keywords。**只要在这里出现过就不算问题**：那是作者自己
    登记的别名，不是错别字。
    """
    known: Dict[str, str] = {}
    for c in getattr(project, "characters", None) or []:
        canon = str(getattr(c, "displayName", "") or getattr(c, "id", "") or "")
        for raw in (getattr(c, "displayName", None), getattr(c, "defineName", None)):
            _add_term(known, raw, canon)
        for alias in getattr(c, "aliases", None) or []:
            _add_term(known, alias, canon)
    for entry in getattr(project, "loreEntries", None) or []:
        canon = str(getattr(entry, "title", "") or "")
        _add_term(known, canon, canon)
        for kw in getattr(entry, "keywords", None) or []:
            _add_term(known, kw, canon or str(kw))
    return known


def _add_term(known: Dict[str, str], raw: Any, canon: str) -> None:
    term = str(raw or "").strip()
    if len(term) < 2:
        # 单字词做"差一个字"的比对毫无意义（满篇都是候选）。
        return
    known.setdefault(term, canon or term)


def _cjk_terms(known: Dict[str, str]) -> List[str]:
    return sorted(
        (t for t in known if _CJK_CHAR_RE.search(t)), key=lambda t: (-len(t), t)
    )


def _spaced_name_re(terms: Sequence[str]) -> Optional[re.Pattern]:
    """构造"名字里被插了空格/间隔号"的匹配式：``林[ 　·]+夏``。

    逐个已知名字生成、而不是泛泛地找"两个汉字中间有空格"：后者会把排版里的正常空格
    全部报出来。只有"去掉这个空格正好等于一个已知专名"才值得提醒。
    """
    alts = []
    for term in terms:
        if len(term) < 2:
            continue
        alts.append(f"[{_NAME_GAP_CHARS}]+".join(re.escape(c) for c in term))
    if not alts:
        return None
    # 长名字排前面：正则择先匹配，长的先试才不会把 `阿林夏` 切成 `林夏`。
    alts.sort(key=len, reverse=True)
    return re.compile("|".join(alts))


# --------------------------------------------------------- A 组：表记逐行扫描


def _line_typography_hits(line: str) -> List[Dict[str, Any]]:
    """一行原文 → 表记类命中（不含引号配对、不含人名：那两类需要按章/按全书看）。"""
    hits: List[Dict[str, Any]] = []
    consumed: set = set()

    for m in _MIXED_PUNCT_RE.finditer(line):
        span = m.span()
        consumed.update(range(span[0], span[1]))
        hits.append(
            {"code": "punct_half_full_adjacent", "quote": _quote_span(line, *span)}
        )

    for m in _HALF_PUNCT_NEAR_CJK_RE.finditer(line):
        start, end = m.span()
        # 半角那一半到底是哪一个字符：两个分支里必有一个非空。
        half_at = start if line[start] in _HALF_PUNCT else end - 1
        if half_at in consumed:
            continue  # 已经作为"半全角连用"报过，不重复计
        if line[half_at] == "." and _in_dot_run(line, half_at):
            continue  # 属于省略号，交给省略号规则
        consumed.add(half_at)
        hits.append(
            {"code": "punct_halfwidth_near_cjk", "quote": _quote_span(line, start, end)}
        )

    for m in _DASH_ASCII_RE.finditer(line):
        hits.append({"code": "dash_ascii_double", "quote": _quote_span(line, *m.span())})

    for m in _SINGLE_EM_DASH_RE.finditer(line):
        hits.append({"code": "dash_single_em", "quote": _quote_span(line, *m.span())})

    for m in _DOTS_RE.finditer(line):
        if not _near_cjk(line, *m.span()):
            continue  # 英文里的 ... 是正常写法
        hits.append({"code": "ellipsis_ascii_dots", "quote": _quote_span(line, *m.span())})

    for m in _FW_PERIOD_RUN_RE.finditer(line):
        if not _near_cjk(line, *m.span()):
            continue
        hits.append(
            {"code": "ellipsis_fullwidth_period", "quote": _quote_span(line, *m.span())}
        )

    return hits


def _in_dot_run(line: str, index: int) -> bool:
    """这个 ``.`` 是不是连点（省略号）的一部分。"""
    left = index > 0 and line[index - 1] == "."
    right = index + 1 < len(line) and line[index + 1] == "."
    return left or right


def _chapter_text_hits(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """一章的逐行命中，附上行号。"""
    out: List[Dict[str, Any]] = []
    for line_no, line in row["lines"]:
        for hit in _line_typography_hits(line):
            out.append({**hit, "line": line_no})
    return out


def _width_hits(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """全角/半角数字、字母的混用（章级判断：只有两种宽度同时出现才算"不一致"）。"""
    text = "\n".join(line for _n, line in row["lines"])
    out: List[Dict[str, Any]] = []
    pairs = (
        ("digit_width_mixed", _FW_DIGIT_RE, _HW_DIGIT_RE),
        ("letter_width_mixed", _FW_LATIN_RE, _HW_LATIN_RE),
    )
    for code, fw_re, hw_re in pairs:
        fw = fw_re.search(text)
        hw = hw_re.search(text)
        if fw is None or hw is None:
            continue
        line_no = _first_line_of(row, fw.group(0)) or _first_line_of(row, hw.group(0))
        out.append(
            {
                "code": code,
                "line": line_no,
                "quote": f"{fw.group(0)} / {hw.group(0)}",
            }
        )
    return out


def _first_line_of(row: Dict[str, Any], needle: str) -> Optional[int]:
    for line_no, line in row["lines"]:
        if needle and needle in line:
            return line_no
    return None


def _quote_hits(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """引号配对与嵌套顺序（章级：对白跨行是正常的，只看单行会误报）。"""
    lines = row["lines"]
    text_parts: List[str] = []
    line_of: List[int] = []
    for line_no, line in lines:
        text_parts.append(line)
        line_of.append(line_no)
    text = "\n".join(text_parts)
    # 每个字符落在哪一行（用来给命中位置反查行号）。
    offsets: List[int] = []
    for i, part in enumerate(text_parts):
        offsets.extend([line_of[i]] * (len(part) + 1))

    counts: Counter = Counter()
    order_issues: List[Dict[str, Any]] = []
    stack: List[Tuple[str, int]] = []
    for index, ch in enumerate(text):
        if ch in _OPEN_TO_CLOSE:
            counts[ch] += 1
            stack.append((ch, index))
        elif ch in _CLOSE_TO_OPEN:
            counts[ch] += 1
            opener = _CLOSE_TO_OPEN[ch]
            if stack and stack[-1][0] == opener:
                stack.pop()
                continue
            # 闭引号没有对应的开引号（含嵌套交叉）：这是能确定的写法错误。
            order_issues.append(
                {
                    "code": "quote_order_illegal",
                    "line": offsets[index] if index < len(offsets) else None,
                    "quote": _quote_span(text, index, index + 1),
                }
            )
            if any(name == opener for name, _pos in stack):
                while stack and stack[-1][0] != opener:
                    stack.pop()
                if stack:
                    stack.pop()

    unbalanced: List[str] = []
    samples: List[str] = []
    for opener, closer in _QUOTE_PAIRS:
        no, nc = counts.get(opener, 0), counts.get(closer, 0)
        if no == nc:
            continue
        unbalanced.append(f"{opener}{closer} {no} 开 / {nc} 闭")
        samples.append(f"{opener}{closer}")
    out = list(order_issues)
    if unbalanced:
        out.append(
            {
                "code": "quote_unbalanced",
                "line": None,
                "quote": "、".join(samples),
                "detail": "；".join(unbalanced),
            }
        )
    return out


def _ellipsis_style_hits(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """同一章里省略号写法混用（`……` 与 `...`/`。。。` 并存）。"""
    text = "\n".join(line for _n, line in row["lines"])
    has_cjk_style = bool(_ELLIPSIS_CJK_RE.search(text))
    others = []
    if _DOTS_RE.search(text):
        others.append("...")
    if _FW_PERIOD_RUN_RE.search(text):
        others.append("。。。")
    if not (has_cjk_style and others):
        return []
    return [
        {
            "code": "ellipsis_style_mixed",
            "line": _first_line_of(row, "…"),
            "quote": f"…… / {'、'.join(others)}",
        }
    ]


# ------------------------------------------------------------ A 组：人名变体


def _one_char_variant(candidate: str, name: str) -> str:
    """"与名字只差一个字符"的三种形态；返回空串表示不构成变体。

    插入/删除**只算名字内部**的：`林夏` 后面多个「的」得到 `林夏的` 是正常语法，
    首尾位置的增删一律排除。替换没有这个限制——两字名字唯一能换的位置就是末字，
    排除它等于放弃最常见的错别字形态。
    """
    if candidate == name or not candidate:
        return ""
    if len(candidate) == len(name):
        diff = sum(1 for a, b in zip(candidate, name) if a != b)
        return "substitute" if diff == 1 else ""
    if len(candidate) == len(name) + 1:
        for i in range(1, len(candidate) - 1):
            if candidate[:i] + candidate[i + 1:] == name:
                return "insert"
        return ""
    if len(candidate) == len(name) - 1:
        for i in range(1, len(name) - 1):
            if name[:i] + name[i + 1:] == candidate:
                return "delete"
        return ""
    return ""


def _variant_hits(
    rows: Sequence[Dict[str, Any]], known: Dict[str, str], cjk_terms: Sequence[str]
) -> Dict[str, Any]:
    """全书扫"与已知名字只差一个字"的候选写法。

    为什么只比**首字相同**的候选：中文名字的错别字绝大多数落在名上（姓通常不会写错），
    而首字也不同的候选（`初夏` 之于 `林夏`）与"另一个正常的词"无法区分，报了就是噪声。
    这个限制写在模块说明里，属于有意为之的取舍。

    返回 ``{候选: {name, kind, count, chapters: {chapterId: [证据]}}}``。
    """
    # 只按 (长度, 首字) 建桶：候选窗口查一次桶就能拿到可能的名字，避免 O(窗口 × 全部名字)。
    buckets: Dict[Tuple[int, str], List[str]] = defaultdict(list)
    for term in cjk_terms:
        buckets[(len(term), term[0])].append(term)
    # 长度差 1 也要能查到（插入/删除形态），所以把三个相邻长度合并成一张查询表。
    lengths = sorted(
        {len(t) for t in cjk_terms}
        | {len(t) - 1 for t in cjk_terms}
        | {len(t) + 1 for t in cjk_terms}
    )
    lookup: Dict[Tuple[int, str], List[str]] = {}
    for length in lengths:
        for first in {t[0] for t in cjk_terms}:
            merged: List[str] = []
            for size in (length, length - 1, length + 1):
                merged.extend(buckets.get((size, first), ()))
            if merged:
                lookup[(length, first)] = merged

    found: Dict[str, Dict[str, Any]] = {}
    exact_cache: Dict[str, bool] = {}
    for row in rows:
        for line_no, line in row["lines"]:
            for run in _CJK_RUN_RE.finditer(line):
                seg = run.group(0)
                for length in lengths:
                    if length <= 1 or length > len(seg):
                        continue
                    for i in range(len(seg) - length + 1):
                        cand = seg[i:i + length]
                        if cand in exact_cache:
                            is_known = exact_cache[cand]
                        else:
                            is_known = cand in known
                            exact_cache[cand] = is_known
                        if is_known:
                            continue
                        for name in lookup.get((length, cand[0]), ()):  # 首字必须相同
                            kind = _one_char_variant(cand, name)
                            if not kind:
                                continue
                            entry = found.setdefault(
                                cand,
                                {
                                    "candidate": cand,
                                    "name": name,
                                    "kind": kind,
                                    "count": 0,
                                    "chapters": defaultdict(list),
                                },
                            )
                            entry["count"] += 1
                            if len(entry["chapters"][row["id"]]) < MAX_SAMPLES:
                                entry["chapters"][row["id"]].append(
                                    {
                                        "line": line_no,
                                        "quote": _quote_span(line, run.start() + i,
                                                            run.start() + i + length),
                                    }
                                )
                            break
    return dict(found)


def _variant_issues(
    rows: Sequence[Dict[str, Any]], known: Dict[str, str], cjk_terms: Sequence[str]
) -> List[Dict[str, Any]]:
    """人名变体问题：同章与正确写法并存 → 提醒；只有孤例 → 降级为提示。"""
    row_by_id = {str(r["id"]): r for r in rows}
    hits = _variant_hits(rows, known, cjk_terms)
    issues: List[Dict[str, Any]] = []
    for cand, entry in sorted(hits.items()):
        name = str(entry["name"])
        canon = known.get(name, name)
        chapters: Dict[str, List[Dict[str, Any]]] = entry["chapters"]
        for cid, samples in sorted(chapters.items(), key=lambda kv: row_by_id[kv[0]]["ordinal"]):
            row = row_by_id[cid]
            chapter_text = "\n".join(line for _n, line in row["lines"])
            co_occurs = name in chapter_text
            count = int(entry["count"])
            if not co_occurs and count < MIN_VARIANT_COUNT_SUSPECT:
                continue
            code = "name_char_variant" if co_occurs else "name_char_variant_suspect"
            if co_occurs and count < MIN_VARIANT_COUNT:
                continue
            rule = _rule(code)
            quote = "、".join(f"『{s['quote']}』" for s in samples[:MAX_SAMPLES])
            if co_occurs:
                tail = f"（全书共 {count} 次）" if count > len(samples) else ""
                message = (
                    f"{_chapter_label(row)}：出现「{cand}」{len(samples)} 处{tail}，"
                    f"它与角色名「{canon}」只差一个字，且这一章里两种写法同时存在"
                    f"——多半是错别字。{rule['advice']}。例如：{quote}"
                )
            else:
                message = (
                    f"{_chapter_label(row)}：出现「{cand}」（全书共 {count} 次），"
                    f"它与角色名「{canon}」只差一个字，但没有和正确写法同时出现过"
                    f"——可能是同一个人的另一种写法，也可能是另一个词。例如：{quote}"
                )
            issues.append(
                _issue(
                    severity=rule["severity"],
                    code=code,
                    category="name",
                    message=message,
                    row=row,
                    line=samples[0]["line"] if samples else None,
                    quote=samples[0]["quote"] if samples else "",
                    evidence={
                        "candidate": cand,
                        "knownName": canon,
                        "editKind": entry["kind"],
                        "candidateCount": count,
                        "sameChapterAsCorrect": co_occurs,
                        "heuristic": True,
                    },
                )
            )
    return issues


# ------------------------------------------------------------------ B 组：视角


def _name_forms(project: VnProject) -> List[str]:
    """用于"角色名作主语"判断的名字写法（只取含汉字的，英文名对中文视角无意义）。"""
    forms = set()
    for c in getattr(project, "characters", None) or []:
        for raw in (getattr(c, "displayName", None), getattr(c, "aliases", None)):
            if isinstance(raw, str):
                values = [raw]
            else:
                values = list(raw or [])
            for v in values:
                t = str(v or "").strip()
                if len(t) >= 2 and _CJK_CHAR_RE.search(t):
                    forms.add(t)
    return sorted(forms, key=lambda t: (-len(t), t))


def _name_subject_count(corpus: str, names: Sequence[str]) -> int:
    """"角色名作主语"的近似计数：名字出现在小句开头（行首，或跟在。，「」等之后）。

    这是启发式：`林夏的同学` 里名字其实是定语，也会被算进来。但反过来
    `我看见了林夏` 里的名字不会被算——那正是我们要区分的。
    """
    if not names:
        return 0
    pattern = re.compile("|".join(re.escape(n) for n in names))
    count = 0
    for m in pattern.finditer(corpus):
        if m.start() == 0 or corpus[m.start() - 1] in _CLAUSE_BOUNDARY:
            count += 1
    return count


def _pov_label(first: int, third: int) -> str:
    if first + third < MIN_POV_SIGNAL:
        return "unclear"
    if first >= third * POV_DOMINANCE_RATIO:
        return "first"
    if third >= first * POV_DOMINANCE_RATIO:
        return "third"
    return "mixed"


_POV_LABELS = {
    "first": "第一人称",
    "third": "第三人称",
    "mixed": "两者相当",
    "unclear": "信号不足",
}


def _pov_report(rows: Sequence[Dict[str, Any]], names: Sequence[str]) -> Dict[str, Any]:
    chapters: List[Dict[str, Any]] = []
    book_first = book_third = 0
    for row in rows:
        corpus = _pov_corpus(str(row["text"]))
        first = len(_FIRST_PERSON_RE.findall(corpus))
        third = len(_THIRD_PERSON_RE.findall(corpus)) + _name_subject_count(corpus, names)
        book_first += first
        book_third += third
        chapters.append(
            {
                "chapterId": row["id"],
                "chapterTitle": row["title"],
                "chapterOrdinal": row["ordinal"],
                "firstPerson": first,
                "thirdPerson": third,
                "pov": _pov_label(first, third),
            }
        )
    dominant = _pov_label(book_first, book_third)
    for ch in chapters:
        ch["deviates"] = bool(
            dominant in ("first", "third") and ch["pov"] in ("first", "third")
            and ch["pov"] != dominant
        )
    return {
        "dominant": dominant,
        "dominantLabel": _POV_LABELS.get(dominant, dominant),
        "bookFirstPerson": book_first,
        "bookThirdPerson": book_third,
        "chapters": chapters,
        "heuristic": True,
    }


def _pov_issues(
    pov: Dict[str, Any], rows: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if pov["dominant"] not in ("first", "third"):
        return []
    row_by_id = {str(r["id"]): r for r in rows}
    issues: List[Dict[str, Any]] = []
    for ch in pov["chapters"]:
        if not ch["deviates"]:
            continue
        row = row_by_id.get(str(ch["chapterId"]))
        if row is None:
            continue
        rule = _rule("pov_shift")
        dominant_label = _POV_LABELS[pov["dominant"]]
        this_label = _POV_LABELS[ch["pov"]]
        message = (
            f"{_chapter_label(row)}：这一章看起来是{this_label}"
            f"（第一人称标记 {ch['firstPerson']} 处 / 第三人称标记 {ch['thirdPerson']} 处），"
            f"而全书主导是{dominant_label}"
            f"（我/我们 {pov['bookFirstPerson']} 处 vs 他/她 + 角色名作主语 {pov['bookThirdPerson']} 处）"
            f"——检查这一章是否视角串了。{rule['advice']}。"
        )
        issues.append(
            _issue(
                severity=rule["severity"],
                code="pov_shift",
                category="pov",
                message=message,
                row=row,
                evidence={
                    "chapterFirstPerson": ch["firstPerson"],
                    "chapterThirdPerson": ch["thirdPerson"],
                    "bookFirstPerson": pov["bookFirstPerson"],
                    "bookThirdPerson": pov["bookThirdPerson"],
                    "dominant": pov["dominant"],
                    "chapterPov": ch["pov"],
                    "heuristic": True,
                },
            )
        )
    return issues


# ------------------------------------------------------------ B 组：称呼漂移


def _character_names(project: VnProject) -> Dict[str, str]:
    """characterId → 展示名。"""
    return {
        str(getattr(c, "id", "")): str(getattr(c, "displayName", "") or getattr(c, "id", ""))
        for c in getattr(project, "characters", None) or []
    }


def _name_to_id(project: VnProject) -> Dict[str, str]:
    """已知写法（含别名）→ characterId，用于把称呼里的名字落回具体角色。"""
    out: Dict[str, str] = {}
    for c in getattr(project, "characters", None) or []:
        cid = str(getattr(c, "id", ""))
        for raw in [getattr(c, "displayName", None), getattr(c, "defineName", None)]:
            _add_name_id(out, raw, cid)
        for alias in getattr(c, "aliases", None) or []:
            _add_name_id(out, alias, cid)
    return out


def _add_name_id(out: Dict[str, str], raw: Any, cid: str) -> None:
    term = str(raw or "").strip()
    if len(term) >= 2:
        out.setdefault(term, cid)


def _address_terms(
    text: str, name_to_id: Dict[str, str]
) -> List[Dict[str, Any]]:
    """一段台词里的称呼用语：``[{level, term, addressee, span}]``。

    顺序很重要：先按名字（长的先试）匹配，再匹配泛称，这样 `林夏同学` 只记一条
    "名字 + 敬称"，不会被 `同学` 再记一遍，也不会漏掉它指的是谁。
    """
    out: List[Dict[str, Any]] = []
    consumed: List[Tuple[int, int]] = []

    for name in sorted(name_to_id, key=lambda t: (-len(t), t)):
        for m in re.finditer(re.escape(name), text):
            if any(s <= m.start() < e for s, e in consumed):
                continue
            tail = text[m.end():m.end() + 3]
            suffix = next((s for s, _lv in _NAME_SUFFIXES if tail.startswith(s)), "")
            if suffix:
                level = next(lv for s, lv in _NAME_SUFFIXES if s == suffix)
                span = (m.start(), m.end() + len(suffix))
                out.append(
                    {
                        "level": level,
                        "term": name + suffix,
                        "addressee": name_to_id[name],
                        "span": span,
                    }
                )
            else:
                # 对白里直呼其名：算"普通"一档（是否算称呼有争议，但它是可用的线索）。
                span = (m.start(), m.end())
                out.append(
                    {
                        "level": "plain",
                        "term": name,
                        "addressee": name_to_id[name],
                        "span": span,
                    }
                )
            consumed.append(span)

    for pattern, level, label in _ADDRESS_COMPILED:
        for m in pattern.finditer(text):
            if any(s <= m.start() < e for s, e in consumed):
                continue
            out.append(
                {
                    "level": level,
                    "term": m.group(0),
                    "addressee": "",
                    "span": m.span(),
                    "_label": label,
                }
            )
            consumed.append(m.span())
    return out


def _resolve_addressee(
    terms: Sequence[Dict[str, Any]],
    speaker: str,
    chapter_speakers: Counter,
    prev_speaker: str,
) -> Tuple[str, str]:
    """推断这段话在对谁说：``(被称呼者的 id 或名字, 推断依据)``。

    三级回落（越靠后越不可靠，依据会记进返回里）：
    1. ``name``：台词里出现了别人的名字（最可靠）；
    2. ``two-speaker``：这一章只有两个人说话 → 只能是另一位；
    3. ``previous``：本章上一个说话的人（VN 对白的常见节奏，B 接 A 的话）。
    """
    named = [
        t["addressee"] for t in terms if t.get("addressee") and t["addressee"] != speaker
    ]
    if named:
        return Counter(named).most_common(1)[0][0], "name"
    others = [s for s in chapter_speakers if s != speaker]
    if len(others) == 1:
        return others[0], "two-speaker"
    if prev_speaker and prev_speaker != speaker:
        return prev_speaker, "previous"
    return "", "unknown"


def _dialogue_rows(project: VnProject, wanted: set) -> List[Dict[str, Any]]:
    """按章序取对白行（说话人 + 文本 + 块序）。"""
    out: List[Dict[str, Any]] = []
    for ordinal, ch in enumerate(getattr(project, "chapters", None) or [], start=1):
        cid = str(getattr(ch, "id", "") or "")
        if wanted and cid not in wanted:
            continue
        blocks = [b for b in (getattr(ch, "blocks", None) or []) if isinstance(b, dict)]
        lines: List[Dict[str, Any]] = []
        for seq, b in enumerate(walk_blocks(blocks), start=1):
            if str(b.get("type") or "") != "dialogue":
                continue
            speaker = str(b.get("characterId") or "")
            text = str(b.get("text") or "").strip()
            if speaker and text:
                lines.append({"speaker": speaker, "text": text, "seq": seq})
        if lines:
            out.append(
                {
                    "id": cid,
                    "title": str(getattr(ch, "title", "") or ""),
                    "ordinal": ordinal,
                    "lines": lines,
                }
            )
    return out


def _address_report(project: VnProject, wanted: set) -> Dict[str, Any]:
    """逐对关系的称呼演变（按章序）。"""
    names = _character_names(project)
    name_to_id = _name_to_id(project)
    pairs: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for chapter in _dialogue_rows(project, wanted):
        speakers: Counter = Counter(line["speaker"] for line in chapter["lines"])
        prev = ""
        for line in chapter["lines"]:
            speaker = line["speaker"]
            terms = _address_terms(line["text"], name_to_id)
            addressee, resolution = _resolve_addressee(
                terms, speaker, speakers, prev
            )
            prev = speaker
            if not terms:
                continue
            key = (speaker, addressee)
            row = pairs.setdefault(
                key,
                {
                    "speakerId": speaker,
                    "speaker": names.get(speaker, speaker),
                    "addresseeId": addressee,
                    "addressee": names.get(addressee, addressee) or "（未能判定的对方）",
                    "events": 0,
                    "reliable": 0,
                    "byChapter": {},
                },
            )
            row["events"] += 1
            if resolution in ("name", "two-speaker"):
                row["reliable"] += 1
            bucket = row["byChapter"].setdefault(
                chapter["id"],
                {
                    "chapterId": chapter["id"],
                    "chapterTitle": chapter["title"],
                    "chapterOrdinal": chapter["ordinal"],
                    "levels": Counter(),
                    "order": [],
                    "samples": [],
                    "resolutions": Counter(),
                },
            )
            for t in terms:
                bucket["levels"][t["level"]] += 1
                bucket["order"].append(t["level"])
                if len(bucket["samples"]) < MAX_SAMPLES:
                    bucket["samples"].append(t["term"])
            bucket["resolutions"][resolution] += 1

    rows: List[Dict[str, Any]] = []
    for key, pair in sorted(pairs.items()):
        timeline = []
        for cid, bucket in sorted(
            pair["byChapter"].items(), key=lambda kv: kv[1]["chapterOrdinal"]
        ):
            timeline.append(
                {
                    "chapterId": cid,
                    "chapterTitle": bucket["chapterTitle"],
                    "chapterOrdinal": bucket["chapterOrdinal"],
                    "level": _dominant_level(bucket["levels"], bucket["order"]),
                    "polite": int(bucket["levels"].get("polite", 0)),
                    "plain": int(bucket["levels"].get("plain", 0)),
                    "samples": list(bucket["samples"]),
                    "resolutions": dict(bucket["resolutions"]),
                }
            )
        compressed = _compress_levels(timeline)
        rows.append(
            {
                **{k: pair[k] for k in
                   ("speakerId", "speaker", "addresseeId", "addressee", "events", "reliable")},
                "timeline": timeline,
                "levelSequence": [t["level"] for t in timeline],
                "changes": max(0, len(compressed) - 1),
                "levelRepeats": len(set(compressed)) < len(compressed),
            }
        )
    return {"pairs": rows, "heuristic": True}


def _dominant_level(levels: Counter, order: Sequence[str]) -> str:
    """一章里这一对关系用的是哪一档：票数最多者；同票取"更客气"的一档。

    同票时偏向敬称，是为了让"先您后你"里的那个"您"不被平票吃掉——敬称是更明确的信号。
    """
    if not levels:
        return ""
    best = max(levels.values())
    winners = [lv for lv, n in levels.items() if n == best]
    winners.sort(key=lambda lv: (_LEVEL_RANK.get(lv, 9), order.index(lv) if lv in order else 0))
    return winners[0]


def _compress_levels(timeline: Sequence[Dict[str, Any]]) -> List[str]:
    """把逐章的层级序列压成"变化点"序列（连续相同的章合成一个）。"""
    out: List[str] = []
    for entry in timeline:
        level = str(entry.get("level") or "")
        if not level:
            continue
        if out and out[-1] == level:
            continue
        out.append(level)
    return out


def _address_issues(address: Dict[str, Any], rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    row_by_id = {str(r["id"]): r for r in rows}
    issues: List[Dict[str, Any]] = []
    for pair in address["pairs"]:
        if int(pair["events"]) < MIN_ADDRESS_EVENTS:
            continue
        if int(pair["reliable"]) < MIN_ADDRESS_EVENTS:
            # 收话人全靠"上一句是谁说的"猜出来的关系，不足以谈漂移。
            continue
        if len(pair["timeline"]) < MIN_ADDRESS_CHAPTERS or pair["changes"] < 1:
            continue
        first_change = _first_change_index(pair["timeline"])
        entry = pair["timeline"][first_change]
        row = row_by_id.get(str(entry["chapterId"]))
        if row is None:
            continue
        rule = _rule("address_level_drift")
        sequence = " → ".join(
            f"{_LEVEL_LABELS.get(str(t['level']), t['level'])}（第 {t['chapterOrdinal']} 章）"
            for t in pair["timeline"]
        )
        repeats = bool(pair["levelRepeats"])
        severity = "warn" if repeats else "info"
        why = (
            "层级来回摆（用过的档位又回去了）"
            if repeats
            else "层级单向变了一次（也可能正是剧情推进）"
        )
        message = (
            f"{pair['speaker']} 对 {pair['addressee']} 的称呼：{sequence}——{why}。"
            f"{rule['advice']}。这是**启发式线索**（依据对白里抽出的称呼用语），"
            "需要作者结合剧情判断，不是结论。"
        )
        issues.append(
            _issue(
                severity=severity,
                code="address_level_drift",
                category="address",
                message=message,
                row=row,
                quote="、".join(entry["samples"][:MAX_SAMPLES]),
                evidence={
                    "speaker": pair["speaker"],
                    "addressee": pair["addressee"],
                    "timeline": pair["timeline"],
                    "levelSequence": pair["levelSequence"],
                    "changes": pair["changes"],
                    "levelRepeats": repeats,
                    "heuristic": True,
                },
            )
        )
    return issues


def _first_change_index(timeline: Sequence[Dict[str, Any]]) -> int:
    for i in range(1, len(timeline)):
        if timeline[i]["level"] != timeline[i - 1]["level"]:
            return i
    return 0


# --------------------------------------------------------------------- 组装


def _chapter_label(row: Dict[str, Any]) -> str:
    """`第 3 章「雨夜」`；标题本身已含"第 N 章"时不再重复前缀。"""
    title = str(row.get("title") or "").strip()
    ordinal = int(row.get("ordinal") or 0)
    if title.startswith("第") and "章" in title[:6]:
        return f"「{title}」"
    if title and ordinal:
        return f"第 {ordinal} 章「{title}」"
    if title:
        return f"「{title}」"
    return f"第 {ordinal} 章" if ordinal else "本作品"


def _issue(
    *,
    severity: str,
    code: str,
    category: str,
    message: str,
    row: Optional[Dict[str, Any]] = None,
    line: Optional[int] = None,
    quote: str = "",
    evidence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """统一的问题结构，与 ``branch_analysis._finding`` 同形（前端可复用同一套渲染）。"""
    return {
        "severity": severity,
        "code": code,
        "category": category,
        "message": message,
        "chapterId": str((row or {}).get("id") or ""),
        "chapterTitle": str((row or {}).get("title") or ""),
        "chapterOrdinal": int((row or {}).get("ordinal") or 0),
        "line": line,
        "quote": quote,
        "evidence": evidence or {},
    }


def _grouped_issues(
    hits: Sequence[Dict[str, Any]], row: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """把一章里同 code 的命中合成一条问题：证据给几个样本，条数给全。

    为什么不逐处报：一部 30 万字的稿子里"半角逗号"可能有几百处，逐条报既淹没其它问题，
    也会把 ``max_issues`` 的额度全部吃掉。合并不丢信息——处数与样本都在，位置取最早一处。
    """
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for hit in hits:
        buckets[str(hit["code"])].append(hit)
    issues: List[Dict[str, Any]] = []
    for code, items in sorted(buckets.items()):
        rule = _rule(code)
        items.sort(key=lambda h: (h.get("line") or 0))
        detail = str(items[0].get("detail") or "") if code == "quote_unbalanced" else ""
        samples = "、".join(f"『{h['quote']}』" for h in items[:MAX_SAMPLES] if h.get("quote"))
        message = (
            f"{_chapter_label(row)}：{rule['headline']}，共 {len(items)} 处"
            + (f"（{detail}）" if detail else "")
            + (f"。例如：{samples}" if samples else "")
            + f"。{rule['advice']}。"
        )
        issues.append(
            _issue(
                severity=rule["severity"],
                code=code,
                category="typography",
                message=message,
                row=row,
                line=items[0].get("line"),
                quote=items[0].get("quote") or "",
                evidence={
                    "occurrences": len(items),
                    "samples": [h.get("quote") for h in items[:MAX_SAMPLES]],
                    "lines": sorted({h.get("line") for h in items if h.get("line")}),
                },
            )
        )
    return issues


def _chapter_rows(
    project: VnProject, *, chapter_char_cap: int, focus: str
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """有正文的章节行 + 取数过程中的如实记录（被 focus 排除的、没正文的、解析失败的）。"""
    chapters = list(getattr(project, "chapters", None) or [])
    key = (focus or "").strip().lower()
    rows: List[Dict[str, Any]] = []
    focus_dropped: List[str] = []
    without_text: List[str] = []
    truncated: List[str] = []
    unscanned: List[str] = []
    errors: List[Dict[str, str]] = []

    for ordinal, ch in enumerate(chapters, start=1):
        cid = str(getattr(ch, "id", "") or "")
        title = str(getattr(ch, "title", "") or "")
        if key and key not in cid.lower() and key not in title.lower():
            focus_dropped.append(cid)
            continue
        try:
            text = _chapter_text(ch, project)
            lines = _author_lines(ch)
        except Exception as exc:  # noqa: BLE001 — 一章解析失败不该让整轮检查没有结果
            errors.append({"chapterId": cid, "error": str(exc)})
            unscanned.append(cid)
            continue
        if not lines:
            # 没有作者文字的章节（只有 label/scene 这类结构块）不算"已检查"：
            # 把它算进来会让 coverage 看起来扫了很多章，其实一个字都没看。
            without_text.append(cid)
            continue
        cap = max(0, int(chapter_char_cap))
        full_chars = len(text)
        trimmed = False
        if cap > 0:
            if len(text) > cap:
                text = text[:cap]
                trimmed = True
            kept: List[Tuple[int, str]] = []
            used = 0
            for line_no, line in lines:
                if used + len(line) > cap:
                    trimmed = True
                    break
                kept.append((line_no, line))
                used += len(line) + 1
            lines = kept
        if trimmed:
            truncated.append(cid)
        rows.append(
            {
                "id": cid,
                "title": title,
                "ordinal": ordinal,
                "text": text,
                "lines": lines,
                "fullChars": full_chars,
                "scannedChars": len(text),
            }
        )
    meta = {
        "focusDroppedChapters": focus_dropped,
        "chaptersWithoutText": without_text,
        "textTruncatedChapters": truncated,
        "unscannedChapters": unscanned,
        "textErrors": errors,
    }
    return rows, meta


def _counts(issues: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    by_severity: Counter = Counter(str(i["severity"]) for i in issues)
    by_code: Counter = Counter(str(i["code"]) for i in issues)
    by_category: Counter = Counter(str(i["category"]) for i in issues)
    return {
        "total": len(issues),
        "bySeverity": {k: by_severity.get(k, 0) for k in ("error", "warn", "info")},
        "byCode": dict(sorted(by_code.items())),
        "byCategory": dict(sorted(by_category.items())),
    }


def _summary(
    coverage: Dict[str, Any], counts: Dict[str, Any], pov: Dict[str, Any]
) -> str:
    total = int(coverage["chaptersTotal"])
    if total <= 0:
        return "作品还没有章节，没有可检查的正文。"
    scanned = int(coverage["chaptersScanned"])
    if scanned <= 0:
        if coverage["focusApplied"]:
            return (
                f"focus「{coverage['focus']}」没有匹配任何章节"
                f"（{total} 章全部被排除），本轮没有检查任何内容。"
            )
        return (
            f"作品有 {total} 章，但都没有散文正文，也没有可读的脚本正文"
            "（注释与 raw 代码不算正文），本轮没有可检查的内容。"
        )
    head = f"全书 {total} 章，扫了 {scanned} 章"
    if not counts["total"]:
        return (
            f"{head}：表记、视角与称呼都没有发现需要改的地方"
            "（视角与称呼是启发式检查，只代表「没发现线索」，不等于「一定没问题」）。"
        )
    sev = counts["bySeverity"]
    cat = counts["byCategory"]
    detail = [
        f"{_CATEGORY_LABELS.get(name, name)} {cat[name]} 条"
        for name in ("typography", "name", "pov", "address")
        if cat.get(name)
    ]
    parts = [
        f"发现 {counts['total']} 条线索（错误 {sev['error']} / 提醒 {sev['warn']} / 提示 {sev['info']}）",
    ]
    if detail:
        parts.append("、".join(detail))
    if pov["dominant"] in ("first", "third"):
        parts.append(f"全书主导视角推断为{pov['dominantLabel']}")
    tail = "；".join(parts)
    extra: List[str] = []
    if coverage["issuesTruncated"]:
        extra.append(f"另有 {coverage['issuesTruncated']} 条超出 max_issues 未列出")
    if coverage["textTruncatedChapters"]:
        extra.append(
            f"{len(coverage['textTruncatedChapters'])} 章正文超过每章上限，尾部未扫"
        )
    if coverage["focusDroppedChapters"]:
        extra.append(f"focus 排除了 {len(coverage['focusDroppedChapters'])} 章")
    if extra:
        tail += "（" + "；".join(extra) + "）"
    return f"{head}：{tail}。"


def _notes(
    project: VnProject,
    coverage: Dict[str, Any],
    pov: Dict[str, Any],
    chapter_char_cap: int,
) -> List[str]:
    notes = [
        "A 组（表记/写法）是确定性规则：纯本地正则，不联网、不调模型，同一份稿子每次结果一致。",
        "B 组（视角/称呼）是启发式线索，不是结论：视角切换、敬称变化本身都可能是作者有意为之。",
        f"视角判定 = 逐章统计第一人称（我/我们/咱）与第三人称（他/她/他们 + 角色名出现在小句开头）"
        f"的出现强度，一侧达到另一侧的 {POV_DOMINANCE_RATIO:g} 倍才算该视角；"
        f"两者都少于 {MIN_POV_SIGNAL} 处时给出「信号不足」，不判。"
        "已知偏差：对白里的“我”也计入，所以对白密集的章节天然偏第一人称。",
        "称呼漂移只比较「敬称 / 普通」两档，模式表（ADDRESS_PATTERNS）可自行扩充；"
        "收话人是推断出来的（对白里的名字 → 本章另一个说话人 → 上一句的说话人），"
        "只有名字/双人场景推断出的证据才用来判漂移，evidence.timeline 里能逐章核对。",
        "人名变体只找“首字相同、与已知名字只差一个字符”的写法：首字不同的写法（如「初夏」之于"
        "「林夏」）与正常词汇无法区分，宁可不报。角色卡的别名/defineName 与世界观条目的"
        "标题/触发词都算已知写法，不会误报。",
        "引号只查「」『』“”‘’（）：ASCII 的 \" 与 ' 无法与英文引用、代码区分，不查。",
        "只扫正文（prose 行，或旁白/对白/选项文案）：注释与 raw 代码不算正文。"
        "脚本工程的“行号”是块序号（含菜单/分支内的块）。",
    ]
    if coverage["textTruncatedChapters"]:
        notes.append(
            f"本轮有 {len(coverage['textTruncatedChapters'])} 章超过每章 {chapter_char_cap} 字上限，"
            "只扫了前一段：这些章节的尾部没有进入检查。"
        )
    if coverage["textErrors"]:
        notes.append(f"有 {len(coverage['textErrors'])} 章正文解析失败，已跳过（见 coverage.textErrors）。")
    if pov["dominant"] not in ("first", "third"):
        notes.append("全书主导视角不明确（各章信号相当或太少），本轮不报视角偏移。")
    if not (getattr(project, "characters", None) or []):
        notes.append("作品还没有角色卡，人名变体与称呼漂移没有“已知写法”可对照，这两项不会产出结论。")
    return notes


# --------------------------------------------------------------------- 主入口


def analyze_novel_consistency(
    project: VnProject,
    *,
    focus: str = "",
    max_issues: int = MAX_ISSUES_DEFAULT,
    chapter_char_cap: int = MAX_CHAPTER_CHARS,
) -> Dict[str, Any]:
    """一书一次，跑完表记（确定性）与视角/称呼（启发式）两组检查。

    - ``focus``：只检查章标题或章 id 包含该子串的章节（大小写不敏感）。被排除的章节
      会列进 ``coverage.focusDroppedChapters``，不会悄悄变成"已检查且没问题"。
    - ``max_issues``：``issues`` 列表的条数上限。超额部分不静默丢弃——``counts`` 仍然按
      **全部检出**统计，差额记在 ``coverage.issuesTruncated`` 并在 summary 里说明。
    - ``chapter_char_cap``：单章扫描上限（<= 0 表示不限）；被截断的章节列进
      ``coverage.textTruncatedChapters``。

    返回 ``issues / counts / summary / coverage / notes``，另有 ``pov`` 与 ``address``
    两个明细段（逐章视角表、逐对关系的称呼演变），便于前端直接展开。任何路径都不抛异常。
    """
    rows, meta = _chapter_rows(
        project, chapter_char_cap=chapter_char_cap, focus=focus
    )
    wanted = {str(r["id"]) for r in rows}
    known = _known_terms(project)
    cjk_terms = _cjk_terms(known)

    findings: List[Dict[str, Any]] = []

    # A 组：逐章表记 + 人名
    spaced_re = _spaced_name_re(cjk_terms)
    for row in rows:
        hits = _chapter_text_hits(row)
        hits.extend(_width_hits(row))
        hits.extend(_quote_hits(row))
        hits.extend(_ellipsis_style_hits(row))
        if spaced_re is not None:
            for line_no, line in row["lines"]:
                for m in spaced_re.finditer(line):
                    text = m.group(0)
                    if text in known:
                        continue  # 作者登记的别名本身带间隔号 → 不是问题
                    hits.append(
                        {
                            "code": "name_spaced_variant",
                            "line": line_no,
                            "quote": text,
                            "detail": (
                                "应为「"
                                + re.sub(f"[{_NAME_GAP_CHARS}]+", "", text)
                                + "」"
                            ),
                        }
                    )
        findings.extend(_grouped_issues(hits, row))
    findings.extend(_variant_issues(rows, known, cjk_terms))

    # B 组：视角与称呼
    names = _name_forms(project)
    pov = _pov_report(rows, names)
    findings.extend(_pov_issues(pov, rows))
    address = _address_report(project, wanted)
    findings.extend(_address_issues(address, rows))

    # 排序与截断
    findings.sort(
        key=lambda i: (
            _SEVERITY_ORDER.get(str(i["severity"]), 3),
            int(i.get("chapterOrdinal") or 0),
            str(i["code"]),
            int(i.get("line") or 0),
        )
    )
    limit = max(0, int(max_issues))
    reported = findings[:limit]
    counts = _counts(findings)

    total_chapters = len(list(getattr(project, "chapters", None) or []))
    scanned = len(rows)
    with_text = scanned + len(meta["chaptersWithoutText"])
    coverage: Dict[str, Any] = {
        "chaptersTotal": total_chapters,
        "chaptersScanned": scanned,
        # 口径与 consistency_scan 一致：分母是"本章范围内有正文的章节"，比值如实反映扫了多少。
        "chaptersWithText": with_text,
        "coverageRatio": round(scanned / with_text, 4) if with_text else 0.0,
        "chaptersWithoutText": meta["chaptersWithoutText"],
        "chapterCharCap": max(0, int(chapter_char_cap)),
        "textTruncatedChapters": meta["textTruncatedChapters"],
        "textErrors": meta["textErrors"],
        "focusApplied": bool((focus or "").strip()),
        "focus": (focus or "").strip(),
        "focusDroppedChapters": meta["focusDroppedChapters"],
        "unscannedChapters": meta["unscannedChapters"],
        "maxIssues": limit,
        "issuesFound": len(findings),
        "issuesReported": len(reported),
        "issuesTruncated": max(0, len(findings) - limit),
        "truncated": bool(
            meta["textTruncatedChapters"]
            or meta["unscannedChapters"]
            or meta["textErrors"]
            or len(findings) > limit
        ),
    }

    return {
        "issues": reported,
        "counts": counts,
        "summary": _summary(coverage, counts, pov),
        "coverage": coverage,
        "notes": _notes(project, coverage, pov, max(0, int(chapter_char_cap))),
        "pov": pov,
        "address": address,
        "focus": coverage["focus"],
    }

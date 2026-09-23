"""轻小说写作技艺度量：注音标记、拟声/感叹、章末钩子、可读性事实。

为什么需要它
------------
既有量具各自只覆盖一层：`voice_fingerprint` 量"角色像不像本人"，
`story_metrics` 量伏笔回收与情感弧线，`writing_stats` 量字数/进度。
而轻小说作者每天真正要盯的**技法层事实**一个都没被量过：

1. **注音（ruby）标记**：`｜汉字《かんじ》` 与 `{汉字|注音}` 是轻小说排版的组成部分。
   少一个 `》`、把 `|` 打成 `｜`、同一汉字这次注 `ゆきな` 下次注 `ゆきの`——
   在几万字里人眼几乎查不全，而这类错在读者那里会直接变成"读错音"或"莫名的书名号"。
2. **拟声/拟态词与感叹号密度**：这是"文风浓度"目前唯一客观的读数。本模块**只报事实**，
   不评判好坏——用多少拟声词是作者的选择；但如果某一章突然比其它章高 5 倍，
   那多半不是选择，是没顾上。
3. **章末钩子（引き）强度**：轻小说按话连载，章末那一段决定读者点不点下一话。
   本模块给一个**确定性启发式**评分（4 项加权），并把每一项依据写出来，
   方便作者直接反驳"这条不成立"。
4. **可读性事实**：地の文/对白占比、平均段落长度、长段落占比、连续对白行数上限。
   这些是"读起来累不累"最接近的可计算代理量。

零模型：本模块**不联网、不调任何模型**，纯 stdlib 统计（与 `voice_fingerprint` 同一路线），
因此能进单元测试、能逐章跑、能当回归量具。同一输入永远同一输出。

口径（先说清楚再算）
--------------------
- **正文字数**用 `services.writing_stats.count_words`：CJK 逐字 + 拉丁词算 1，
  与写作面板显示的字数完全一致（同一处实现，不另立一套）。
- **正文来源**：一章有 `prose` 就只量 `prose`，没有才量 `blocks`——
  与 `count_chapter_words` 同一口径。为什么不是两者相加：blocks 通常由 prose 生成，
  相加会把同一段内容数两遍。逐章结果里的 `source` 字段会写明这一章量的是哪一种。
- **没有直接复用 `agent_context._blocks_to_plain`**：它把对白与旁白都渲染成一行文本
  （`旁白: …` / `名字: …`），而本模块的占比统计**必须**区分这两者，且它不递归进
  菜单选项/if 分支正文。遍历语义改用 `core.blocks.walk_blocks`（含分支正文，见该模块说明）。
- **选项文本单列**：菜单的 prompt 与 choices 记为 `choice`，计入总字数但**不进**
  对白/叙述占比（选项既可能是主角说话，也可能是动作，按对白算会污染占比）。

已知边界（诚实标注）
--------------------
- 注音只认**两种显式写法**。裸 `《…》` 一律当书名号看待，只给 info 提示、不计入注音密度
  ——本项目自身就用 `《书名》`（见 `core/global_memory.py`），把它们算成注音会满屏假警报。
- 同一汉字注音不一致是**全书**比对（跨章）。两种读法出现次数并列时**不下判断**，
  只报"这里有两种读法"，因为此时"哪个是笔误"没有依据。
- 拟声/拟态词表是**人工整理的不完整词表**（见 `ONOMATOPOEIA_GROUPS`），
  包含少量"意译借用词"（心跳/心跳声），口径比纯拟声宽，因此另有 `strictCount`。
- 章末钩子评分是**启发式**，不是文学判断，也不能替代编辑通读。
- 相对提示（偏高/偏低）是**与本书其它章比较**，不是与外部标准比较。
- `blocks` 模式下"段落"= 一个 block（文本框一行量级），因此长段落很少是正常的；
  只有 prose 写作的稿子才反映真实段落长度。

纯确定性：无随机数、无时间戳、无模型调用（`updatedAt` 之类字段一概不读）。
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.blocks import walk_blocks
from app.domain.types import VnProject

# ---------------------------------------------------------------- 正文单元

KIND_DIALOGUE = "dialogue"
KIND_NARRATION = "narration"
KIND_CHOICE = "choice"


@dataclass
class ProseUnit:
    """一章里的一段正文单元：对白一条 / 叙述一段 / 选项一条。

    为什么要有"单元"这一层：占比、段落长度、连续对白行数都要求**保持原有顺序**
    且能区分对白与叙述，直接拼成一大段纯文本后这些信息就丢了。
    """

    kind: str
    text: str
    speaker: str = ""


# ---------------------------------------------------------------- 注音（ruby）

RUBY_FORM_BAR = "bar"
"""日式写法：`｜汉字《かんじ》`（`｜` 标出基准词的起点）。"""

RUBY_FORM_BRACE = "brace"
"""花括号写法：`{汉字|注音}`。"""

ISSUE_RUBY_UNCLOSED_BRACKET = "ruby_unclosed_bracket"
ISSUE_RUBY_UNCLOSED_BRACE = "ruby_unclosed_brace"
ISSUE_RUBY_PIPE_MISMATCH = "ruby_pipe_mismatch"
ISSUE_RUBY_MISSING_SEPARATOR = "ruby_missing_separator"
ISSUE_RUBY_EMPTY_READING = "ruby_empty_reading"
ISSUE_RUBY_EMPTY_BASE = "ruby_empty_base"
ISSUE_RUBY_INCONSISTENT = "ruby_inconsistent_reading"
ISSUE_RUBY_READING_WITHOUT_BASE = "ruby_reading_without_base"
ISSUE_RUBY_DENSITY_HIGH = "ruby_density_high"

SEVERITY_WARN = "warn"
"""作者大概率要改的（未闭合 / 注音为空 / 分隔符数量不对 / 前后不一致）。"""

SEVERITY_INFO = "info"
"""只提一句的（可能是别的用法，或只是密度异常高）。"""

MAX_RUBY_BASE_CHARS = 24
"""基准词最长这么多字；更长的 `｜…《…》` 不再按注音解析（避免把整句吞成基准词）。"""

RUBY_DENSITY_INFO_PER_1000 = 25.0
"""每千字注音标记数超过它就给一条 info。

**手调阈值**，不是行业标准：按"平均每 40 字一处注音"定的经验值。
"""

MAX_TITLE_LIKE_ISSUES_PER_CHAPTER = 5
"""每章最多报几条"裸《…》"提示：书名号可能成百上千，全报会把真问题淹掉。"""

MAX_RUBY_ISSUES = 200
"""返回的注音问题总上限；超出部分靠 `coverage.rubyIssuesTruncated` 如实告知。"""

MAX_RUBY_MARKS_SHOWN = 40
"""逐章回显的注音标记条数上限（只影响展示，不影响计数）。"""

_BAR_RE = re.compile(r"[｜|](?P<base>[^｜|《》{}\n]{1,24})《(?P<reading>[^《》\n]*)》")
_BAR_EMPTY_BASE_RE = re.compile(r"[｜|]《(?P<reading>[^《》\n]*)》")
_BRACE_RE = re.compile(r"\{(?P<inner>[^{}\n]*)\}")
_BRACE_PIPE_RE = re.compile(r"[|｜]")
_TITLE_RE = re.compile(r"《[^》\n]*》")


def _snippet(text: str, column: int, *, span: int = 12) -> str:
    """问题位置周围的上下文（column 是 1 起的字符下标）。"""
    i = max(0, column - 1)
    lo = max(0, i - span)
    hi = min(len(text), i + span)
    head = "…" if lo > 0 else ""
    tail = "…" if hi < len(text) else ""
    return f"{head}{text[lo:hi]}{tail}"


def _bracket_problems(text: str, open_ch: str, close_ch: str) -> List[Tuple[int, str]]:
    """返回 (位置, 类型) 列表；类型 = unclosed_open（多出来的开符）/ extra_close。"""
    stack: List[int] = []
    problems: List[Tuple[int, str]] = []
    for i, ch in enumerate(text):
        if ch == open_ch:
            stack.append(i)
        elif ch == close_ch:
            if stack:
                stack.pop()
            else:
                problems.append((i, "extra_close"))
    problems.extend((pos, "unclosed_open") for pos in stack)
    problems.sort()
    return problems


def _issue(
    code: str,
    severity: str,
    message: str,
    *,
    chapter_id: str,
    chapter_title: str,
    line: Optional[int],
    column: Optional[int],
    snippet: str = "",
    **extra: Any,
) -> Dict[str, Any]:
    """统一的问题行结构：章节、行、列、上下文、可选的 base/reading/expected。"""
    row: Dict[str, Any] = {
        "code": code,
        "severity": severity,
        "chapterId": chapter_id,
        "chapterTitle": chapter_title,
        "line": line,
        "column": column,
        "snippet": snippet,
        "message": message,
    }
    row.update(extra)
    return row


def _scan_ruby_line(
    text: str, *, chapter_id: str = "", chapter_title: str = "", line: Optional[int] = None
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """扫**一行**正文 → (注音标记, 问题)。标记内部带 span（用于判定裸《》是否已消费）。"""
    line_text = text or ""
    marks: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []

    def issue(code: str, severity: str, message: str, col: int, **kw: Any) -> None:
        issues.append(
            _issue(
                code,
                severity,
                message,
                chapter_id=chapter_id,
                chapter_title=chapter_title,
                line=line,
                column=col,
                snippet=_snippet(line_text, col),
                **kw,
            )
        )

    # 1) 日式写法：｜汉字《注音》
    # bar_spans 记下**所有**日式匹配的区间（包括注音为空这种写坏的）：
    # 否则 `｜雪菜《》` 会被第 4 步再当成"没有基准的《》"报第二遍——
    # 同一个位置两条问题，作者只会觉得量具在乱叫。
    bar_spans: List[Tuple[int, int]] = []
    for m in _BAR_RE.finditer(line_text):
        bar_spans.append((m.start(), m.end()))
        base = (m.group("base") or "").strip()
        reading = (m.group("reading") or "").strip()
        col = m.start() + 1
        if not reading:
            issue(
                ISSUE_RUBY_EMPTY_READING,
                SEVERITY_WARN,
                f"注音为空：`｜{base}《》` 里的括号是空的，导出时读者只会看到汉字",
                col,
                form=RUBY_FORM_BAR,
                base=base,
                reading="",
            )
            continue
        marks.append(
            {
                "form": RUBY_FORM_BAR,
                "base": base,
                "reading": reading,
                "column": col,
                "span": (m.start(), m.end()),
            }
        )

    # 1b) ｜《注音》：基准词为空
    for m in _BAR_EMPTY_BASE_RE.finditer(line_text):
        reading = (m.group("reading") or "").strip()
        issue(
            ISSUE_RUBY_EMPTY_BASE,
            SEVERITY_WARN,
            "注音缺少基准词：`｜` 后面直接接《》，没有要注音的汉字",
            m.start() + 1,
            form=RUBY_FORM_BAR,
            base="",
            reading=reading,
        )

    # 2) 花括号写法：{汉字|注音}
    for m in _BRACE_RE.finditer(line_text):
        inner = m.group("inner") or ""
        parts = [p.strip() for p in _BRACE_PIPE_RE.split(inner)]
        col = m.start() + 1
        if len(parts) == 1:
            issue(
                ISSUE_RUBY_MISSING_SEPARATOR,
                SEVERITY_INFO,
                "花括号里没有 `|` 分隔符：若这是注音请写成 `{汉字|注音}`，"
                "若只是普通花括号文本可以忽略本条",
                col,
                form=RUBY_FORM_BRACE,
                raw=inner,
            )
            continue
        if len(parts) != 2:
            issue(
                ISSUE_RUBY_PIPE_MISMATCH,
                SEVERITY_WARN,
                f"`|` 数量不匹配：花括号里有 {len(parts) - 1} 个分隔符，"
                "注音应当是 `{汉字|注音}` 恰好一个",
                col,
                form=RUBY_FORM_BRACE,
                raw=inner,
            )
            continue
        base, reading = parts
        if not base:
            issue(
                ISSUE_RUBY_EMPTY_BASE,
                SEVERITY_WARN,
                "注音缺少基准词：`{|注音}` 里没有要注音的汉字",
                col,
                form=RUBY_FORM_BRACE,
                base="",
                reading=reading,
            )
            continue
        if not reading:
            issue(
                ISSUE_RUBY_EMPTY_READING,
                SEVERITY_WARN,
                f"注音为空：`{{{base}|}}` 里的注音是空的，导出时读者只会看到汉字",
                col,
                form=RUBY_FORM_BRACE,
                base=base,
                reading="",
            )
            continue
        marks.append(
            {
                "form": RUBY_FORM_BRACE,
                "base": base,
                "reading": reading,
                "column": col,
                "span": (m.start(), m.end()),
            }
        )

    # 3) 《》未闭合（含多出来的 》，两者都会让整段注音失效）
    bracket_problems = _bracket_problems(line_text, "《", "》")
    if bracket_problems:
        pos, kind = bracket_problems[0]
        detail = (
            "`《` 没有闭合的 `》`"
            if kind == "unclosed_open"
            else "多出一个 `》`（前面没有配对的 `《`）"
        )
        issue(
            ISSUE_RUBY_UNCLOSED_BRACKET,
            SEVERITY_WARN,
            f"《》不配对：{detail}"
            + (f"（本行共 {len(bracket_problems)} 处）" if len(bracket_problems) > 1 else ""),
            pos + 1,
        )

    # 3b) {} 未闭合（注音用的花括号漏了闭括号）
    brace_problems = _bracket_problems(line_text, "{", "}")
    if brace_problems:
        pos, kind = brace_problems[0]
        detail = "`{` 没有闭合的 `}`" if kind == "unclosed_open" else "多出一个 `}`"
        issue(
            ISSUE_RUBY_UNCLOSED_BRACE,
            SEVERITY_WARN,
            f"花括号不配对：{detail}（若这是注音标记，注音会失效）",
            pos + 1,
        )

    # 4) 裸《…》：没有 ｜ 基准，也没有被花括号包住——按书名号提示，不当注音
    consumed: List[Tuple[int, int]] = list(bar_spans)

    def _consumed(start: int, end: int) -> bool:
        return any(s <= start and end <= e for s, e in consumed)

    for m in _TITLE_RE.finditer(line_text):
        if _consumed(m.start(), m.end()):
            continue
        issue(
            ISSUE_RUBY_READING_WITHOUT_BASE,
            SEVERITY_INFO,
            "《…》前面没有 `｜`：若这是注音请写成 `｜汉字《注音》`；"
            "也可能只是书名号，本条不计入注音密度",
            m.start() + 1,
            text=m.group(0),
        )

    marks.sort(key=lambda mk: mk["column"])
    issues.sort(key=lambda r: (r.get("line") or 0, r.get("column") or 0))
    return marks, issues


def parse_ruby_marks(text: str) -> List[Dict[str, Any]]:
    """解析一行文本里的注音标记，只返回**语法完整**的标记。

    form: `bar` = `｜汉字《注音》`，`brace` = `{汉字|注音}`；
    column 为 1 起的字符下标；base/reading 已去掉首尾空白。
    不完整的写法不在这里返回——它们由 `scan_ruby_issues` 作为问题报出。
    """
    marks, _issues = _scan_ruby_line(text or "")
    return [
        {"form": mk["form"], "base": mk["base"], "reading": mk["reading"], "column": mk["column"]}
        for mk in marks
    ]


def scan_ruby_issues(
    text: str, *, chapter_id: str = "", chapter_title: str = "", line: Optional[int] = None
) -> List[Dict[str, Any]]:
    """一行文本里的注音问题（供单测与手工排查直接调用）。"""
    _marks, issues = _scan_ruby_line(
        text or "", chapter_id=chapter_id, chapter_title=chapter_title, line=line
    )
    return issues


# ------------------------------------------------------ 拟声/拟态词表与感叹统计

#: 人工整理的拟声/拟态词表。**不完整、无权威词表依据**，只是"常见写法"的集合。
#:
#: 维护方式：往对应分类的元组里加词即可，匹配表（`_ONOMATOPOEIA_RE` / `_WORD_GROUP`）
#: 在 import 时按"长词优先"自动重建。约定：
#: - 同一个词只放一组（跨组重复时后写的那组生效，会让计数归类变得莫名其妙）；
#: - `borrowed` 前缀的组是**意译借用词**（如"心跳"对应ドキドキ），口径比纯拟声宽，
#:   因此逐章结果里另有 `strictCount`（不含这些组）；
#: - 单字条目（咚/砰/嗡…）在叠用时会计多次（"咚咚咚" = 咚咚 + 咚 = 2 次），
#:   这是有意的：叠用本身也是信息。
ONOMATOPOEIA_GROUPS: Dict[str, Tuple[str, ...]] = {
    "ja_sound": (
        "ガチャ", "ガチャッ", "ガチャン", "ガタガタ", "ガタン", "バタン", "バタバタ",
        "ドサッ", "ドサドサ", "ドン", "ドーン", "ドンドン", "コツコツ", "コトコト",
        "カチカチ", "チクタク", "カタカタ", "パタパタ", "ぱたぱた", "パタン", "パチパチ",
        "ぱちぱち", "バチバチ", "ばちばち", "ピチャピチャ", "ぴちゃぴちゃ", "ザアザア",
        "ざあざあ", "ザワザワ", "ざわざわ", "ゴロゴロ", "ごろごろ", "グツグツ", "ぐつぐつ",
        "チリン", "リンリン", "ブルブル", "ぶるぶる", "ヒュウ", "ピュウ", "ビュウ",
        "コンコン", "トントン", "カンカン", "チーン", "ガシャン", "メキメキ", "ミシミシ",
        "ギシギシ", "パキッ", "ピシッ", "ビリッ",
    ),
    "ja_motion": (
        "ふらふら", "よろよろ", "こそこそ", "ごそごそ", "すたすた", "どたどた", "ぐるぐる",
        "くるくる", "ゆらゆら", "ふわふわ", "ひらひら", "ぐいぐい", "うろうろ",
        "きょろきょろ", "じろじろ", "のっそり", "ぷるぷる", "ぐんぐん", "ずんずん",
        "ぼんやり", "ぐっすり", "うとうと", "すやすや", "ぐうぐう",
    ),
    "ja_feeling": (
        "ドキドキ", "どきどき", "ドキッ", "どきっ", "ドキンドキン", "わくわく", "そわそわ",
        "はらはら", "いらいら", "イライラ", "むかむか", "ムカムカ", "しくしく", "じわじわ",
        "ぞくぞく", "うるうる", "にこにこ", "にやにや", "しょんぼり", "どんより",
        "はあはあ", "ふうふう",
    ),
    "zh_sound": (
        "啪嗒", "啪哒", "吧嗒", "噼里啪啦", "噼啪", "哗啦", "哗啦啦", "哗哗", "咕噜",
        "咕嘟", "咕咚", "轰隆", "轰隆隆", "隆隆", "叮咚", "叮当", "叮铃", "沙沙", "簌簌",
        "唰", "嗖", "咔嚓", "咔哒", "咔擦", "吱呀", "吱嘎", "噗通", "扑通", "砰", "砰砰",
        "咚", "咚咚", "嗡", "嗡嗡", "滴答", "嘀嗒", "哐当", "当啷", "窸窸窣窣", "呼啦",
        "呼哧", "笃笃", "怦怦",
    ),
    "zh_mimicry": (
        "磨磨蹭蹭", "跌跌撞撞", "晃晃悠悠", "颤颤巍巍", "蹑手蹑脚", "慢慢吞吞",
        "慌慌张张", "匆匆忙忙", "稀里糊涂", "迷迷糊糊", "摇摇晃晃", "歪歪扭扭",
        "软绵绵", "沉甸甸", "静悄悄", "轻飘飘", "暖洋洋", "凉飕飕", "火辣辣", "湿漉漉",
        "黏糊糊", "亮晶晶", "红彤彤", "白茫茫", "黑漆漆", "阴森森", "空荡荡", "闹哄哄",
        "乱糟糟", "懒洋洋", "兴冲冲", "气冲冲",
    ),
    # 意译借用词：日语拟声在中文译文里最常见的对应写法（口径更宽，strictCount 不计）
    "borrowed_heartbeat": ("心跳声", "心跳", "心怦怦"),
}

ONOMATOPOEIA_BORROWED_GROUPS = frozenset({"borrowed_heartbeat"})
"""口径更宽的"意译借用"分组名；`strictCount` 会排除这些组。"""


def _build_onomatopoeia_matcher(
    groups: Dict[str, Tuple[str, ...]]
) -> Tuple[Any, Dict[str, str]]:
    """词表 → (匹配用正则, 词 → 分组)。长词优先，保证"心跳声"不会被"心跳"截断。"""
    pairs = sorted(
        ((word, group) for group, words in groups.items() for word in words),
        key=lambda p: (-len(p[0]), p[0]),
    )
    pattern = re.compile("|".join(re.escape(word) for word, _ in pairs)) if pairs else None
    return pattern, {word: group for word, group in pairs}


_ONOMATOPOEIA_RE, _WORD_GROUP = _build_onomatopoeia_matcher(ONOMATOPOEIA_GROUPS)

_ELLIPSIS_RE = re.compile(r"…+|\.{3,}")
_LONG_DASH_RE = re.compile(r"[—―]{2,}|-{2,}")


def onomatopoeia_hits(text: str) -> List[Dict[str, Any]]:
    """一段文本里命中的拟声/拟态词（不含重叠命中：长词优先，命中区间不重复计数）。"""
    if _ONOMATOPOEIA_RE is None or not text:
        return []
    return [
        {"word": m.group(0), "group": _WORD_GROUP.get(m.group(0), ""), "column": m.start() + 1}
        for m in _ONOMATOPOEIA_RE.finditer(text)
    ]


def onomatopoeia_stats(text: str, *, words: int) -> Dict[str, Any]:
    """一段文本的拟声/拟态与感叹/疑问统计。`words` 是同一段文本的字数（密度分母）。"""
    hits = onomatopoeia_hits(text)
    by_group: Dict[str, int] = {}
    by_word: Dict[str, int] = {}
    strict = 0
    for hit in hits:
        group = str(hit["group"])
        by_group[group] = by_group.get(group, 0) + 1
        by_word[str(hit["word"])] = by_word.get(str(hit["word"]), 0) + 1
        if group not in ONOMATOPOEIA_BORROWED_GROUPS:
            strict += 1

    exclaim = text.count("！") + text.count("!")
    question = text.count("？") + text.count("?")
    ellipsis = len(_ELLIPSIS_RE.findall(text))
    dash = len(_LONG_DASH_RE.findall(text))
    return {
        "onomatopoeia": {
            "count": len(hits),
            "strictCount": strict,
            "per1000Chars": (round(len(hits) / words * 1000, 2) if words else None),
            "byCategory": dict(sorted(by_group.items())),
            "topWords": [
                {"word": w, "count": c}
                for w, c in sorted(by_word.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
            ],
        },
        "punctuation": {
            "exclaim": exclaim,
            "question": question,
            "ellipsis": ellipsis,
            "dash": dash,
            "exclaimPer1000": (round(exclaim / words * 1000, 2) if words else None),
            "questionPer1000": (round(question / words * 1000, 2) if words else None),
        },
    }


# ------------------------------------------------------------ 章末钩子（启发式）

HOOK_WEIGHTS: Dict[str, float] = {
    "endingKind": 0.25,
    "endingLength": 0.20,
    "endingPunctuation": 0.30,
    "ledgerHook": 0.25,
}
"""4 项依据的权重，和为 1。权重是**手调**的：收尾特征与末段类型最能说明"这一话有没有留得住人"，
长度与记账完整度次之。作者完全可以不同意这套权重——所以才把逐项依据一并返回。"""

HOOK_LABELS: Dict[str, str] = {
    "endingKind": "末段类型",
    "endingLength": "末段长度",
    "endingPunctuation": "收尾特征",
    "ledgerHook": "章末钩子记账",
}

HOOK_DISCLAIMER = (
    "启发式评分（0–1）：由末段类型 / 末段长度 / 收尾标点与悬念词 / 账本 closeHook 四项加权得到，"
    "**不是文学判断**，也不代表读者的真实反应；请连同逐项依据一起读，并保留你自己推翻它的权利。"
)

_ENDING_KIND_SCORES: Dict[str, Tuple[float, str]] = {
    KIND_DIALOGUE: (1.0, "末段是对白"),
    KIND_CHOICE: (0.6, "末段是选项（读者被交回决定权）"),
    KIND_NARRATION: (0.4, "末段是叙述"),
}
_ENDING_KIND_EMPTY = (0.0, "本章没有正文，不评分")

_HOOK_LENGTH_BANDS: Tuple[Tuple[int, int, float], ...] = (
    (0, 0, 0.0),
    (1, 3, 0.6),
    (4, 40, 1.0),
    (41, 80, 0.6),
    (81, 10**9, 0.25),
)
"""末段长度 → 分数。钩子偏好在 4–40 字：太短说不出事，太长（一大段）把钩子埋掉了。"""

_HOOK_TAIL_FEATURES: Tuple[Tuple[str, str, float], ...] = (
    ("question", "以问号收尾", 0.45),
    ("ellipsis", "以省略号收尾", 0.40),
    ("dash", "以破折号收尾（话被打断）", 0.35),
    ("exclaim", "以感叹号收尾", 0.20),
)

_HOOK_SUSPENSE_WORDS: Tuple[str, ...] = (
    "但是", "然而", "却", "突然", "忽然", "就在这时", "没想到", "原来", "竟然", "难道",
    "直到", "下一秒", "下一瞬",
)
"""末段出现这些词算一次"悬念/转折提示"。这是**词表**不是语义判断：反用、误用都会计分。"""

HOOK_LEVEL_STRONG = 0.65
HOOK_LEVEL_MEDIUM = 0.40

_TAIL_WRAPPER_RE = re.compile(r"[\s」』”\"'’）)\]】》]+$")


def _tail_features(text: str) -> Tuple[List[str], str]:
    """末段的收尾特征 + 去掉收尾引号后的核心串。"""
    core = _TAIL_WRAPPER_RE.sub("", (text or "").strip())
    keys: List[str] = []
    if re.search(r"[？?]$", core):
        keys.append("question")
    if re.search(r"(?:…|\.{2,})$", core):
        keys.append("ellipsis")
    if re.search(r"[—―]$|-{2,}$", core):
        keys.append("dash")
    if re.search(r"[！!]$", core):
        keys.append("exclaim")
    return keys, core


def _hook_level(score: float, *, has_text: bool) -> str:
    if not has_text:
        return "empty"
    if score >= HOOK_LEVEL_STRONG:
        return "strong"
    if score >= HOOK_LEVEL_MEDIUM:
        return "medium"
    return "weak"


def score_chapter_hook(
    units: Sequence[ProseUnit],
    *,
    close_hook: Optional[str] = None,
    hook_source: str = "none",
    chapter_id: str = "",
    chapter_title: str = "",
) -> Dict[str, Any]:
    """章末钩子的**确定性启发式**评分（0–1）+ 逐项依据。

    `close_hook` 是账本/章摘要里为这一章记下的章末钩子文本（没有就传 None）。
    它进评分是因为"作者自己为这一章记下过钩子"是一个便宜的客观信号；
    但要清楚这一项量的是**记账完整度**，不是文笔——所以依据里写明了它来自哪里。
    """
    last = units[-1] if units else None
    last_text = last.text if last is not None else ""
    has_text = bool(units)
    # 收尾特征先算：(a) 要用它判断"叙述末段是不是悬念句"，(c) 自己也要用
    tail_keys, core = _tail_features(last_text)
    keyword_hits = [w for w in _HOOK_SUSPENSE_WORDS if w in last_text] if last is not None else []
    suspense_like = bool(tail_keys or keyword_hits)

    components: List[Dict[str, Any]] = []

    # (a) 末段类型（对白 / 悬念句 / 普通叙述 / 选项）
    if last is None:
        kind_value, kind_basis = _ENDING_KIND_EMPTY
    elif last.kind == KIND_NARRATION and suspense_like:
        kind_value, kind_basis = (0.7, "末段是叙述，但以疑问/省略/转折收束（悬念句）")
    else:
        kind_value, kind_basis = _ENDING_KIND_SCORES.get(last.kind, (0.4, "末段是叙述"))
    components.append(
        {
            "key": "endingKind",
            "label": HOOK_LABELS["endingKind"],
            "weight": HOOK_WEIGHTS["endingKind"],
            "value": kind_value,
            "basis": kind_basis,
        }
    )

    # (b) 末段长度
    words = _count_words(last_text) if last is not None else 0
    length_value = 0.0
    for lo, hi, band in _HOOK_LENGTH_BANDS:
        if lo <= words <= hi:
            length_value = band
            break
    components.append(
        {
            "key": "endingLength",
            "label": HOOK_LABELS["endingLength"],
            "weight": HOOK_WEIGHTS["endingLength"],
            "value": length_value,
            "basis": (
                f"末段 {words} 字（启发式偏好在 4–40 字）"
                if last is not None
                else "本章没有正文，无从判断末段长度"
            ),
        }
    )

    # (c) 收尾特征：标点 + 悬念词
    hits = [f for f in _HOOK_TAIL_FEATURES if f[0] in tail_keys]
    punctu_score = sum(f[2] for f in hits) + (0.35 if keyword_hits else 0.0)
    punctu_score = min(1.0, punctu_score)
    bits = [f"{f[1]}（+{f[2]:g}）" for f in hits]
    if keyword_hits:
        bits.append("末段出现悬念/转折词「" + "」「".join(keyword_hits[:3]) + "」（+0.35）")
    components.append(
        {
            "key": "endingPunctuation",
            "label": HOOK_LABELS["endingPunctuation"],
            "weight": HOOK_WEIGHTS["endingPunctuation"],
            "value": round(punctu_score, 4),
            "basis": (
                "、".join(bits)
                if bits
                else "末段没有疑问/省略/破折号收尾，也没有出现悬念转折词"
            ),
            "evidence": {"tail": core[-40:], "features": tail_keys, "keywords": keyword_hits},
        }
    )

    # (d) 账本里这一章的 closeHook 是否已填
    hook_text = str(close_hook or "").strip()
    components.append(
        {
            "key": "ledgerHook",
            "label": HOOK_LABELS["ledgerHook"],
            "weight": HOOK_WEIGHTS["ledgerHook"],
            "value": 1.0 if hook_text else 0.0,
            "basis": (
                f"账本/章摘要（{hook_source}）里已填章末钩子：「{hook_text[:60]}」"
                if hook_text
                else "账本/章摘要里这一章没有 closeHook（未入库，或这一章确实是空章）"
            ),
        }
    )

    score = 0.0 if last is None else sum(
        float(c["weight"]) * float(c["value"]) for c in components
    )
    for c in components:
        c["weighted"] = round(float(c["weight"]) * float(c["value"]), 4)

    return {
        "chapterId": chapter_id,
        "chapterTitle": chapter_title,
        "score": round(score, 4),
        "level": _hook_level(score, has_text=has_text),
        "heuristic": True,
        "endingKind": last.kind if last is not None else "empty",
        "endingWords": words,
        "endingTail": last_text[-40:],
        "ledgerCloseHook": hook_text or None,
        "hookSource": hook_source if hook_text else "none",
        "components": components,
        "disclaimer": HOOK_DISCLAIMER,
    }


# ------------------------------------------------------------ 正文提取与可读性

_QUOTE_STARTS: Tuple[str, ...] = ("「", "『", "“", "\"", "‘")
"""prose 模式下"行首是引号 ⇒ 对白"的判据。只认行首：行中间的引号多半是叙述里的引用。"""

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ALNUM_RE = re.compile(r"[A-Za-z0-9]")


def _count_words(text: str) -> int:
    """字数口径复用 `services.writing_stats.count_words`（CJK 逐字 + 拉丁词算 1）。

    懒导入：`core` 层不该在 import 期把 sqlalchemy 一并拉进来
    （`core/snapshot_diff.py` 出于同一理由也是函数内导入）。
    """
    from app.services.writing_stats import count_words

    return count_words(text or "")


def _split_paragraphs(text: str) -> List[str]:
    """块内按**空行**分段：导入正文时一段内的换行是段内换行，空行才换段。"""
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _classify_prose_line(line: str, names: Dict[str, str]) -> Tuple[str, str]:
    """prose 的一行 → (kind, speaker)。

    判据只有两条：行首是引号 ⇒ 对白；行首是**项目里已知的角色名**+冒号 ⇒ 对白。
    两行里既有叙述又有引号的"混合行"只能整行算叙述，因此 prose 模式下的对白占比会**略偏低**
    （已在模块文档里标注；宁可少算一点，也不要靠正则去猜哪半句是台词）。
    """
    stripped = line.strip()
    if stripped.startswith(_QUOTE_STARTS):
        return KIND_DIALOGUE, ""
    for name, display in names.items():
        if not name:
            continue
        for sep in ("：", ":"):
            if stripped.startswith(f"{name}{sep}"):
                return KIND_DIALOGUE, display or name
    return KIND_NARRATION, ""


def _units_from_prose(prose: str, names: Dict[str, str]) -> List[ProseUnit]:
    """prose → 正文单元。**一行一段**：网文/轻小说的常见排版就是一行一段，
    按空行分段会把整章并成一个"段落"，段落长度指标就废了。"""
    units: List[ProseUnit] = []
    for raw in (prose or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        kind, speaker = _classify_prose_line(line, names)
        units.append(ProseUnit(kind, line, speaker))
    return units


def _character_names(project: VnProject) -> Dict[str, str]:
    """一切已知叫法 → 显示名（id / defineName / displayName / aliases）。"""
    names: Dict[str, str] = {}
    for c in project.characters or []:
        display = str(getattr(c, "displayName", "") or getattr(c, "defineName", "") or c.id)
        for term in [
            getattr(c, "id", ""),
            getattr(c, "defineName", ""),
            display,
            *(c.aliases or []),
        ]:
            term = str(term or "").strip()
            if term:
                names.setdefault(term, display)
    return names


def _chapter_units(chapter: Any, names: Dict[str, str]) -> Tuple[List[ProseUnit], str]:
    """一章 → (正文单元, 来源)。来源 ∈ prose / blocks / empty。"""
    prose = str(getattr(chapter, "prose", None) or "")
    if prose.strip():
        return _units_from_prose(prose, names), "prose"

    units: List[ProseUnit] = []
    for b in walk_blocks(list(getattr(chapter, "blocks", None) or [])):
        btype = str(b.get("type") or "")
        if btype == KIND_DIALOGUE:
            text = str(b.get("text") or "").strip()
            if text:
                speaker = names.get(str(b.get("characterId") or ""), "")
                units.append(ProseUnit(KIND_DIALOGUE, text, speaker))
        elif btype == KIND_NARRATION:
            for para in _split_paragraphs(str(b.get("text") or "")):
                units.append(ProseUnit(KIND_NARRATION, para))
        elif btype == "menu":
            prompt = str(b.get("prompt") or "").strip()
            if prompt:
                units.append(ProseUnit(KIND_CHOICE, prompt))
            for choice in b.get("choices") or []:
                if isinstance(choice, dict):
                    ctext = str(choice.get("text") or "").strip()
                    if ctext:
                        units.append(ProseUnit(KIND_CHOICE, ctext))
    # 演出指令（scene/show/music/…）、label、raw 不进统计：它们是结构或手写代码，
    # 计进来会把"字数基线"和段落长度一起弄脏（口径写在模块文档里）。
    return units, ("blocks" if units else "empty")


def _cut_to_word_budget(text: str, budget: int) -> str:
    """按**字数**口径把文本截到预算内（截断上限用，尽量不切在词中间）。"""
    if budget <= 0:
        return ""
    used = 0
    prev_alnum = False
    for i, ch in enumerate(text):
        if _CJK_RE.match(ch):
            add, prev_alnum = 1, False
        elif _ALNUM_RE.match(ch):
            add, prev_alnum = (0 if prev_alnum else 1), True
        else:
            add, prev_alnum = 0, False
        if used + add > budget:
            return text[:i]
        used += add
    return text


def _truncate_units(units: List[ProseUnit], budget: int) -> Tuple[List[ProseUnit], bool]:
    """超预算时按字数截断（**确定性**：永远从头保留）。返回 (单元, 是否截断)。"""
    if budget <= 0:
        return [], bool(units)
    total = sum(_count_words(u.text) for u in units)
    if total <= budget:
        return list(units), False
    kept: List[ProseUnit] = []
    used = 0
    for u in units:
        w = _count_words(u.text)
        if used + w <= budget:
            kept.append(u)
            used += w
            continue
        remain = budget - used
        if remain > 0:
            cut = _cut_to_word_budget(u.text, remain)
            if cut:
                kept.append(ProseUnit(u.kind, cut, u.speaker))
        break
    return kept, True


def chapter_readability(
    units: Sequence[ProseUnit], *, long_paragraph_chars: int = 300
) -> Dict[str, Any]:
    """地の文/对白占比、段落长度、长段落占比、连续行数上限——**只给事实**。"""
    dialogue = [u for u in units if u.kind == KIND_DIALOGUE]
    narration = [u for u in units if u.kind == KIND_NARRATION]
    choice = [u for u in units if u.kind == KIND_CHOICE]

    d_words = sum(_count_words(u.text) for u in dialogue)
    n_words = sum(_count_words(u.text) for u in narration)
    c_words = sum(_count_words(u.text) for u in choice)
    total = d_words + n_words + c_words
    prose = [u for u in units if u.kind in (KIND_DIALOGUE, KIND_NARRATION)]
    prose_words = d_words + n_words

    long_count = sum(1 for u in prose if _count_words(u.text) > long_paragraph_chars)
    max_dialogue_run = 0
    max_narration_run = 0
    d_run = 0
    n_run = 0
    for u in units:
        if u.kind == KIND_DIALOGUE:
            d_run += 1
            n_run = 0
        elif u.kind == KIND_NARRATION:
            n_run += 1
            d_run = 0
        else:  # 选项会打断连续段：它是给读者看的 UI 文本，不是叙事行
            d_run = 0
            n_run = 0
        max_dialogue_run = max(max_dialogue_run, d_run)
        max_narration_run = max(max_narration_run, n_run)

    return {
        "words": {
            "total": total,
            "dialogue": d_words,
            "narration": n_words,
            "choice": c_words,
            # 字符数（含标点、不含换行）：与"字数"并列给出，方便对照——
            # 假名不在 count_words 的口径里（它只数 CJK 汉字 + 拉丁词），纯日文稿的字数会偏小。
            "chars": sum(len(u.text) for u in units),
        },
        "ratio": {
            # 分母为 0 时给 None 而不是 0.0：没有正文 ≠ "对白占比 0%"
            "dialogue": (round(d_words / prose_words, 3) if prose_words else None),
            "narration": (round(n_words / prose_words, 3) if prose_words else None),
        },
        "lines": {
            "dialogue": len(dialogue),
            "narration": len(narration),
            "choice": len(choice),
        },
        "paragraphs": {
            "count": len(prose),
            "avgChars": (round(prose_words / len(prose), 1) if prose else None),
            "longCount": long_count,
            "longRatio": (round(long_count / len(prose), 3) if prose else None),
            "maxConsecutiveDialogue": max_dialogue_run,
            "maxConsecutiveNarration": max_narration_run,
        },
    }


# ------------------------------------------------------------ 相对比较（本书内）

RELATIVE_METRICS: Dict[str, Tuple[str, float, float]] = {
    # 指标 key: (中文名, 相对倍数阈值, 绝对下限)
    # 两条同时满足才算"偏高/偏低"：倍数挡住小数值上的假差异，绝对下限挡住"1 个感叹号 vs 0 个"。
    # 表里的倍数与下限都是**手调**的，只服务于"这个差异值不值得作者看一眼"。
    "dialogueRatio": ("对白占比", 1.5, 0.08),
    "avgParagraphChars": ("平均段落长度", 1.4, 15.0),
    "longParagraphRatio": ("长段落占比", 1.5, 0.10),
    "onomatopoeiaPer1000": ("拟声/拟态词密度", 1.5, 1.0),
    "exclaimPer1000": ("感叹号密度", 1.5, 1.0),
    "questionPer1000": ("问号密度", 1.5, 1.0),
    "hookScore": ("章末钩子评分", 1.3, 0.10),
}

MIN_CHAPTERS_FOR_RELATIVE = 3
"""少于这么多"其它章"就不做相对比较：两三章的"中位数"没有意义。"""


def _metric_value(row: Dict[str, Any], key: str) -> Optional[float]:
    if key == "dialogueRatio":
        return row["ratio"]["dialogue"]
    if key == "avgParagraphChars":
        return row["paragraphs"]["avgChars"]
    if key == "longParagraphRatio":
        return row["paragraphs"]["longRatio"]
    if key == "onomatopoeiaPer1000":
        return row["onomatopoeia"]["per1000Chars"]
    if key == "exclaimPer1000":
        return row["punctuation"]["exclaimPer1000"]
    if key == "questionPer1000":
        return row["punctuation"]["questionPer1000"]
    if key == "hookScore":
        # 空章不参与钩子比较（它没有"章末"可言）
        return None if row["hook"]["level"] == "empty" else row["hook"]["score"]
    return None


def _apply_relative_hints(rows: List[Dict[str, Any]]) -> None:
    """逐章与**其它章**的中位数比：只给"相对偏高/偏低"，措辞里写明是相对比较。"""
    for row in rows:
        row["relative"] = {}
        row["relativeHints"] = []
    for key, (label, ratio, floor) in RELATIVE_METRICS.items():
        values = [_metric_value(r, key) for r in rows]
        for i, row in enumerate(rows):
            value = values[i]
            if value is None:
                continue
            others = [v for j, v in enumerate(values) if j != i and v is not None]
            if len(others) < MIN_CHAPTERS_FOR_RELATIVE:
                continue
            median = float(statistics.median(others))
            level = None
            if median <= 0.0:
                if value >= floor:
                    level = "high"
            elif value >= median * ratio and (value - median) >= floor:
                level = "high"
            elif median >= value * ratio and (median - value) >= floor:
                level = "low"
            if level is None:
                continue
            hint = (
                f"{label}相对{'偏高' if level == 'high' else '偏低'}：本章 "
                f"{value:g}，其余 {len(others)} 章中位数 {median:g}"
                "（与本书其它章比较的相对读数，不是好坏判断，也不是外部标准）"
            )
            row["relative"][key] = {"level": level, "median": round(median, 3), "hint": hint}
            row["relativeHints"].append(hint)


# ------------------------------------------------------------ 账本 closeHook

def _ledger_close_hook(project: VnProject, chapter_id: str) -> Tuple[Optional[str], str]:
    """这一章在账本/章摘要里记下的 closeHook（没有返回 (None, "none")）。

    查两处：`chapterIndex`（保存时算出的抽取式摘要，字段就叫 closeHook）与
    `writingLedger.chapterFacts`（`digest_chapter_into_ledger` 把收束钩写进 facts 文本）。
    为什么两处都查：前者是"摘要算出来了"，后者是"入库了"，两者都可能只有一边有。
    """
    cid = str(chapter_id or "")
    for entry in project.chapterIndex or []:
        if str(getattr(entry, "chapterId", "") or "") != cid:
            continue
        hook = str(getattr(entry, "closeHook", "") or "").strip()
        if hook:
            return hook, "chapterIndex"
    ledger = getattr(project, "writingLedger", None)
    if isinstance(ledger, dict):
        for fact in ledger.get("chapterFacts") or []:
            if not isinstance(fact, dict) or str(fact.get("chapterId") or "") != cid:
                continue
            for line in fact.get("facts") or []:
                text = str(line or "").strip()
                for prefix in ("收束钩：", "收束钩:", "closeHook:"):
                    if text.startswith(prefix):
                        hook = text[len(prefix) :].strip()
                        if hook:
                            return hook, "writingLedger"
    return None, "none"


# ------------------------------------------------------------ 主入口

MAX_CHAPTERS = 300
"""一次最多分析这么多章（超出部分如实记入 coverage.chaptersSkipped）。"""

MAX_CHAPTER_CHARS = 60_000
"""单章字数上限（超出按字数截断，逐章 truncated 标记 + coverage.truncated）。

为什么要有上限：度量会被"顺手跑一下"（保存后、面板打开时），
而这台机器上真出现过几十万字的单章导入——量具不能把保存路径拖住。
"""

LONG_PARAGRAPH_CHARS = 300
"""长段落阈值（字数）。手调值：超过 300 字的一段在轻小说里已经算"一大坨"了。"""


def _summary(
    rows: List[Dict[str, Any]], ruby_issues: List[Dict[str, Any]], coverage: Dict[str, Any]
) -> str:
    """给作者的一句话中文结论。只复述事实与相对读数，不下文学判断。"""
    if not rows:
        return (
            "没有可分析的章节正文——本模块只做统计，未改动任何正文；"
            "写了一章之后再跑一次即可。"
        )
    words = int(coverage["wordsScanned"])
    d_ratios = [r["ratio"]["dialogue"] for r in rows if r["ratio"]["dialogue"] is not None]
    hooks = [r["hook"]["score"] for r in rows if r["hook"]["level"] != "empty"]
    ono = sum(int(r["onomatopoeia"]["count"]) for r in rows)
    ono_per1000 = round(ono / words * 1000, 2) if words else None
    exclaims = sum(int(r["punctuation"]["exclaim"]) for r in rows)
    ruby_marks = sum(int(r["ruby"]["count"]) for r in rows)

    bits = [
        f"共扫 {len(rows)} 章 / {words} 字"
        + ("（正文超上限已截断，统计不完整）" if coverage["truncated"] else ""),
    ]
    if d_ratios:
        bits.append(f"对白占比中位数 {round(statistics.median(d_ratios) * 100, 1)}%")
    if hooks:
        bits.append(
            f"章末钩子评分中位数 {round(statistics.median(hooks), 2)}（启发式，非文学判断）"
        )
        weakest = min(
            (r for r in rows if r["hook"]["level"] != "empty"),
            key=lambda r: (float(r["hook"]["score"]), str(r["chapterId"])),
        )
        bits.append(
            f"钩子最弱的是《{weakest['chapterTitle']}》({weakest['hook']['score']:g})"
        )
    if ono:
        bits.append(f"拟声/拟态词 {ono} 次（{ono_per1000}/千字）")
    if exclaims:
        bits.append(f"感叹号 {exclaims} 个")
    bits.append(
        f"注音标记 {ruby_marks} 处，检出 {len(ruby_issues)} 条提示/问题"
        + ("（列表已截断）" if coverage["rubyIssuesTruncated"] else "")
    )
    return "；".join(bits) + "。"


def _notes(
    *, long_paragraph_chars: int, coverage: Dict[str, Any]
) -> List[str]:
    """口径说明与启发式声明。每一条都是"这个数是怎么来的、它不成立在哪里"。"""
    return [
        "注音只认两种显式写法：`｜汉字《注音》`（也接受 ASCII `|`）与 `{汉字|注音}`；"
        "裸 `《…》` 一律按书名号看待，只给 info 提示、不计入注音密度"
        "（本项目自身就用《书名》，当成注音会满屏假警报）。",
        "「同一汉字注音前后不一致」是**全书范围**比对（跨章）；两种读法出现次数并列时不下判断，"
        "只报「这里有两种读法」，因为此时「哪个是笔误」没有依据。",
        "拟声/拟态词表是**人工整理的不完整词表**（见模块顶部 ONOMATOPOEIA_GROUPS），"
        "同一段里长词优先、不重复计数；含意译借用组（心跳/心跳声等，口径更宽）时另有 strictCount。"
        "统计只报出现次数，不评价多少才合适。",
        "章末钩子评分是**确定性启发式**：末段类型 0.25 / 末段长度 0.20 / 收尾标点与悬念词 0.30 / "
        "账本 closeHook 0.25。它不是文学判断，也不能替代编辑通读。",
        "其中「账本 closeHook」一项量的是**记账完整度**（chapterIndex 或 writingLedger 里这一章"
        "有没有记下章末钩子），不是文笔：没入库的章节会因此少 0.25 分。",
        "可读性事实按**字数**口径（count_words：CJK 逐字 + 拉丁词算 1），与写作面板字数一致；"
        f"选项文本单列，不进对白/叙述占比；长段落阈值 {long_paragraph_chars} 字。"
        "注意该口径**不数日文假名**（项目历史口径如此），纯假名文本的字数会偏小、"
        "因此密度类指标在日文段落上会偏高——逐章另有 words.chars（字符数）可对照。",
        "正文来源：一章有 prose 就只量 prose，没有才量 blocks（与 count_chapter_words 同一口径，"
        "避免同一段内容数两遍）；blocks 模式下「段落」= 一个 block（文本框一行量级），"
        "长段落少是正常的，只有 prose 稿才反映真实段落长度；"
        "演出指令 / label / raw 不进统计。",
        "prose 模式下「行首是引号或已知角色名+冒号」才算对白，"
        "叙述与引号混在一行的「混合行」整行算叙述，因此该模式的对白占比会**略偏低**。",
        "「相对偏高/偏低」是**与本书其它章的中位数比较**，不是与外部标准比较；"
        f"其它章少于 {MIN_CHAPTERS_FOR_RELATIVE} 章时不做相对比较。",
        "长段落阈值、注音密度提示阈值、相对比较倍数都是手调参数，不是行业标准；"
        "改常量即可整体调整敏感度。",
        "本模块纯本地统计：不联网、不调模型、无随机数、不读时间戳，同一份稿子永远同一结果。",
        "已知未覆盖：注音与导出（Ren'Py/HTML）的实际渲染未做校验；"
        "拟声词表不完整；对白「信息量」「节奏好坏」这类语义判断不在本模块范围内。",
    ] + ([str(coverage["note"])] if coverage.get("note") else [])


def analyze_novel_craft(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    max_chapters: int = MAX_CHAPTERS,
    max_chapter_chars: int = MAX_CHAPTER_CHARS,
    long_paragraph_chars: int = LONG_PARAGRAPH_CHARS,
) -> Dict[str, Any]:
    """轻小说写作技艺度量：逐章数值 + 注音问题 + 章末钩子启发式评分 + 可读性事实。

    纯确定性、零网络、零模型调用；同一输入永远同一输出（可进回归测试）。
    不修改 project，不做任何持久化。

    返回键：`perChapter` / `summary` / `rubyIssues` / `hookScores` /
    `rubyConsistency` / `notes` / `coverage`。
    """
    chapters_all = list(project.chapters or [])
    names = _character_names(project)

    # 带上"在整本书里的第几章"：按 chapter_id 过滤或截断后，序号不能退化成"本次第几章"
    indexed: List[Tuple[int, Any]] = list(enumerate(chapters_all))
    filtered = chapter_id is not None
    missing: Optional[str] = None
    if filtered:
        wanted = str(chapter_id)
        indexed = [
            (i, ch) for i, ch in indexed if str(getattr(ch, "id", "") or "") == wanted
        ]
        if not indexed:
            missing = wanted

    skipped: List[str] = []
    if len(indexed) > max_chapters:
        skipped = [str(getattr(ch, "id", "") or "") for _i, ch in indexed[max_chapters:]]
        indexed = indexed[:max_chapters]

    rows: List[Dict[str, Any]] = []
    hook_rows: List[Dict[str, Any]] = []
    ruby_issues: List[Dict[str, Any]] = []
    empty_chapters: List[str] = []
    truncated_chapters: List[str] = []
    all_marks: List[Dict[str, Any]] = []
    words_scanned = 0

    for index, chapter in indexed:
        cid = str(getattr(chapter, "id", "") or "")
        title = str(getattr(chapter, "title", "") or "") or cid
        units, source = _chapter_units(chapter, names)
        units, cut = _truncate_units(units, max_chapter_chars)
        if cut:
            truncated_chapters.append(cid)
        if not units:
            empty_chapters.append(cid)

        text = "\n".join(u.text for u in units)
        words = _count_words(text)
        words_scanned += words

        readability = chapter_readability(units, long_paragraph_chars=long_paragraph_chars)
        ono = onomatopoeia_stats(text, words=words)

        # —— 注音：逐行扫，位置（行/列）才有意义 ——
        marks: List[Dict[str, Any]] = []
        chapter_issues: List[Dict[str, Any]] = []
        title_like = 0
        for line_no, unit in enumerate(units, start=1):
            line_marks, line_issues = _scan_ruby_line(
                unit.text, chapter_id=cid, chapter_title=title, line=line_no
            )
            for mk in line_marks:
                marks.append(
                    {
                        "form": mk["form"],
                        "base": mk["base"],
                        "reading": mk["reading"],
                        "line": line_no,
                        "column": mk["column"],
                    }
                )
            for issue in line_issues:
                if issue["code"] == ISSUE_RUBY_READING_WITHOUT_BASE:
                    # 书名号可能成百上千，逐章限量：真问题不能被提示淹掉
                    title_like += 1
                    if title_like > MAX_TITLE_LIKE_ISSUES_PER_CHAPTER:
                        continue
                chapter_issues.append(issue)

        ruby_per1000 = round(len(marks) / words * 1000, 2) if words else None
        if ruby_per1000 is not None and ruby_per1000 > RUBY_DENSITY_INFO_PER_1000:
            chapter_issues.append(
                _issue(
                    ISSUE_RUBY_DENSITY_HIGH,
                    SEVERITY_INFO,
                    f"注音密度偏高：{len(marks)} 处 / {words} 字 = {ruby_per1000}/千字"
                    f"（提示阈值 {RUBY_DENSITY_INFO_PER_1000:g}/千字，手调值）"
                    "——密到一定程度会打断阅读节奏，是否要减由你判断",
                    chapter_id=cid,
                    chapter_title=title,
                    line=None,
                    column=None,
                )
            )
        ruby_issues.extend(chapter_issues)
        forms: Dict[str, int] = {}
        for mk in marks:
            forms[mk["form"]] = forms.get(mk["form"], 0) + 1
        for mk in marks:
            all_marks.append({**mk, "chapterId": cid, "chapterTitle": title})

        close_hook, hook_source = _ledger_close_hook(project, cid)
        hook = score_chapter_hook(
            units,
            close_hook=close_hook,
            hook_source=hook_source,
            chapter_id=cid,
            chapter_title=title,
        )
        hook["chapterIndex"] = index
        hook_rows.append(hook)

        rows.append(
            {
                "chapterId": cid,
                "chapterTitle": title,
                "chapterIndex": index,
                "volumeId": str(getattr(chapter, "volumeId", "") or ""),
                "source": source,
                "truncated": cut,
                "words": readability["words"],
                "ratio": readability["ratio"],
                "lines": readability["lines"],
                "paragraphs": readability["paragraphs"],
                "punctuation": ono["punctuation"],
                "onomatopoeia": ono["onomatopoeia"],
                "ruby": {
                    "count": len(marks),
                    "baseChars": sum(len(mk["base"]) for mk in marks),
                    "per1000Chars": ruby_per1000,
                    "forms": forms,
                    "titleLikeCount": title_like,
                    "marks": marks[:MAX_RUBY_MARKS_SHOWN],
                },
                "hook": hook,
            }
        )

    # —— 全书注音一致性（跨章）——
    ruby_consistency, consistency_issues = _ruby_consistency(all_marks)
    ruby_issues.extend(consistency_issues)
    # 按**稿件顺序**（章序 → 行 → 列）排，而不是按 chapterId 字符串排：
    # 作者是从头往下改稿的，"c10 排在 c2 前面"只会让人来回翻。
    order_by_id = {r["chapterId"]: i for i, r in enumerate(rows)}
    ruby_issues.sort(
        key=lambda r: (
            order_by_id.get(str(r.get("chapterId") or ""), len(rows)),
            r.get("line") if r.get("line") is not None else -1,
            r.get("column") if r.get("column") is not None else -1,
            str(r.get("code") or ""),
        )
    )
    issues_truncated = len(ruby_issues) > MAX_RUBY_ISSUES
    if issues_truncated:
        ruby_issues = ruby_issues[:MAX_RUBY_ISSUES]

    _apply_relative_hints(rows)

    coverage: Dict[str, Any] = {
        "chaptersTotal": len(chapters_all),
        "chaptersAnalyzed": len(rows),
        "chapterIds": [r["chapterId"] for r in rows],
        "chapterIdFilter": str(chapter_id) if chapter_id is not None else None,
        "missingChapterId": missing,
        "chaptersSkipped": skipped,
        "truncated": bool(truncated_chapters or skipped),
        "truncatedChapters": truncated_chapters,
        "emptyChapters": empty_chapters,
        "chapterCap": max_chapters,
        "perChapterWordCap": max_chapter_chars,
        "wordsScanned": words_scanned,
        "rubyIssuesReturned": len(ruby_issues),
        "rubyIssuesTruncated": issues_truncated,
        "note": "",
    }
    coverage["note"] = (
        f"本次覆盖：{coverage['chaptersAnalyzed']}/{coverage['chaptersTotal']} 章"
        + ("（按 chapter_id 过滤）" if filtered else "")
        + (f"，另有 {len(skipped)} 章超出章数上限未扫" if skipped else "")
        + (f"，{len(truncated_chapters)} 章正文超单章上限被截断" if truncated_chapters else "")
        + (f"，{len(empty_chapters)} 章没有正文" if empty_chapters else "")
        + (f"；未找到章节 {missing}" if missing else "")
        + "。"
    )

    notes = _notes(long_paragraph_chars=long_paragraph_chars, coverage=coverage)
    return {
        "perChapter": rows,
        "summary": _summary(rows, ruby_issues, coverage),
        "rubyIssues": ruby_issues,
        "hookScores": hook_rows,
        "rubyConsistency": ruby_consistency,
        "notes": notes,
        "coverage": coverage,
    }


def _ruby_consistency(
    marks: Sequence[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """同一基准词出现多种注音时：列出分歧，并对**少数派**逐个报问题。

    判据是"多数派即正确"——这只是一个便宜的默认假设（同一汉字在一本书里通常只有一种读法）。
    并列时（每种读法出现次数相同）不下判断，只报 info，`expected` 留 None。
    """
    by_base: Dict[str, List[Dict[str, Any]]] = {}
    for mk in marks:
        by_base.setdefault(str(mk["base"]), []).append(mk)

    consistency: List[Dict[str, Any]] = []
    issues: List[Dict[str, Any]] = []
    for base, occ in sorted(by_base.items()):
        counts: Dict[str, int] = {}
        for mk in occ:
            counts[str(mk["reading"])] = counts.get(str(mk["reading"]), 0) + 1
        if len(counts) < 2:
            continue
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        majority, majority_count = ranked[0]
        runner_up_count = ranked[1][1]
        tied = majority_count == runner_up_count
        consistency.append(
            {
                "base": base,
                "occurrences": len(occ),
                "readings": [
                    {"reading": reading, "count": count} for reading, count in ranked
                ],
                "majority": None if tied else majority,
                "tied": tied,
                "locations": [
                    {
                        "chapterId": mk["chapterId"],
                        "line": mk["line"],
                        "column": mk["column"],
                        "reading": mk["reading"],
                    }
                    for mk in occ
                ],
            }
        )
        for mk in occ:
            reading = str(mk["reading"])
            if tied or reading == majority:
                continue
            issues.append(
                _issue(
                    ISSUE_RUBY_INCONSISTENT,
                    SEVERITY_WARN,
                    f"「{base}」的注音前后不一致：这里注作「{reading}」，"
                    f"全书多数处（{majority_count} 次）注作「{majority}」——很可能是笔误",
                    chapter_id=str(mk["chapterId"]),
                    chapter_title=str(mk.get("chapterTitle") or ""),
                    line=mk["line"],
                    column=mk["column"],
                    form=mk["form"],
                    base=base,
                    reading=reading,
                    expected=majority,
                )
            )
        if tied:
            for mk in occ:
                issues.append(
                    _issue(
                        ISSUE_RUBY_INCONSISTENT,
                        SEVERITY_INFO,
                        f"「{base}」有 {len(counts)} 种注音，各出现 {majority_count} 次"
                        "——无法判断哪个是笔误，请人工确认（本模块在并列时不下结论）",
                        chapter_id=str(mk["chapterId"]),
                        chapter_title=str(mk.get("chapterTitle") or ""),
                        line=mk["line"],
                        column=mk["column"],
                        form=mk["form"],
                        base=base,
                        reading=str(mk["reading"]),
                        expected=None,
                    )
                )
    return consistency, issues

"""Ported from packages/core/src/agentContext.ts"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.domain.types import Character, Location, SceneChapter, ScriptBlock, VnProject

from .chapter_digest import digest_all_chapters, format_chapter_digest_index
from .longform_memory import select_outline_beats

AgentTaskKind = str

# Specialized writing tasks — drives both prompt hints and retrieval bias.
AGENT_TASKS: List[str] = [
    "chat",
    "continue",
    "rewrite",
    "polish",
    "branch",
    "outline",
    "voice",
    "consistency",
    "scene",
]


def is_agent_task(v: Any) -> bool:
    return isinstance(v, str) and v in AGENT_TASKS


def _default_context_max_chars() -> int:
    """Agent 上下文主预算：优先 AGENT_CONTEXT_MAX_CHARS（Settings），默认 12000。

    用 try/except 包裹，保证纯上下文拼装（含测试）永远有可用默认值，
    不会因 SECRET_KEY 校验等环境问题抛错。
    """
    try:
        from app.config import get_settings

        v = get_settings().agent_context_max_chars
        return int(v) if v and v > 0 else 12000
    except Exception:  # noqa: BLE001 - core util must never raise for tuning knob
        return 12000


@dataclass
class AgentContextOptions:
    chapterId: Optional[str] = None
    selection: Optional[str] = None
    # Latest user utterance — used for keyword retrieval
    userMessage: Optional[str] = None
    task: Optional[str] = None
    # Soft budget for the assembled context string
    maxChars: Optional[int] = None
    # Rolling chat memory (extractive, from client)
    chatMemory: Optional[str] = None
    # NovelMaster-style long chapter archive (from PostgreSQL)
    longChapterMemory: Optional[str] = None
    # Distilled ACG craft cards (萌百启发)
    loreCraft: Optional[str] = None
    # User-uploaded reference documents (plain text block)
    referenceDocs: Optional[str] = None


@dataclass
class AgentContextResult:
    text: str
    # Human-readable list of what was injected (for UI transparency)
    included: List[str]
    charsUsed: int
    task: str
    # 这次**没带**的资料块 key（前端可显示、可让作者改回来）
    excluded: List[str] = field(default_factory=list)
    # 「证明它记得」：这次实际依据了什么（可展开看摘录），前端默认摆出来
    includedDetails: List[Dict[str, str]] = field(default_factory=list)


# 可以被作者按需摘掉的资料块：key → 人话（前端「资料」面板直接用它渲染）
EXCLUDABLE_SECTIONS: Dict[str, str] = {
    "bible": "设定 bible（世界观 / 大纲 / 背景）",
    "lore": "设定条目",
    "longMemory": "长程章节记忆",
    "craft": "ACG 工艺卡",
    "referenceDocs": "上传的参考资料",
    "chatMemory": "对话滚动记忆",
    "index": "章节目录与本地摘要",
    "characters": "角色卡",
    "relations": "角色关系",
    "locations": "地点与通路",
    "variables": "变量 / 状态机",
    "sprites": "立绘",
    "otherChapters": "其他章节摘录",
    "style": "文风记忆",
}

# 按任务默认丢掉的**噪音**块：机制类资料对写散文没用，带上去只会分散注意力。
# 注意：这里只放"去掉不影响正确性"的块（人设/地点/摘要一律保留）。
TASK_DROP_SECTIONS: Dict[str, set] = {
    "continue": {"sprites", "variables"},
    "rewrite": {"sprites", "variables"},
    "polish": {"sprites", "variables"},
    "chat": {"otherChapters"},
}


def sections_to_drop(task: str, exclude: Optional[Iterable[str]] = None) -> set:
    """本轮要丢掉的资料块 = 任务默认裁剪 ∪ 作者手动摘掉的（只认已知 key）。"""
    drop = set(TASK_DROP_SECTIONS.get(task or "chat", set()))
    for key in exclude or []:
        if key in EXCLUDABLE_SECTIONS:
            drop.add(key)
    return drop


# 每个任务的**硬规则**：短、可执行、且会在上下文末尾再重复一次。
# 为什么单列：长上下文里夹在中间的要求最容易被忽略，末尾的位置才是"当场生效"的。
TASK_KEY_RULES: Dict[str, List[str]] = {
    "continue": [
        "紧接「当前章节」正文末尾续写，不要重述已经写过的内容。",
        "只输出正文本身：不要解释、不要总结、不要加小标题。",
        "保持紧邻前文的人称、时态与专名；新出现的专名必须能在设定里找到出处。",
        "对白与叙述的比例、句子长短要贴近紧邻的前文。",
    ],
    "rewrite": [
        "只改指定的这一段（或这一章），其余一字不动。",
        "不新增事实、不删关键信息；专名原样保留。",
        "只输出正文本身：不要解释、不要前后对比。",
    ],
    "polish": [
        "只做语言层面的润色：节奏、用词、具体程度；不改情节。",
        "只输出润色后的正文，不加说明。",
    ],
    "consistency": [
        "逐条比对设定/台账与正文，指出冲突，并给出可执行的修法。",
        "不要为了「看起来没问题」而放过可疑处；拿不准就明确标出来。",
    ],
    "chat": [
        "给结论与理由，不要客套、不要复述我的问题。",
        "除非我明确要求，否则不要改工程。",
    ],
}


def task_key_rules(task: str) -> List[str]:
    return TASK_KEY_RULES.get(task or "chat", TASK_KEY_RULES["chat"])


# 每个任务的**输出契约**：长度与形态。写清楚"给我什么形状的东西"，
# 模型就不会拿解释、总结、小标题来凑数——这也是"工具不如裸聊"的一个常见原因。
TASK_OUTPUT_CONTRACT: Dict[str, str] = {
    "continue": "只输出续写的正文（300–900 字，用户另有要求按用户要求）；不要解释、不要小结、不要标题。",
    "scene": "只输出这一场的正文；场景切换用空行分隔，不要写镜头术语或舞台指令（除非用户要求）。",
    "rewrite": "只输出改写后的正文；长度与原文相当；不附说明、不附对照。",
    "polish": "只输出润色后的正文；不改情节、不改专名。",
    "consistency": "先列冲突（每条一行：位置 → 与什么设定冲突 → 建议改法），再给一句总体判断；不要重写正文。",
    "outline": "输出分级大纲：卷/章/节三层用缩进或编号表示；每条一句话，不要展开成正文。",
    "voice": "输出调整后的台词或段落；旁边不写解释。",
    "chat": "直接回答：先结论后理由；需要时给可执行的改法；不要复述我的问题。",
}


def output_contract(task: str) -> str:
    return TASK_OUTPUT_CONTRACT.get(task or "chat", TASK_OUTPUT_CONTRACT["chat"])


TASK_HINTS: Dict[str, str] = {
    "chat": (
        "本轮模式：自由讨论。可给方案、点评、大纲；把完整意见写进 message。"
        "仅当用户明确要求写入工程时再给 actions。设定勿当讲义复述。"
        "若用户征求修改意见/点评长文分析：actions=[]，用 message 长文回应。"
    ),
    "continue": (
        "本轮任务：续写一小段可上演节拍。紧接【当前章末尾】；人设只校准语气。禁止设定宣讲；"
        "禁止陌生人连问盘人（一拍一角色 ideally ≤1 问）；信息用环境/失言/残缺感推进。默认 append_script；不要重写前文。"
        "message 须简要说明本段节拍意图。"
    ),
    "rewrite": (
        "本轮任务：改写选区。保持剧情意图，砍盘问串与说明书腔，提升画面感与对白张力；"
        "append_script 追加改写稿（勿 replace 整章，除非用户要求）。message 说明改法要点。"
    ),
    "polish": (
        "本轮任务：润色。不改情节；重点砍盘问串、问答乒乓、过熟闲聊与套话，打磨对白自然度；"
        "append_script 写入。message 说明润了哪些口气问题。"
    ),
    "branch": (
        "本轮任务：有意义的分支。2～4 个 Ren'Py menu，每项后果不同；选项文案短而有戏剧性，"
        "勿在选项里塞设定说明；append_script。"
    ),
    "outline": "本轮任务：场景大纲。规划 3～5 场（冲突/人物/钩子），用戏剧事件而非设定条目来写；先 message；同意后再 update_bible/add_chapter。",
    "voice": "本轮任务：人设语气审校。对照 voice/bio 找破功句；改写时仍禁止设定宣讲与过熟盘问。",
    "consistency": (
        "本轮任务：一致性排查。列矛盾与最小改法；报告里可以引用设定，但建议写入正文时仍遵守反倾倒。"
        "优先用 get_chapter 一次读多章（chapterRefs）做跨章对照，再结合 get_character/get_bible 核对；"
        "不要只凭片段猜。"
    ),
    "scene": (
        "本轮任务：写完整一小场戏（进场→冲突→收束钩子）。设定溶于表演；对照社交温度与人设惜话程度，"
        "勿把冷角色写成访谈主持。append_script。"
    ),
}


def infer_agent_task(message: str) -> str:
    m = message.strip()
    # Long paste asking for opinions/critique stays in chat (don't mis-fire rewrite).
    if len(m) > 800 and re.search(
        r"(修改意见|审稿|你觉得|对吗|据此|怎么改|提一些|征求)", m
    ):
        return "chat"
    if re.search(r"【任务：续写】|^续写|请续写|往下写", m):
        return "continue"
    if re.search(r"【任务：改写】|改写选区", m) or (
        len(m) < 240 and re.search(r"请改写", m)
    ):
        return "rewrite"
    if re.search(r"【任务：润色】|请润色", m):
        return "polish"
    if re.search(r"【任务：分支】|生成分支|设计分支|menu", m):
        return "branch"
    if re.search(r"【任务：大纲】|场景大纲|给出.*大纲", m):
        return "outline"
    if re.search(r"【任务：语气】|统一语气|人设一致|voice", m):
        return "voice"
    if re.search(r"【任务：查矛盾】|一致性|矛盾|冲突检查|状态机", m):
        return "consistency"
    if re.search(r"【任务：写一场戏】|写一场戏|完整一场|一场戏", m):
        return "scene"
    return "chat"


def task_hint(task: str) -> str:
    return TASK_HINTS[task]


def _js(v: Optional[str]) -> str:
    """Mirror JS template-literal embedding of an undefined value as 'undefined'."""
    return v if v is not None else "undefined"


def _blocks_to_plain(blocks: List[ScriptBlock], characters: List[Character]) -> str:
    char_map = {c.id: c for c in characters}
    lines: List[str] = []
    for b in blocks:
        btype = b.get("type")
        if btype == "label":
            line: Optional[str] = f"[label {b['name']}]"
        elif btype == "scene":
            line = f"[scene {b['image']}]"
        elif btype == "show":
            line = f"[show {b['image']}]"
        elif btype == "hide":
            line = f"[hide {b['image']}]"
        elif btype == "narration":
            line = f"旁白: {b['text']}"
        elif btype == "dialogue":
            ch = char_map.get(b.get("characterId"))
            name = ch.displayName if ch else b.get("characterId")
            line = f"{name}: {b['text']}"
        elif btype == "menu":
            line = f"选项: {' / '.join(c['text'] for c in b.get('choices', []))}"
        elif btype == "jump":
            line = f"[jump {b['target']}]"
        elif btype == "comment":
            line = f"# {b['text']}"
        elif btype == "raw":
            line = b.get("code", "")
        elif btype == "music":
            line = (
                f"[音乐 {b.get('file') or ''}]"
                if (b.get("action") or "play") == "play"
                else "[音乐 停]"
            )
        elif btype == "sound":
            line = (
                f"[音效 {b.get('file') or ''}]"
                if (b.get("action") or "play") == "play"
                else "[音效 停]"
            )
        elif btype == "voice":
            line = (
                f"[语音 {b.get('file') or ''}]"
                if (b.get("action") or "play") == "play"
                else "[语音 停]"
            )
        elif btype == "wait":
            line = f"[等待 {b.get('seconds') or 0} 秒]"
        elif btype == "camera":
            zoom = b.get("zoom")
            line = f"[镜头 at {b['at']}]" if b.get("at") else f"[镜头 zoom={zoom or 1}]"
        elif btype == "effect":
            line = f"[特效 {b.get('kind') or ''}]"
        elif btype == "set":
            line = f"[变量 {b.get('key')} {b.get('op') or '='} {b.get('value')}]"
        elif btype == "if":
            # 条件分支：把每个分支的条件与正文都折进行，让 AI 看得到分支结构
            branch_bits = []
            for branch in b.get("branches") or []:
                cond = (branch.get("condition") or "").strip() or "否则"
                body = _blocks_to_plain(branch.get("blocks") or [], characters)
                branch_bits.append(f"条件({cond}) {{ {body} }}")
            line = "[如果 " + " 否则 ".join(branch_bits) + "]" if branch_bits else ""
        else:
            line = ""
        if line:
            lines.append(line)
    return "\n".join(lines)


_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[a-z0-9_]{3,}")
_CJK_ONLY = re.compile(r"^[\u4e00-\u9fff]+$")


def _tokenize(query: str) -> List[str]:
    lower = query.lower()
    tokens: List[str] = []
    seen: set = set()

    def _add(tok: str) -> None:
        if tok not in seen:
            seen.add(tok)
            tokens.append(tok)

    for m in _TOKEN_RE.finditer(lower):
        t = m.group(0)
        if len(t) >= 2:
            _add(t)
        # CJK bigrams for denser matching
        if _CJK_ONLY.match(t) and len(t) >= 3:
            for i in range(len(t) - 1):
                _add(t[i : i + 2])
    return tokens[:80]


def _score_haystack(hay: str, tokens: List[str]) -> int:
    if not tokens or not hay:
        return 0
    h = hay.lower()
    score = 0
    for tok in tokens:
        if tok not in h:
            continue
        score += 4 if len(tok) >= 4 else 3 if len(tok) >= 3 else 2
    return score


def _ask_text(userMessage: Optional[str], selection: Optional[str]) -> str:
    """提问原文（小写）。名字类命中要按"整串出现在提问里"判断，不能只看分词。"""
    return "\n".join([userMessage or "", selection or ""]).lower()


def _names_of(obj: Any, *field_names: str) -> List[str]:
    """取一个条目的所有叫法：主名字段 + aliases 列表。"""
    out: List[str] = []
    for f in field_names:
        v = getattr(obj, f, None)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    aliases = getattr(obj, "aliases", None)
    if isinstance(aliases, (list, tuple)):
        for a in aliases:
            if isinstance(a, str) and a.strip():
                out.append(a.strip())
    # 去重但保序
    seen: set = set()
    uniq: List[str] = []
    for n in out:
        low = n.lower()
        if low not in seen:
            seen.add(low)
            uniq.append(n)
    return uniq


def _name_hit_bonus(names: Sequence[str], ask: str) -> int:
    """名字/别名**整串**出现在提问里 = 强信号。

    为什么单独算：只靠分词的话，"雪见" 这种两字名字只值 2 分，而正文里随便一个
    常见词也可能值 2~4 分——命中名字反而被淹没。名字命中应该明显压过正文里的巧合。
    """
    if not ask:
        return 0
    bonus = 0
    for n in names:
        low = n.strip().lower()
        if len(low) >= 2 and low in ask:
            bonus += 10
    return min(bonus, 20)


def _entry_text(e: Any) -> str:
    return str(getattr(e, "body", "") or "")


def _entry_keywords(e: Any) -> List[str]:
    raw = getattr(e, "keywords", None)
    if not isinstance(raw, (list, tuple)):
        return []
    return [str(k).strip() for k in raw if str(k).strip()]


def _entry_score(e: Any, ask: str, tokens: List[str]) -> int:
    """设定条目的相关度：触发词 > 标题 > 正文（正文封顶，防止长文里凑巧撞词）。

    标题命中按"标签级"计入（每个命中词 5 分），因为标题通常就是条目的名字
    （"镜湖封印推演"里的"镜湖"），比正文里恰好出现同一个字可靠得多。
    """
    keys = _entry_keywords(e)
    title = str(getattr(e, "title", "") or "")
    title_low = title.lower()
    score = 0
    for k in keys:
        low = k.lower()
        if len(low) >= 2 and low in ask:
            score += 12
    if len(title) >= 2 and title_low in ask:
        score += 8
    score += _score_haystack(" ".join(keys), tokens)
    title_hits = sum(1 for tok in tokens if len(tok) >= 2 and tok in title_low)
    score += min(title_hits * 5, 15)
    # 正文命中只算很弱的信号，并且封顶（长正文里撞到常见词太容易了）
    score += min(_score_haystack(_entry_text(e), tokens), 6)
    return score


# 非钉住的条目至少要过这条线才进上下文。
#
# 取值依据（用 80 条目的评测语料量过）：正文命中两个词 ≈ 4 分，是"这条确实相关"的
# 最低可信信号（例如问"白砚的妹妹去哪了"命中正文里的"白砚/妹妹"）；只撞上一个两字词
# （2 分）多半是巧合，滤掉。而没进来的条目仍会以标题形式出现在末尾的可点名提示里，
# 所以这里收紧的是**精度**，不是召回。
_ENTRY_MIN_SCORE = 4


def rank_lore_entries(
    entries: Sequence[Any],
    query: str,
    *,
    limit: int = 8,
    min_score: int = _ENTRY_MIN_SCORE,
) -> List[Tuple[Any, int]]:
    """按提问给设定条目打分排序。

    存在的理由：自动注入（开场拼上下文）和 Agent 的 `search_lore` 工具必须是**同一把尺子**，
    否则会出现"工具说命中、注入却不带"这种自相矛盾的行为。所以两处都走这个函数。
    """
    ask = (query or "").strip().lower()
    tokens = _tokenize(query or "")
    scored = [
        (e, _entry_score(e, ask, tokens))
        for e in (entries or [])
        if e is not None and not bool(getattr(e, "pinned", None))
    ]
    scored = [(e, s) for e, s in scored if s >= min_score]
    scored.sort(
        key=lambda pair: (pair[1], int(getattr(pair[0], "priority", 0) or 0)),
        reverse=True,
    )
    return scored[: max(1, limit)]


def lore_entry_index(entries: Sequence[Any], limit: int = 60) -> str:
    """条目索引（标题 + 触发词一行一条）：模型不知道叫什么名字时先看这个。"""
    lines: List[str] = []
    for e in (entries or [])[:limit]:
        if e is None:
            continue
        title = str(getattr(e, "title", "") or "").strip()
        if not title:
            continue
        keys = _entry_keywords(e)
        pin = " ☆钉住" if bool(getattr(e, "pinned", None)) else ""
        lines.append(f"- {title}" + (f"（{'/'.join(keys)}）" if keys else "") + pin)
    return "\n".join(lines)


def _clip(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 12]}\n…(截断)"


def _char_card(c: Character) -> str:
    from app.core.character_voice.corpus import format_corpus_for_prompt, format_mind_for_prompt

    mind = format_mind_for_prompt(c, max_chars=1600)
    corpus = format_corpus_for_prompt(c, max_samples=6, max_chars=1400)
    return "\n".join(
        p
        for p in [
            f"- {c.displayName} ({c.defineName})",
            f"  语气: {c.voice}" if c.voice else "",
            f"  人设: {c.bio}" if c.bio else "",
            f"  关系: {c.relationships}" if c.relationships else "",
            mind,
            corpus,
        ]
        if p
    )


def _loc_card(l: Location) -> str:
    tags = f" #{'#'.join(l.tags)}" if l.tags else ""
    return (
        f"- {l.name}"
        + (f" [{l.imageTag}]" if l.imageTag else "")
        + (f": {l.description}" if l.description else "")
        + tags
    )


def _chapter_tail(plain: str, max_len: int) -> str:
    if len(plain) <= max_len:
        return plain
    return f"…(前文省略)\n{plain[len(plain) - max_len:]}"


def _chapter_head_tail(plain: str, max_len: int) -> str:
    if len(plain) <= max_len:
        return plain
    head = int(max_len * 0.35)
    tail = max_len - head - 20
    return f"{plain[:head]}\n…(中间省略)…\n{plain[len(plain) - tail:]}"


def build_agent_context(
    project: VnProject,
    chapterId: Optional[str] = None,
    selection: Optional[str] = None,
    userMessage: Optional[str] = None,
    task: Optional[str] = None,
    maxChars: Optional[int] = None,
    chatMemory: Optional[str] = None,
    longChapterMemory: Optional[str] = None,
    loreCraft: Optional[str] = None,
    referenceDocs: Optional[str] = None,
    exclude: Optional[Iterable[str]] = None,
) -> AgentContextResult:
    """Build a retrieval-biased project context for long-form Agent use.

    Prefer: meta + bible digest + chapter index + focus chapter + scored slices.
    """
    max_chars = maxChars if maxChars is not None else _default_context_max_chars()
    resolved_task = task or (infer_agent_task(userMessage) if userMessage else "chat")
    included: List[str] = [f"模式:{resolved_task}"]

    focus_chapter = next((c for c in project.chapters if c.id == chapterId), None) or (
        project.chapters[0] if project.chapters else None
    )

    # Perf: blocks→plain conversion is O(blocks) and hot in character scoring /
    # chapter excerpts below — memoize per chapter so each chapter converts once.
    plain_cache: Dict[str, str] = {}

    def plain_of(ch: Optional[SceneChapter]) -> str:
        if ch is None:
            return ""
        cached = plain_cache.get(ch.id)
        if cached is None:
            cached = _blocks_to_plain(ch.blocks, project.characters)
            plain_cache[ch.id] = cached
        return cached

    ask_tokens = _tokenize("\n".join([userMessage or "", selection or ""]))
    ask_lower = _ask_text(userMessage, selection)
    # Only score against the user ask / selection — never seed with every name
    # (that would make every character card match itself).
    effective_tokens = ask_tokens

    bible = project.bible
    meta_lines = [
        p
        for p in [
            f"# {project.title}",
            f"Logline: {project.logline}" if project.logline else "",
            f"Genre: {project.genre}" if project.genre else "",
        ]
        if p
    ]

    bible_budget = 2800 if resolved_task in ("outline", "consistency") else 2000
    bible_parts: List[str] = []
    if (bible and bible.world) or project.lore:
        bible_parts.append(f"世界观:\n{_clip((bible.world if bible else None) or project.lore or '', 900)}")
    if bible and bible.background:
        bible_parts.append(f"故事背景:\n{_clip(bible.background, 500)}")
    if bible and bible.outline:
        related_beats = select_outline_beats(bible.outline, effective_tokens, 5)
        if related_beats and resolved_task != "outline":
            bible_parts.append("大纲相关节拍（检索）:\n" + "\n".join(f"- {b}" for b in related_beats))
            included.append(f"大纲节拍×{len(related_beats)}")
        bible_parts.append(f"大纲:\n{_clip(bible.outline, 1200 if resolved_task == 'outline' else 500)}")
    if bible and bible.themes:
        bible_parts.append(f"主题/基调:\n{_clip(bible.themes, 300)}")
    if bible and bible.notes:
        bible_parts.append(f"备忘:\n{_clip(bible.notes, 300)}")
    bible_block = "\n\n".join(bible_parts)
    if len(bible_block) > bible_budget:
        bible_block = _clip(bible_block, bible_budget)
    if bible_block:
        included.append("设定bible")

    digests = digest_all_chapters(project)
    # 分卷的作品：模型看到的章节目录也带卷（长篇续写时它要知道自己在写哪一卷）
    volume_titles: Dict[str, str] = {}
    if project.volumes:
        title_by_id = {str(v.id): (v.title or "") for v in project.volumes}
        for ch in project.chapters or []:
            title = title_by_id.get(str(getattr(ch, "volumeId", "") or ""))
            if title:
                volume_titles[ch.id] = title
    digest_fmt = format_chapter_digest_index(
        digests,
        focus_id=focus_chapter.id if focus_chapter else None,
        tokens=effective_tokens,
        max_related_excerpts=5 if resolved_task == "consistency" else 3,
        volume_titles=volume_titles,
    )
    included.extend([x for x in digest_fmt.included if not x.startswith("章摘要")])

    if digest_fmt.indexLines:
        index_lines = digest_fmt.indexLines
    else:
        index_lines = []
        for i, ch in enumerate(project.chapters):
            mark = "◀当前" if focus_chapter and ch.id == focus_chapter.id else ""
            syn = f" — {_clip(ch.synopsis, 80)}" if ch.synopsis else ""
            index_lines.append(f"{i + 1}. {ch.title}{mark}{syn}")
    included.append(f"章节目录×{len(project.chapters)}")

    # Score characters
    ranked_chars: List[Tuple[Character, int]] = []
    for c in project.characters:
        names = _names_of(c, "displayName", "defineName")
        # 别名也要进 haystack：正文里提到"阿雪"这种别称时同样该命中
        hay = (
            f"{' '.join(names)} {_js(c.voice)} {_js(c.bio)} "
            f"{_js(c.relationships)} {_js(getattr(c, 'voiceMind', None))}"
        )
        score = _score_haystack(hay, effective_tokens) + _name_hit_bonus(names, ask_lower)
        if focus_chapter:
            plain = plain_of(focus_chapter)
            if any(n in plain for n in names):
                score += 8
        if resolved_task in ("voice", "consistency"):
            score += 2
        ranked_chars.append((c, score))
    ranked_chars.sort(key=lambda pair: pair[1], reverse=True)

    char_pick_count = (
        min(12, len(ranked_chars))
        if resolved_task in ("voice", "consistency")
        else min(6, len(ranked_chars))
    )
    picked_chars = [r for i, r in enumerate(ranked_chars) if r[1] > 0 or i < 3][:char_pick_count]
    if not picked_chars and ranked_chars:
        picked_chars = ranked_chars[: min(3, len(ranked_chars))]

    locs = project.locations or []
    ranked_locs: List[Tuple[Location, int]] = []
    for l in locs:
        names = _names_of(l, "name", "imageTag")
        hay = f"{' '.join(names)} {l.description or ''} {' '.join(l.tags or [])}"
        score = _score_haystack(hay, effective_tokens) + _name_hit_bonus(names, ask_lower)
        if resolved_task in ("scene", "consistency"):
            score += 1
        ranked_locs.append((l, score))
    ranked_locs.sort(key=lambda pair: pair[1], reverse=True)
    loc_pick_max = 8 if resolved_task == "scene" else 5
    picked_locs = [r for i, r in enumerate(ranked_locs) if r[1] > 0 or i < 4][:loc_pick_max]
    if not picked_locs and ranked_locs:
        picked_locs = ranked_locs[: min(4, len(ranked_locs))]

    link_lines: List[str] = []
    links = project.locationLinks or []
    related_loc_lines: List[str] = []
    if links and picked_locs:
        by_id = {l.id: l.name for l in locs}
        id_set = {r[0].id for r in picked_locs}
        loc_by_id = {l.id: l for l in locs}
        for link in links:
            if link.fromId in id_set or link.toId in id_set:
                link_lines.append(
                    f"- {by_id.get(link.fromId, link.fromId)} --{link.relation}--> "
                    f"{by_id.get(link.toId, link.toId)}" + (f" ({link.note})" if link.note else "")
                )
        # 链接扩展：命中地点的直接邻居也带进来（只列一行要点，不占整张卡）
        for link in links:
            for near, far in ((link.fromId, link.toId), (link.toId, link.fromId)):
                if near not in id_set or far in id_set:
                    continue
                other = loc_by_id.get(far)
                if other is None:
                    continue
                brief = _clip((other.description or "").strip(), 60)
                related_loc_lines.append(
                    f"- {other.name}" + (f"：{brief}" if brief else "")
                )
        # 去重、限量
        seen_rel: set = set()
        related_loc_lines = [
            ln for ln in related_loc_lines if not (ln in seen_rel or seen_rel.add(ln))
        ][:6]

    import json as _json

    var_lines = [
        f"- {v.name} ({v.key}: {v.type}) = {_json.dumps(v.value, ensure_ascii=False)}"
        + (f" [char:{v.bindCharacterId}]" if v.bindCharacterId else "")
        + (f" // {v.note}" if v.note else "")
        for v in (project.variables or [])
    ]
    sprite_lines = [
        f"- {s.name} image={s.imageTag}"
        + (f" char={s.characterId}" if s.characterId else "")
        + f" exprs=[{', '.join(e.tag for e in s.expressions)}]"
        for s in (project.sprites or [])
    ]

    # ── 设定条目：按触发词/标题/正文检索，只有命中的进上下文 ──────────────
    # 这是"设定很大也用得动"的关键：条目可以无上限地堆，而每次调用只带相关的几条。
    # 钉住的条目（pinned）永远带上——作者认为"绝不能写错"的那几条。
    entries = [e for e in (getattr(project, "loreEntries", None) or []) if e is not None]
    entry_blocks: List[str] = []
    entry_titles_all: List[str] = []
    pinned_entries: List[Any] = []
    scored_entries: List[Tuple[Any, int]] = []
    for e in entries:
        title = str(getattr(e, "title", "") or "").strip()
        if title:
            entry_titles_all.append(title)
        if bool(getattr(e, "pinned", None)):
            pinned_entries.append(e)
            continue
        scored_entries.append((e, _entry_score(e, ask_lower, effective_tokens)))
    scored_entries.sort(
        key=lambda pair: (pair[1], int(getattr(pair[0], "priority", 0) or 0)), reverse=True
    )

    entry_budget = 3200 if resolved_task in ("outline", "consistency", "scene") else 2400
    used_entry = 0
    picked_entry_titles: List[str] = []

    def _entry_block(e: Any, tag: str) -> str:
        title = str(getattr(e, "title", "") or "（无标题）").strip() or "（无标题）"
        body = _entry_text(e).strip()
        keys = _entry_keywords(e)
        head = f"### {title}" + (f"　[{'/'.join(keys)}]" if keys else "")
        return f"{head}\n{_clip(body, 700)}" if body else head + f"（{tag}）"

    for e in pinned_entries[:6]:
        block = _entry_block(e, "钉住")
        if used_entry + len(block) > entry_budget and entry_blocks:
            break
        entry_blocks.append(block)
        used_entry += len(block)
        picked_entry_titles.append(str(getattr(e, "title", "") or ""))

    for e, score in scored_entries:
        if score < _ENTRY_MIN_SCORE:
            break
        block = _entry_block(e, f"score={score}")
        if used_entry + len(block) > entry_budget:
            break
        entry_blocks.append(block)
        used_entry += len(block)
        picked_entry_titles.append(str(getattr(e, "title", "") or ""))

    # 没进上下文的条目只列标题：让模型（和用户）知道"还有哪些设定可点名"
    rest_titles = [t for t in entry_titles_all if t and t not in picked_entry_titles]
    entry_index_note = ""
    if rest_titles:
        entry_index_note = (
            f"\n（另有 {len(rest_titles)} 条设定未进上下文，需要时可让用户点名："
            f"{_clip('、'.join(rest_titles), 300)}）"
        )

    # ── 角色关系：命中角色的直接关系带出来，避免写错立场 ────────────────
    relation_lines: List[str] = []
    char_links = getattr(project, "characterLinks", None) or []
    if char_links and picked_chars:
        picked_ids = {r[0].id for r in picked_chars}
        char_by_id = {c.id: c for c in project.characters}
        for link in char_links:
            if link.fromId in picked_ids or link.toId in picked_ids:
                a = char_by_id.get(link.fromId)
                b = char_by_id.get(link.toId)
                an = a.displayName if a else str(link.fromId)
                bn = b.displayName if b else str(link.toId)
                line = f"- {an} --{link.label}--> {bn}"
                # 对面没进上下文时，附一行要点（立场判断往往就靠这句）
                far = b if link.fromId in picked_ids else a
                if far is not None and far.id not in picked_ids:
                    brief = _clip((far.bio or far.voice or "").strip(), 60)
                    if brief:
                        line += f"（{far.displayName}：{brief}）"
                relation_lines.append(line)
        seen_rel2: set = set()
        relation_lines = [
            ln for ln in relation_lines if not (ln in seen_rel2 or seen_rel2.add(ln))
        ][:8]

    # Other chapters: prefer extractive digests; raw excerpt only if high score + short
    other_chapter_blocks: List[str] = list(digest_fmt.relatedBlocks)
    for ch in project.chapters:
        if focus_chapter and ch.id == focus_chapter.id:
            continue
        plain = plain_of(ch)
        hay = f"{ch.title}\n{ch.synopsis or ''}\n{plain}"
        score = _score_haystack(hay, effective_tokens)
        already = score >= 4 and any(f"### {ch.title}" in b for b in other_chapter_blocks)
        if score >= 8 and plain and len(plain) < 2500 and not already:
            budget = min(900, 300 + score * 40)
            other_chapter_blocks.append(
                f"### {ch.title}（正文摘录 score={score}）\n{_chapter_head_tail(plain, budget)}"
            )
            included.append(f"摘录章:{ch.title}")

    # Focus chapter — prefer tail for continue/polish/branch/scene
    focus_body = ""
    focus_digest = next((d for d in digests if focus_chapter and d.chapterId == focus_chapter.id), None)
    if focus_chapter:
        plain = plain_of(focus_chapter)
        focus_budget = (
            1800
            if resolved_task == "outline"
            else 5000
            if resolved_task in ("continue", "branch", "scene")
            else 4200
        )
        use_tail = resolved_task in ("continue", "polish", "branch", "scene")
        focus_body = "\n".join(
            p
            for p in [
                f"## 当前章节：{focus_chapter.title}",
                f"Synopsis: {focus_chapter.synopsis}" if focus_chapter.synopsis else "",
                _chapter_tail(plain, focus_budget) if use_tail else _chapter_head_tail(plain, focus_budget),
            ]
            if p
        )
        included.append(f"当前章:{focus_chapter.title}")

    if picked_chars:
        included.append(f"角色×{len(picked_chars)}")
    if picked_locs:
        included.append(f"地点×{len(picked_locs)}")
    if entry_blocks:
        included.append(f"设定条目×{len(entry_blocks)}")
    if relation_lines:
        included.append(f"角色关系×{len(relation_lines)}")
    if related_loc_lines:
        included.append(f"相邻地点×{len(related_loc_lines)}")
    if var_lines:
        included.append(f"变量×{len(var_lines)}")
    if selection:
        included.append(f"选区{len(selection)}字")
    if chatMemory and chatMemory.strip():
        included.append("对话记忆")
    if longChapterMemory and longChapterMemory.strip():
        included.append("长程章节记忆")
    if loreCraft and loreCraft.strip():
        included.append("ACG工艺卡")
    if referenceDocs and referenceDocs.strip():
        included.append("上传资料")

    show_vars = bool(
        var_lines
        and (
            resolved_task in ("consistency", "branch", "scene", "continue")
            or effective_tokens
        )
    )
    show_vars_chat_clipped = bool(var_lines and resolved_task == "chat" and not show_vars)

    # Author style memory: LLM-learned writing-style guide (continuity of voice)
    style_block = ""
    style_samples: List[str] = []
    sm = getattr(project, "styleMemory", None)
    if isinstance(sm, dict):
        guide = str(sm.get("guide") or "").strip()
        samples = [
            str(s).strip() for s in (sm.get("samples") or []) if str(s or "").strip()
        ][:3]
        style_samples = samples
        if guide:
            style_block = (
                "\n## 作者文风记忆（延续作者自己的习惯：续写/改写/润色请贴合此风格；"
                "它是归纳不是圣旨，具体情节仍听用户）\n" + _clip(guide, 1200)
            )
            included.append("文风记忆")
        if samples:
            # 样例比规则更管用：模型模仿"看得见的句子"远比遵守"形容词式的规则"稳。
            style_block += (
                "\n\n【作者原文样例（最重要：模仿它们的句法、节奏与用词密度，不要照抄内容）】\n"
                + "\n".join(f"- {_clip(s, 200)}" for s in samples)
            )
            included.append(f"文风样例×{len(samples)}")

    # 每块都带一个 key：既方便按任务裁剪/作者摘掉，也让"这次带了什么"可解释。
    # 注意 `rules` 刻意**不在** EXCLUDABLE_SECTIONS 里：本次硬规则不是"可摘的参考资料"，
    # 而是这一轮的任务契约，必须首尾各出现一次（末尾那次见下方 tail）。
    head_rules = task_key_rules(resolved_task)
    keyed_sections: List[Tuple[str, str]] = [
        ("meta", "\n".join(meta_lines)),
        (
            "rules",
            (
                "\n## 本次硬规则（先读一遍；末尾会再出现一次）\n"
                + "\n".join(f"- {r}" for r in head_rules)
            )
            if head_rules
            else "",
        ),
        ("bible", f"\n## Story Bible（内部参考，禁止整段搬进正文）\n{bible_block}" if bible_block else ""),
        (
            "lore",
            (
                "\n## 设定条目（按触发词/正文检索命中；内部参考，禁止整段搬进正文）\n"
                + "\n\n".join(entry_blocks)
                + entry_index_note
                if entry_blocks
                else ""
            ),
        ),
        (
            "longMemory",
            (
                f"\n{_clip(longChapterMemory.strip(), 3200)}"
                if longChapterMemory and longChapterMemory.strip()
                else ""
            ),
        ),
        (
            "craft",
            (
                f"\n{_clip(loreCraft.strip(), 2400)}"
                if loreCraft and loreCraft.strip()
                else ""
            ),
        ),
        (
            "referenceDocs",
            (
                f"\n{_clip(referenceDocs.strip(), 12000)}"
                if referenceDocs and referenceDocs.strip()
                else ""
            ),
        ),
        (
            "chatMemory",
            (
                f"\n## 对话滚动记忆（更早轮次压缩，非正式剧情）\n{_clip(chatMemory.strip(), 2800)}"
                if chatMemory and chatMemory.strip()
                else ""
            ),
        ),
        ("index", "\n## 章节目录（含本地摘要）\n" + "\n".join(index_lines)),
        (
            "characters",
            (
                "\n## Characters（内部参考：只校准语气与行为，禁止写入对白当说明书）\n"
                + "\n".join(_char_card(r[0]) for r in picked_chars)
                if picked_chars
                else ""
            ),
        ),
        (
            "relations",
            (
                "\n## 角色关系（命中角色的直接关系；用来避免写错立场）\n"
                + "\n".join(relation_lines)
                if relation_lines
                else ""
            ),
        ),
        (
            "locations",
            (
                "\n## Locations（内部参考：氛围与走位，勿念地名百科）\n"
                + "\n".join(_loc_card(r[0]) for r in picked_locs)
                + ("\n通路:\n" + "\n".join(link_lines) if link_lines else "")
                + ("\n相邻地点:\n" + "\n".join(related_loc_lines) if related_loc_lines else "")
                if picked_locs
                else ""
            ),
        ),
        (
            "variables",
            (
                "\n## Variables / 状态机\n" + "\n".join(var_lines)
                if show_vars
                else (f"\n## Variables / 状态机\n{_clip(chr(10).join(var_lines), 600)}" if show_vars_chat_clipped else "")
            ),
        ),
        ("sprites", f"\n## Sprites\n{_clip(chr(10).join(sprite_lines), 400)}" if sprite_lines else ""),
        ("otherChapters", "\n## 其他章节（摘要优先）\n" + "\n\n".join(other_chapter_blocks) if other_chapter_blocks else ""),
        (
            "focus",
            (
                f"\n{focus_body}" + (f"\n（章摘要备忘: {focus_digest.beatSummary}）" if focus_digest and focus_digest.beatSummary else "")
                if focus_body
                else ""
            ),
        ),
        ("selection", f"\n## 用户选区（审稿/改写焦点）\n{_clip(selection, 2000)}" if selection else ""),
        ("style", style_block),
    ]

    dropped = sections_to_drop(resolved_task, exclude)
    kept_sections = [text for key, text in keyed_sections if text and key not in dropped]
    if dropped:
        # 透明化：告诉作者这次省掉了什么（前端会把没省的显示成"依据"）
        included.append("省去:" + "、".join(sorted(dropped)))
    tail = f"\n## 编排说明\n上下文按任务「{resolved_task}」检索拼装：章摘要本地抽取、大纲节拍检索、对话记忆压缩。人设与 bible 是作者备忘不是讲稿。续写请紧接「当前章节」正文末尾。"
    # 硬规则在**末尾再出现一次**：长上下文里夹在中间的要求最容易被忽略。
    key_rules = task_key_rules(resolved_task)
    if key_rules:
        tail += "\n\n## 本次硬规则（务必遵守）\n" + "\n".join(f"- {r}" for r in key_rules)
        included.append("本次硬规则")
    tail += "\n\n## 输出契约\n" + output_contract(resolved_task)
    included.append("输出契约")

    # 作者自己写的硬规则（"必须/不要/禁止…"）单独拎出来，放进末尾的硬规则区：
    # 它们最容易淹没在世界观叙述里，而末尾的位置才是"当场生效"的。
    from .constraints import author_hard_rules

    bible = project.bible
    author_rules = author_hard_rules(
        bible_text="\n".join(
            [
                str(getattr(bible, "world", "") or ""),
                str(getattr(bible, "notes", "") or ""),
                str(getattr(bible, "themes", "") or ""),
                str(getattr(bible, "outline", "") or ""),
            ]
        ),
        entry_texts=[
            f"{e.title}：{e.body}" for e in (project.loreEntries or [])
        ],
        limit=5,
    )
    if author_rules:
        tail += "\n\n## 作者自己的硬规则（最高优先，务必遵守）\n" + "\n".join(
            f"- {r}" for r in author_rules
        )
        included.append(f"作者硬约束×{len(author_rules)}")
    kept_sections.append(tail)

    # 「证明它记得」：把这次真正用到的资料连同摘录列出来（前端可展开看），
    # 这是"聊天给不了"的东西——作者能核对它到底读了什么，而不是只能猜。
    details: List[Dict[str, str]] = []
    if "lore" not in dropped and entry_blocks:
        for block in entry_blocks[:5]:
            details.append({"label": "设定条目", "preview": _clip(block, 120)})
    if "characters" not in dropped and picked_chars:
        details.append(
            {"label": f"角色×{len(picked_chars)}", "preview": "、".join(r[0].displayName for r in picked_chars[:8])}
        )
    if "locations" not in dropped and picked_locs:
        details.append(
            {"label": f"地点×{len(picked_locs)}", "preview": "、".join(r[0].name for r in picked_locs[:8])}
        )
    if "bible" not in dropped and bible_block:
        details.append({"label": "设定 bible", "preview": _clip(bible_block, 120)})
    if "style" not in dropped and style_samples:
        details.append({"label": "文风样例", "preview": _clip(style_samples[0], 120)})
    if "index" not in dropped and index_lines:
        details.append(
            {"label": f"章节目录×{len(index_lines)}", "preview": "；".join(index_lines[:3])}
        )
    if focus_chapter is not None and "focus" not in dropped:
        details.append(
            {
                "label": "当前章",
                "preview": f"{focus_chapter.title}（{len(focus_body or '')} 字）",
            }
        )

    text = "\n".join(kept_sections)


    # Trim from the least critical middle (other chapters) if over budget
    if len(text) > max_chars:
        overflow = len(text) - max_chars
        if overflow > 0 and other_chapter_blocks:
            light_others_parts = []
            for ch in project.chapters:
                if focus_chapter and ch.id == focus_chapter.id:
                    continue
                if ch.synopsis:
                    light_others_parts.append(f"### {ch.title}\n摘要: {_clip(ch.synopsis, 100)}")
                else:
                    light_others_parts.append(f"### {ch.title}")
            light_others = "\n\n".join(light_others_parts)
            pattern = re.compile(
                r"## 其他章节[\s\S]*?(?=\n## 当前章节|\n## 用户选区|\n## 编排说明|\Z)"
            )
            text = pattern.sub(
                f"## 其他章节（仅摘要，因篇幅压缩）\n{light_others}\n\n", text, count=1
            )
            included.append("已压缩其他章摘录")
        if len(text) > max_chars:
            keep_tail = min(
                int(max_chars * 0.55), len(focus_body) + len(selection or "") + 400
            )
            keep_head = max_chars - keep_tail - 30
            text = f"{text[:keep_head]}\n\n…(上下文中段压缩)…\n\n{text[len(text) - keep_tail:]}"
            included.append("中段压缩")

    return AgentContextResult(
        text=text,
        included=included,
        charsUsed=len(text),
        task=resolved_task,
        excluded=sorted(dropped),
        includedDetails=details,
    )

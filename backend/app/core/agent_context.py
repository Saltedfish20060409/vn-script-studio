"""Ported from packages/core/src/agentContext.ts"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.domain.types import Character, Location, ScriptBlock, VnProject

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
    "consistency": "本轮任务：一致性排查。列矛盾与最小改法；报告里可以引用设定，但建议写入正文时仍遵守反倾倒。",
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
) -> AgentContextResult:
    """Build a retrieval-biased project context for long-form Agent use.

    Prefer: meta + bible digest + chapter index + focus chapter + scored slices.
    """
    max_chars = maxChars if maxChars is not None else 12000
    resolved_task = task or (infer_agent_task(userMessage) if userMessage else "chat")
    included: List[str] = [f"模式:{resolved_task}"]

    focus_chapter = next((c for c in project.chapters if c.id == chapterId), None) or (
        project.chapters[0] if project.chapters else None
    )

    ask_tokens = _tokenize("\n".join([userMessage or "", selection or ""]))
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
    digest_fmt = format_chapter_digest_index(
        digests,
        focus_id=focus_chapter.id if focus_chapter else None,
        tokens=effective_tokens,
        max_related_excerpts=5 if resolved_task == "consistency" else 3,
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
        hay = f"{c.displayName} {c.defineName} {_js(c.voice)} {_js(c.bio)} {_js(c.relationships)} {_js(getattr(c, 'voiceMind', None))}"
        score = _score_haystack(hay, effective_tokens)
        if focus_chapter:
            plain = _blocks_to_plain(focus_chapter.blocks, project.characters)
            if (
                c.displayName in plain
                or c.defineName in plain
                or c.defineName.lower() in plain.lower()
            ):
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
        hay = f"{l.name} {l.imageTag or ''} {l.description or ''} {' '.join(l.tags or [])}"
        score = _score_haystack(hay, effective_tokens)
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
    if links and picked_locs:
        by_id = {l.id: l.name for l in locs}
        id_set = {r[0].id for r in picked_locs}
        for link in links:
            if link.fromId in id_set or link.toId in id_set:
                link_lines.append(
                    f"- {by_id.get(link.fromId, link.fromId)} --{link.relation}--> "
                    f"{by_id.get(link.toId, link.toId)}" + (f" ({link.note})" if link.note else "")
                )

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

    # Other chapters: prefer extractive digests; raw excerpt only if high score + short
    other_chapter_blocks: List[str] = list(digest_fmt.relatedBlocks)
    for ch in project.chapters:
        if focus_chapter and ch.id == focus_chapter.id:
            continue
        plain = _blocks_to_plain(ch.blocks, project.characters)
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
        plain = _blocks_to_plain(focus_chapter.blocks, project.characters)
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

    sections: List[str] = [
        "\n".join(meta_lines),
        f"\n## Story Bible（内部参考，禁止整段搬进正文）\n{bible_block}" if bible_block else "",
        (
            f"\n{_clip(longChapterMemory.strip(), 3200)}"
            if longChapterMemory and longChapterMemory.strip()
            else ""
        ),
        (
            f"\n{_clip(loreCraft.strip(), 2400)}"
            if loreCraft and loreCraft.strip()
            else ""
        ),
        (
            f"\n{_clip(referenceDocs.strip(), 8000)}"
            if referenceDocs and referenceDocs.strip()
            else ""
        ),
        (
            f"\n## 对话滚动记忆（更早轮次压缩，非正式剧情）\n{_clip(chatMemory.strip(), 2800)}"
            if chatMemory and chatMemory.strip()
            else ""
        ),
        "\n## 章节目录（含本地摘要）\n" + "\n".join(index_lines),
        (
            "\n## Characters（内部参考：只校准语气与行为，禁止写入对白当说明书）\n"
            + "\n".join(_char_card(r[0]) for r in picked_chars)
            if picked_chars
            else ""
        ),
        (
            "\n## Locations（内部参考：氛围与走位，勿念地名百科）\n"
            + "\n".join(_loc_card(r[0]) for r in picked_locs)
            + ("\n通路:\n" + "\n".join(link_lines) if link_lines else "")
            if picked_locs
            else ""
        ),
        (
            "\n## Variables / 状态机\n" + "\n".join(var_lines)
            if show_vars
            else (f"\n## Variables / 状态机\n{_clip(chr(10).join(var_lines), 600)}" if show_vars_chat_clipped else "")
        ),
        f"\n## Sprites\n{_clip(chr(10).join(sprite_lines), 400)}" if sprite_lines else "",
        "\n## 其他章节（摘要优先）\n" + "\n\n".join(other_chapter_blocks) if other_chapter_blocks else "",
        (
            f"\n{focus_body}" + (f"\n（章摘要备忘: {focus_digest.beatSummary}）" if focus_digest and focus_digest.beatSummary else "")
            if focus_body
            else ""
        ),
        f"\n## 用户选区（审稿/改写焦点）\n{_clip(selection, 2000)}" if selection else "",
        f"\n## 编排说明\n上下文按任务「{resolved_task}」检索拼装：章摘要本地抽取、大纲节拍检索、对话记忆压缩。人设与 bible 是作者备忘不是讲稿。续写请紧接「当前章节」正文末尾。",
    ]

    text = "\n".join(s for s in sections if s)

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
        text=text, included=included, charsUsed=len(text), task=resolved_task
    )

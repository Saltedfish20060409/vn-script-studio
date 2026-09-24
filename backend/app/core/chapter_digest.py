"""Ported from packages/core/src/chapterDigest.ts"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from app.domain.types import Character, SceneChapter, ScriptBlock, VnProject

_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"

#: 本作品约定的对白写法：「角色名：台词」。只用来**认行首**，名字还要能在角色卡里对上。
_PROSE_SPEAKER_RE = re.compile(r"^([^\s：:，。！？、]{1,12})[：:]")


def _to_base36(n: int) -> str:
    if n == 0:
        return "0"
    digits: List[str] = []
    while n:
        n, r = divmod(n, 36)
        digits.append(_BASE36[r])
    return "".join(reversed(digits))


@dataclass
class ChapterDigest:
    chapterId: str
    title: str
    hash: str
    synopsis: str
    speakers: List[str]
    # Extractive beat summary for long-form index
    beatSummary: str
    openHook: str
    closeHook: str


def _line_from_block(b: ScriptBlock, char_map: Dict[str, Character]) -> Optional[str]:
    btype = b.get("type")
    if btype == "narration":
        return f"旁白: {b['text']}"
    if btype == "dialogue":
        ch = char_map.get(b.get("characterId"))
        name = ch.displayName if ch else b.get("characterId")
        return f"{name}: {b['text']}"
    if btype == "menu":
        return f"选项: {' / '.join(c['text'] for c in b.get('choices', []))}"
    if btype == "raw":
        code = b.get("code", "")
        return code if code.strip() else None
    if btype == "scene":
        return f"[scene {b['image']}]"
    if btype == "label":
        return f"[label {b['name']}]"
    # 演出指令也要进摘要：否则"这章演了什么"在摘要与账本里完全缺失
    if btype == "music":
        return (
            f"[音乐 {b.get('file') or ''}]"
            if (b.get("action") or "play") == "play"
            else "[音乐 停]"
        )
    if btype == "sound":
        return (
            f"[音效 {b.get('file') or ''}]"
            if (b.get("action") or "play") == "play"
            else "[音效 停]"
        )
    if btype == "voice":
        return "[语音]" if (b.get("action") or "play") == "play" else "[语音 停]"
    if btype == "wait":
        return f"[等待 {b.get('seconds') or 0}s]"
    if btype == "camera":
        return f"[镜头 {b.get('at') or ('zoom ' + str(b.get('zoom') or 1))}]"
    if btype == "effect":
        return f"[特效 {b.get('kind') or ''}]"
    if btype == "set":
        return f"[变量 {b.get('key')} {b.get('op') or '='} {b.get('value')}]"
    if btype == "if":
        conds = [
            (br.get("condition") or "否则").strip() for br in (b.get("branches") or [])
        ]
        return f"[条件分支 {' / '.join(conds)}]" if conds else None
    return None


def _collect_lines(chapter: SceneChapter, characters: List[Character]):
    char_map = {c.id: c for c in characters}
    lines: List[str] = []
    speakers: List[str] = []
    seen_speakers: set = set()

    # 正文优先：本作品的主写作面是 `prose`。过去这里只遍历 blocks，于是纯正文写作的章节
    # 收集到 0 行 → 摘要变成「（空章）」、openHook/closeHook 全空 → 账本里既没有章末钩子
    # 也没有出场角色（"保存即攒记忆"对小说作者整条失效）。与 `agent_context.plain_of`、
    # `consistency_scan._chapter_source_text`、`writing_stats.count_chapter_words` 同一口径。
    prose = str(getattr(chapter, "prose", None) or "").strip()
    if prose:
        lines = [p.strip() for p in prose.split("\n") if p.strip()]
        # 出场角色：按本作品约定的对白写法「角色名：台词」从行首认名字（只在名字确实
        # 属于角色卡时才记，避免把"注意："这类普通行首当成人名）。
        names = {}
        for c in characters:
            for key in (c.displayName, getattr(c, "defineName", None), *(c.aliases or [])):
                key = str(key or "").strip()
                if key:
                    names.setdefault(key, c.displayName or key)
        for line in lines:
            head = _PROSE_SPEAKER_RE.match(line)
            if not head:
                continue
            name = names.get(head.group(1).strip())
            if name and name not in seen_speakers:
                seen_speakers.add(name)
                speakers.append(name)
        return lines, speakers

    for b in chapter.blocks:
        if b.get("type") == "dialogue":
            ch = char_map.get(b.get("characterId"))
            name = ch.displayName if ch else b.get("characterId")
            if name not in seen_speakers:
                seen_speakers.add(name)
                speakers.append(name)
        line = _line_from_block(b, char_map)
        if line:
            lines.append(line)
    return lines, speakers


def _hash_str(s: str) -> str:
    h = 2166136261
    for ch in s:
        h = (h ^ ord(ch)) & 0xFFFFFFFF
        h = (h * 16777619) & 0xFFFFFFFF
    return _to_base36(h)


def chapter_content_hash(chapter: SceneChapter) -> str:
    """Cheap content fingerprint for cache invalidation.

    ``sort_keys=True`` 是必须的，不是风格问题：项目 blob 存在 Postgres 的 **jsonb**
    列里，而 jsonb 不保留对象的键顺序（按 key 长度+字节序重排）。不排序的话，
    同一章内容在「新建时的内存对象」与「从库里读回来的对象」之间会算出不同指纹
    ——实测：新建时 stamp 的账本指纹与之后每次保存重算的指纹全部不同，
    导致每一章都被判定为"内容变了"（见 core/pipeline/ledger.py 的增量入库）。
    core/snapshots.py::content_hash_for_payload 用的是同一套写法。

    **prose 必须进指纹**（这是修过的一个真问题）：本作品的主写作面是正文，而过去这里
    只哈希 blocks + 摘要 + 标题——于是纯正文工程里改了正文，指纹不变，
    章摘要/账本被判定为"没变"而永不刷新（"保存即攒记忆"对小说作者整条失效）。
    """
    n = len(chapter.blocks)
    tail = "|".join(
        json.dumps(b, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for b in chapter.blocks[-3:]
    )
    syn = chapter.synopsis or ""
    prose = str(getattr(chapter, "prose", None) or "")
    # 正文只取长度 + 首尾片段：指纹只需要"变了没变"，不必把全文塞进哈希输入
    # （全文哈希会让长章节每次保存都做一遍 O(n) 的字符串拼接）。
    prose_sig = f"{len(prose)}:{prose[:80]}:{prose[-80:]}"
    return f"{chapter.id}:{n}:{len(syn)}:{_hash_str(tail + syn + chapter.title + prose_sig)}"


def _clip(s: str, n: int) -> str:
    t = " ".join(s.split())
    if len(t) <= n:
        return t
    return f"{t[: n - 1]}…"


def make_chapter_digest(chapter: SceneChapter, characters: List[Character]) -> ChapterDigest:
    """Local extractive chapter digest — no server / no LLM.

    Uses synopsis + open/close hooks + speaker list.
    """
    lines, speakers = _collect_lines(chapter, characters)
    open_ = " / ".join(lines[:3])
    close = " / ".join(lines[-4:]) if lines else ""
    beat_parts = [
        p
        for p in [
            (chapter.synopsis or "").strip(),
            f"出场: {'、'.join(speakers)}" if speakers else "",
            f"起: {_clip(open_, 160)}" if open_ else "",
            f"迄: {_clip(close, 200)}" if close and close != open_ else "",
        ]
        if p
    ]

    return ChapterDigest(
        chapterId=chapter.id,
        title=chapter.title,
        hash=chapter_content_hash(chapter),
        synopsis=(chapter.synopsis or "").strip(),
        speakers=speakers,
        beatSummary=" · ".join(beat_parts) or "（空章）",
        openHook=_clip(open_, 120),
        closeHook=_clip(close, 160),
    )


def digest_all_chapters(project: VnProject) -> List[ChapterDigest]:
    return [make_chapter_digest(ch, project.characters) for ch in project.chapters]


def refresh_chapter_index(project: VnProject) -> VnProject:
    """Recompute extractive chapterIndex on the project blob (local, no LLM)."""
    from app.domain.types import ChapterIndexEntry

    entries = [
        ChapterIndexEntry(
            chapterId=d.chapterId,
            title=d.title,
            hash=d.hash,
            synopsis=d.synopsis,
            speakers=list(d.speakers),
            openHook=d.openHook,
            closeHook=d.closeHook,
        )
        for d in digest_all_chapters(project)
    ]
    return project.model_copy(update={"chapterIndex": entries})


def _score_text(hay: str, tokens: List[str]) -> int:
    if not tokens or not hay:
        return 0
    h = hay.lower()
    s = 0
    for tok in tokens:
        if tok.lower() in h:
            s += 3 if len(tok) >= 3 else 2
    return s


@dataclass
class ChapterDigestIndex:
    indexLines: List[str]
    relatedBlocks: List[str]
    included: List[str]


def format_chapter_digest_index(
    digests: List[ChapterDigest],
    focus_id: Optional[str] = None,
    tokens: Optional[List[str]] = None,
    max_related_excerpts: Optional[int] = None,
    volume_titles: Optional[Dict[str, str]] = None,
) -> ChapterDigestIndex:
    """Format other-chapter digests for Agent context (prefer digest over raw dump).

    ``volume_titles`` 是 章节 id → 卷标题 的映射（分卷的作品才有）。带上它，模型看到的
    章节目录就是「【第一卷】1. …」这种带卷的结构——长篇续写时它才知道自己在写哪一卷。
    """
    tokens = tokens or []
    included = [f"章摘要×{len(digests)}"]
    volumes = volume_titles or {}
    lines: List[str] = []
    for i, d in enumerate(digests):
        label = volumes.get(d.chapterId)
        prefix = f"【{label}】" if label else ""
        lines.append(
            f"{prefix}{i + 1}. {d.title}{'◀当前' if d.chapterId == focus_id else ''} — {_clip(d.beatSummary, 100)}"
        )
    index_lines = lines

    ranked = sorted(
        (
            (d, _score_text(f"{d.title} {d.synopsis} {d.beatSummary} {' '.join(d.speakers)}", tokens))
            for d in digests
            if d.chapterId != focus_id
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )

    related_blocks: List[str] = []
    max_ex = max_related_excerpts if max_related_excerpts is not None else 3
    excerpted = 0
    for d, score in ranked:
        if score >= 4 and excerpted < max_ex:
            related_blocks.append(
                f"### {d.title}（摘要 score={score}）\n{d.beatSummary}\n迄钩子: {d.closeHook or '（无）'}"
            )
            included.append(f"摘要章:{d.title}")
            excerpted += 1
        else:
            related_blocks.append(f"### {d.title}\n{_clip(d.beatSummary, 140)}")

    return ChapterDigestIndex(indexLines=index_lines, relatedBlocks=related_blocks, included=included)

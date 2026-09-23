"""长程一致性图检查：把「事实总线」从扁平候选列表补成可推理的图。

为什么需要这个模块
------------------
`fact_extract.py` 那条事实总线存的是**候选与证据**（角色关系 / 时间线事件），
`reconcile_stale` 只会做一件事：正文里找不到引文了就标 stale。两者都答不出
作者真正会踩的坑：

- 「这句台词是谁说的」——说话人 id 既不是角色 id 也不是 defineName，导出后静默变成旁白；
- 「这条关系连到谁」——关系 / 地图的某一端指向已被删掉的实体（断头边）；
- 「这两个角色是不是同一个人」——两人撞了同一个显示名或别名，检索与 AI 提取会串味；
- 「这个事件发生在哪一章」——章节被删了，时间线事件失去落脚点；
- 「角色已经去世了，第 5 章怎么还在说话」——跨章事实冲突。

本模块把这些做成**确定性静态检查**（纯本地、不调任何 LLM），因此可进单测、可进 CI。
输出形状与 `branch_analysis.analyze_branches` 对齐（`findings` 扁平列表 + `counts`），
前端可以复用同一套渲染。

设计取舍（踩过的坑）
--------------------
1. **一次遍历喂所有检测器**：文本类检查共用 `blocks.iter_project_blocks` 的一次遍历
   结果（**含菜单选项正文与 if 分支正文**）。分开各遍历一次，就会重演
   "某条检查少算一层、作者写在分支里的台词凭空消失"那类缺陷。
2. **只报能确证的**：名字匹配、死亡标记这类启发式判断，拿不准的一律进
   `summary["unknown"]` 计数，不塞进 `findings`——一个会误报的静态检查最终会被
   作者整体关掉，那时它连真问题也报不出来了。
3. **死亡判定取"最晚的一条死亡记录"当分界**：取最早那条的话，"第一章受伤/宣告死亡"
   之后第三章的正常戏份会被误报成"死人说话"。宁可漏报，也不给一眼假的报告。
4. **与 `reconcile_stale` 不重复**：那个机制要作者先跑一次对账并把 stale 标记存回工程；
   这里只读工程本身，任何时候都能算，也不改任何数据。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.blocks import iter_project_blocks
from app.core.fact_extract import timeline_dedupe_key
from app.domain.types import Character, VnProject

# --------------------------------------------------------------------- 参数

DEATH_MARKERS: Tuple[str, ...] = (
    "死亡",
    "死了",
    "牺牲",
    "去世",
    "身亡",
    "殒命",
    "不在了",
    "已故",
)
"""死亡 / 退场标记词。**故意收得很窄**：像"失踪""昏迷""退场""离开"都不是死亡，
混进来必然误报，而误报会让整条检查失去可信度。"""

_BG_PREFIXES = frozenset({"bg", "cg", "background", "scenery"})
"""Ren'Py 约定里背景 / CG 的首词。

`show` 块只有在首词落在这里（且不是任何立绘 tag）时才去查地点覆盖；其余一律跳过。
理由：`show linxia sad` 这种写错的立绘属于资产审计（`asset_audit`）的活，
在这里报成"未知地点"只会制造噪音。"""

_SNIPPET_LIMIT = 30
_MAX_ORDER_FINDINGS = 20
_SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}
_ASCII_NAME_RE = re.compile(r"[0-9a-z_\- .]+")
"""纯 ASCII 名字（英文名 / 拼音 / Ren'Py defineName）。中文名不走这条分支。"""


# ------------------------------------------------------------------ 数据结构


@dataclass(frozen=True)
class _FoldedText:
    """折叠后的文本：小写、空白压缩，另存一份去掉空白的版本。

    为什么不只留一份：英文名要按**词边界**匹配（否则 defineName「lin」会在
    「lining」里命中），而中文名在文本里可能被空格/换行打断，按去空白后的子串匹配
    才稳。两种匹配需要两种形态，都在这里一次算好。
    """

    plain: str
    nospace: str

    @classmethod
    def of(cls, text: str) -> "_FoldedText":
        plain = re.sub(r"\s+", " ", text or "").casefold()
        return cls(plain=plain, nospace=plain.replace(" ", ""))


@dataclass(frozen=True)
class _Line:
    """一条台词：说话人 + 所在章节与 label（label 让前端能定位到剧本里那一行）。"""

    chapter_id: str
    label: str
    character_id: str
    text: str


@dataclass(frozen=True)
class _ImageRef:
    """一次图片来源引用（scene / show）。"""

    chapter_id: str
    label: str
    image: str
    block_type: str


@dataclass
class _Corpus:
    """一次遍历得到的全项目视图，所有检测器共用。"""

    chapter_ids: List[str]
    chapter_index: Dict[str, int]
    chapter_titles: Dict[str, str]
    lines: List[_Line]
    scene_images: List[_ImageRef]
    show_images: List[_ImageRef]
    text: _FoldedText


@dataclass
class _Check:
    """一个检测器的产出：findings + 检查量 + 拿不准而**没报**的计数。"""

    code: str
    checked: int = 0
    findings: List[Dict[str, Any]] = field(default_factory=list)
    unknown: Dict[str, int] = field(default_factory=dict)

    def note_unknown(self, key: str, n: int = 1) -> None:
        self.unknown[key] = self.unknown.get(key, 0) + n


# -------------------------------------------------------------------- 遍历


def _collect(project: VnProject) -> _Corpus:
    """一次遍历收集全部检测器需要的东西（含菜单选项与 if 分支正文）。"""
    chapters = list(project.chapters or [])
    chapter_ids = [str(getattr(ch, "id", "") or "") for ch in chapters]
    chapter_index = {cid: i for i, cid in enumerate(chapter_ids) if cid}
    chapter_titles = {
        str(getattr(ch, "id", "") or ""): str(getattr(ch, "title", "") or "")
        for ch in chapters
    }
    lines: List[_Line] = []
    scene_images: List[_ImageRef] = []
    show_images: List[_ImageRef] = []
    # 「被提到过没有」要算上标题/简介/手稿：它们也是作品的一部分，漏算的话
    # 只在章节标题里出现的角色会被误报成"废弃角色卡"。手稿（prose）是默认写作面，
    # 更不能不算——作者可能整章都写在手稿里。
    texts: List[str] = []
    for ch in chapters:
        texts.append(str(getattr(ch, "title", "") or ""))
        texts.append(str(getattr(ch, "synopsis", "") or ""))
        texts.append(str(getattr(ch, "prose", "") or ""))
    current_label: Dict[str, str] = {}
    for cid, b in iter_project_blocks(project):
        btype = str(b.get("type") or "")
        if btype == "label":
            name = str(b.get("name") or "").strip()
            if name:
                current_label[cid] = name
            continue
        label = current_label.get(cid, "")
        if btype == "dialogue":
            text = str(b.get("text") or "").strip()
            lines.append(_Line(cid, label, str(b.get("characterId") or ""), text))
            if text:
                texts.append(text)
        elif btype == "narration":
            texts.append(str(b.get("text") or ""))
        elif btype == "menu":
            texts.append(str(b.get("prompt") or ""))
            for choice in b.get("choices") or []:
                if isinstance(choice, dict):
                    texts.append(str(choice.get("text") or ""))
        elif btype in ("scene", "show"):
            image = str(b.get("image") or "").strip()
            if not image:
                continue
            ref = _ImageRef(cid, label, image, btype)
            (scene_images if btype == "scene" else show_images).append(ref)
    return _Corpus(
        chapter_ids=chapter_ids,
        chapter_index=chapter_index,
        chapter_titles=chapter_titles,
        lines=lines,
        scene_images=scene_images,
        show_images=show_images,
        text=_FoldedText.of("\n".join(t for t in texts if t.strip())),
    )


# ---------------------------------------------------------------- 小工具


def _chapter_display(corpus: _Corpus, chapter_id: str) -> str:
    """章节的可读名字：`第 3 章（雪夜）`。找不到 id 时说清是"未定位"。"""
    cid = str(chapter_id or "")
    idx = corpus.chapter_index.get(cid)
    title = (corpus.chapter_titles.get(cid) or "").strip()
    if idx is None:
        return f"章节「{cid}」" if cid else "未定位章节"
    return f"第 {idx + 1} 章（{title}）" if title else f"第 {idx + 1} 章"


def _where(corpus: _Corpus, chapter_id: str, label: str) -> str:
    loc = _chapter_display(corpus, chapter_id)
    return f"{loc} label「{label}」" if label else loc


def _snippet(text: str, limit: int = _SNIPPET_LIMIT) -> str:
    flat = re.sub(r"\s+", " ", (text or "").strip())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def _num(value: float) -> str:
    return f"{value:g}"


def _finding(
    severity: str,
    code: str,
    message: str,
    chapter_id: str = "",
    label: str = "",
) -> Dict[str, Any]:
    """与 `branch_analysis._finding` 同形，只把 source 换成 continuity。"""
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "source": "continuity",
        "chapterId": chapter_id,
        "label": label,
    }


def _character_index(project: VnProject) -> Dict[str, Character]:
    """角色索引：**id 与 defineName 都能解析**。

    为什么两个都要：导出器（`renpy._char_lookup`）本身就是按 id 或 defineName 找人的，
    老工程与导入的剧本两种写法都有。只认 id 会把合法说话人误报成"角色不存在"。
    """
    index: Dict[str, Character] = {}
    for c in project.characters or []:
        raw_id = str(getattr(c, "id", "") or "")
        if raw_id:
            index.setdefault(raw_id, c)
            index.setdefault(raw_id.casefold(), c)
        define = str(getattr(c, "defineName", "") or "").strip()
        if define:
            index.setdefault(define, c)
            index.setdefault(define.casefold(), c)
    return index


def _resolve_character(index: Dict[str, Character], raw: str) -> Optional[Character]:
    key = str(raw or "").strip()
    if not key:
        return None
    return index.get(key) or index.get(key.casefold())


def _character_names(c: Character) -> List[str]:
    """用于"被提到过没有"的名字集合：显示名 + defineName + 别名。"""
    raw = [str(getattr(c, "displayName", "") or ""), str(getattr(c, "defineName", "") or "")]
    raw += [str(a) for a in (getattr(c, "aliases", None) or [])]
    return [n for n in raw if n.strip()]


def _mentions(text: _FoldedText, name: str) -> bool:
    """名字（或别名）是否真的出现在文本里。

    ASCII 名走词边界匹配、且要求至少 2 个字符：不做边界的话 defineName「lin」会在
    「lining」里命中，于是"从未被提到"的角色永远报不出来；单字母名则任何文本里几乎
    都能凑出来，直接视为不可判定（不当作命中，也不报缺口）。
    """
    raw = str(name or "").strip()
    if not raw:
        return False
    folded = _FoldedText.of(raw)
    if _ASCII_NAME_RE.fullmatch(folded.plain):
        if len(folded.nospace) < 2:
            return False
        pattern = re.escape(folded.plain).replace(r"\ ", r"\s+")
        return re.search(rf"(?<![0-9a-z_]){pattern}(?![0-9a-z_])", text.plain) is not None
    return folded.nospace in text.nospace


def _mentions_any(text: str, names: List[str]) -> bool:
    folded = _FoldedText.of(text)
    return any(_mentions(folded, n) for n in names)


def _death_marker(text: str) -> Optional[str]:
    for marker in DEATH_MARKERS:
        if marker in text:
            return marker
    return None


def _event_chapter(event: Any, corpus: _Corpus) -> str:
    """事件能定位到哪个章节：先看 chapterRef，再退回 evidence 里的 chapterId。"""
    ref = str(getattr(event, "chapterRef", "") or "").strip()
    if ref and ref in corpus.chapter_index:
        return ref
    for ev in getattr(event, "evidence", None) or []:
        cid = str(getattr(ev, "chapterId", "") or "").strip()
        if cid and cid in corpus.chapter_index:
            return cid
    return ""


def _lore_chapter(entry: Any, corpus: _Corpus) -> str:
    """设定条目靠 `links` 里的章节边定位；没有这条边就没法判断先后。"""
    for link in getattr(entry, "links", None) or []:
        if str(getattr(link, "toType", "") or "") != "chapter":
            continue
        cid = str(getattr(link, "toId", "") or "").strip()
        if cid and cid in corpus.chapter_index:
            return cid
    return ""


# -------------------------------------------------------------- 检测器：角色


def _check_unknown_speaker(project: VnProject, corpus: _Corpus) -> _Check:
    """说话人解析不到任何角色卡（导出后会静默变成旁白）。"""
    chk = _Check(code="unknown_speaker")
    index = _character_index(project)
    for line in corpus.lines:
        chk.checked += 1
        if _resolve_character(index, line.character_id) is not None:
            continue
        where = _where(corpus, line.chapter_id, line.label)
        quote = _snippet(line.text) or "（空台词）"
        raw = line.character_id.strip()
        if raw:
            message = (
                f"{where}的台词说话人 id「{raw}」既不是角色 id 也不是 defineName"
                f"（台词：「{quote}」）：导出 Ren'Py 时这句会静默变成旁白 narrator，"
                "试玩时也归不到任何角色"
            )
        else:
            message = (
                f"{where}有一句台词没有指定说话人（台词：「{quote}」）："
                "导出 Ren'Py 时会算成旁白"
            )
        chk.findings.append(
            _finding("error", chk.code, message, line.chapter_id, line.label)
        )
    return chk


def _check_character_links(project: VnProject, corpus: _Corpus) -> _Check:
    """角色关系的某一端指向不存在的角色（图上的断头边）。"""
    chk = _Check(code="dangling_character_link")
    known = {str(getattr(c, "id", "") or "") for c in project.characters or []}
    known.discard("")
    for link in project.characterLinks or []:
        chk.checked += 1
        missing: List[str] = []
        seen: Set[str] = set()
        for end, value in (("起点", str(link.fromId or "")), ("终点", str(link.toId or ""))):
            if value in known or value in seen:
                continue
            seen.add(value)
            missing.append(f"{end}「{value or '（空）'}」")
        if not missing:
            continue
        label = str(link.label or "")
        chk.findings.append(
            _finding(
                "error",
                chk.code,
                f"角色关系「{label or '未命名'}」的{'、'.join(missing)}不在角色卡里："
                "这条边连不上任何角色，沿它检索会捞到空",
                "",
                label,
            )
        )
    return chk


def _check_location_links(project: VnProject, corpus: _Corpus) -> _Check:
    """地图连线的某一端指向不存在的地点。"""
    chk = _Check(code="dangling_location_link")
    known = {str(getattr(loc, "id", "") or "") for loc in project.locations or []}
    known.discard("")
    for link in project.locationLinks or []:
        chk.checked += 1
        missing: List[str] = []
        seen: Set[str] = set()
        for end, value in (("起点", str(link.fromId or "")), ("终点", str(link.toId or ""))):
            if value in known or value in seen:
                continue
            seen.add(value)
            missing.append(f"{end}「{value or '（空）'}」")
        if not missing:
            continue
        relation = str(getattr(link, "relation", "") or "")
        chk.findings.append(
            _finding(
                "error",
                chk.code,
                f"地图连线（{relation or '未标关系'}）的{'、'.join(missing)}不在地点表里："
                "这条连线画不到任何地点上",
                "",
                relation,
            )
        )
    return chk


def _check_alias_collision(project: VnProject, corpus: _Corpus) -> _Check:
    """两个角色共用了同一个名字/别名（含跨角色的别名撞名）。"""
    chk = _Check(code="alias_collision")
    buckets: Dict[str, List[Tuple[str, str, str, str]]] = {}
    for c in project.characters or []:
        chk.checked += 1
        cid = str(getattr(c, "id", "") or "")
        owner = str(getattr(c, "displayName", "") or cid)
        entries: List[Tuple[str, str]] = [
            ("显示名", str(getattr(c, "displayName", "") or "")),
            ("defineName", str(getattr(c, "defineName", "") or "")),
        ]
        entries += [("别名", str(a)) for a in (getattr(c, "aliases", None) or [])]
        for kind, raw in entries:
            key = _FoldedText.of(raw).nospace
            if not key:
                continue
            buckets.setdefault(key, []).append((cid, owner, kind, raw))
    for key in sorted(buckets):
        entries = buckets[key]
        # 同一个角色自己的显示名与别名相同不算撞名：只有**跨角色**共用才是问题。
        owners: Dict[str, Tuple[str, str, str]] = {}
        for cid, owner, kind, raw in entries:
            owners.setdefault(cid, (owner, kind, raw))
        if len(owners) < 2:
            continue
        shown = "、".join(
            f"角色「{owner}」（{kind}：{raw}）" for owner, kind, raw in owners.values()
        )
        chk.findings.append(
            _finding(
                "error",
                chk.code,
                f"撞名「{entries[0][3]}」：{shown} 用的是同一个名字："
                "检索与 AI 提取会把两个人当成一个，台词与关系都会串味",
                "",
                entries[0][3],
            )
        )
    return chk


def _check_unused_cards(project: VnProject, corpus: _Corpus) -> _Check:
    """角色卡既没有说话、名字也没在任何文本里出现过（info，不是缺陷）。"""
    chk = _Check(code="unused_character_card")
    index = _character_index(project)
    speaking: Set[str] = set()
    for line in corpus.lines:
        c = _resolve_character(index, line.character_id)
        if c is not None:
            speaking.add(str(getattr(c, "id", "") or ""))
    for c in project.characters or []:
        chk.checked += 1
        if str(getattr(c, "id", "") or "") in speaking:
            continue
        names = _character_names(c)
        if not names:
            chk.note_unknown("characterWithoutAnyName")
            continue
        if any(_mentions(corpus.text, n) for n in names):
            continue
        display = str(getattr(c, "displayName", "") or getattr(c, "id", "") or "")
        chk.findings.append(
            _finding(
                "info",
                chk.code,
                f"角色卡「{display}」全篇没有台词，名字/别名也从没在旁白、对白或手稿里"
                "出现过：要么这是一张废弃设定，要么作者忘了让它上场",
                "",
                display,
            )
        )
    return chk


# -------------------------------------------------------------- 检测器：地点


def _location_keys(project: VnProject) -> Set[str]:
    """地点能"认领"哪些图：name / imageTag / id / 别名（都去空白小写）。

    为什么带上别名与 id：只是为了让**真能对上**的图不被误报成"没人认领"；
    这不会放过真正的写错——拼错的图名对不上任何一项。
    """
    keys: Set[str] = set()
    for loc in project.locations or []:
        raw = [
            str(getattr(loc, "name", "") or ""),
            str(getattr(loc, "imageTag", "") or ""),
            str(getattr(loc, "id", "") or ""),
        ]
        raw += [str(a) for a in (getattr(loc, "aliases", None) or [])]
        for item in raw:
            key = _FoldedText.of(item).nospace
            if len(key) >= 2:
                keys.add(key)
    return keys


def _sprite_tags(project: VnProject) -> Set[str]:
    tags: Set[str] = set()
    for sprite in project.sprites or []:
        tag = str(getattr(sprite, "imageTag", "") or "").strip().casefold()
        if tag:
            tags.add(tag)
    for c in project.characters or []:
        tag = str(getattr(c, "imageTag", "") or "").strip().casefold()
        if tag:
            tags.add(tag)
    return tags


def _check_location_tags(project: VnProject, corpus: _Corpus) -> _Check:
    """场景图（以及明显不是立绘的 show）没有被任何地点认领。"""
    chk = _Check(code="unknown_location_tag")
    keys = _location_keys(project)
    sprite_tags = _sprite_tags(project)
    refs = list(corpus.scene_images) + list(corpus.show_images)
    first_seen: Dict[str, _ImageRef] = {}
    if not project.locations:
        # 项目压根没建地点表时，这里没有"权威"可比对：全报会变成一片噪音，
        # 所以整条检查跳过，只把数量记进 unknown（作者补了地点表它才会开始说话）。
        for ref in refs:
            chk.checked += 1
            chk.note_unknown("locationTableEmpty")
        return chk
    for ref in refs:
        chk.checked += 1
        head = ref.image.split()[0].strip().casefold() if ref.image.split() else ""
        if ref.block_type == "show":
            if head in sprite_tags:
                continue  # 立绘：交给 asset_audit，不在这里报
            if head not in _BG_PREFIXES:
                chk.note_unknown("showImageNotClassified")
                continue
        image_key = _FoldedText.of(ref.image).nospace
        if any(key in image_key for key in keys):
            continue
        first_seen.setdefault(image_key, ref)
    for image_key in sorted(first_seen):
        ref = first_seen[image_key]
        chk.findings.append(
            _finding(
                "warn",
                chk.code,
                f"{_where(corpus, ref.chapter_id, ref.label)}引用的场景图「{ref.image}」"
                "没有任何地点认领：地点表里没有哪个 name/imageTag 能对上它——"
                "要么补一条地点，要么这是拼错的图名（Ren'Py 里会直接缺图）",
                ref.chapter_id,
                ref.label,
            )
        )
    return chk


# ------------------------------------------------------------ 检测器：时间线


def _check_timeline_refs(project: VnProject, corpus: _Corpus) -> _Check:
    """时间线事件的 chapterRef 指向不存在的章节。"""
    chk = _Check(code="timeline_bad_ref")
    for event in project.timeline or []:
        chk.checked += 1
        ref = str(getattr(event, "chapterRef", "") or "").strip()
        if not ref:
            chk.note_unknown("timelineWithoutChapter")
            continue
        if ref in corpus.chapter_index:
            continue
        chk.findings.append(
            _finding(
                "error",
                chk.code,
                f"时间线事件「{str(getattr(event, 'title', '') or '未命名')}」关联的章节 "
                f"id「{ref}」不存在（章节多半已被删除）：这条事件在故事线上没有落脚点",
                "",
                str(getattr(event, "title", "") or ""),
            )
        )
    return chk


def _check_timeline_duplicates(project: VnProject, corpus: _Corpus) -> _Check:
    """同标题 + 同章节的事件登记了多次。

    去重键直接复用事实总线的 `timeline_dedupe_key`：两处对"同一条事件"的判定必须一致，
    否则作者会在收件箱里看到"已存在"，体检报告却说"重复"。
    """
    chk = _Check(code="duplicate_timeline_event")
    groups: Dict[str, List[Any]] = {}
    for event in project.timeline or []:
        chk.checked += 1
        key = timeline_dedupe_key(
            str(getattr(event, "title", "") or ""), getattr(event, "chapterRef", None)
        )
        groups.setdefault(key, []).append(event)
    for key in sorted(groups):
        events = groups[key]
        if len(events) < 2:
            continue
        first = events[0]
        ref = str(getattr(first, "chapterRef", "") or "").strip()
        where = _chapter_display(corpus, ref) if ref else "（未关联章节）"
        chk.findings.append(
            _finding(
                "warn",
                chk.code,
                f"时间线事件「{str(getattr(first, 'title', '') or '未命名')}」在{where}"
                f"登记了 {len(events)} 次：同一条事件重复登记，对账时会当成多个事件，"
                "先后顺序也说不清",
                ref,
                str(getattr(first, "title", "") or ""),
            )
        )
    return chk


def _check_timeline_order(project: VnProject, corpus: _Corpus) -> _Check:
    """事件的 `order` 排序与它们所在章节的先后矛盾。

    判定的是**跨章**的矛盾：第 1 章的事件 order 比第 3 章的还大，说明按 order 排出来的
    顺序会把两章读反。同章内的事件怎么排是作者的自由，这里不管。
    """
    chk = _Check(code="timeline_order_conflict")
    located: List[Tuple[int, float, Any]] = []
    for event in project.timeline or []:
        chk.checked += 1
        ref = str(getattr(event, "chapterRef", "") or "").strip()
        idx = corpus.chapter_index.get(ref)
        if idx is None:
            chk.note_unknown("timelineOrderUncheckable")
            continue
        try:
            order = float(getattr(event, "order", 0.0) or 0.0)
        except (TypeError, ValueError):
            chk.note_unknown("timelineOrderNotNumeric")
            continue
        located.append((idx, order, event))
    # 不同章却给了同一个 order：排序有歧义，但**不算矛盾**，只计数。
    by_order: Dict[float, Set[int]] = {}
    for idx, order, _event in located:
        by_order.setdefault(order, set()).add(idx)
    chk.note_unknown(
        "timelineOrderTies", sum(1 for chapters in by_order.values() if len(chapters) > 1)
    )
    reported: Set[Tuple[str, str]] = set()
    for idx, order, event in located:
        if len(chk.findings) >= _MAX_ORDER_FINDINGS:
            chk.note_unknown("timelineOrderFindingsTruncated")
            continue
        candidate: Optional[Tuple[int, float, Any]] = None
        for other_idx, other_order, other in located:
            if other_idx <= idx or other_order >= order:
                continue
            if candidate is None or (other_order, str(getattr(other, "id", ""))) < (
                candidate[1],
                str(getattr(candidate[2], "id", "")),
            ):
                candidate = (other_idx, other_order, other)
        if candidate is None:
            continue
        pair = (str(getattr(event, "id", "")), str(getattr(candidate[2], "id", "")))
        if pair in reported:
            continue
        reported.add(pair)
        ref = str(getattr(event, "chapterRef", "") or "")
        other_ref = str(getattr(candidate[2], "chapterRef", "") or "")
        chk.findings.append(
            _finding(
                "warn",
                chk.code,
                f"时间线顺序冲突：{_chapter_display(corpus, ref)}的事件"
                f"「{str(getattr(event, 'title', '') or '未命名')}」order={_num(order)}，"
                f"却排在{_chapter_display(corpus, other_ref)}的事件"
                f"「{str(getattr(candidate[2], 'title', '') or '未命名')}」"
                f"order={_num(candidate[1])} 之后——只按 order 排会把两章读反",
                ref,
                str(getattr(event, "title", "") or ""),
            )
        )
    return chk


# ------------------------------------------------------ 检测器：死亡后还有戏


@dataclass(frozen=True)
class _DeathRecord:
    """一条"该角色已死亡/退场"的线索，以及它能定位到的章节。"""

    chapter_id: str
    source: str
    title: str
    marker: str


def _check_death_then_speaks(project: VnProject, corpus: _Corpus) -> _Check:
    """**启发式**：文本里记了某角色死亡，但更靠后的章节里他还有台词。"""
    chk = _Check(code="death_then_speaks")
    index = _character_index(project)
    records: Dict[str, List[_DeathRecord]] = {}
    for c in project.characters or []:
        chk.checked += 1
        names = _character_names(c)
        if not names:
            chk.note_unknown("characterWithoutAnyName")
            continue
        cid = str(getattr(c, "id", "") or "")
        # ① 时间线事件：标题/摘要/时间标签里同时出现名字与死亡标记
        for event in project.timeline or []:
            text = " ".join(
                [
                    str(getattr(event, "title", "") or ""),
                    str(getattr(event, "summary", "") or ""),
                    str(getattr(event, "when", "") or ""),
                ]
            )
            marker = _death_marker(text)
            if marker is None or not _mentions_any(text, names):
                continue
            chapter_id = _event_chapter(event, corpus)
            if not chapter_id:
                chk.note_unknown("deathEvidenceWithoutChapter")
                continue
            records.setdefault(cid, []).append(
                _DeathRecord(chapter_id, "时间线事件", str(getattr(event, "title", "") or ""), marker)
            )
        # ② 设定条目：靠 links 里的章节边定位，没这条边就不敢报
        for entry in project.loreEntries or []:
            text = " ".join(
                [
                    str(getattr(entry, "title", "") or ""),
                    str(getattr(entry, "body", "") or ""),
                    " ".join(str(k) for k in (getattr(entry, "keywords", None) or [])),
                ]
            )
            marker = _death_marker(text)
            if marker is None or not _mentions_any(text, names):
                continue
            chapter_id = _lore_chapter(entry, corpus)
            if not chapter_id:
                chk.note_unknown("deathEvidenceWithoutChapter")
                continue
            records.setdefault(cid, []).append(
                _DeathRecord(chapter_id, "设定条目", str(getattr(entry, "title", "") or ""), marker)
            )
        # ③ 角色卡 bio：只有文字、没有章节落点 → 判不了先后，只进 unknown
        if _death_marker(str(getattr(c, "bio", "") or "")) is not None:
            chk.note_unknown("deathMentionedInCardOnly")

    by_character: Dict[str, List[_Line]] = {}
    for line in corpus.lines:
        owner = _resolve_character(index, line.character_id)
        if owner is not None:
            by_character.setdefault(str(getattr(owner, "id", "") or ""), []).append(line)

    for cid in sorted(records):
        event_records = records[cid]
        # 取最晚的一条死亡记录当分界（模块 docstring 的取舍 3）：把"第一章宣告死亡"
        # 之后第三章的正常戏份从误报里摘出去。
        best = max(
            event_records,
            key=lambda r: (
                corpus.chapter_index.get(r.chapter_id, -1),
                r.title,
                r.marker,
            ),
        )
        death_idx = corpus.chapter_index.get(best.chapter_id, -1)
        if death_idx < 0:
            continue
        later = [
            line
            for line in by_character.get(cid, [])
            if corpus.chapter_index.get(line.chapter_id, -1) > death_idx
        ]
        if not later:
            continue
        first = later[0]
        owner_char = _resolve_character(index, cid)
        display = str(getattr(owner_char, "displayName", "") or cid)
        chk.findings.append(
            _finding(
                "warn",
                chk.code,
                f"角色「{display}」在{_chapter_display(corpus, first.chapter_id)}还有台词"
                f"（「{_snippet(first.text) or '（空台词）'}」），但"
                f"{_chapter_display(corpus, best.chapter_id)}的{best.source}"
                f"「{best.title or '未命名'}」已记录该角色{best.marker}"
                f"（命中标记词「{best.marker}」）：这是**启发式**判断（按名字+关键词匹配），"
                "闪回、倒叙、回忆、转述请忽略",
                first.chapter_id,
                first.label,
            )
        )
    return chk


# ------------------------------------------------------------------ 汇总


def analyze_continuity(project: VnProject) -> Dict[str, Any]:
    """长程一致性体检（确定性静态分析，纯本地）。

    空工程、没有角色的工程、没有章节的工程都安全返回：所有检测器只读不写，
    不抛异常。`counts["pass"]` 与 `branch_analysis` 保持同一口径——**没有 error 就算过**，
    warn/info 是提示不是失败。
    """
    corpus = _collect(project)
    checks = [
        _check_unknown_speaker(project, corpus),
        _check_character_links(project, corpus),
        _check_location_links(project, corpus),
        _check_alias_collision(project, corpus),
        _check_unused_cards(project, corpus),
        _check_location_tags(project, corpus),
        _check_timeline_refs(project, corpus),
        _check_timeline_duplicates(project, corpus),
        _check_timeline_order(project, corpus),
        _check_death_then_speaks(project, corpus),
    ]
    findings = [f for chk in checks for f in chk.findings]
    findings.sort(
        key=lambda f: (
            _SEVERITY_ORDER.get(str(f["severity"]), 9),
            str(f["code"]),
            str(f["message"]),
        )
    )
    counts = Counter(str(f["severity"]) for f in findings)
    unknown: Dict[str, int] = {}
    for chk in checks:
        for key, value in chk.unknown.items():
            unknown[key] = unknown.get(key, 0) + value
    return {
        "findings": findings,
        "counts": {
            "error": counts.get("error", 0),
            "warn": counts.get("warn", 0),
            "info": counts.get("info", 0),
            "pass": counts.get("error", 0) == 0,
        },
        "summary": {
            "chapters": len(corpus.chapter_ids),
            "characters": len(project.characters or []),
            "locations": len(project.locations or []),
            "dialogueLines": len(corpus.lines),
            "sceneImages": len(corpus.scene_images),
            "timelineEvents": len(project.timeline or []),
            "characterLinks": len(project.characterLinks or []),
            "locationLinks": len(project.locationLinks or []),
            "checks": {
                chk.code: {"checked": chk.checked, "issues": len(chk.findings)}
                for chk in checks
            },
            "unknown": dict(sorted(unknown.items())),
        },
    }

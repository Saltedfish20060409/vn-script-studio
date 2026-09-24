"""记忆探针：按 LongMemEval 的维度检查"该进上下文的东西有没有真的进去"。

## 依据与定位

[LongMemEval](https://arxiv.org/abs/2410.10813) 把长期记忆拆成几个可分别测量的维度
（信息抽取 / 多会话推理 / 时间推理 / 知识更新 / 拒答），而不是笼统问"记性好不好"。
这套拆法的价值在于**每一步都能单独判定**——我们的上下文组装正好也是这样一条流水线，
所以可以拿来当检查表。

**本模块测的是"检索层"，不是"模型层"**：不调模型，只回答"这一轮的上下文里有没有
那段该有的证据"。它不能证明模型会用、也不能证明用得对——那需要真实调用与人工评分
（见 docs/longrange-consistency-and-eval.md 的评估部分）。但它能在零成本下抓住
"证据根本没进上下文"这类问题——**这类问题的表现与"模型记不住"一模一样**，
而两者的修法完全不同。写这个模块时就是这么抓到一个真缺口的：作者登记的时间线
从没进过写作时的上下文（见 `_timeline_lines`）。

## 维度 → 我们流水线里的对应物

| LongMemEval 维度 | 本项目的对应物 | 探针怎么判 |
|---|---|---|
| 信息抽取（单会话事实） | 章摘要 / 焦点章正文 | 摘要片段与正文是否在上下文里 |
| 多会话推理（跨章聚合） | 按触发词检索的设定条目 | 条目**正文**片段（不只是标题）是否在 |
| 时间推理 | `project.timeline` | 焦点章之前的事件是否在时间线段里 |
| 知识更新 | 账本 / 长程记忆（**调用方提供**） | 不在本探针范围：那两块是调用方拼好传进来的 |
| 拒答 | 检索无命中时的行为 | 问一个书里没有的词，**不能有任何（非钉住的）条目正文被注入** |

"知识更新"一栏刻意留空而不是假装覆盖：`loreCraft` / `globalMemory` / `longChapterMemory`
是 HTTP 层拼好传进 `build_agent_context` 的字符串，本模块看不到它们的构造过程。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.core.agent_context import build_agent_context
from app.domain.types import VnProject

#: 抽取"证据片段"时的最小长度：太短会在长文里随机命中，太长则容易被截断。
_SNIPPET_LEN = 14
#: 每个维度最多造多少个探针：探针多了没意义（同一条规则会被反复验），还会拖慢测量。
_MAX_PROBES_PER_DIMENSION = 6
#: 用于拒答探针的"书里一定没有"的词。
_ABSENT_KEYWORD = "zzz▷不存在的词◁zzz"


@dataclass
class Probe:
    id: str
    dimension: str
    question: str
    #: 期望在上下文里出现的片段（present 模式）或**不该**出现的片段（absent 模式）
    needles: List[str]
    #: 这条探针要**用哪个提问去组装上下文**。
    #: 关键：检索类探针（"问到 X 时这条设定会进上下文吗"）必须用它自己的提问去组装，
    #: 否则等于拿无关的问题去考检索——第一版就栽在这里（所有探针共用"接着写"一次组装，
    #: 于是"设定条目能否被检索到"永远失败，而失败原因与被测对象无关）。
    query: str = "接着写"
    mode: str = "present"
    note: str = ""


@dataclass
class ProbeResult:
    id: str
    dimension: str
    question: str
    ok: bool
    hits: List[str] = field(default_factory=list)
    misses: List[str] = field(default_factory=list)


@dataclass
class ProbeReport:
    results: List[ProbeResult]
    by_dimension: Dict[str, Dict[str, Any]]
    summary: str
    chars_used: int
    notes: List[str]


def _snippet(text: str) -> str:
    """从一段文本里抽一段有辨识度的片段（跳过开头的标点/空白）。"""
    clean = " ".join((text or "").split())
    if len(clean) <= _SNIPPET_LEN:
        return clean
    return clean[: _SNIPPET_LEN + 6]


def _entry_body(entry: Any) -> str:
    return str(getattr(entry, "body", "") or "")


def build_probes(
    project: VnProject, *, focus_chapter_id: Optional[str] = None
) -> List[Probe]:
    """按维度造探针。数据不足的维度不造探针（由报告如实说明，而不是算成通过）。"""
    probes: List[Probe] = []
    chapters = list(getattr(project, "chapters", None) or [])
    focus = next(
        (c for c in chapters if str(getattr(c, "id", "") or "") == (focus_chapter_id or "")),
        chapters[0] if chapters else None,
    )

    # —— 信息抽取：焦点章正文必须进上下文（尾部窗口） ——
    if focus is not None:
        prose = str(getattr(focus, "prose", None) or "").strip()
        if prose:
            probes.append(
                Probe(
                    id="focus-body",
                    dimension="info_extraction",
                    question="当前章正文在上下文里吗",
                    needles=[_snippet(prose)],
                    note="续写必须紧接着它，所以它在尾部窗口",
                )
            )
    # 其它有摘要的章：摘要片段应在章节目录里
    for ch in chapters[:_MAX_PROBES_PER_DIMENSION]:
        if focus is not None and str(getattr(ch, "id", "")) == str(getattr(focus, "id", "")):
            continue
        synopsis = str(getattr(ch, "synopsis", None) or "").strip()
        if len(synopsis) >= _SNIPPET_LEN:
            probes.append(
                Probe(
                    id=f"synopsis-{getattr(ch, 'id', '')}",
                    dimension="info_extraction",
                    question=f"「{getattr(ch, 'title', '')}」的摘要能带出来吗",
                    needles=[_snippet(synopsis)],
                )
            )

    # —— 多会话推理 + 拒答：设定条目的检索 ——
    entries = [e for e in (getattr(project, "loreEntries", None) or []) if e is not None]
    unpinned = [e for e in entries if not bool(getattr(e, "pinned", None))]
    for entry in entries:
        keywords = [str(k) for k in (getattr(entry, "keywords", None) or []) if str(k).strip()]
        body = _entry_body(entry)
        if not keywords or len(body) < _SNIPPET_LEN:
            continue
        probes.append(
            Probe(
                id=f"lore-{getattr(entry, 'id', '')}",
                dimension="multi_session",
                question=f"问到「{keywords[0]}」时，这条设定会进上下文吗",
                needles=[_snippet(body)],
                query=str(keywords[0]),
                note="判的是**正文**片段：只列标题不算带出来；用该关键词本身去检索",
            )
        )
        if len([p for p in probes if p.dimension == "multi_session"]) >= _MAX_PROBES_PER_DIMENSION:
            break

    # 拒答：书里没有的词 → 不该注入任何非钉住条目的正文
    if unpinned:
        probes.append(
            Probe(
                id="abstain-unknown",
                dimension="abstention",
                question="问一个书里没有的词时，会不会凭空塞进设定",
                needles=[_snippet(_entry_body(e)) for e in unpinned if len(_entry_body(e)) >= _SNIPPET_LEN],
                mode="absent",
                note="钉住的条目永远带上，所以只判非钉住的那批",
            )
        )

    # —— 时间推理：焦点章之前的事件应该在时间线段里 ——
    timeline = [e for e in (getattr(project, "timeline", None) or []) if e is not None]
    focus_ordinal = None
    for idx, ch in enumerate(chapters, start=1):
        if focus is not None and str(getattr(ch, "id", "")) == str(getattr(focus, "id", "")):
            focus_ordinal = idx
    order_of = {}
    for idx, ch in enumerate(chapters, start=1):
        order_of[str(getattr(ch, "id", "") or "")] = idx
        title = str(getattr(ch, "title", "") or "")
        if title:
            order_of.setdefault(title, idx)
    for event in timeline[:_MAX_PROBES_PER_DIMENSION]:
        if bool(getattr(event, "stale", None)):
            continue
        ref_ordinal = order_of.get(str(getattr(event, "chapterRef", None) or "").strip())
        if focus_ordinal is not None and ref_ordinal is not None and ref_ordinal > focus_ordinal:
            continue
        title = str(getattr(event, "title", "") or "").strip()
        if not title:
            continue
        probes.append(
            Probe(
                id=f"timeline-{getattr(event, 'id', '')}",
                dimension="temporal",
                question=f"「{title}」这件已经发生的事，写作时看得到吗",
                needles=[title],
            )
        )

    # —— 一跳可达（MemGPT / GraphRAG 那一侧）：条目 links 指向的实体 ——
    for entry in entries[:_MAX_PROBES_PER_DIMENSION]:
        links = getattr(entry, "links", None) or []
        for link in links:
            raw = link if isinstance(link, dict) else getattr(link, "__dict__", {})
            to_type = str(raw.get("toType") or "")
            to_id = str(raw.get("toId") or "")
            if to_type == "chapter":
                continue  # 章节由目录覆盖，这里只看角色/地点这类实体
            target = None
            if to_type == "character":
                target = next(
                    (
                        c
                        for c in (getattr(project, "characters", None) or [])
                        if str(getattr(c, "id", "")) == to_id
                    ),
                    None,
                )
                name = str(getattr(target, "displayName", "") or "") if target else ""
            elif to_type == "location":
                target = next(
                    (
                        l
                        for l in (getattr(project, "locations", None) or [])
                        if str(getattr(l, "id", "")) == to_id
                    ),
                    None,
                )
                name = str(getattr(target, "name", "") or "") if target else ""
            else:
                name = ""
            if name:
                probes.append(
                    Probe(
                        id=f"hop-{getattr(entry, 'id', '')}-{to_id}",
                        dimension="graph_hop",
                        question=f"沿设定条目的 links 能不能走到「{name}」",
                        needles=[name],
                        note="这一步就是 MemGPT/GraphRAG 那类分层/图谱检索的最小形态",
                    )
                )
                break

    return probes


def run_probes(
    project: VnProject,
    *,
    focus_chapter_id: Optional[str] = None,
    task: str = "continue",
    max_chars: Optional[int] = None,
    probes: Optional[Sequence[Probe]] = None,
) -> ProbeReport:
    """造探针 → 按各自提问组装上下文（每个不同提问一次）→ 逐条判定。

    开销 = **不同提问的个数**次上下文组装（全部离线、零模型调用），而不是探针条数：
    同一提问下的多条探针共用同一份组装结果。默认提问"接着写"复用一次，
    检索类探针各用自己的关键词（这样"能不能检索到"才是被真正测到的东西）。
    """
    all_probes = list(probes) if probes is not None else build_probes(
        project, focus_chapter_id=focus_chapter_id
    )
    chapters = list(getattr(project, "chapters", None) or [])
    focus = next(
        (
            c
            for c in chapters
            if str(getattr(c, "id", "") or "") == (focus_chapter_id or "")
        ),
        chapters[0] if chapters else None,
    )

    def _assemble(query: str):
        kwargs: Dict[str, Any] = {
            "chapterId": str(getattr(focus, "id", "")) if focus is not None else None,
            "userMessage": query,
            "task": task,
        }
        if max_chars is not None:
            kwargs["maxChars"] = max_chars
        return build_agent_context(project, **kwargs)

    contexts: Dict[str, Any] = {}

    def _text_for(query: str) -> str:
        ctx = contexts.get(query)
        if ctx is None:
            ctx = _assemble(query)
            contexts[query] = ctx
        return ctx.text

    results: List[ProbeResult] = []
    for probe in all_probes:
        text = _text_for(probe.query)
        if probe.mode == "absent":
            hits = [n for n in probe.needles if n and n in text]
            results.append(
                ProbeResult(
                    id=probe.id,
                    dimension=probe.dimension,
                    question=probe.question,
                    ok=not hits,
                    hits=hits,
                    misses=[],
                )
            )
            continue
        hits = [n for n in probe.needles if n and n in text]
        misses = [n for n in probe.needles if not n or n not in text]
        results.append(
            ProbeResult(
                id=probe.id,
                dimension=probe.dimension,
                question=probe.question,
                ok=not misses,
                hits=hits,
                misses=misses,
            )
        )

    by_dimension: Dict[str, Dict[str, Any]] = {}
    for res in results:
        bucket = by_dimension.setdefault(
            res.dimension, {"probes": 0, "passed": 0, "rate": None, "missed": []}
        )
        bucket["probes"] += 1
        if res.ok:
            bucket["passed"] += 1
        else:
            bucket["missed"].append(res.id)
    for bucket in by_dimension.values():
        bucket["rate"] = round(bucket["passed"] / bucket["probes"], 4) if bucket["probes"] else None

    expected_dimensions = (
        "info_extraction",
        "multi_session",
        "temporal",
        "graph_hop",
        "abstention",
    )
    notes: List[str] = []
    missing = [d for d in expected_dimensions if d not in by_dimension]
    if missing:
        notes.append(
            "本书没有可用于这些维度的数据，因此**没有测量**（不是「通过」）：" + "、".join(missing)
        )
    notes.append(
        "「知识更新」维度不在本探针范围：账本与长程记忆是调用方拼好传进上下文的字符串。"
    )
    notes.append(
        f"本次共组装 {len(contexts)} 份上下文（每个不同提问一份），零模型调用。"
    )
    notes.append("本报告只说明证据有没有进上下文，不代表模型会不会用、用得对不对。")
    failed = [r for r in results if not r.ok]
    summary = (
        f"探针 {len(results)} 条：通过 {len(results) - len(failed)}，"
        f"未通过 {len(failed)}"
        + (f"（{', '.join(r.id for r in failed[:5])}）" if failed else "")
    )
    return ProbeReport(
        results=results,
        by_dimension=by_dimension,
        summary=summary,
        chars_used=sum(int(ctx.charsUsed) for ctx in contexts.values()),
        notes=notes,
    )

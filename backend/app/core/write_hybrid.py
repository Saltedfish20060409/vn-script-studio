"""写路径 hybrid 检索：关键词排序（+ 可选语义）→ 注入块。

默认不依赖模型调 tool：在 ``stage_write`` 里按本轮 instruction 召回相关章摘录 /
设定片段，塞进硬锚附近。pgvector 不可用时退化为纯 ``retrieval.rank_texts``。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.core.agent_context import chapter_plain
from app.core.retrieval import rank_texts
from app.domain.types import VnProject

DEFAULT_HYBRID_LIMIT = 6
DEFAULT_HYBRID_MAX_CHARS = 1400


def _bible_candidates(project: VnProject) -> List[Tuple[str, str]]:
    bible = getattr(project, "bible", None)
    if bible is None:
        return []
    out: List[Tuple[str, str]] = []
    for key, label in (
        ("world", "世界观"),
        ("background", "背景"),
        ("outline", "大纲"),
        ("themes", "主题"),
        ("notes", "备注"),
    ):
        text = str(getattr(bible, key, None) or "").strip()
        if text:
            out.append((f"bible:{label}", text))
    return out


def _chapter_candidates(
    project: VnProject, *, exclude_id: Optional[str]
) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for ch in project.chapters or []:
        cid = str(getattr(ch, "id", "") or "")
        if exclude_id and cid == exclude_id:
            continue
        plain = chapter_plain(ch, project.characters) or ""
        syn = str(getattr(ch, "synopsis", None) or "").strip()
        # 长章只取首尾，避免把整章塞进排序器
        if len(plain) > 2400:
            body = plain[:900] + "\n…\n" + plain[-900:]
        else:
            body = plain
        text = (syn + "\n" + body).strip()
        if text:
            out.append((f"章「{ch.title or cid}」", text))
    return out


def _lore_candidates(project: VnProject) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for entry in getattr(project, "loreEntries", None) or []:
        title = str(getattr(entry, "title", None) or getattr(entry, "id", "") or "")
        body = str(getattr(entry, "body", None) or getattr(entry, "content", None) or "")
        triggers = getattr(entry, "triggers", None) or []
        trig = " ".join(str(t) for t in triggers[:8])
        text = f"{title}\n{trig}\n{body}".strip()
        if text:
            out.append((f"设定:{title or '?'}", text))
    return out


def _try_semantic_rerank(
    query: str,
    hits: List[Tuple[str, str, float]],
) -> List[Tuple[str, str, float]]:
    """词面重叠重排（零依赖）；失败则原样返回。

    pgvector 索引检索仍走 ``semantic_search.semantic_search``（需 DB+embedding）；
    写路径默认同进程 ``rerank_texts``，不挡主链路。
    """
    if not hits or not (query or "").strip():
        return hits
    try:
        from app.core.semantic_search import rerank_texts

        return rerank_texts(query, hits)
    except Exception:  # noqa: BLE001
        return hits


def collect_hybrid_hits(
    project: VnProject,
    query: str,
    *,
    chapter_id: Optional[str] = None,
    limit: int = DEFAULT_HYBRID_LIMIT,
) -> List[Dict[str, Any]]:
    q = (query or "").strip()
    if not q:
        return []
    candidates = (
        _chapter_candidates(project, exclude_id=chapter_id)
        + _bible_candidates(project)
        + _lore_candidates(project)
    )
    if not candidates:
        return []
    ranked = rank_texts(q, candidates, limit=limit, min_score=0.45)
    ranked = _try_semantic_rerank(q, ranked)
    return [
        {"label": label, "snippet": snippet, "score": score}
        for label, snippet, score in ranked
    ]


def format_hybrid_block(
    hits: List[Dict[str, Any]],
    *,
    max_chars: int = DEFAULT_HYBRID_MAX_CHARS,
) -> str:
    if not hits:
        return ""
    lines = ["## 相关检索（hybrid · 本轮指令命中，供对照勿编造）"]
    used = len(lines[0])
    for h in hits:
        line = f"- [{h.get('label')}] {h.get('snippet')}"
        if used + len(line) + 1 > max_chars:
            lines.append("…（检索块已满，其余命中省略）")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def build_write_hybrid_block(
    project: VnProject,
    query: str,
    *,
    chapter_id: Optional[str] = None,
    limit: int = DEFAULT_HYBRID_LIMIT,
    max_chars: int = DEFAULT_HYBRID_MAX_CHARS,
) -> Tuple[str, List[Dict[str, Any]]]:
    """返回 (注入文本, hits 元数据)。"""
    hits = collect_hybrid_hits(
        project, query, chapter_id=chapter_id, limit=limit
    )
    return format_hybrid_block(hits, max_chars=max_chars), hits

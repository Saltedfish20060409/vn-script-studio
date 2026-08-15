"""Optional LLM semantic layer for analysis fact candidates.

Heuristics in fact_extract.py stay the fast offline path (Phase 1, no LLM).
This module lets an LLM verify & refine a batch of ``FactCandidate`` before
they land in the pending analysis inbox:

- drop obvious false positives (co-occurrence noise),
- normalize vague heuristic labels (同场 / 设定共现 / 粘贴共现),
- supplement / correct evidence with original-text quotes,
- annotate a confidence score per candidate.

Everything degrades gracefully: no API key, network error, timeout or
malformed JSON returns the original candidates untouched, so heuristic
results are never lost and the flow never raises.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from app.core.ai import DeepSeekConfig
from app.domain.types import VnProject

from .agent_context import _blocks_to_plain
from .fact_extract import FactCandidate, link_dedupe_key, timeline_dedupe_key
from .llm_http import chat_completions, content_from_response

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")

# Token budget: only the first N candidates are sent to the LLM.
_DEFAULT_MAX_CANDIDATES = 40
_QUOTE_CAP = 120
_CHAPTER_TEXT_CAP = 2000
_MAX_CHAPTER_TEXTS = 6
_MAX_CHARACTERS = 30

_KINDS = ("character_link", "timeline_event")

_SYSTEM_PROMPT = """你是视觉小说「事实核查编辑」。下面是用启发式规则自动生成的事实候选（角色关系 / 时间线事件），其中混有共现噪声。请逐一验证并精炼，只输出 JSON，不要解释。

处理规则：
1. 明显误报（两个角色仅因同框/同段被提及、没有真实互动或关系含义；或"事件"只是共现描述、无实际情节推进）→ action=drop，reason 写一句话理由。
2. 模糊标签（如同场、设定共现、粘贴共现、角色卡上的关系描述片段）归一化为具体关系短语（如"旧友""青梅竹马""宿敌""姐弟"）；若无法从材料确认，保留原标签，不要编造。
3. 为保留的候选补充/修正 evidence：必须是材料中的原文短语（含角色名或事件相关句子），并给出 source（script/bible/card/paste）与 chapterId（如来自某章节剧本）。没有可引用的原文依据 → action=drop。
4. 每条保留的候选标注 confidence（0~1 的小数，>0.6 才算可信）。
5. payload 必须完整输出：character_link 含 fromId/toId/label；timeline_event 含 title/when/summary/chapterRef/order。index 必须与输入候选一一对应。
6. 每条输出必须带 evidence 列表（至少一条，含 quote 原文短语）；无 evidence 的条目会被丢弃。"""


@dataclass
class EnrichStats:
    """Outcome counters for one enrich_fact_candidates run."""

    total: int = 0
    sent: int = 0
    kept: int = 0
    dropped: int = 0
    refined: int = 0
    llm_used: bool = False
    error: Optional[str] = None
    model: str = ""


@dataclass
class EnrichResult:
    candidates: List[FactCandidate]
    stats: EnrichStats


# ---------------------------------------------------------------- serialization


def _evidence_items(candidate: FactCandidate, cap: int = 3) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in candidate.evidence or []:
        item: Dict[str, Any] = {}
        if e.get("source"):
            item["source"] = str(e["source"])
        if e.get("chapterId"):
            item["chapterId"] = str(e["chapterId"])
        quote = (e.get("quote") or "").strip()
        if quote:
            item["quote"] = quote[:_QUOTE_CAP]
        out.append(item)
        if len(out) >= cap:
            break
    return out


def _serialize_candidates(
    candidates: Sequence[FactCandidate],
) -> List[Dict[str, Any]]:
    return [
        {
            "index": i,
            "kind": c.kind,
            "payload": dict(c.payload or {}),
            "evidence": _evidence_items(c),
        }
        for i, c in enumerate(candidates)
    ]


def _referenced_chapter_ids(candidates: Sequence[FactCandidate]) -> List[str]:
    ids: List[str] = []
    seen = set()
    for c in candidates:
        for e in c.evidence or []:
            cid = e.get("chapterId")
            if cid and cid not in seen:
                seen.add(cid)
                ids.append(str(cid))
        ref = (c.payload or {}).get("chapterRef")
        if ref and ref not in seen:
            seen.add(ref)
            ids.append(str(ref))
    return ids


def _build_messages(
    project: VnProject,
    candidates: Sequence[FactCandidate],
    chapter_texts: Optional[Dict[str, str]] = None,
) -> List[Dict[str, str]]:
    chars = [
        {
            "id": c.id,
            "defineName": c.defineName,
            "displayName": c.displayName,
            "bio": (c.bio or "")[:100],
        }
        for c in project.characters
    ][:_MAX_CHARACTERS]

    ref_ids = set(_referenced_chapter_ids(candidates))
    chapters: List[Dict[str, Any]] = []
    for ch in project.chapters:
        if ch.id not in ref_ids:
            continue
        text = ""
        if chapter_texts and chapter_texts.get(ch.id):
            text = chapter_texts[ch.id]
        else:
            text = _blocks_to_plain(ch.blocks, project.characters)
        text = (text or "").strip()
        if text:
            chapters.append(
                {"id": ch.id, "title": ch.title or "", "text": text[:_CHAPTER_TEXT_CAP]}
            )
        if len(chapters) >= _MAX_CHAPTER_TEXTS:
            break

    user: Dict[str, Any] = {
        "title": project.title,
        "genre": project.genre or "",
        "characters": chars,
        "chapters": chapters,
        "candidates": _serialize_candidates(candidates),
        "output_schema": {
            "items": [
                {
                    "index": "候选序号（0 起，必须与输入对应）",
                    "action": "keep | refine | drop",
                    "kind": "character_link | timeline_event",
                    "payload": {
                        "fromId": "角色 id（character_link 必填）",
                        "toId": "角色 id（character_link 必填）",
                        "label": "归一化后的关系标签",
                        "title": "事件标题（timeline_event 必填）",
                        "when": "时间标签",
                        "summary": "一句话摘要",
                        "chapterRef": "章节 id 或 null",
                        "order": 1,
                    },
                    "evidence": [
                        {
                            "source": "script | bible | card | paste",
                            "chapterId": "章节 id",
                            "quote": "原文短语",
                        }
                    ],
                    "confidence": 0.0,
                    "reason": "drop 时的一句话理由（可选）",
                }
            ]
        },
    }
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


# ---------------------------------------------------------------------- parsing


def _parse_llm_json(content: str) -> Dict[str, Any]:
    """Strict JSON object parse with optional markdown-fence stripping."""
    raw = (content or "").strip() or "{}"
    fence = _FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("模型未返回 JSON 对象")
    return data


def _clean_confidence(raw: Any) -> Optional[float]:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v < 0 or v > 1:
        return None
    return round(v, 3)


def _clean_evidence(raw: Any) -> List[Dict[str, Any]]:
    """LLM-provided evidence: only entries carrying a non-empty quote count."""
    out: List[Dict[str, Any]] = []
    if not isinstance(raw, list):
        return out
    for e in raw:
        if not isinstance(e, dict):
            continue
        quote = str(e.get("quote") or "").strip()
        if not quote:
            continue
        item: Dict[str, Any] = {"quote": quote[:_QUOTE_CAP]}
        src = str(e.get("source") or "").strip()
        if src:
            item["source"] = src
        if e.get("chapterId"):
            item["chapterId"] = str(e["chapterId"])
        if e.get("field"):
            item["field"] = str(e["field"])
        out.append(item)
    return out


def _merge_evidence(
    orig: Sequence[Dict[str, Any]], llm: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Keep original provenance, append LLM quotes (JSON-deduped)."""
    seen = {json.dumps(e, ensure_ascii=False, sort_keys=True) for e in orig}
    merged = [dict(e) for e in orig]
    for e in llm:
        s = json.dumps(e, ensure_ascii=False, sort_keys=True)
        if s not in seen:
            merged.append(dict(e))
            seen.add(s)
    return merged


def _refined_payload(
    orig: FactCandidate, kind: str, raw: Any
) -> Optional[Dict[str, Any]]:
    base = dict(orig.payload or {})
    raw = raw if isinstance(raw, dict) else {}
    merged = {**base, **{k: v for k, v in raw.items() if v is not None}}
    if kind == "character_link":
        fid = str(merged.get("fromId") or "").strip()
        tid = str(merged.get("toId") or "").strip()
        if not fid or not tid:
            return None
        label = str(merged.get("label") or "关系").strip()[:40] or "关系"
        return {"fromId": fid, "toId": tid, "label": label}
    title = str(merged.get("title") or "").strip()
    if not title:
        return None
    out: Dict[str, Any] = {"title": title[:80]}
    if merged.get("when"):
        out["when"] = str(merged["when"])[:80]
    if merged.get("summary"):
        out["summary"] = str(merged["summary"])[:200]
    if merged.get("chapterRef"):
        out["chapterRef"] = merged["chapterRef"]
    if merged.get("order") is not None:
        try:
            out["order"] = float(merged["order"])
        except (TypeError, ValueError):
            pass
    return out


def _build_refined_candidate(
    orig: FactCandidate, item: Dict[str, Any]
) -> Optional[FactCandidate]:
    """Rebuild one candidate from an LLM item; None → entry is dropped."""
    llm_evidence = _clean_evidence(item.get("evidence"))
    if not llm_evidence:
        # Entries without evidence quotes are dropped (map_extract_smart style).
        return None
    kind = str(item.get("kind") or orig.kind or "").strip()
    if kind not in _KINDS:
        kind = orig.kind
    payload = _refined_payload(orig, kind, item.get("payload"))
    if payload is None:
        return None
    if kind == "character_link":
        key = link_dedupe_key(
            payload.get("fromId", ""), payload.get("toId", ""), payload.get("label", "")
        )
    else:
        key = timeline_dedupe_key(
            payload.get("title", ""), payload.get("chapterRef")
        )
    return FactCandidate(
        kind=kind,
        payload=payload,
        evidence=_merge_evidence(orig.evidence, llm_evidence),
        dedupe_key=key,
        confidence=_clean_confidence(item.get("confidence")),
    )


def _apply_llm_items(
    candidates: Sequence[FactCandidate],
    data: Dict[str, Any],
    stats: EnrichStats,
) -> List[FactCandidate]:
    items = data.get("items")
    if not isinstance(items, list):
        raise ValueError("模型未返回 items 数组")
    by_index: Dict[int, Dict[str, Any]] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        idx = it.get("index")
        if isinstance(idx, bool) or not isinstance(idx, int):
            continue
        if 0 <= idx < len(candidates):
            by_index[idx] = it

    out: List[FactCandidate] = []
    for i, orig in enumerate(candidates):
        item = by_index.get(i)
        if item is None:
            # Unmentioned candidates stay as heuristic output.
            out.append(orig)
            stats.kept += 1
            continue
        action = str(item.get("action") or "keep").strip().lower()
        if action == "drop":
            stats.dropped += 1
            continue
        built = _build_refined_candidate(orig, item)
        if built is None:
            stats.dropped += 1
            continue
        if action == "refine":
            stats.refined += 1
        else:
            stats.kept += 1
        out.append(built)
    return out


# ------------------------------------------------------------------ main entry


async def enrich_fact_candidates(
    config: Optional[DeepSeekConfig],
    project: VnProject,
    candidates: Sequence[FactCandidate],
    *,
    chapter_texts: Optional[Dict[str, str]] = None,
    max_candidates: int = _DEFAULT_MAX_CANDIDATES,
) -> EnrichResult:
    """Verify & refine a batch of heuristic fact candidates through an LLM.

    - Valid LLM JSON is applied: drops, label normalization, evidence fixes
      and confidence scores; candidates the model does not mention stay as-is.
    - Candidates beyond ``max_candidates`` are never sent (token budget) and
      stay untouched.
    - On any failure (no key, network, timeout, malformed JSON) the original
      candidates are returned unchanged — never raises.
    """
    cands = list(candidates)
    stats = EnrichStats(total=len(cands))
    if not cands:
        return EnrichResult(candidates=[], stats=stats)

    if config is None or not config.apiKey or "your-key" in config.apiKey:
        stats.error = "未配置 DEEPSEEK_API_KEY，已跳过模型精炼"
        stats.kept = len(cands)
        return EnrichResult(candidates=cands, stats=stats)

    sent = cands[:max_candidates]
    rest = cands[max_candidates:]
    stats.sent = len(sent)
    stats.kept = len(rest)  # over-budget candidates kept as-is
    try:
        res = await chat_completions(
            config,
            messages=_build_messages(project, sent, chapter_texts),
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=120,
        )
        content, used_model = content_from_response(res)
        stats.model = used_model or (config.model or "")
        data = _parse_llm_json(content)
        refined = _apply_llm_items(sent, data, stats)
        stats.llm_used = True
        return EnrichResult(candidates=[*refined, *rest], stats=stats)
    except Exception as exc:  # noqa: BLE001 — graceful degradation on any failure
        stats.llm_used = False
        stats.error = f"模型精炼失败，已保留启发式候选：{exc}"
        stats.kept = len(cands)
        return EnrichResult(candidates=cands, stats=stats)

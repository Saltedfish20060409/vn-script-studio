"""Retrieval scoring for project text (chapters / bible / lore).

Heuristic multi-keyword relevance: tokenize the query into keywords, score each
candidate text by matched-keyword coverage, hit density, and proximity of hits.
This is the zero-dependency default behind ``search_script`` / ``search_bible``.
When pgvector + an embedding endpoint are available, ``semantic_search`` can
rank the same candidates with vector similarity instead (or in addition).
"""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple

_WORD_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


def tokenize_query(query: str) -> List[str]:
    """Split a query into keywords, preserving CJK character n-grams."""
    q = (query or "").strip().lower()
    if not q:
        return []
    # Latin/ASCII words stay whole; CJK text is split into bigrams so
    # multi-char phrases still match partial continuity (e.g. 雨夜 → 雨/夜).
    tokens: List[str] = []
    cjk_run = ""
    ascii_run = ""
    for ch in q:
        if (
            "\u4e00" <= ch <= "\u9fff"
            or "\u3040" <= ch <= "\u30ff"
            or "\uac00" <= ch <= "\ud7af"
        ):
            if ascii_run:
                tokens.append(ascii_run)
                ascii_run = ""
            cjk_run += ch
        elif ch.isalnum():
            if cjk_run:
                tokens.extend(_cjk_ngrams(cjk_run))
                cjk_run = ""
            ascii_run += ch
        else:
            if cjk_run:
                tokens.extend(_cjk_ngrams(cjk_run))
                cjk_run = ""
            if ascii_run:
                tokens.append(ascii_run)
                ascii_run = ""
    if cjk_run:
        tokens.extend(_cjk_ngrams(cjk_run))
    if ascii_run:
        tokens.append(ascii_run)
    # Dedupe, keep order, drop single-char noise for CJK (too many false hits).
    seen: set[str] = set()
    out: List[str] = []
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _cjk_ngrams(run: str) -> List[str]:
    if len(run) <= 1:
        return [run]
    # bigrams + the full run (full run helps exact-phrase hits rank higher)
    grams = [run[i : i + 2] for i in range(len(run) - 1)]
    grams.append(run)
    return grams


def score_text(text: str, keywords: List[str]) -> Tuple[float, List[Tuple[str, int]]]:
    """Return (score, [(keyword, count)]). Higher = more relevant.

    Score combines: fraction of keywords that matched (coverage), total hit
    count (density), and a bonus when several distinct keywords are present.
    """
    if not keywords:
        return 0.0, []
    low = (text or "").lower()
    if not low:
        return 0.0, []
    matched: List[Tuple[str, int]] = []
    for kw in keywords:
        cnt = low.count(kw)
        if cnt > 0:
            matched.append((kw, cnt))
    if not matched:
        return 0.0, []
    coverage = len(matched) / len(keywords)
    density = min(sum(c for _, c in matched) / max(1, len(low) / 120), 20)
    distinct_bonus = 1.0 + 0.5 * max(0, len(matched) - 1)
    return round(coverage * density * distinct_bonus, 4), matched


def rank_texts(
    query: str,
    candidates: Sequence[Tuple[str, str]],
    limit: int = 8,
    min_score: float = 0.6,
) -> List[Tuple[str, str, float]]:
    """Rank (label, text) candidates by relevance. Returns (label, snippet, score)."""
    kws = tokenize_query(query)
    scored: List[Tuple[str, str, float, List[Tuple[str, int]]]] = []
    for label, text in candidates:
        score, matched = score_text(text, kws)
        if score < min_score:
            continue
        snippet = _snippet(text, kws, matched)
        scored.append((label, snippet, score, matched))
    scored.sort(key=lambda x: x[2], reverse=True)
    return [(label, snippet, score) for label, snippet, score, _ in scored[:limit]]


def _snippet(
    text: str,
    keywords: List[str],
    matched: List[Tuple[str, int]],
) -> str:
    low = text.lower()
    positions: List[int] = []
    for kw, _cnt in matched:
        idx = low.find(kw)
        if idx >= 0:
            positions.append(idx)
    if not positions:
        return (text[:160].replace("\n", " ") + "…") if len(text) > 160 else text.replace("\n", " ")
    anchor = min(positions)
    start = max(0, anchor - 40)
    end = min(len(text), anchor + 160)
    snippet = text[start:end].replace("\n", " ")
    if start > 0:
        snippet = "…" + snippet
    if end < len(text):
        snippet += "…"
    return snippet

"""Unit tests for the optional LLM semantic layer (fact_llm).

All LLM calls are mocked — no network, no real key. Covers:
- valid JSON refinement (label normalization, drops, evidence-less drop,
  confidence, AnalysisInboxItem-compatible payload),
- graceful degradation on missing key / exception / malformed JSON,
- token budget cap on the number of sent candidates,
- optional chapter-text passthrough into the prompt.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx

from app.core.ai import DeepSeekConfig
from app.core.demo import create_demo_project
from app.core.fact_extract import build_scan_candidates, link_dedupe_key
from app.core.fact_llm import enrich_fact_candidates


def _cfg(**kw) -> DeepSeekConfig:
    return DeepSeekConfig(apiKey="sk-test-not-real", model="mock", **kw)


def _response(payload: dict) -> httpx.Response:
    content = json.dumps(payload, ensure_ascii=False)
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}], "model": "mock"},
    )


def _candidates():
    p = create_demo_project()
    cands, _delta, _meta = build_scan_candidates(p, full=True)
    assert cands, "demo project must yield heuristic candidates"
    return p, cands


def test_valid_llm_json_refines_and_drops():
    p, cands = _candidates()
    # Demo candidate index map (deterministic):
    #   0: character_link linxia→zhouyu 设定共现 (bible)
    #   1: timeline_event 雨夜月台相遇 (outline)
    #   2: timeline_event 伞下试探：天桥与便利店视线 (outline)
    #   3: timeline_event 进入停用站厅 (outline)
    #   4..: others (unmentioned → kept as-is)
    payload = {
        "items": [
            {
                "index": 0,
                "action": "refine",
                "kind": "character_link",
                "payload": {
                    "fromId": "linxia",
                    "toId": "zhouyu",
                    "label": "旧识",
                },
                "evidence": [
                    {"source": "bible", "quote": "林夏的姐姐失踪三周，最后出现记录停在这座换乘站。"}
                ],
                "confidence": 0.9,
            },
            {
                "index": 1,
                "action": "keep",
                "kind": "timeline_event",
                "payload": {
                    "title": "雨夜月台相遇",
                    "when": "大纲 · 1",
                    "summary": "雨夜月台相遇",
                    "chapterRef": None,
                    "order": 1,
                },
                "evidence": [{"source": "bible", "field": "outline", "quote": "雨夜月台相遇"}],
                "confidence": 0.8,
            },
            {"index": 2, "action": "drop", "reason": "仅同框提及，无真实事件含义"},
            # Evidence-less entry must be dropped even though action=refine.
            {"index": 3, "action": "refine", "kind": "timeline_event", "evidence": []},
        ]
    }

    async def _run():
        with patch(
            "app.core.fact_llm.chat_completions",
            new=AsyncMock(return_value=_response(payload)),
        ):
            return await enrich_fact_candidates(_cfg(), p, cands)

    out = asyncio.run(_run())
    stats = out.stats
    assert stats.llm_used is True
    assert stats.model == "mock"
    assert stats.total == len(cands) == 13
    assert stats.sent == 13
    assert stats.dropped == 2  # index 2 (drop) + index 3 (evidence-less)
    assert stats.refined == 1
    assert stats.kept == 10  # index 1 + 9 unmentioned indices 4..12
    assert len(out.candidates) == 11

    by_label = {c.payload.get("label"): c for c in out.candidates}
    refined = by_label["旧识"]
    assert refined.kind == "character_link"
    assert refined.payload == {"fromId": "linxia", "toId": "zhouyu", "label": "旧识"}
    assert refined.confidence == 0.9
    assert refined.dedupe_key == link_dedupe_key("linxia", "zhouyu", "旧识")
    # original provenance merged with LLM evidence
    assert any(e.get("source") == "bible" for e in refined.evidence)
    assert any("失踪" in (e.get("quote") or "") for e in refined.evidence)

    kept = next(c for c in out.candidates if c.payload.get("title") == "雨夜月台相遇")
    assert kept.confidence == 0.8
    assert kept.payload.get("chapterRef") is None

    # dropped indices gone; unmentioned candidates untouched
    titles = [c.payload.get("title") or c.payload.get("label") for c in out.candidates]
    assert "进入停用站厅" not in titles
    assert "伞下试探：天桥与便利店视线" not in titles
    assert "维修通道发现换乘记号" in titles  # unmentioned → kept as-is
    assert all(c.evidence for c in out.candidates)


def test_no_api_key_returns_original():
    p, cands = _candidates()
    out = asyncio.run(
        enrich_fact_candidates(DeepSeekConfig(apiKey=""), p, cands)
    )
    assert out.candidates == list(cands)
    assert out.stats.llm_used is False
    assert "DEEPSEEK_API_KEY" in (out.stats.error or "")


def test_llm_exception_returns_original():
    p, cands = _candidates()

    async def _boom(*_a, **_k):
        raise RuntimeError("upstream timeout")

    async def _run():
        with patch(
            "app.core.fact_llm.chat_completions",
            new=AsyncMock(side_effect=_boom),
        ):
            return await enrich_fact_candidates(_cfg(), p, cands)

    out = asyncio.run(_run())
    assert out.candidates == list(cands)
    assert out.stats.llm_used is False
    assert "保留启发式候选" in (out.stats.error or "")


def test_malformed_json_returns_original():
    p, cands = _candidates()
    res = httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "这不是 JSON {{{"}}],
            "model": "mock",
        },
    )

    async def _run():
        with patch(
            "app.core.fact_llm.chat_completions",
            new=AsyncMock(return_value=res),
        ):
            return await enrich_fact_candidates(_cfg(), p, cands)

    out = asyncio.run(_run())
    assert out.candidates == list(cands)
    assert out.stats.llm_used is False
    assert out.stats.error


def test_token_budget_caps_sent_candidates():
    p, cands = _candidates()
    many = cands * 5  # 65 candidates
    captured: dict = {}

    async def _fake(config, **kw):
        captured["messages"] = kw["messages"]
        return _response({"items": []})

    async def _run():
        with patch(
            "app.core.fact_llm.chat_completions",
            new=AsyncMock(side_effect=_fake),
        ):
            return await enrich_fact_candidates(_cfg(), p, many, max_candidates=40)

    out = asyncio.run(_run())
    assert out.stats.sent == 40
    assert out.stats.llm_used is True
    user = json.loads(captured["messages"][1]["content"])
    assert len(user["candidates"]) == 40
    # Over-budget candidates kept as-is; every sent candidate unmentioned → kept.
    assert out.stats.kept == len(many)
    assert len(out.candidates) == len(many)


def test_chapter_texts_passed_to_prompt():
    p, cands = _candidates()
    texts = {ch.id: f"CUSTOM CHAPTER TEXT {ch.id}" for ch in p.chapters}
    captured: dict = {}

    async def _fake(config, **kw):
        captured["messages"] = kw["messages"]
        return _response({"items": []})

    async def _run():
        with patch(
            "app.core.fact_llm.chat_completions",
            new=AsyncMock(side_effect=_fake),
        ):
            return await enrich_fact_candidates(_cfg(), p, cands, chapter_texts=texts)

    asyncio.run(_run())
    user = json.loads(captured["messages"][1]["content"])
    assert user["chapters"], "referenced chapters should be included"
    for ch in user["chapters"]:
        assert ch["text"].startswith("CUSTOM CHAPTER TEXT")

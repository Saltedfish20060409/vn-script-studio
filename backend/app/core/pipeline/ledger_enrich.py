"""LLM enrichment for writing ledger digests."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.core.agent_context import _blocks_to_plain
from app.core.ai import DeepSeekConfig
from app.core.llm_http import chat_completions, content_from_response
from app.domain.types import VnProject


def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


async def enrich_chapter_ledger_payload(
    config: DeepSeekConfig,
    project: VnProject,
    chapter_id: str,
) -> Dict[str, Any]:
    """
    Ask LLM for facts / character states / foreshadows.
    Returns keys suitable for digest_chapter_into_ledger(...).
    """
    ch = next((c for c in project.chapters if c.id == chapter_id), None)
    if not ch:
        raise ValueError("章节不存在")
    if not config.apiKey or "your-key" in config.apiKey:
        return {}

    plain = _blocks_to_plain(ch.blocks, project.characters) or ""
    if not plain.strip():
        return {}

    cast = [
        {"id": c.id, "name": c.displayName or c.defineName}
        for c in (project.characters or [])[:16]
    ]
    prompt = (
        "从视觉小说章节正文提炼写作账本硬锚。只输出 JSON：\n"
        '{"facts":["事实1",...],'
        '"states":[{"characterName":"","emotion":"","body":"","relations":""}],'
        '"foreshadows":[{"hook":"","status":"open","note":""}]}\n'
        "facts 3～8 条；states 覆盖出场角色；foreshadows 0～4 条未回收钩子。\n\n"
        f"## 角色表\n{json.dumps(cast, ensure_ascii=False)}\n\n"
        f"## 章节「{ch.title}」\n{plain[:7000]}"
    )
    res = await chat_completions(
        config,
        messages=[
            {"role": "system", "content": "只输出 JSON。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        timeout=90,
    )
    content, _ = content_from_response(res)
    parsed = _extract_json_obj(content) or {}
    facts = [str(x).strip() for x in (parsed.get("facts") or []) if str(x).strip()]
    states: List[Dict[str, Any]] = []
    for s in parsed.get("states") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("characterName") or "").strip()
        if not name:
            continue
        char = next(
            (
                c
                for c in project.characters
                if c.displayName == name or c.defineName == name
            ),
            None,
        )
        states.append(
            {
                "characterId": char.id if char else "",
                "characterName": name,
                "emotion": str(s.get("emotion") or "").strip() or "平静",
                "body": str(s.get("body") or "").strip() or "—",
                "relations": str(s.get("relations") or "").strip()
                or (char.relationships[:80] if char and char.relationships else "—"),
            }
        )
    fores: List[Dict[str, Any]] = []
    for fo in parsed.get("foreshadows") or []:
        if not isinstance(fo, dict):
            continue
        hook = str(fo.get("hook") or "").strip()
        if not hook:
            continue
        fores.append(
            {
                "hook": hook[:120],
                "status": str(fo.get("status") or "open"),
                "note": str(fo.get("note") or "LLM充实"),
            }
        )
    return {
        "llm_facts": facts[:12],
        "llm_states": states[:12],
        "llm_foreshadows": fores[:6],
    }

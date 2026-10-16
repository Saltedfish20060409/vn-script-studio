"""Harness C layer — narrow LLM judge for semantic narrative conflicts.

Only covers what A/B cannot: motive inconsistency, hidden knowledge leaks,
and world-rule violations. Always requires quote + chapterIds + audit code.

Default severity is ``warn`` (does not block the write gate). ``high`` stays
``warn`` in the write-gate merge path for v1 to avoid false hard-blocks;
callers may escalate later once eval false-positive rate is measured.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from app.core import llm_budget
from app.core.agent_context import chapter_plain
from app.core.ai import DeepSeekConfig
from app.core.harness.world_consistency import WorldConflict
from app.core.llm_http import chat_completions, content_from_response
from app.core.pipeline.ledger import get_ledger
from app.core.world_state import format_world_constraints, get_world_state
from app.domain.types import VnProject

#: Audit codes for C layer (must be registered in audit_codes.py).
WS_MOTIVE = "ws_motive"
WS_KNOWLEDGE = "ws_knowledge"
WS_WORLD_RULE = "ws_world_rule"

C_LAYER_CODES = frozenset({WS_MOTIVE, WS_KNOWLEDGE, WS_WORLD_RULE})

_CODE_ALIASES = {
    "motive": WS_MOTIVE,
    "motivation": WS_MOTIVE,
    "动机": WS_MOTIVE,
    "knowledge": WS_KNOWLEDGE,
    "hidden_knowledge": WS_KNOWLEDGE,
    "隐含知识": WS_KNOWLEDGE,
    "world_rule": WS_WORLD_RULE,
    "world": WS_WORLD_RULE,
    "世界规则": WS_WORLD_RULE,
    WS_MOTIVE: WS_MOTIVE,
    WS_KNOWLEDGE: WS_KNOWLEDGE,
    WS_WORLD_RULE: WS_WORLD_RULE,
}

_SYSTEM = """你是叙事一致性的窄范围检查器。只检查三类问题，其它一律不报：
1. ws_motive — 角色动机/性格与已建立状态明显矛盾（不是风格挑剔）
2. ws_knowledge — 角色使用了其不应知道的信息（隐含知识泄露）
3. ws_world_rule — 正文违反已给出的世界观规则/禁忌

只输出 JSON：
{"issues":[{"code":"ws_motive|ws_knowledge|ws_world_rule","severity":"warn|high","subject":"角色或规则名","quote":"必须逐字来自本稿","message":"一句话说明矛盾","chapterIds":["可选章id"]}]}

纪律：
- 拿不准就不报；最多 5 条。
- quote 必须是本稿原文片段（≥4 字），禁止编造。
- 合法的剧情转折、新信息引入不要报。
- 不要报告错别字、文风、节奏问题。"""


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


def _bible_snip(project: VnProject, *, limit: int = 1200) -> str:
    bible = getattr(project, "bible", None)
    if not bible:
        return ""
    parts: List[str] = []
    for key, label in (
        ("world", "世界观"),
        ("themes", "主题/禁忌"),
        ("notes", "备忘"),
    ):
        val = str(getattr(bible, key, None) or "").strip()
        if val:
            parts.append(f"### {label}\n{val[:400]}")
    text = "\n\n".join(parts)
    return text[:limit]


def _focus_plain(project: VnProject, chapter_id: Optional[str]) -> str:
    if not chapter_id:
        return ""
    ch = next(
        (c for c in (project.chapters or []) if str(c.id) == str(chapter_id)),
        None,
    )
    if ch is None:
        return ""
    return (chapter_plain(ch, project.characters) or "")[:2000]


def parse_semantic_issues(
    raw: Any,
    *,
    draft: str,
    chapter_id: Optional[str] = None,
) -> List[WorldConflict]:
    """Parse model JSON into WorldConflict list (testable without network)."""
    if not isinstance(raw, dict):
        return []
    draft = draft or ""
    out: List[WorldConflict] = []
    for item in raw.get("issues") or []:
        if not isinstance(item, dict):
            continue
        code_raw = str(item.get("code") or "").strip()
        code = _CODE_ALIASES.get(code_raw, "")
        if code not in C_LAYER_CODES:
            continue
        quote = str(item.get("quote") or "").strip()
        if len(quote) < 4 or (draft and quote not in draft):
            # Must be grounded in draft when draft is provided
            continue
        msg = str(item.get("message") or "").strip()
        if not msg:
            continue
        subject = str(item.get("subject") or "").strip()[:40]
        sev_in = str(item.get("severity") or "warn").strip().lower()
        # v1: never hard-block from C alone — map high → warn for gate merge
        severity = "warn"
        cids = [
            str(x)
            for x in (item.get("chapterIds") or [])
            if str(x).strip()
        ]
        if chapter_id and chapter_id not in cids:
            cids = [chapter_id] + cids
        category = {
            WS_MOTIVE: "characterization",
            WS_KNOWLEDGE: "plot",
            WS_WORLD_RULE: "world_building",
        }.get(code, "factual")
        out.append(
            WorldConflict(
                code=code,
                severity=severity,
                message=msg[:200],
                subject=subject,
                quote=quote[:160],
                chapterIds=cids[:4],
                category=category,
                kind="violation",
            )
        )
        if len(out) >= 5:
            break
    return out


def build_semantic_user_prompt(
    project: VnProject,
    draft: str,
    *,
    chapter_id: Optional[str] = None,
) -> str:
    ledger = get_ledger(project)
    world = get_world_state(ledger)
    constraints = format_world_constraints(
        world,
        chapters=project.chapters,
        focus_chapter_id=chapter_id,
        foreshadows=None,
        limit=1600,
    )
    bible = _bible_snip(project)
    focus = _focus_plain(project, chapter_id)
    cast = [
        str(getattr(c, "displayName", None) or getattr(c, "defineName", None) or "")
        for c in (project.characters or [])[:12]
    ]
    cast = [n for n in cast if n]
    parts = [
        "## 角色名",
        "、".join(cast) or "（无）",
        "",
        "## 世界状态约束（硬）",
        constraints or "（暂无）",
        "",
        "## 设定摘录",
        bible or "（暂无）",
        "",
        "## 焦点章已有正文（摘）",
        focus or "（无）",
        "",
        "## 本稿（待检）",
        (draft or "")[:5000],
    ]
    return "\n".join(parts)


async def run_semantic_layer_c(
    config: DeepSeekConfig,
    project: VnProject,
    draft: str,
    *,
    chapter_id: Optional[str] = None,
) -> List[WorldConflict]:
    """Call LLM for C-layer issues. Returns [] on any soft failure."""
    text = (draft or "").strip()
    if not text or not config or not getattr(config, "apiKey", None):
        return []
    if "your-key" in str(config.apiKey):
        return []
    # No hard anchors / bible → C 层无事实可对，省一次 LLM。
    world = get_world_state(get_ledger(project))
    constraints = format_world_constraints(
        world, chapters=project.chapters, focus_chapter_id=chapter_id
    )
    if not (constraints or "").strip() and not _bible_snip(project).strip():
        return []
    try:
        res = await chat_completions(
            config,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": build_semantic_user_prompt(
                        project, text, chapter_id=chapter_id
                    ),
                },
            ],
            temperature=0.1,
            timeout=llm_budget.QUICK,
        )
        content, _ = content_from_response(res)
        parsed = _extract_json_obj(content) or {}
        return parse_semantic_issues(parsed, draft=text, chapter_id=chapter_id)
    except Exception:  # noqa: BLE001 — C 层失败不得拖垮写路径
        return []


def merge_c_into_write_gate(
    write_gate: Any,
    conflicts: Sequence[WorldConflict],
) -> Any:
    """Append C-layer conflicts as warn issues + warnings on a WriteGateResult."""
    if write_gate is None or not conflicts:
        return write_gate
    for c in conflicts:
        write_gate.issues.append(
            {
                "severity": "warn",
                "code": c.code,
                "message": c.message,
            }
        )
        if c.message and c.message not in write_gate.warnings:
            write_gate.warnings.append(c.message)
        if c.quote:
            write_gate.markHints.append(
                {
                    "quote": c.quote[:240],
                    "reason": c.message,
                    "instruction": (
                        f"语义一致性（{c.code}）：核对「{c.subject or '相关角色'}」"
                        "是否合理；只改本处，不要扩写全章。"
                    ),
                    "code": c.code,
                }
            )
    # Cap lists
    write_gate.warnings = list(write_gate.warnings)[:8]
    write_gate.markHints = list(write_gate.markHints)[:6]
    return write_gate

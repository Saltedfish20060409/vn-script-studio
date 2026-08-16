"""Project-scoped tools for the multi-step editor agent loop.

No shell / filesystem — only in-memory VnProject data.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from app.core.agent_context import _blocks_to_plain
from app.core.character_voice.corpus import format_corpus_for_prompt
from app.core.harness.audit_full import full_audit_draft
from app.core.pipeline.ledger import format_ledger_for_agent, get_ledger
from app.domain.types import Character, VnProject

TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "get_chapter",
        "description": "读取一章正文（可截断）。不传 chapterRef 则用当前焦点章。",
        "parameters": {
            "chapterRef": "章节 id 或标题，可选",
            "maxChars": "最大字符，默认 3500",
        },
    },
    {
        "name": "search_script",
        "description": "在各章正文中按关键词检索命中片段。",
        "parameters": {
            "query": "关键词或短语，必填",
            "limit": "最多命中条数，默认 8",
        },
    },
    {
        "name": "list_characters",
        "description": "列出角色 id / 显示名 / defineName 一览。",
        "parameters": {},
    },
    {
        "name": "get_character",
        "description": "读取角色卡与口吻语料摘要。",
        "parameters": {
            "ref": "角色 id、defineName 或显示名",
        },
    },
    {
        "name": "get_bible",
        "description": "读取故事设定（bible）字段摘要。",
        "parameters": {
            "section": "可选 world/background/outline/themes/notes；空=全量摘要",
        },
    },
    {
        "name": "search_bible",
        "description": "在设定文本中检索关键词。",
        "parameters": {"query": "关键词，必填"},
    },
    {
        "name": "get_locations",
        "description": "列出地点与关系链接摘要。",
        "parameters": {"query": "可选过滤词"},
    },
    {
        "name": "lint_draft",
        "description": "对候选正文或当前章跑叙事/AI 腔体检，返回问题列表。",
        "parameters": {
            "text": "要检查的正文；空则检查当前章",
            "chapterRef": "当 text 为空时指定章节",
        },
    },
    {
        "name": "ledger_digest",
        "description": "读取写作账本（事实/角色状态/伏笔）摘要。",
        "parameters": {},
    },
]


def tool_catalog_for_prompt() -> str:
    lines = ["可用工具（仅项目数据；禁止声称使用 shell/文件系统）："]
    for t in TOOL_SPECS:
        params = t.get("parameters") or {}
        pbits = ", ".join(f"{k}" for k in params) if params else "（无参）"
        lines.append(f"- {t['name']}({pbits}): {t['description']}")
    return "\n".join(lines)


def _find_chapter(project: VnProject, ref: Optional[str], default_id: Optional[str] = None):
    chapters = list(project.chapters or [])
    if not chapters:
        return None
    key = (ref or default_id or "").strip()
    if not key:
        return chapters[0]
    for ch in chapters:
        if ch.id == key or (ch.title or "") == key:
            return ch
    low = key.lower()
    for ch in chapters:
        if low in (ch.title or "").lower() or low in ch.id.lower():
            return ch
    return None


def _find_character(project: VnProject, ref: str) -> Optional[Character]:
    key = (ref or "").strip()
    if not key:
        return None
    for c in project.characters or []:
        if c.id == key or c.defineName == key or c.displayName == key:
            return c
    low = key.lower()
    for c in project.characters or []:
        if (
            low in (c.displayName or "").lower()
            or low in (c.defineName or "").lower()
            or low in c.id.lower()
        ):
            return c
    return None


def _clip(text: str, max_chars: int) -> str:
    text = text or ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 12] + "\n…(截断)"


def _bible_blob(project: VnProject) -> Dict[str, str]:
    b = project.bible
    if not b:
        return {}
    data = b.model_dump(mode="json") if hasattr(b, "model_dump") else dict(b)  # type: ignore[arg-type]
    out: Dict[str, str] = {}
    for k in ("world", "background", "outline", "themes", "notes"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
        elif isinstance(v, list):
            out[k] = "；".join(str(x) for x in v if x)
    return out


def run_agent_tool(
    name: str,
    arguments: Optional[Dict[str, Any]],
    *,
    project: VnProject,
    chapter_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """Execute one tool. Returns (ok, preview_text)."""
    args = arguments if isinstance(arguments, dict) else {}
    try:
        if name == "get_chapter":
            ch = _find_chapter(project, args.get("chapterRef"), chapter_id)
            if not ch:
                return False, "未找到章节"
            plain = _blocks_to_plain(ch.blocks or [], project.characters or [])
            max_c = int(args.get("maxChars") or 3500)
            return True, f"#{ch.title or ch.id}\n{_clip(plain, max_c)}"

        if name == "search_script":
            q = str(args.get("query") or "").strip()
            if not q:
                return False, "query 必填"
            limit = max(1, min(20, int(args.get("limit") or 8)))
            from app.core.retrieval import rank_texts

            candidates = [
                (
                    ch.title or ch.id,
                    _blocks_to_plain(ch.blocks or [], project.characters or []),
                )
                for ch in project.chapters or []
            ]
            hits = rank_texts(q, candidates, limit=limit, min_score=0.5)
            if not hits:
                return True, f"无命中：{q}"
            return True, "\n".join(f"[{label}] …{snippet}…" for label, snippet, _ in hits)

        if name == "list_characters":
            rows = [
                f"- {c.displayName}（{c.defineName}） id={c.id}"
                for c in (project.characters or [])
            ]
            return True, "\n".join(rows) if rows else "（无角色）"

        if name == "get_character":
            ref = str(args.get("ref") or args.get("id") or "").strip()
            c = _find_character(project, ref)
            if not c:
                return False, f"未找到角色：{ref}"
            corpus = format_corpus_for_prompt(c, max_samples=4, max_chars=800)
            parts = [
                f"{c.displayName}（{c.defineName}） id={c.id}",
                f"语气：{c.voice or '（空）'}",
                f"简介：{c.bio or '（空）'}",
                f"关系：{c.relationships or '（空）'}",
                corpus or "",
            ]
            return True, "\n".join(p for p in parts if p)

        if name == "get_bible":
            blob = _bible_blob(project)
            if not blob:
                return True, "（设定为空）"
            section = str(args.get("section") or "").strip()
            if section and section in blob:
                return True, f"[{section}]\n{_clip(blob[section], 4000)}"
            parts = [f"[{k}]\n{_clip(v, 1200)}" for k, v in blob.items()]
            return True, "\n\n".join(parts)

        if name == "search_bible":
            q = str(args.get("query") or "").strip()
            if not q:
                return False, "query 必填"
            from app.core.retrieval import rank_texts

            blob = _bible_blob(project)
            hits = rank_texts(q, list(blob.items()), limit=8, min_score=0.4)
            if not hits:
                return True, f"设定中无命中：{q}"
            return True, "\n".join(f"[{k}] …{snippet}…" for k, snippet, _ in hits)

        if name == "get_locations":
            q = str(args.get("query") or "").strip().lower()
            locs = list(project.locations or [])
            lines = []
            for loc in locs:
                name_l = loc.name or loc.id
                desc = (loc.description or "").strip()
                row = f"- {name_l}: {desc}" if desc else f"- {name_l}"
                if q and q not in row.lower():
                    continue
                lines.append(_clip(row, 200))
            links = list(project.locationLinks or [])
            if links:
                lines.append("链接：")
                for lk in links[:30]:
                    lines.append(
                        f"  · {getattr(lk, 'fromId', '')} → {getattr(lk, 'toId', '')}"
                        f" {getattr(lk, 'relation', '') or ''}".rstrip()
                    )
            return True, "\n".join(lines) if lines else "（无地点）"

        if name == "lint_draft":
            text = str(args.get("text") or "").strip()
            if not text:
                ch = _find_chapter(project, args.get("chapterRef"), chapter_id)
                if not ch:
                    return False, "无正文可检"
                text = _blocks_to_plain(ch.blocks or [], project.characters or [])
            audit = full_audit_draft(text)
            issues = audit.get("issues") or []
            if not issues:
                return True, "体检通过：未发现明显问题。"
            head = (
                f"error {audit.get('errorCount', 0)} / "
                f"warn {audit.get('warnCount', 0)} / "
                f"info {audit.get('infoCount', 0)}"
            )
            lines = [head]
            for iss in issues[:24]:
                if isinstance(iss, dict):
                    lines.append(
                        f"- [{iss.get('severity')}] {iss.get('message')}"
                    )
            return True, "\n".join(lines)

        if name == "ledger_digest":
            block = format_ledger_for_agent(get_ledger(project))
            return True, block.strip() or "（账本为空）"

        return False, f"未知工具：{name}"
    except Exception as exc:  # noqa: BLE001 — surface to model
        return False, f"工具错误：{exc}"


def format_tool_result_message(name: str, ok: bool, preview: str) -> str:
    status = "ok" if ok else "error"
    body = _clip(preview, 6000)
    return f"[tool_result name={name} status={status}]\n{body}"


def dumps_tool_args(arguments: Any) -> str:
    try:
        return json.dumps(arguments or {}, ensure_ascii=False)[:500]
    except Exception:
        return "{}"

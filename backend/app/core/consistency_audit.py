"""Cross-chapter consistency audit.

The LLM scans the whole novel against the authoritative setting (character
cards, bible, locations, timeline) and against itself (chapter vs chapter),
then returns a structured list of conflicts: category, severity, affected
chapters, evidence quote, description and a minimal fix suggestion.

Degrades gracefully: on any failure (no key, network, timeout, malformed
JSON) it returns an empty issue list plus an error string — never raises.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core.ai import DeepSeekConfig
from app.core.llm_http import chat_completions, content_from_response
from app.domain.types import VnProject

from .agent_context import _blocks_to_plain

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")

# Token budget for the whole-novel scan.
_CHAPTER_TEXT_CAP = 1600
_MAX_CHAPTER_TEXTS = 14
_MAX_CHARACTERS = 40
_MAX_LOCATIONS = 40
_MAX_TIMELINE = 80
_MAX_ISSUES = 30

_CATEGORIES = ("character", "timeline", "location", "bible", "plot", "style")
_SEVERITIES = ("high", "medium", "low")

_SYSTEM_PROMPT = """你是视觉小说「全书一致性总编」。下面给出作品的权威设定（角色卡 / 设定库 / 地图 / 时间线）与全部章节正文。请跨章节排查一致性冲突，只输出 JSON，不要解释。

冲突类型（category）：
- character：角色设定被违反（名字、身份、年龄、外貌、能力、关系、称谓、生死状态）
- timeline：时间线矛盾（事件顺序、日期、昼夜、季节、"昨天说X今天说Y"）
- location：地点矛盾（场景位置、布局、往返路线、气候）
- bible：正文与设定库冲突（世界观规则、禁忌、背景设定）
- plot：剧情逻辑矛盾（角色知道不该知道的事、物品凭空出现/消失、动机前后不一）
- style：基础书写问题（同一角色署名不一致、明显笔误、前后人称/时态混乱）

对每条冲突给出：
- severity: high（读者必然察觉）/ medium（明显但可修复）/ low（细节微瑕）
- chapterIds: 涉及的章节 id 列表（至少一个；若为设定与正文冲突，正文章节必列）
- quote: 一句原文证据（必须是正文或设定中的原句/原短语）
- description: 一句话说明矛盾在哪
- suggestion: 最小修改建议（具体到改哪个词/哪句）

要求：
1. 只报告真实的、可引证的冲突；拿不准的宁可不报。
2. 同源冲突合并为一条（如某角色名字在三章不一致 → 一条，列出全部章节）。
3. 每条 quote 必须逐字来自材料，禁止改写或编造。
4. 报告数量上限 {max_issues} 条，按 severity 从高到低排列。
5. summary 用一句话总结全书一致性状况（好/中/差 + 最突出的问题）。"""


@dataclass
class ConsistencyIssue:
    category: str
    severity: str
    chapterIds: List[str] = field(default_factory=list)
    quote: str = ""
    description: str = ""
    suggestion: str = ""


@dataclass
class ConsistencyAuditResult:
    issues: List[ConsistencyIssue] = field(default_factory=list)
    summary: str = ""
    scanned_chapters: int = 0
    model: str = ""
    error: Optional[str] = None


# ---------------------------------------------------------------- serialization


def _bible_text(project: VnProject) -> str:
    parts: List[str] = []
    bible = project.bible
    if bible:
        for key, label in (
            ("world", "世界观"),
            ("background", "背景"),
            ("outline", "大纲"),
            ("themes", "主题"),
            ("notes", "备忘"),
        ):
            val = getattr(bible, key, None)
            if val and str(val).strip():
                parts.append(f"## {label}\n{str(val).strip()}")
    return "\n\n".join(parts)


def _build_authority(project: VnProject) -> Dict[str, Any]:
    """Authoritative setting facts (not the whole novel)."""
    chars = [
        {
            "defineName": c.defineName,
            "displayName": c.displayName,
            "voice": (c.voice or "")[:80],
            "bio": (c.bio or "")[:200],
            "relationships": (c.relationships or "")[:200],
        }
        for c in project.characters
    ][:_MAX_CHARACTERS]

    locs = [
        {
            "name": l.name,
            "imageTag": l.imageTag or "",
            "description": (l.description or "")[:150],
        }
        for l in project.locations or []
    ][:_MAX_LOCATIONS]

    timeline = [
        {
            "title": t.title,
            "when": t.when or "",
            "summary": (t.summary or "")[:150],
            "chapterRef": t.chapterRef or "",
        }
        for t in sorted(project.timeline or [], key=lambda t: t.order)
    ][:_MAX_TIMELINE]

    return {
        "title": project.title,
        "genre": project.genre or "",
        "bible": _bible_text(project)[:4000],
        "characters": chars,
        "locations": locs,
        "timeline": timeline,
    }


def _chapter_texts(project: VnProject) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for ch in project.chapters:
        text = (ch.blocks and _blocks_to_plain(ch.blocks, project.characters) or "").strip()
        if not text:
            continue
        out.append({"id": ch.id, "title": ch.title or "", "text": text[:_CHAPTER_TEXT_CAP]})
        if len(out) >= _MAX_CHAPTER_TEXTS:
            break
    return out


def _build_messages(project: VnProject, focus: str = "") -> List[Dict[str, str]]:
    authority = _build_authority(project)
    chapters = _chapter_texts(project)
    user: Dict[str, Any] = {
        "authority": authority,
        "chapters": chapters,
        "focus": (focus or "").strip()[:300],
        "output_schema": {
            "summary": "一句话总结",
            "issues": [
                {
                    "category": "character | timeline | location | bible | plot | style",
                    "severity": "high | medium | low",
                    "chapterIds": ["章节 id"],
                    "quote": "原文证据",
                    "description": "矛盾说明",
                    "suggestion": "最小修改建议",
                }
            ],
        },
    }
    system = _SYSTEM_PROMPT.format(max_issues=_MAX_ISSUES)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


# ---------------------------------------------------------------------- parsing


def _parse_json(content: str) -> Dict[str, Any]:
    raw = (content or "").strip() or "{}"
    fence = _FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("模型未返回 JSON 对象")
    return data


def _clean_issue(raw: Any) -> Optional[ConsistencyIssue]:
    if not isinstance(raw, dict):
        return None
    category = str(raw.get("category") or "").strip().lower()
    if category not in _CATEGORIES:
        category = "plot"
    severity = str(raw.get("severity") or "").strip().lower()
    if severity not in _SEVERITIES:
        severity = "medium"
    desc = str(raw.get("description") or "").strip()
    if not desc:
        return None
    chapter_ids: List[str] = []
    raw_ids = raw.get("chapterIds")
    if isinstance(raw_ids, list):
        for cid in raw_ids:
            s = str(cid or "").strip()
            if s and s not in chapter_ids:
                chapter_ids.append(s)
    return ConsistencyIssue(
        category=category,
        severity=severity,
        chapterIds=chapter_ids[:8],
        quote=str(raw.get("quote") or "").strip()[:200],
        description=desc[:300],
        suggestion=str(raw.get("suggestion") or "").strip()[:300],
    )


def _parse_issues(data: Dict[str, Any]) -> List[ConsistencyIssue]:
    raw_items = data.get("issues")
    if not isinstance(raw_items, list):
        raise ValueError("模型未返回 issues 数组")
    issues: List[ConsistencyIssue] = []
    seen = set()
    for it in raw_items:
        issue = _clean_issue(it)
        if issue is None:
            continue
        key = json.dumps(
            (issue.category, issue.severity, issue.quote, issue.description),
            ensure_ascii=False,
        )
        if key in seen:
            continue
        seen.add(key)
        issues.append(issue)
        if len(issues) >= _MAX_ISSUES:
            break
    order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: (order.get(i.severity, 1), i.category))
    return issues


# ------------------------------------------------------------------ main entry


async def run_consistency_audit(
    config: Optional[DeepSeekConfig],
    project: VnProject,
    *,
    focus: str = "",
    chapter_texts: Optional[Dict[str, str]] = None,
) -> ConsistencyAuditResult:
    """Scan the whole novel against the authoritative setting.

    - chapter_texts (id → plain text) overrides in-project blocks when the
      caller has fresher server-side text (e.g. unsaved chapter rows).
    - Any failure returns an empty issue list + error; never raises.
    """
    result = ConsistencyAuditResult(
        scanned_chapters=min(len([c for c in project.chapters if c.blocks]), _MAX_CHAPTER_TEXTS)
    )
    if not project.chapters:
        result.summary = "作品还没有章节。"
        return result

    if config is None or not config.apiKey or "your-key" in config.apiKey:
        result.error = "未配置 DEEPSEEK_API_KEY，已跳过一致性审计"
        return result

    messages = _build_messages(project, focus)
    if chapter_texts:
        # Rebuild with server-fresh chapter text (same budget).
        authority = _build_authority(project)
        chapters: List[Dict[str, str]] = []
        for ch in project.chapters:
            text = (chapter_texts.get(ch.id) or "").strip()
            if not text:
                continue
            chapters.append(
                {"id": ch.id, "title": ch.title or "", "text": text[:_CHAPTER_TEXT_CAP]}
            )
            if len(chapters) >= _MAX_CHAPTER_TEXTS:
                break
        messages[1] = {
            "role": "user",
            "content": json.dumps(
                {
                    "authority": authority,
                    "chapters": chapters,
                    "focus": (focus or "").strip()[:300],
                    "output_schema": json.loads(messages[1]["content"]).get("output_schema"),
                },
                ensure_ascii=False,
            ),
        }

    try:
        res = await chat_completions(
            config,
            messages=messages,
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=180,
        )
        content, used_model = content_from_response(res)
        result.model = used_model or (config.model or "")
        data = _parse_json(content)
        result.issues = _parse_issues(data)
        summary = str(data.get("summary") or "").strip()
        if summary:
            result.summary = summary[:400]
    except Exception as exc:  # noqa: BLE001 — audit must never crash the request
        result.error = f"一致性审计失败：{exc}"
    return result

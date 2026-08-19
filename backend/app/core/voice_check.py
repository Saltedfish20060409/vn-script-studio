"""Ported from packages/core/src/voiceCheck.ts

Persists reports on project.voiceReports keyed by chapterId + content fingerprint.
Mark stale when chapter fingerprint drifts; never write characterLinks/timeline.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import List, Optional

from app.domain.types import VnProject
from app.llm_models import DEFAULT_LLM_MODEL

from .ai import DeepSeekConfig
from .llm_http import content_from_response
from .llm_provider import LlmProvider, provider_from_config
from .renpy import project_to_context


@dataclass
class VoiceIssue:
    character: str
    severity: str  # "info" | "warn" | "high"
    quote: str
    note: str
    suggestion: Optional[str] = None


@dataclass
class VoiceReport:
    summary: str
    issues: List[VoiceIssue]
    model: str


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


async def run_voice_check(
    config: DeepSeekConfig,
    project: VnProject,
    chapterId: Optional[str] = None,
    *,
    provider: Optional[LlmProvider] = None,
) -> VoiceReport:
    if not config.apiKey or "your-key" in config.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")

    focus_chapter = (
        next((c for c in project.chapters if c.id == chapterId), None) if chapterId else None
    )

    llm = provider or provider_from_config(config)
    res = await llm.chat_completions(
        messages=[
            {
                "role": "system",
                "content": """你是视觉小说对白审稿编辑。根据角色 voice/bio、角色思维卡与口吻正例，检查对白是否破人设。
只输出 JSON：
{
  "summary": "总体评价（中文）",
  "issues": [
    { "character": "角色名", "severity": "info|warn|high", "quote": "原句摘录", "note": "问题", "suggestion": "改写建议" }
  ]
}
若整体稳定，issues 可为空，summary 给鼓励与微调建议。优先对照思维卡/正例中的表达 DNA，勿只看形容词人设。""",
            },
            {
                "role": "user",
                "content": (
                    f"{project_to_context(project, 10000)}\n\n"
                    f"重点检查章节: {focus_chapter.title if focus_chapter else '全部'}"
                ),
            },
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
        timeout=120,
    )

    raw, used_model = content_from_response(res)
    raw = (raw or "{}").strip() or "{}"
    fence = _FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"声线检查 JSON 解析失败：{exc}") from exc
    issues_raw = parsed.get("issues")
    issues = (
        [
            VoiceIssue(
                character=i.get("character", ""),
                severity=i.get("severity", "info"),
                quote=i.get("quote", ""),
                note=i.get("note", ""),
                suggestion=i.get("suggestion"),
            )
            for i in issues_raw
            if isinstance(i, dict)
        ]
        if isinstance(issues_raw, list)
        else []
    )
    return VoiceReport(
        summary=parsed.get("summary") or "无摘要",
        issues=issues,
        model=used_model or (config.model or DEFAULT_LLM_MODEL),
    )

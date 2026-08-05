"""Ported from packages/core/src/voiceCheck.ts"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

from app.domain.types import VnProject

from .ai import DeepSeekConfig
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
    config: DeepSeekConfig, project: VnProject, chapterId: Optional[str] = None
) -> VoiceReport:
    if not config.apiKey or "your-key" in config.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")
    base_url = (config.baseUrl or "https://api.deepseek.com").rstrip("/")
    model = config.model or "deepseek-chat"

    focus_chapter = (
        next((c for c in project.chapters if c.id == chapterId), None) if chapterId else None
    )

    async with httpx.AsyncClient(timeout=120) as client:
        res = await client.post(
            f"{base_url}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.apiKey}",
            },
            json={
                "model": model,
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
                "messages": [
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
            },
        )

    if res.status_code >= 400:
        err_text = res.text
        raise RuntimeError(f"DeepSeek API {res.status_code}: {err_text[:400]}")

    data = res.json()
    choices = data.get("choices") or []
    raw = "{}"
    if choices:
        raw = ((choices[0] or {}).get("message") or {}).get("content", "{}") or "{}"
        raw = raw.strip() or "{}"
    fence = _FENCE_RE.search(raw)
    if fence:
        raw = fence.group(1).strip()
    parsed = json.loads(raw)
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
        ]
        if isinstance(issues_raw, list)
        else []
    )
    return VoiceReport(
        summary=parsed.get("summary") or "无摘要", issues=issues, model=data.get("model") or model
    )

"""Ported from packages/core/src/voiceCheck.ts

Persists reports on project.voiceReports keyed by chapterId + content fingerprint.
Mark stale when chapter fingerprint drifts; never write characterLinks/timeline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.core import llm_budget
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
        timeout=llm_budget.CHAT,
    )

    raw, used_model = content_from_response(res)
    from app.core.llm_text import extract_json_object

    # 不再"先找围栏"：模型常在字符串值里嵌示例对白，先找围栏会把示例当成整份输出。
    parsed = extract_json_object(raw)
    if parsed is None:
        raise RuntimeError("声线检查 JSON 解析失败：模型未返回 JSON 对象")
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

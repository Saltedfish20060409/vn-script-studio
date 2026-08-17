"""Author style memory — LLM learns the writer's style from their own text.

The model reads the whole novel (plain-text chapters) and distils a concrete,
actionable style guide: sentence rhythm, word choice, narrative voice,
punctuation habits, dialogue style and explicit avoidances. The guide is
stored on the project and later injected into the agent context so every
continuation / rewrite matches the author's own voice.

Degrades gracefully: on any failure the caller gets an error string; the
project state is never corrupted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.core.ai import DeepSeekConfig
from app.core.llm_http import chat_completions, content_from_response
from app.domain.types import VnProject

from .agent_context import _blocks_to_plain

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")

_CHAPTER_TEXT_CAP = 2200
_MAX_CHAPTER_TEXTS = 12
_GUIDE_CAP = 600

_SYSTEM_PROMPT = """你是资深编辑。下面是一位作者自己的作品全文（Ren'Py 风格视觉小说脚本，旁白与对白）。请从【作者自己的写法】中提炼 ta 的写作风格，输出 JSON，不要解释。

分析维度：
1. 句式节奏：长句/短句偏好、段落密度、流水句或断句习惯
2. 用词：白话/书面/文艺的倾向、常用词与口头禅（如"罢了""仿佛""简直"）
3. 叙述视角与距离：心理描写深浅、感官细节密度
4. 对白风格：台词长度、语气词、省略号/破折号使用、角色区分度
5. 标点与格式习惯：引号类型、破折号、省略号、括号备注
6. 禁忌/缺点：重复用词、套话、形容词堆砌等【要避免】的具体项

输出 schema：
{
  "guide": "一段 ≤600 字的风格指南。每条都是具体可执行的规则，用「你习惯…」「避免…」「保持…」句式，不要泛泛而谈",
  "samples": ["3 条最能代表该风格的原文句子，逐字摘自正文"]
}

要求：只基于作者自己的文本归纳，不要套用外部文风理论；指南必须具体到能指导续写。"""


@dataclass
class StyleMemoryResult:
    guide: str = ""
    samples: List[str] = None  # type: ignore[assignment]
    error: Optional[str] = None
    model: str = ""

    def __post_init__(self) -> None:
        if self.samples is None:
            self.samples = []


def _chapter_texts(project: VnProject) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for ch in project.chapters:
        text = (ch.blocks and _blocks_to_plain(ch.blocks, project.characters) or "").strip()
        if not text:
            continue
        out.append({"title": ch.title or "", "text": text[:_CHAPTER_TEXT_CAP]})
        if len(out) >= _MAX_CHAPTER_TEXTS:
            break
    return out


def _build_messages(project: VnProject) -> List[Dict[str, str]]:
    chapters = _chapter_texts(project)
    user: Dict[str, Any] = {
        "title": project.title,
        "genre": project.genre or "",
        "chapters": chapters,
        "output_schema": {
            "guide": "≤600 字风格指南",
            "samples": ["3 条原文代表句"],
        },
    }
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
    ]


def _parse(content: str) -> StyleMemoryResult:
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
    guide = str(data.get("guide") or "").strip()[:_GUIDE_CAP]
    if not guide:
        raise ValueError("模型未返回风格指南")
    samples: List[str] = []
    raw_samples = data.get("samples")
    if isinstance(raw_samples, list):
        for s in raw_samples:
            t = str(s or "").strip()
            if t:
                samples.append(t[:200])
        samples = samples[:3]
    return StyleMemoryResult(guide=guide, samples=samples)


async def learn_style_memory(
    config: Optional[DeepSeekConfig],
    project: VnProject,
) -> StyleMemoryResult:
    """Distil a style guide from the author's own chapters."""
    if not project.chapters:
        return StyleMemoryResult(error="作品还没有章节，先写几章再学习。")
    if config is None or not config.apiKey or "your-key" in config.apiKey:
        return StyleMemoryResult(error="未配置 DEEPSEEK_API_KEY，已跳过文风学习")
    try:
        res = await chat_completions(
            config,
            messages=_build_messages(project),
            temperature=0.3,
            response_format={"type": "json_object"},
            timeout=180,
        )
        content, used_model = content_from_response(res)
        result = _parse(content)
        result.model = used_model or (config.model or "")
        return result
    except Exception as exc:  # noqa: BLE001 — learning must never crash the request
        return StyleMemoryResult(error=f"文风学习失败：{exc}")

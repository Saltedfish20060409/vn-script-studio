"""Ported from packages/core/src/ai.ts"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from app.core import llm_budget
from app.domain.types import AiRequest, AiResponse, VnProject
from app.llm_models import DEFAULT_LLM_MODEL

from .renpy import project_to_context
from .writing_surface import PROSE_FIRST_ONE_LINE


@dataclass
class DeepSeekConfig:
    apiKey: str
    baseUrl: Optional[str] = None
    model: Optional[str] = None
    # openai (default) | ollama (local via Ollama's OpenAI-compatible endpoint)
    provider: str = "openai"


ACTION_PROMPTS: Dict[str, str] = {
    "continue": (
        "根据上下文续写这一段视觉小说剧本。写**自然语言剧本**：对白一行一句（角色：「台词」）、"
        "旁白短句、动作与场景写在括号里。不要写 label/jump/menu:/scene/show/$ 这类引擎语法"
        "——RPY 由「生成脚本 / 导出」那一步从剧本转换。不要解释。"
    ),
    "rewrite": "改写用户选中的片段，保持剧情意图与人物语气与**原有形态**（自然语言剧本就还它自然语言剧本），不要顺手加引擎语法，不要解释。",
    "choices": "为当前情节设计 2～4 个有意义的分支选项：每项一行选项文案，紧跟它会演成什么（自然语言，不要写 menu/jump/label 这类引擎语法）。",
    "polish": "润色对白与旁白：更自然、更有画面感，保持人物声音一致。输出润色后的自然语言剧本片段。",
    "outline": "根据已有设定，给出接下来 3～5 个场景的大纲（场景标题 + 一句话冲突 + 可选分支），用中文条目列表。",
    "character_voice": "检查并改写，使对白更符合角色人设与语气。输出改写后的对白片段（自然语言剧本）。",
}


def _build_system_prompt(project: VnProject) -> str:
    return "\n".join(
        [
            "你是资深视觉小说编剧助手。",
            PROSE_FIRST_ONE_LINE,
            "约定：",
            "- 对白一行一句：角色：「台词」；旁白用短句；动作与场景提示写在括号里",
            "- 需要选项时用自然语言列出（选项：… → 它会演成什么），不要写 menu/label/jump",
            "- 除非用户明确要引擎脚本（rpy），否则不要输出 scene/show/$ 这类语法",
            "- 除非用户要求，不要输出大段讲解，直接给剧本正文。",
            "",
            "作品上下文：",
            project_to_context(project),
        ]
    )


async def run_ai(config: DeepSeekConfig, request: AiRequest) -> AiResponse:
    if not config.apiKey or "your-key" in config.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")

    from app.core.llm_http import chat_completions, content_from_response

    model = config.model or DEFAULT_LLM_MODEL
    user_parts = [
        p
        for p in [
            ACTION_PROMPTS[request.action],
            f"额外要求：{request.instruction}" if request.instruction else "",
            f"选中/焦点内容：\n{request.selection}" if request.selection else "",
        ]
        if p
    ]

    res = await chat_completions(
        config,
        messages=[
            {"role": "system", "content": _build_system_prompt(request.project)},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ],
        temperature=0.8 if request.action == "outline" else 0.7,
        timeout=llm_budget.CHAT,
    )
    content, used_model = content_from_response(res)
    return AiResponse(content=content, model=used_model or model)

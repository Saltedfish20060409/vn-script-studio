"""Ported from packages/core/src/ai.ts"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import httpx

from app.domain.types import AiRequest, AiResponse, VnProject

from .renpy import project_to_context


@dataclass
class DeepSeekConfig:
    apiKey: str
    baseUrl: Optional[str] = None
    model: Optional[str] = None


ACTION_PROMPTS: Dict[str, str] = {
    "continue": (
        "根据上下文续写视觉小说脚本。输出纯 Ren'Py 风格片段：旁白用双引号行，"
        '对白用 角色名 "台词"，需要时用 menu/jump/label。不要解释。'
    ),
    "rewrite": "改写用户选中的片段，保持剧情意图与人物语气，输出改进后的 Ren'Py 风格脚本，不要解释。",
    "choices": "为当前情节设计 2～4 个有意义的分支选项（menu），每个选项给出简短后果或 jump 目标名，输出 Ren'Py menu 代码。",
    "polish": "润色对白与旁白：更自然、更有画面感，保持人物声音一致。输出润色后的 Ren'Py 片段。",
    "outline": "根据已有设定，给出接下来 3～5 个场景的大纲（场景标题 + 一句话冲突 + 可选分支），用中文条目列表。",
    "character_voice": "检查并改写，使对白更符合角色人设与语气。输出改写后的 Ren'Py 对白片段。",
}


def _build_system_prompt(project: VnProject) -> str:
    return "\n".join(
        [
            "你是资深视觉小说编剧助手，输出默认贴近 Ren'Py script。",
            "约定：",
            '- 角色 define 名用英文小写标识符；对白行写成：name "台词"',
            '- 旁白："旁白文字"',
            "- 场景：scene bg_xxx / show char_xxx / hide char_xxx",
            "- 分支：menu: 与 jump label_name",
            "- 除非用户要求，不要输出大段讲解，直接给可粘贴的脚本。",
            "",
            "作品上下文：",
            project_to_context(project),
        ]
    )


async def run_ai(config: DeepSeekConfig, request: AiRequest) -> AiResponse:
    if not config.apiKey or "your-key" in config.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")

    base_url = (config.baseUrl or "https://api.deepseek.com").rstrip("/")
    model = config.model or "deepseek-chat"

    user_parts = [
        p
        for p in [
            ACTION_PROMPTS[request.action],
            f"额外要求：{request.instruction}" if request.instruction else "",
            f"选中/焦点内容：\n{request.selection}" if request.selection else "",
        ]
        if p
    ]

    async with httpx.AsyncClient(timeout=120) as client:
        res = await client.post(
            f"{base_url}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {config.apiKey}",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _build_system_prompt(request.project)},
                    {"role": "user", "content": "\n\n".join(user_parts)},
                ],
                "temperature": 0.8 if request.action == "outline" else 0.7,
                "stream": False,
            },
        )

    if res.status_code >= 400:
        err_text = res.text
        raise RuntimeError(f"DeepSeek API {res.status_code}: {err_text[:400]}")

    data = res.json()
    choices = data.get("choices") or []
    content = ""
    if choices:
        content = ((choices[0] or {}).get("message") or {}).get("content", "") or ""
        content = content.strip()
    return AiResponse(content=content, model=data.get("model") or model)

"""Curated model presets for the LLM settings panel.

Every preset speaks the OpenAI-compatible /v1/chat/completions wire format,
so a single client (llm_http) serves them all. Presets only fill in the
base URL and model name; the user still supplies their own API key.
"""

from __future__ import annotations

from typing import Dict, List

MODEL_PRESETS: List[Dict[str, object]] = [
    {
        "id": "deepseek-chat",
        "label": "DeepSeek-V3（deepseek-chat）",
        "vendor": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "json_mode": True,
        "context_k": 64,
        "note": "默认。写作/审稿/事实抽取通用，性价比高。",
    },
    {
        "id": "deepseek-reasoner",
        "label": "DeepSeek-R1（deepseek-reasoner）",
        "vendor": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-reasoner",
        "json_mode": False,
        "context_k": 64,
        "note": "推理模型，适合深度分析；不支持 JSON 结构化输出。",
    },
    {
        "id": "moonshot-v1-32k",
        "label": "Kimi（moonshot-v1-32k）",
        "vendor": "Moonshot",
        "base_url": "https://api.moonshot.cn",
        "model": "moonshot-v1-32k",
        "json_mode": True,
        "context_k": 32,
        "note": "中文长文表现好，适合长章节上下文。",
    },
    {
        "id": "moonshot-v1-128k",
        "label": "Kimi（moonshot-v1-128k）",
        "vendor": "Moonshot",
        "base_url": "https://api.moonshot.cn",
        "model": "moonshot-v1-128k",
        "json_mode": True,
        "context_k": 128,
        "note": "超大上下文，适合整本小说的跨章节分析。",
    },
    {
        "id": "qwen-plus",
        "label": "通义千问（qwen-plus）",
        "vendor": "Alibaba",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "json_mode": True,
        "context_k": 131,
        "note": "中文创作能力强，长上下文。",
    },
    {
        "id": "qwen-max",
        "label": "通义千问旗舰（qwen-max）",
        "vendor": "Alibaba",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
        "json_mode": True,
        "context_k": 32,
        "note": "旗舰模型，质量优先。",
    },
    {
        "id": "glm-4-plus",
        "label": "智谱 GLM-4-Plus",
        "vendor": "Zhipu",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-plus",
        "json_mode": True,
        "context_k": 128,
        "note": "中文创作稳定，128k 上下文。",
    },
    {
        "id": "gpt-4o-mini",
        "label": "OpenAI GPT-4o-mini",
        "vendor": "OpenAI",
        "base_url": "https://api.openai.com",
        "model": "gpt-4o-mini",
        "json_mode": True,
        "context_k": 128,
        "note": "国际访问需要代理；轻量快速。",
    },
    {
        "id": "gpt-4o",
        "label": "OpenAI GPT-4o",
        "vendor": "OpenAI",
        "base_url": "https://api.openai.com",
        "model": "gpt-4o",
        "json_mode": True,
        "context_k": 128,
        "note": "国际访问需要代理；质量高。",
    },
    {
        "id": "local-ollama",
        "label": "本地 Ollama（离线）",
        "vendor": "Ollama",
        "base_url": "http://localhost:11434",
        "model": "qwen2.5:7b",
        "json_mode": False,
        "context_k": 32,
        "note": "免费离线。需在本机运行 Ollama 并已拉取模型；模型名可改。",
    },
]


def list_model_presets() -> List[Dict[str, object]]:
    """Return presets without any server internals (there are none)."""
    return [dict(p) for p in MODEL_PRESETS]


def find_preset(preset_id: str) -> Dict[str, object] | None:
    for p in MODEL_PRESETS:
        if p["id"] == preset_id:
            return dict(p)
    return None

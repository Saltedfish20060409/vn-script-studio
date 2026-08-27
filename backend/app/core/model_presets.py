"""Curated model presets for the LLM settings panel.

Every preset speaks the OpenAI-compatible /v1/chat/completions wire format,
so a single client (llm_http) serves them all. Presets only fill in the
base URL and model name; the user still supplies their own API key.

DeepSeek V4 official IDs are deepseek-v4-flash / deepseek-v4-pro.
``*-think`` suffixes are this studio's alias for thinking mode (rewritten
in llm_http before the request leaves the server).
"""

from __future__ import annotations

from typing import Dict, List

from app.llm_models import DEFAULT_LLM_MODEL

MODEL_PRESETS: List[Dict[str, object]] = [
    {
        "id": "deepseek-v4-flash",
        "label": "DeepSeek-V4 Flash",
        "vendor": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": DEFAULT_LLM_MODEL,
        "json_mode": True,
        "context_k": 1000,
        "note": "默认。官方 ID deepseek-v4-flash，非思考（等价旧 deepseek-chat）。",
    },
    {
        "id": "deepseek-v4-flash-think",
        "label": "DeepSeek-V4 Flash 推理",
        "vendor": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash-think",
        "json_mode": False,
        "context_k": 1000,
        "note": "思考模式（等价旧 deepseek-reasoner）。请求改写为官方 Flash + thinking；不支持 JSON 模式。",
    },
    {
        "id": "deepseek-v4-pro",
        "label": "DeepSeek-V4 Pro",
        "vendor": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-pro",
        "json_mode": True,
        "context_k": 1000,
        "note": "官方旗舰。默认非思考，质量优先。",
    },
    {
        "id": "kimi-k2.6",
        "label": "Kimi K2.6（kimi-k2.6）",
        "vendor": "Moonshot",
        "base_url": "https://api.moonshot.cn",
        "model": "kimi-k2.6",
        "json_mode": True,
        "context_k": 256,
        "note": "K2 系列已下线，现为 K2.6；中文长文与 Agent 能力突出。",
    },
    {
        "id": "qwen-max",
        "label": "通义千问旗舰（qwen-max · Qwen3.7）",
        "vendor": "Alibaba",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
        "json_mode": True,
        "context_k": 131,
        "note": "旗舰模型（当前 Qwen3.7 系列），质量优先，中文创作强。",
    },
    {
        "id": "qwen-plus",
        "label": "通义千问均衡（qwen-plus · Qwen3.7）",
        "vendor": "Alibaba",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "json_mode": True,
        "context_k": 131,
        "note": "均衡款（当前 Qwen3.7 系列），速度与质量兼顾。",
    },
    {
        "id": "glm-5",
        "label": "智谱 GLM-5",
        "vendor": "Zhipu",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5",
        "json_mode": True,
        "context_k": 200,
        "note": "GLM 最新一代（5.1 已退役，自动指向 5.2）；中文创作稳定。",
    },
    {
        "id": "glm-4-flash",
        "label": "GLM-4-Flash-250414（免费）",
        "vendor": "Zhipu",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash-250414",
        "json_mode": True,
        "context_k": 128,
        "note": "智谱长期免费模型，稳定、json 模式可用；适合无 key 用户的试用/兜底。GLM-4.7-Flash 免费档当前访问量过大易限流，暂不推荐。",
    },
    {
        "id": "gpt-5",
        "label": "OpenAI GPT-5",
        "vendor": "OpenAI",
        "base_url": "https://api.openai.com",
        "model": "gpt-5",
        "json_mode": True,
        "context_k": 400,
        "note": "国际访问需要代理；当前 GPT-5 系列旗舰。",
    },
    {
        "id": "gpt-5-mini",
        "label": "OpenAI GPT-5-mini",
        "vendor": "OpenAI",
        "base_url": "https://api.openai.com",
        "model": "gpt-5-mini",
        "json_mode": True,
        "context_k": 400,
        "note": "国际访问需要代理；轻量快速，日常写作够用。",
    },
    {
        "id": "local-ollama",
        "label": "本地 Ollama（离线）",
        "vendor": "Ollama",
        "base_url": "http://localhost:11434",
        "model": "qwen3:8b",
        "json_mode": False,
        "context_k": 32,
        "note": "免费离线。需在本机运行 Ollama 并已拉取模型（如 qwen3:8b）；模型名可改。",
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

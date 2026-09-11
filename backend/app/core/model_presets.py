"""Curated model presets for the LLM settings panel.

Every preset speaks the OpenAI-compatible /v1/chat/completions wire format,
so a single client (llm_http) serves them all. Presets only fill in the
base URL and model name; the user still supplies their own API key.

ID 可信度分级（2026-09-11 校对）：
- **实测验证**：智谱（用线上 key 拉过 /models：glm-5.3 / glm-5.3-flash / glm-5-turbo…）、
  豆包（用户在站内真实调用成功：doubao-seed-2-1-turbo-260628）、
  DeepSeek（官方更新日志 + 定价页：正式名 deepseek-flash，服务端为 V4.1-Flash）。
- **仅官方文档/官方更新说明**（未在线校验）：Claude、Gemini、GPT、Kimi、Qwen 的最新档。
  这类条目的 note 里都标了「ID 未在线校验，以官方控制台为准」——它们在国内多数还需
  自备网络条件；用户若报 model 不存在，在「设置 → 模型」里改成控制台显示的名字即可
  （预设只是帮忙填端点，不锁定模型名）。

``*-think`` 后缀是本工作室对思考模式的别名（在 llm_http 出站前改写）。
"""

from __future__ import annotations

from typing import Dict, List

from app.llm_models import DEFAULT_LLM_MODEL

MODEL_PRESETS: List[Dict[str, object]] = [
    # ---------------- DeepSeek（默认） ----------------
    {
        "id": "deepseek-flash",
        "label": "DeepSeek-V4.1 Flash（默认）",
        "vendor": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": DEFAULT_LLM_MODEL,
        "json_mode": True,
        "context_k": 1000,
        "note": "官方正式名 deepseek-flash，服务端即 DeepSeek-V4.1-Flash（2026-09-10 发布，新架构、原生多模态）。默认非思考。",
    },
    {
        "id": "deepseek-flash-think",
        "label": "DeepSeek-V4.1 Flash 推理",
        "vendor": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-flash-think",
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
        "note": "上代旗舰，仍可用；官方公告：2026-09-14 12:00 起至 V4.1 Pro 发布前，其请求会路由到 V4.1 Flash 并按 V4.1 计费。",
    },
    {
        "id": "deepseek-v4-flash",
        "label": "DeepSeek-V4 Flash（兼容旧名）",
        "vendor": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "json_mode": True,
        "context_k": 1000,
        "note": "旧模型名。V4 Flash 已退役，官方保留此名做兼容：请求实际由 V4.1 Flash 承接。建议直接用上面的 deepseek-flash。",
    },
    # ---------------- 智谱 GLM（实测可用 ID） ----------------
    {
        "id": "glm-5",
        "label": "智谱 GLM-5.3（旗舰）",
        "vendor": "Zhipu",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5.3",
        "json_mode": True,
        "context_k": 200,
        "note": "智谱最新旗舰（实测可用）。中文创作稳定，质量优先。",
    },
    {
        "id": "glm-5-flash",
        "label": "智谱 GLM-5.3-Flash（快 / 省）",
        "vendor": "Zhipu",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5.3-flash",
        "json_mode": True,
        "context_k": 128,
        "note": "智谱 Flash 档（实测可用）：速度快、便宜，适合日常续写与润色。额度与限流以智谱控制台为准。",
    },
    {
        "id": "glm-5-turbo",
        "label": "智谱 GLM-5-Turbo（均衡）",
        "vendor": "Zhipu",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5-turbo",
        "json_mode": True,
        "context_k": 200,
        "note": "智谱 Turbo 档（实测可用）：速度与质量折中。",
    },
    {
        "id": "glm-4-flash",
        "label": "GLM-4-Flash-250414（站内免费档）",
        "vendor": "Zhipu",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash-250414",
        "json_mode": True,
        "context_k": 128,
        "note": "站方免费兜底档（每日限额、可能限流），无 key 先体验用；正式写作建议换上面的档位或自带 Key。",
    },
    # ---------------- 豆包（实测可用 ID） ----------------
    {
        "id": "doubao-seed-turbo",
        "label": "豆包 Seed 2.1 Turbo",
        "vendor": "ByteDance",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-seed-2-1-turbo-260628",
        "json_mode": True,
        "context_k": 256,
        "note": "火山方舟（实测可用，站内已有用户在用）：中文长文快、价格低。若控制台改版，按控制台显示改模型名。",
    },
    # ---------------- 通义千问 ----------------
    {
        "id": "qwen-max",
        "label": "通义千问旗舰（qwen3.7-max）",
        "vendor": "Alibaba",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3.7-max",
        "json_mode": True,
        "context_k": 1000,
        "note": "Qwen3.7 旗舰（MoE、百万级上下文），质量优先，中文创作强。若报 model 不存在，改用控制台里的当前旗舰 ID。",
    },
    {
        "id": "qwen-plus",
        "label": "通义千问均衡（qwen-plus）",
        "vendor": "Alibaba",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "json_mode": True,
        "context_k": 131,
        "note": "均衡款，速度与质量兼顾，适合日常写作。也会自动指向 Qwen 最新均衡版本。",
    },
    # ---------------- Kimi ----------------
    {
        "id": "kimi-k3",
        "label": "Kimi K3（moonshot）",
        "vendor": "Moonshot",
        "base_url": "https://api.moonshot.cn",
        "model": "kimi-k3",
        "json_mode": True,
        "context_k": 256,
        "note": "最新一代，中文长文与 Agent 能力突出。若报 model 不存在，按 Moonshot 控制台显示的 ID 改。",
    },
    {
        "id": "kimi-k2.6",
        "label": "Kimi K2.6（moonshot）",
        "vendor": "Moonshot",
        "base_url": "https://api.moonshot.cn",
        "model": "kimi-k2.6",
        "json_mode": True,
        "context_k": 256,
        "note": "上一代，仍可用；长文与对话稳定。",
    },
    # ---------------- Claude（OpenAI 兼容端点） ----------------
    {
        "id": "claude-opus-5",
        "label": "Claude Opus 5",
        "vendor": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-opus-5",
        "json_mode": False,
        "context_k": 200,
        "note": "最新一代（ID 未在线校验，以 Anthropic 控制台为准）。文风与长文改写口碑好；国内需自备网络条件，不支持 JSON 模式。",
    },
    {
        "id": "claude-opus",
        "label": "Claude Opus 4.8",
        "vendor": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-opus-4-8",
        "json_mode": False,
        "context_k": 200,
        "note": "上一代旗舰（ID 未在线校验）。若报 model 不存在，按控制台显示的名字改。",
    },
    {
        "id": "claude-sonnet",
        "label": "Claude Sonnet 4.8",
        "vendor": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-8",
        "json_mode": False,
        "context_k": 200,
        "note": "轻量档：更快更省，适合日常润色（ID 未在线校验）。国内需自备网络条件。",
    },
    # ---------------- Gemini（OpenAI 兼容端点） ----------------
    {
        "id": "gemini-flash",
        "label": "Gemini 3.7 Flash",
        "vendor": "Google",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.7-flash",
        "json_mode": True,
        "context_k": 1000,
        "note": "Google 官方文档标注的最新主力 Flash（ID 未在线校验）。超长上下文、价格低；国内需自备网络条件。",
    },
    {
        "id": "gemini-pro",
        "label": "Gemini 3.7 Pro",
        "vendor": "Google",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.7-pro",
        "json_mode": True,
        "context_k": 1000,
        "note": "旗舰档（ID 未在线校验；若控制台暂无该档，改用 Flash）。国内需自备网络条件。",
    },
    # ---------------- OpenAI ----------------
    {
        "id": "gpt-5.5",
        "label": "OpenAI GPT-5.5",
        "vendor": "OpenAI",
        "base_url": "https://api.openai.com",
        "model": "gpt-5.5",
        "json_mode": True,
        "context_k": 1000,
        "note": "最新一代（ID 未在线校验，以 OpenAI 控制台为准）。国际访问需要网络条件。",
    },
    {
        "id": "gpt-5",
        "label": "OpenAI GPT-5",
        "vendor": "OpenAI",
        "base_url": "https://api.openai.com",
        "model": "gpt-5",
        "json_mode": True,
        "context_k": 400,
        "note": "上一代，仍可用；模型名以 OpenAI 控制台为准。",
    },
    {
        "id": "gpt-5-mini",
        "label": "OpenAI GPT-5-mini",
        "vendor": "OpenAI",
        "base_url": "https://api.openai.com",
        "model": "gpt-5-mini",
        "json_mode": True,
        "context_k": 400,
        "note": "国际访问需要网络条件；轻量快速，日常写作够用。",
    },
    # ---------------- 本地 ----------------
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

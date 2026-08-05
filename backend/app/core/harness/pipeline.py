"""VN/LN Harness pipeline — NovelMaster multi-role idea, studio-native execution."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx

from app.core.ai import DeepSeekConfig
from app.core.harness.ai_flavor import (
    HarnessIssue,
    issues_to_dict,
    lint_vn_harness,
    summarize_issues,
)
from app.core.harness.roles import build_role_system
from app.core.novel_memory import format_memory_for_agent
from app.domain.types import VnProject
from app.core.renpy import project_to_context


async def run_harness_llm(
    config: DeepSeekConfig,
    *,
    role: str,
    user_prompt: str,
    project: Optional[VnProject] = None,
    temperature: float = 0.7,
) -> Dict[str, Any]:
    if not config.apiKey or "your-key" in config.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")
    base_url = (config.baseUrl or "https://api.deepseek.com").rstrip("/")
    model = config.model or "deepseek-chat"
    extra = ""
    if project is not None:
        extra = "作品上下文（节选）：\n" + project_to_context(project)[:3500]
    system = build_role_system(role, extra=extra, project=project)
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
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "stream": False,
            },
        )
    if res.status_code >= 400:
        raise RuntimeError(f"DeepSeek API {res.status_code}: {res.text[:400]}")
    data = res.json()
    choices = data.get("choices") or []
    content = ""
    if choices:
        content = ((choices[0] or {}).get("message") or {}).get("content", "") or ""
    return {"content": content.strip(), "model": data.get("model") or model, "role": role}


def audit_draft(draft: str) -> Dict[str, Any]:
    issues = lint_vn_harness(draft)
    err, warn, info = summarize_issues(issues)
    return {
        "issues": issues_to_dict(issues),
        "errorCount": err,
        "warnCount": warn,
        "infoCount": info,
        "pass": err == 0,
    }


async def harness_editor_pass(
    config: DeepSeekConfig,
    draft: str,
    project: Optional[VnProject] = None,
) -> Dict[str, Any]:
    """Lint first, then Editor LLM for minimal fixes if needed."""
    audit = audit_draft(draft)
    if audit["pass"] and audit["warnCount"] == 0:
        return {
            **audit,
            "role": "editor",
            "content": "",
            "skippedLlm": True,
            "message": "确定性体检通过，无需责编改写",
        }
    prompt = (
        "请根据下列体检问题，给出最小改动后的文本（保持剧情意图）。"
        "先用条目列出仍须注意的点，再给出改写正文。\n\n"
        f"## 体检\n{json.dumps(audit['issues'][:20], ensure_ascii=False)}\n\n"
        f"## 原文\n{draft[:8000]}"
    )
    llm = await run_harness_llm(
        config, role="editor", user_prompt=prompt, project=project, temperature=0.4
    )
    return {**audit, **llm, "skippedLlm": False}


def build_writer_user_prompt(
    instruction: str,
    *,
    selection: str = "",
    chapter_tail: str = "",
    long_memory: str = "",
    lore_craft: str = "",
) -> str:
    parts = [
        instruction.strip() or "请续写下一小段可上演内容。",
        f"## 当前章末尾\n{chapter_tail}" if chapter_tail.strip() else "",
        f"## 选区\n{selection}" if selection.strip() else "",
        long_memory.strip(),
        lore_craft.strip(),
    ]
    return "\n\n".join(p for p in parts if p)

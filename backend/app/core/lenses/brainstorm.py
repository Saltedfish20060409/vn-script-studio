"""强实现头脑风暴：每位作家独立 LLM 调用 → 责编综合。"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import httpx

from app.core.ai import DeepSeekConfig
from app.core.agent_context import _blocks_to_plain
from app.core.lenses import (
    MentorPack,
    custom_lenses_for_project,
    pack_prompt_block,
    resolve_lenses,
    resolve_project_lenses,
)
from app.core.mentors import build_mentor_prompt_for_project
from app.core.pipeline.ledger import format_ledger_for_agent, get_ledger
from app.core.renpy import project_to_context
from app.domain.types import VnProject


async def _chat(
    cfg: DeepSeekConfig,
    *,
    system: str,
    user: str,
    temperature: float = 0.75,
) -> Dict[str, Any]:
    if not cfg.apiKey or "your-key" in cfg.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")
    base = (cfg.baseUrl or "https://api.deepseek.com").rstrip("/")
    model = cfg.model or "deepseek-chat"
    async with httpx.AsyncClient(timeout=120) as client:
        res = await client.post(
            f"{base}/v1/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg.apiKey}",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
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
    return {"content": content.strip(), "model": data.get("model") or model}


def _work_snippet(
    project: VnProject,
    *,
    chapter_id: Optional[str],
    selection: str,
    draft: str,
) -> str:
    parts: List[str] = []
    ctx = project_to_context(project)
    if ctx:
        parts.append("## 作品节选\n" + ctx[:2800])
    ledger = format_ledger_for_agent(get_ledger(project))
    if ledger.strip():
        parts.append(ledger[:1200])
    if chapter_id:
        ch = next((c for c in project.chapters if c.id == chapter_id), None)
        if ch:
            plain = _blocks_to_plain(ch.blocks, project.characters)
            if plain:
                parts.append(f"## 当前章「{ch.title}」末尾\n{(plain or '')[-1000:]}")
    if (draft or "").strip():
        parts.append("## 当前草稿片段\n" + draft.strip()[-1200:])
    if (selection or "").strip():
        parts.append("## 选区\n" + selection.strip()[:1200])
    return "\n\n".join(parts) if parts else "（暂无额外正文上下文）"


def _author_system(pack: MentorPack) -> str:
    lens = pack_prompt_block(pack, max_chars=min(pack.budget_chars, 2600))
    return (
        f"你是圆桌头脑风暴中的一位**独立参谋**，只使用「{pack.name}」的思维框架。\n"
        "硬规则：\n"
        "- 不是真人扮演，不仿写受版权原文句式。\n"
        "- 本轮禁止迎合其他作家；你看不到别人的发言，只对自己的框架负责。\n"
        "- 面向轻小说/视觉小说：建议要可演、可写进对白或场面。\n"
        "- 输出结构：\n"
        "  1) **立场**（两句内）\n"
        "  2) **具体思路**（3～5条，尽量具体到场次/物件/信息差）\n"
        "  3) **大胆一票**（一条可能不被常识喜欢、但符合本框架的想法）\n"
        "  4) **不要做什么**（1～2条）\n"
        f"\n{lens}"
    )


def _synth_system(project: VnProject) -> str:
    mentor = ""
    try:
        mentor = build_mentor_prompt_for_project(project, stage="plan", total_budget=2200)
    except Exception:
        pass
    return (
        "你是圆桌主持责编（通用文学编辑）。你刚收到多位作家参谋的**独立发言**。\n"
        "任务：做真正的综合，而不是复读。\n"
        "硬规则：\n"
        "- 先标出**分歧**（至少指出两处视角冲突或侧重点不同）。\n"
        "- 再标出**互补**（哪些建议可拼在一起）。\n"
        "- 最后给出对本作品**可执行的下一步**（恰好 3 步，排序：最该先做的在前）。\n"
        "- 禁止和稀泥：不要说「都可以」「各有道理」而不做选择。\n"
        "- 禁止把所有发言改写成同一套正确废话。\n"
        "- 服从视觉小说/轻小说可演底盘；不要仿写某作家原文。\n"
        f"\n{mentor}"
    )


async def _run_one_author(
    cfg: DeepSeekConfig,
    pack: MentorPack,
    *,
    question: str,
    work: str,
) -> Dict[str, Any]:
    user = (
        f"## 头脑风暴议题\n{question}\n\n"
        f"{work}\n\n"
        "请仅用你的框架发言。不要提及其他作家。"
    )
    try:
        out = await _chat(
            cfg,
            system=_author_system(pack),
            user=user,
            temperature=0.82,
        )
        return {
            "id": pack.id,
            "name": pack.name,
            "content": out.get("content") or "",
            "model": out.get("model"),
            "ok": True,
            "error": None,
        }
    except Exception as exc:
        return {
            "id": pack.id,
            "name": pack.name,
            "content": "",
            "model": None,
            "ok": False,
            "error": str(exc)[:300],
        }


async def run_brainstorm(
    cfg: DeepSeekConfig,
    project: VnProject,
    *,
    question: str,
    lens_ids: Optional[List[str]] = None,
    chapter_id: Optional[str] = None,
    selection: str = "",
    draft: str = "",
) -> Dict[str, Any]:
    q = (question or "").strip()
    if not q:
        raise ValueError("请提供头脑风暴议题（你想解决的问题）")

    if lens_ids is not None:
        packs = resolve_lenses(
            lens_ids, custom=custom_lenses_for_project(project), max_active=3
        )
    else:
        packs = resolve_project_lenses(project)
    if len(packs) < 2:
        raise ValueError("强头脑风暴至少需要 2 位作家（请在 ⇄ 中多选）")
    if len(packs) > 3:
        packs = packs[:3]

    work = _work_snippet(
        project, chapter_id=chapter_id, selection=selection, draft=draft
    )

    # 并行：每位作家独立调用（彼此不可见）
    perspectives = await asyncio.gather(
        *[_run_one_author(cfg, p, question=q, work=work) for p in packs]
    )
    perspectives_list = list(perspectives)
    ok_views = [p for p in perspectives_list if p.get("ok") and (p.get("content") or "").strip()]
    if not ok_views:
        raise RuntimeError("所有作家视角调用均失败，请检查 API Key / 网络")

    joined = "\n\n".join(
        f"### 作家：{p['name']}（`{p['id']}`）\n{p['content']}" for p in ok_views
    )
    synth_user = (
        f"## 议题\n{q}\n\n"
        f"{work}\n\n"
        f"## 独立发言（互不可见时生成）\n{joined}\n\n"
        "请按：分歧 → 互补 → 三步行动 输出。"
    )
    synth = await _chat(
        cfg,
        system=_synth_system(project),
        user=synth_user,
        temperature=0.45,
    )

    return {
        "mode": "parallel_then_synthesize",
        "question": q,
        "lensIds": [p.id for p in packs],
        "perspectives": perspectives_list,
        "synthesis": synth.get("content") or "",
        "model": synth.get("model"),
        "authorCount": len(packs),
        "okCount": len(ok_views),
    }


def format_brainstorm_markdown(result: Dict[str, Any]) -> str:
    parts: List[str] = [
        "### 头脑风暴（强实现：分视角独立 → 责编综合）",
        f"**议题：** {result.get('question') or ''}",
        f"_模式：`{result.get('mode')}` · 成功视角 {result.get('okCount')}/{result.get('authorCount')}_",
    ]
    for p in result.get("perspectives") or []:
        name = p.get("name") or p.get("id")
        if p.get("ok"):
            parts.append(f"## 视角：{name}\n\n{p.get('content') or '（空）'}")
        else:
            parts.append(f"## 视角：{name}\n\n_调用失败：{p.get('error') or 'unknown'}_")
    parts.append(f"## 综合（责编）\n\n{result.get('synthesis') or '（无）'}")
    return "\n\n".join(parts)

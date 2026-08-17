"""Workshop chat: user↔character and character↔character (mind pack required)."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.core.ai import DeepSeekConfig
from app.core.character_voice.corpus import (
    find_character,
    format_corpus_for_prompt,
    format_mind_for_prompt,
)
from app.core.llm_http import content_from_response
from app.core.llm_provider import provider_from_config
from app.domain.types import Character, VnProject

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def _require_mind(c: Character) -> None:
    if not (c.voiceMind or "").strip():
        raise ValueError(
            f"角色「{c.displayName}」尚无思维包，请先合成或导入后再对话"
        )


def _persona_block(c: Character, project: VnProject) -> str:
    from app.core.character_voice.extract import format_script_anchors_for_prompt

    parts = [
        f"角色：{c.displayName}（{c.defineName}）",
        f"语气：{c.voice or ''}",
        f"简介：{c.bio or ''}",
        f"关系：{c.relationships or ''}",
        format_mind_for_prompt(c, max_chars=2200),
        format_corpus_for_prompt(c, max_samples=8, max_chars=1600),
        # 该角色在剧本里最近写的对白：保持人设与当下剧情的连续性
        format_script_anchors_for_prompt(project, c.id, limit=4, max_chars=600),
    ]
    return "\n".join(p for p in parts if p and str(p).strip())


async def workshop_chat(
    cfg: DeepSeekConfig,
    project: VnProject,
    *,
    character_id: str,
    mode: str = "user",
    message: str = "",
    partner_id: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    mode=user: user talks to focus character → one reply from character.
    mode=duo: user directs a scene beat; generate next exchange(s) between focus and partner.
    """
    focus = find_character(project, character_id)
    _require_mind(focus)
    msg = (message or "").strip()
    if not msg:
        raise ValueError("请输入内容")

    hist = history or []
    hist_txt = "\n".join(
        f"{h.get('role', '?')}: {h.get('content', '')}" for h in hist[-16:] if h.get("content")
    )

    if not cfg.apiKey or "your-key" in cfg.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")
    model = cfg.model or "deepseek-chat"
    provider = provider_from_config(cfg)

    if mode == "duo":
        if not partner_id:
            raise ValueError("互聊需要指定 partnerId")
        partner = find_character(project, partner_id)
        _require_mind(partner)
        system = (
            "你是视觉小说排练导演助手。两位角色均有思维包；根据用户出题/旁白，"
            "生成他们接下来的交锋对白。\n"
            "输出 JSON：{ lines:[{speakerId, speakerName, text, action, mood}, ...] }，"
            "2～4 句交替。\n"
            "action 是台词伴随的微动作（如：冷笑一声、别过头），无则空字符串；"
            "mood 是情绪标签（如：烦躁、试探），无则空字符串。\n"
            "严格服从各自思维包、正例感觉与剧本锚点；禁止设定说明书；像能演的 VN 对白。"
        )
        user = "\n".join(
            [
                "## 角色 A（焦点）",
                _persona_block(focus, project),
                "## 角色 B（搭档）",
                _persona_block(partner, project),
                "## 近期对白",
                hist_txt or "（无）",
                f"## 用户出题/旁白\n{msg}",
                f"speakerId 只能是 `{focus.id}` 或 `{partner.id}`。",
            ]
        )
    else:
        system = (
            f"你在角色工坊中扮演「{focus.displayName}」。用户在与你排练对话。\n"
            "只以该角色口吻回复；可短可刺，服从思维包。\n"
            "输出 JSON：{ reply: \"...\", action: \"...\", mood: \"...\" }。\n"
            "action 是该句台词伴随的微动作（如：叹了口气、低头摆弄伞），无则空字符串；"
            "mood 是情绪标签（如：平静、抗拒），无则空字符串。不要出戏解释。"
        )
        user = "\n".join(
            [
                _persona_block(focus, project),
                "## 近期对话",
                hist_txt or "（无）",
                f"## 用户说\n{msg}",
            ]
        )

    res = await provider.chat_completions(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.8,
        response_format={"type": "json_object"},
        timeout=120,
    )
    content, used_model = content_from_response(res)
    content = (content or "{}").strip()
    m = _FENCE_RE.search(content)
    if m:
        content = m.group(1).strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("模型未返回有效 JSON") from exc

    if mode == "duo":
        lines_out: List[Dict[str, str]] = []
        raw_lines = parsed.get("lines") if isinstance(parsed, dict) else None
        if isinstance(raw_lines, list):
            for ln in raw_lines:
                if not isinstance(ln, dict):
                    continue
                text = str(ln.get("text") or "").strip()
                if not text:
                    continue
                sid = str(ln.get("speakerId") or "").strip()
                sname = str(ln.get("speakerName") or "").strip()
                if sid == partner_id:
                    sname = sname or partner.displayName
                elif sid == character_id:
                    sname = sname or focus.displayName
                lines_out.append(
                    {
                        "speakerId": sid,
                        "speakerName": sname or sid,
                        "text": text,
                        "action": str(ln.get("action") or "").strip()[:80],
                        "mood": str(ln.get("mood") or "").strip()[:24],
                    }
                )
        if not lines_out:
            raise RuntimeError("互聊未生成有效对白")
        return {
            "mode": "duo",
            "lines": lines_out,
            "model": used_model or model,
        }

    reply = ""
    if isinstance(parsed, dict):
        reply = str(parsed.get("reply") or parsed.get("text") or "").strip()
    if not reply:
        raise RuntimeError("角色未给出回复")
    return {
        "mode": "user",
        "reply": reply,
        "action": str(parsed.get("action") or "").strip()[:80] if isinstance(parsed, dict) else "",
        "mood": str(parsed.get("mood") or "").strip()[:24] if isinstance(parsed, dict) else "",
        "speakerId": focus.id,
        "speakerName": focus.displayName,
        "model": used_model or model,
    }

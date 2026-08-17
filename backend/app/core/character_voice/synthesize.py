"""Synthesize a lightweight character mind pack from accepted corpus."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from app.core.ai import DeepSeekConfig
from app.core.character_voice.corpus import corpus_stats, find_character
from app.core.llm_http import content_from_response
from app.core.llm_provider import provider_from_config
from app.domain.types import VnProject

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


async def synthesize_voice_mind(
    cfg: DeepSeekConfig,
    project: VnProject,
    *,
    character_id: str,
    force: bool = False,
) -> Dict[str, Any]:
    char = find_character(project, character_id)
    stats = corpus_stats(char)
    n = stats["sampleCount"]
    if n < 1:
        raise ValueError("没有正例语料，无法合成思维包")
    if not force and not stats["readyForMind"]:
        raise ValueError(
            f"样本体量不足：正例 {n} 条、场景覆盖 {stats['scenarioCoverage']}、"
            f"角色台词约 {stats['volumeChars']} 字、长场次 {stats['sceneCount']}、"
            f"采访 {stats['interviewCount']}。"
            "建议：≥6 条短正例，或覆盖 5 类场景，或台词≥800 字，或≥2 段长场次"
            "（可 force=true 强制）。"
        )

    samples_txt: List[str] = []
    for s in char.voiceCorpus or []:
        lines = " | ".join(
            f"{ln.speaker}:{ln.text}" for ln in (s.lines or []) if ln.text
        )
        samples_txt.append(
            f"- [{s.scenarioLabel or s.scenario}] src={s.source or '?'} "
            f"axis={s.axis or '?'} hyp={s.hypothesis or ''} :: {lines}"
        )
    rejects = [str(x).strip() for x in (char.voiceRejectNotes or []) if str(x).strip()]
    prefers = [str(x).strip() for x in (char.voicePreferNotes or []) if str(x).strip()]
    from app.core.character_voice.corpus import confirmed_axes
    from app.core.character_voice.extract import format_script_anchors_for_prompt

    dirs = confirmed_axes(char)
    # Script anchors: the character's own written dialogue in the novel —
    # read-only evidence so the mind pack matches what's actually on page
    # (beyond the hand-picked corpus samples).
    anchors = format_script_anchors_for_prompt(project, character_id, limit=8, max_chars=900)
    anchor_lines = anchors.splitlines()[1:] if anchors else []
    script_anchors_used = len(anchor_lines)

    system = (
        "你是角色思维包蒸馏助手。根据作者挑选的正例对白（**正例**）与角色在剧本中已写的对白（**剧本锚点**），"
        "写一张**轻量角色思维包**（中文 markdown）。\n"
        "结构必须含这些小节标题：\n"
        "## 视角一句话\n## 心智模型\n## 表达 DNA\n## 决策启发式\n## 审阅时问什么\n"
        "## 反模式\n## 诚实边界\n"
        "要求：可操作、短句条目、面向视觉小说可演对白；禁止大段原文照抄正例或剧本锚点；"
        "「视角一句话」必须是该角色最典型的**一句话**（可直接作为语气摘要，不加引号、不分行）；"
        "已确认方向与作者【偏好】优先写入「表达 DNA」与「心智模型」；忌讳写入「反模式」；"
        "诚实边界写明此卡非真人、服从工程 style_guide 与角色事实卡。\n"
        "只输出 markdown 正文，不要包 JSON。"
    )
    user = "\n".join(
        [
            f"角色：{char.displayName}（{char.defineName}）",
            f"语气：{char.voice or ''}",
            f"简介：{char.bio or ''}",
            f"关系：{char.relationships or ''}",
            f"已确认方向：{'、'.join(dirs) if dirs else '（尚无）'}",
            "正例：",
            *samples_txt[:24],
            anchors or "剧本锚点：（无）",
            "偏好笔记：" + ("；".join(prefers[-10:]) if prefers else "（无）"),
            "忌讳笔记：" + ("；".join(rejects[-8:]) if rejects else "（无）"),
        ]
    )

    if not cfg.apiKey or "your-key" in cfg.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")

    provider = provider_from_config(cfg)
    res = await provider.chat_completions(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.55,
        timeout=120,
    )
    content, used_model = content_from_response(res)
    content = (content or "").strip()
    m = _FENCE_RE.search(content)
    if m and "视角" not in content[:80]:
        inner = m.group(1).strip()
        if inner.startswith("#") or "视角" in inner:
            content = inner

    if not content or len(content) < 40:
        raise RuntimeError("思维包生成结果过短")

    # suggestedVoice: take the「视角一句话」section line (the model wrote it
    # to be exactly that one sentence), instead of guessing the first short
    # line or keeping the old card's voice. The API only applies it to the
    # character's voice field when that field is still empty.
    voice_line = ""
    in_perspective = False
    for line in content.splitlines():
        t = line.strip()
        if t.startswith("##"):
            in_perspective = "视角一句话" in t
            continue
        if not in_perspective:
            continue
        t = t.lstrip("-•*").strip()
        if t and len(t) <= 60 and not voice_line:
            voice_line = t
            break

    return {
        "markdown": content,
        **{k: stats[k] for k in (
            "sampleCount",
            "scenarioCoverage",
            "volumeChars",
            "sceneCount",
            "interviewCount",
            "readyForMind",
        )},
        "suggestedVoice": voice_line or None,
        "scriptAnchorsUsed": script_anchors_used,
        "model": used_model or (cfg.model or "deepseek-chat"),
        "ready": True,
    }

"""Export / import character mind packs for offline nuwa distillation."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from app.core.character_voice.corpus import find_character, sample_count, scenario_coverage
from app.domain.types import VnProject

_FM_RE = re.compile(r"^---\s*\n([\s\S]*?)\n---\s*\n?", re.M)


def build_nuwa_export_markdown(project: VnProject, *, character_id: str) -> Dict[str, Any]:
    char = find_character(project, character_id)
    slug = re.sub(r"[^a-z0-9]+", "-", (char.defineName or char.id).lower()).strip("-") or "char"
    pack_id = f"character-{slug}"

    samples_md = []
    for s in char.voiceCorpus or []:
        lines = "\n".join(
            f"  - {ln.speaker}: {ln.text}" for ln in (s.lines or []) if ln.text
        )
        samples_md.append(
            f"### {s.scenarioLabel or s.scenario}\n"
            f"- source: {s.source}\n"
            f"- axis: {s.axis or ''}\n"
            f"- hypothesis: {s.hypothesis or ''}\n"
            f"- lines:\n{lines}\n"
        )

    rejects = "\n".join(f"- {n}" for n in (char.voiceRejectNotes or []) if n)

    body = "\n".join(
        [
            f"# {char.displayName} — 角色蒸馏包（女娲进料）",
            "",
            "## 基础信息",
            f"- displayName: {char.displayName}",
            f"- defineName: {char.defineName}",
            f"- voice: {char.voice or ''}",
            f"- bio: {char.bio or ''}",
            f"- relationships: {char.relationships or ''}",
            f"- sampleCount: {sample_count(char)}",
            f"- scenarioCoverage: {scenario_coverage(char)}",
            "",
            "## 正例语料",
            "\n".join(samples_md) if samples_md else "（无）",
            "",
            "## 忌讳 / 负例笔记",
            rejects or "（无）",
            "",
            "## 现有轻量思维包（可被女娲加深替换）",
            (char.voiceMind or "（无）").strip(),
            "",
            "## 蒸馏说明（给女娲 / Cursor）",
            "请基于以上正例与忌讳，蒸馏为 character_lens（女娲五层）：",
            "视角一句话 / 心智模型 / 表达 DNA / 决策启发式 / 审阅时问什么 / 反模式 / 诚实边界。",
            "面向视觉小说可演对白；禁止仿写侵权原文；非真人授权人格。",
            "输出 SKILL.md 后人工清洗，frontmatter 使用 kind: character_lens。",
            "导入回工作室「角色工坊 → 思维包 → 导入」以解锁对话。",
        ]
    )

    front = "\n".join(
        [
            "---",
            f"id: {pack_id}",
            f"name: {char.displayName}",
            "kind: character_lens",
            "persona: character",
            "modes: [voice, write]",
            "budget_chars: 2400",
            "provenance: studio-export",
            "---",
            "",
        ]
    )

    markdown = front + body
    return {
        "filename": f"{pack_id}-export.md",
        "packId": pack_id,
        "markdown": markdown,
        "sampleCount": sample_count(char),
        "scenarioCoverage": scenario_coverage(char),
    }


def parse_mind_import(markdown: str, *, fallback_name: str = "") -> Dict[str, Any]:
    """Accept full SKILL.md or bare mind markdown; return mind body + meta."""
    md = (markdown or "").strip()
    if not md:
        raise ValueError("markdown 不能为空")
    meta: Dict[str, str] = {}
    body = md
    m = _FM_RE.match(md)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = md[m.end() :].strip()
    name = meta.get("name") or fallback_name
    return {
        "id": meta.get("id") or "",
        "name": name,
        "kind": meta.get("kind") or "character_lens",
        "markdown": body,
        "meta": meta,
    }

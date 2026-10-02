"""Deterministic LLM ingest: sources → bible / characters / meta / locations actions.

P7：多源（附件 ∪ 章 ∪ 选区 ∪ 大纲）；默认 dry-run（apply=False），
确认后再 apply_agent_actions。INGEST_DIRECT_APPLY 仅事故直写。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.core import llm_budget
from app.domain.types import AgentAction, Character, VnProject

from .agent import _normalize_bible_patch, apply_agent_actions
from .ai import DeepSeekConfig
from .llm_http import chat_completions, content_from_response

INGEST_SYSTEM = """你是视觉小说 / 轻小说设定编辑。根据用户资料与当前工程摘要，产出要写入工程的结构化 JSON（不要 markdown 围栏）。

只输出：
{
  "message": "中文：说明拟写入哪些栏",
  "bible": {
    "world": "世界观/规则，可空字符串表示不改",
    "background": "故事背景/前情",
    "outline": "大纲/节拍",
    "themes": "主题/基调/禁忌",
    "notes": "其他备忘"
  },
  "meta": { "title": "", "logline": "", "genre": "", "writingGenre": "vn|novel|空" },
  "characters": [
    {
      "displayName": "角色名",
      "defineName": "yingwen_id",
      "voice": "语气",
      "bio": "简介",
      "relationships": "关系摘要",
      "aliases": ["别名"],
      "color": "#6b7280"
    }
  ],
  "locations": [
    { "name": "地点名", "description": "说明", "imageTag": "可选" }
  ],
  "locationLinks": [
    { "fromName": "地点A", "toName": "地点B", "relation": "通路说明" }
  ],
  "lore": [
    { "title": "设定条目标题", "body": "正文", "keywords": ["词"] }
  ],
  "characterLinks": [
    { "fromName": "角色A", "toName": "角色B", "label": "关系" }
  ],
  "timeline": [
    { "title": "节点", "summary": "说明", "order": 1 }
  ]
}

规则：
- 某字段资料不足：省略或 ""（空=不改）。
- 有实质内容才填；从资料提炼，勿编造。
- characters：重要角色都列出；已有角色同名则 update。
- defineName 仅英文小写+数字下划线。
- writingGenre 仅 vn 或 novel。
- locationLinks / characterLinks / lore / timeline：资料明确才写。
"""


@dataclass
class SettingsIngestResult:
    message: str
    actions: List[AgentAction] = field(default_factory=list)
    project: Optional[VnProject] = None
    applied: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)


def _parse_json_obj(raw: str) -> Dict[str, Any]:
    from app.core.llm_text import extract_json_object

    data = extract_json_object(raw)
    if data is None:
        raise json.JSONDecodeError("模型未返回 JSON 对象", (raw or "").strip(), 0)
    return data


def _char_index(project: VnProject) -> Dict[str, Character]:
    idx: Dict[str, Character] = {}
    for c in project.characters:
        idx[c.displayName.strip().lower()] = c
        idx[c.defineName.strip().lower()] = c
        idx[c.id.strip().lower()] = c
    return idx


def _loc_index(project: VnProject) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for loc in project.locations or []:
        out[str(loc.name or "").strip().lower()] = loc.id
        out[str(loc.id).strip().lower()] = loc.id
    return out


def plan_to_actions(project: VnProject, plan: Dict[str, Any]) -> List[AgentAction]:
    actions: List[AgentAction] = []
    bible_raw = plan.get("bible") if isinstance(plan.get("bible"), dict) else {}
    bible_patch = _normalize_bible_patch(bible_raw or {})
    bible_patch = {k: v for k, v in bible_patch.items() if str(v).strip()}
    if bible_patch:
        actions.append({"op": "update_bible", "patch": bible_patch})

    meta = plan.get("meta") if isinstance(plan.get("meta"), dict) else {}
    meta_action: Dict[str, Any] = {"op": "update_meta"}
    for key in ("title", "logline", "genre", "writingGenre"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            if key == "writingGenre" and val.strip().lower() not in ("vn", "novel"):
                continue
            meta_action[key] = val.strip()
    if len(meta_action) > 1:
        actions.append(meta_action)

    idx = _char_index(project)
    chars = plan.get("characters")
    if isinstance(chars, list):
        for item in chars:
            if not isinstance(item, dict):
                continue
            name = str(item.get("displayName") or item.get("name") or "").strip()
            if not name:
                continue
            existing = idx.get(name.lower())
            patch = {
                k: str(item[k]).strip()
                for k in (
                    "voice",
                    "bio",
                    "relationships",
                    "color",
                    "displayName",
                    "defineName",
                )
                if item.get(k) is not None and str(item.get(k)).strip()
            }
            aliases = item.get("aliases")
            if isinstance(aliases, list):
                clean = [str(a).strip() for a in aliases if str(a).strip()]
                if clean:
                    patch["aliases"] = clean  # type: ignore[assignment]
            if existing:
                body = {k: v for k, v in patch.items() if k not in ("defineName",)}
                if body:
                    actions.append(
                        {"op": "update_character", "ref": existing.id, "patch": body}
                    )
            else:
                actions.append(
                    {
                        "op": "add_character",
                        "displayName": name,
                        "defineName": patch.get("defineName"),
                        "voice": patch.get("voice") or "",
                        "bio": patch.get("bio") or "",
                        "relationships": patch.get("relationships") or "",
                        "color": patch.get("color") or "#6b7280",
                        "aliases": patch.get("aliases") or [],
                    }
                )

    locs = plan.get("locations")
    pending_loc_names: List[str] = []
    if isinstance(locs, list):
        for item in locs:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            pending_loc_names.append(name)
            actions.append(
                {
                    "op": "add_location",
                    "name": name,
                    "description": str(item.get("description") or "").strip() or None,
                    "imageTag": str(item.get("imageTag") or "").strip() or None,
                }
            )

    links = plan.get("locationLinks")
    if isinstance(links, list):
        loc_idx = _loc_index(project)
        for item in links:
            if not isinstance(item, dict):
                continue
            a = str(item.get("fromName") or item.get("fromId") or "").strip()
            b = str(item.get("toName") or item.get("toId") or "").strip()
            if not a or not b:
                continue
            # 新地点可能在同批 add_location；用名字留给 apply 层解析失败则 skip
            actions.append(
                {
                    "op": "add_location_link",
                    "fromRef": loc_idx.get(a.lower()) or a,
                    "toRef": loc_idx.get(b.lower()) or b,
                    "relation": str(item.get("relation") or "相关").strip() or "相关",
                }
            )

    lore = plan.get("lore")
    if isinstance(lore, list):
        for item in lore:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            body = str(item.get("body") or "").strip()
            if not title or not body:
                continue
            kws = item.get("keywords") if isinstance(item.get("keywords"), list) else []
            actions.append(
                {
                    "op": "propose_lore_entries",
                    "entries": [
                        {
                            "title": title,
                            "body": body,
                            "keywords": [str(k).strip() for k in kws if str(k).strip()],
                        }
                    ],
                }
            )

    clinks = plan.get("characterLinks")
    if isinstance(clinks, list):
        for item in clinks:
            if not isinstance(item, dict):
                continue
            a = str(item.get("fromName") or item.get("fromRef") or "").strip()
            b = str(item.get("toName") or item.get("toRef") or "").strip()
            if not a or not b:
                continue
            actions.append(
                {
                    "op": "propose_character_link",
                    "fromRef": a,
                    "toRef": b,
                    "label": str(item.get("label") or "关系").strip() or "关系",
                }
            )

    timeline = plan.get("timeline")
    if isinstance(timeline, list):
        for item in timeline:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            actions.append(
                {
                    "op": "propose_timeline_event",
                    "title": title,
                    "summary": str(item.get("summary") or "").strip(),
                    "order": item.get("order"),
                }
            )

    return actions


def _project_digest(project: VnProject) -> str:
    b = project.bible
    lines = [
        f"标题：{project.title}",
        f"类型：{project.genre or ''}",
        f"写作体裁：{getattr(project, 'writingGenre', None) or ''}",
        f"一句话：{project.logline or ''}",
        "角色："
        + "；".join(
            f"{c.displayName}({c.defineName}) voice={c.voice or ''} bio={c.bio or ''}"
            for c in project.characters[:20]
        ),
        "地点："
        + "；".join(f"{l.name}" for l in (project.locations or [])[:20]),
    ]
    if b:
        lines.append(f"world：{(b.world or '')[:400]}")
        lines.append(f"background：{(b.background or '')[:400]}")
        lines.append(f"outline：{(b.outline or '')[:400]}")
        lines.append(f"themes：{(b.themes or '')[:200]}")
        lines.append(f"notes：{(b.notes or '')[:200]}")
    return "\n".join(lines)


def format_extra_sources(
    *,
    chapter_text: str = "",
    selection: str = "",
    outline: str = "",
) -> str:
    parts: List[str] = []
    if (outline or "").strip():
        parts.append(f"## 大纲\n{outline.strip()[:6000]}")
    if (chapter_text or "").strip():
        parts.append(f"## 当前章正文\n{chapter_text.strip()[:12000]}")
    if (selection or "").strip():
        parts.append(f"## 选区\n{selection.strip()[:4000]}")
    return "\n\n".join(parts)


async def ingest_sources_to_settings(
    config: DeepSeekConfig,
    project: VnProject,
    attachments: List[Dict[str, Any]],
    *,
    user_note: str = "",
    chapter_text: str = "",
    selection: str = "",
    outline: str = "",
    apply: bool = False,
) -> SettingsIngestResult:
    if not config.apiKey or "your-key" in config.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")
    from .file_text import format_attachment_block

    docs = format_attachment_block(attachments) if attachments else ""
    extra = format_extra_sources(
        chapter_text=chapter_text, selection=selection, outline=outline
    )
    if not docs.strip() and not extra.strip():
        raise RuntimeError("没有可用的入库资料（附件 / 章 / 选区 / 大纲）")

    user_content = (
        f"## 当前工程摘要\n{_project_digest(project)}\n\n"
        f"{docs}\n\n"
        f"{extra}\n\n"
        f"## 用户说明\n{(user_note or '请把资料写入设定页与角色卡').strip()}"
    )

    res = await chat_completions(
        config,
        messages=[
            {"role": "system", "content": INGEST_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
        response_format={"type": "json_object"},
        timeout=llm_budget.CHAT,
    )
    raw, _model = content_from_response(res)
    raw = (raw or "{}").strip() or "{}"
    plan = _parse_json_obj(raw)
    actions = plan_to_actions(project, plan)
    if not actions:
        return SettingsIngestResult(
            message=str(plan.get("message") or "资料里没有足够可写入设定的信息。"),
            actions=[],
        )

    msg = str(plan.get("message") or "").strip() or "已根据资料整理设定方案。"
    if not apply:
        return SettingsIngestResult(
            message=msg + "\n（待确认后写入；本次未落库）",
            actions=actions,
        )

    applied = apply_agent_actions(project, actions)
    if applied.applied:
        msg = f"{msg}\n\n已落地：{'；'.join(applied.applied)}"
    if applied.skipped:
        msg = f"{msg}\n未执行：{'；'.join(applied.skipped)}"
    return SettingsIngestResult(
        message=msg,
        actions=actions,
        project=applied.project,
        applied=list(applied.applied),
        skipped=list(applied.skipped),
    )


async def ingest_attachments_to_settings(
    config: DeepSeekConfig,
    project: VnProject,
    attachments: List[Dict[str, Any]],
    *,
    user_note: str = "",
    apply: bool = False,
) -> SettingsIngestResult:
    """兼容旧调用名。"""
    return await ingest_sources_to_settings(
        config,
        project,
        attachments,
        user_note=user_note,
        apply=apply,
    )
